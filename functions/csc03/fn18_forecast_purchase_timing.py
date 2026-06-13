"""
CSC-03/04  |  fn18: forecast_purchase_timing()

비행시간 기반 부품 구매/도입 시기 예측 (시뮬레이션 핵심 로직).

단순 재고 가시화를 넘어, 기체의 누적 비행시간과 연간 비행시간 가정을 바탕으로
정비 도래 시점을 '날짜'로 환산하고, BOM 소요 부품·현재고·조달 리드타임을 결합해
"언제 발주해야 하는지"를 산출한다.

기준 (2026-06-13 피드백 반영):
    · 실제 비행시간 기준 계산 (청주/무안 공통, aircraft.total_flight_hours 사용)
    · 하루 최대 비행 6~7h, 연간 총비행 약 700~750h(안전 고려)
      → 기본 연간 800h(청주주4일/무안주7일). 캘린더 환산: 시간/일 = 연간비행 / 365
        (운항일에만 비행하므로 '하루 최대'가 아닌 '연간 총량 분산'으로 환산)
    · 정비 도래시점(due_hours) - 현재 누적시간 = 잔여 비행시간
      → 잔여시간 / (연간/365) = 도래까지 캘린더 일수
    · 발주 기준일 = 도래일 - 조달 리드타임(reorder_points.lead_time_days)

호출 테이블:
    aircraft (SELECT) / maintenance_schedule (SELECT) /
    bom (SELECT) / parts_inventory (SELECT) / reorder_points (SELECT) /
    components (SELECT, 품명)
"""

from __future__ import annotations
from datetime import date, timedelta
import math

# ── 비행시간 가정 기본값 (피드백 기준) ─────────────────────────
# ANNUAL_FLIGHT_HOURS = 725.0  → functions.constants.ANNUAL_FLIGHT_HOURS (800h) 로 통합
# DEFAULT_DAILY_MAX_HOURS     = 6.5   → functions.constants 참고
DEFAULT_HORIZON_DAYS        = 365     # 예측 기간(기본 1년)
DEFAULT_LEAD_TIME_DAYS      = 30      # 리드타임 기본값(reorder_points 미설정 시)

from functions.db import get_client
from functions.constants import ANNUAL_FLIGHT_HOURS, DAILY_AVG_FLIGHT_HOURS


def forecast_purchase_timing(
    aircraft_id: int,
    annual_flight_hours: float = ANNUAL_FLIGHT_HOURS,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    default_lead_time_days: int = DEFAULT_LEAD_TIME_DAYS,
    today: str | None = None,
) -> dict:
    """
    특정 기체의 비행시간 추세를 기반으로 정비 도래 시점과 부품 발주 시기를 예측한다.

    Parameters
    ----------
    aircraft_id : int
        aircraft.id (PK)
    annual_flight_hours : float
        연간 총비행시간 가정(기본 800h — constants.ANNUAL_FLIGHT_HOURS). 0 초과.
    horizon_days : int
        예측 기간(일). 이 기간 내 도래 정비만 결과에 포함(초과/임박 부품 발주 판단).
    default_lead_time_days : int
        reorder_points.lead_time_days 미설정 부품에 적용할 기본 리드타임.
    today : str | None
        기준일 'YYYY-MM-DD'. None 이면 오늘. (테스트 고정용)

    Returns
    -------
    dict
        {
            "aircraft_id", "model", "current_flight_hours",
            "annual_flight_hours", "hours_per_calendar_day", "horizon_days",
            "as_of": "YYYY-MM-DD",
            "items": [
                {
                    "maintenance_schedule_id", "maintenance_type",
                    "interval_hours", "remaining_hours",
                    "days_until_due", "due_date",
                    "part_id", "nomenclature", "required_qty",
                    "current_stock", "shortfall",
                    "lead_time_days", "order_by_date",
                    "recommendation"   # 초과(즉시발주)|지금발주|발주예정|여유
                }, ...
            ],
            "summary": {"즉시발주", "지금발주", "발주예정", "여유"}  # 건수
        }

    Raises
    ------
    ValueError
        · aircraft_id 미존재 / annual_flight_hours <= 0 / horizon_days < 0
    """
    if annual_flight_hours <= 0:
        raise ValueError(f"annual_flight_hours 는 0 보다 커야 합니다. 입력값: {annual_flight_hours}")
    if horizon_days < 0:
        raise ValueError(f"horizon_days 는 0 이상이어야 합니다. 입력값: {horizon_days}")

    today_d = date.fromisoformat(today) if today else date.today()
    hours_per_day = annual_flight_hours / 365.0

    client = get_client()

    # ── 기체 조회
    ac = (
        client.table("aircraft")
        .select("id, model, total_flight_hours")
        .eq("id", aircraft_id)
        .maybe_single()
        .execute()
    )
    if not ac.data:
        raise ValueError(f"aircraft_id {aircraft_id} 에 해당하는 항공기가 없습니다.")
    model = ac.data.get("model")
    current_hours = float(ac.data.get("total_flight_hours") or 0)

    # ── 활성 정비 스케줄 조회
    scheds = (
        client.table("maintenance_schedule")
        .select("id, maintenance_type, interval_hours, due_hours, status")
        .eq("aircraft_id", aircraft_id)
        .in_("status", ["scheduled", "overdue"])
        .execute()
    ).data or []

    items: list[dict] = []

    for s in scheds:
        interval_hours = s.get("interval_hours")
        if not interval_hours or float(interval_hours) <= 0:
            continue  # 순수 날짜기반 주기는 시간환산 대상 아님(별도 처리 영역)

        due_hours = s.get("due_hours")
        if due_hours is not None:
            remaining_hours = float(due_hours) - current_hours
        else:
            remaining_hours = float(interval_hours)  # 신규: 한 주기분 남은 것으로 가정

        days_until_due = math.ceil(remaining_hours / hours_per_day)
        due_date = today_d + timedelta(days=days_until_due)

        # 예측 기간 밖(여유 많음)은 스킵 — 단, 초과/임박은 항상 포함
        if days_until_due > horizon_days:
            continue

        # ── 해당 정비의 BOM 부품
        bom_rows = (
            client.table("bom")
            .select("part_id, required_qty, aircraft_model, maintenance_type")
            .eq("maintenance_type", s["maintenance_type"])
            .execute()
        ).data or []
        # 기종 일치 또는 전기종(null) 만
        bom_rows = [
            b for b in bom_rows
            if b.get("aircraft_model") in (None, model)
        ]

        for b in bom_rows:
            part_id = b["part_id"]
            required_qty = int(b.get("required_qty") or 1)

            # 현재고 (중앙 단일행 가정이나 분리행도 합산 대응)
            inv = (
                client.table("parts_inventory")
                .select("quantity_on_hand")
                .eq("part_id", part_id)
                .execute()
            ).data or []
            current_stock = sum(int(r.get("quantity_on_hand") or 0) for r in inv)

            # 리드타임 / 품명
            rp = (
                client.table("reorder_points")
                .select("lead_time_days")
                .eq("part_id", part_id)
                .maybe_single()
                .execute()
            )
            lead_time = default_lead_time_days
            if rp.data and rp.data.get("lead_time_days") is not None:
                lead_time = int(rp.data["lead_time_days"])

            comp = (
                client.table("components")
                .select("nomenclature")
                .eq("id", part_id)
                .maybe_single()
                .execute()
            )
            nomenclature = comp.data.get("nomenclature") if comp.data else None

            order_by_date = due_date - timedelta(days=lead_time)
            shortfall = max(0, required_qty - current_stock)

            # ── 발주 권고 판정
            if remaining_hours < 0:
                rec = "초과(즉시발주)"
            elif order_by_date <= today_d:
                rec = "지금발주"
            elif days_until_due <= horizon_days:
                rec = "발주예정"
            else:
                rec = "여유"

            items.append({
                "maintenance_schedule_id": s["id"],
                "maintenance_type":        s["maintenance_type"],
                "interval_hours":          float(interval_hours),
                "remaining_hours":         round(remaining_hours, 1),
                "days_until_due":          days_until_due,
                "due_date":                due_date.isoformat(),
                "part_id":                 part_id,
                "nomenclature":            nomenclature,
                "required_qty":            required_qty,
                "current_stock":           current_stock,
                "shortfall":               shortfall,
                "lead_time_days":          lead_time,
                "order_by_date":           order_by_date.isoformat(),
                "recommendation":          rec,
            })

    # 발주 기준일 빠른 순 정렬
    items.sort(key=lambda x: x["order_by_date"])

    summary = {
        "즉시발주": sum(1 for i in items if i["recommendation"] == "초과(즉시발주)"),
        "지금발주": sum(1 for i in items if i["recommendation"] == "지금발주"),
        "발주예정": sum(1 for i in items if i["recommendation"] == "발주예정"),
        "여유":    sum(1 for i in items if i["recommendation"] == "여유"),
    }

    return {
        "aircraft_id":            aircraft_id,
        "model":                  model,
        "current_flight_hours":   current_hours,
        "annual_flight_hours":    annual_flight_hours,
        "hours_per_calendar_day": round(hours_per_day, 3),
        "horizon_days":           horizon_days,
        "as_of":                  today_d.isoformat(),
        "items":                  items,
        "summary":                summary,
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-13  신규 작성 (피드백 반영)
#       · 비행시간 → 정비 도래일 캘린더 환산 (연간 800h / 365 기준, 청주주4일/무안주7일)
#       · BOM 소요부품 × 현재고 × 리드타임 결합 → 발주 기준일 산출
#       · 초과/지금발주/발주예정/여유 4단계 권고
# 향후 변경 예정
#       · 최근 flight_hours 추세로 annual_flight_hours 자동 추정(현재는 파라미터)
#       · 청주/무안 운용 분리 시 기지별 비행시간 가정 분기
# =============================================================================
