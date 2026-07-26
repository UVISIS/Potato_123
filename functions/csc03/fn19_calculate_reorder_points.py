from __future__ import annotations
import math
from functions.db import get_client
from functions.constants import (
    ANNUAL_FLIGHT_HOURS,
    normalize_aircraft_model,
    normalize_maintenance_type,
)

# ── 가정치 (팀 확인 전 임시값 — 이슈#14 참고)
DEFAULT_LEAD_TIME_DAYS = 30      # reorder_points.lead_time_days 없을 때 기본 리드타임 가정
DEFAULT_REORDER_CYCLE_DAYS = 90  # 발주 1회당 커버 기간 (분기 발주 가정)


def calculate_reorder_points(part_id: int | None = None) -> list[dict]:
    """
    비행시간(ANNUAL_FLIGHT_HOURS)과 BOM 정비주기별 소요량을 근거로
    reorder_points의 최소/최대/안전재고/재주문수량을 계산한다. (이슈 #14)

    산정 로직
    ---------
    1. 부품별 연간 소요량
       = Σ [ (ANNUAL_FLIGHT_HOURS / maintenance_schedule.interval_hours)
             × bom.required_qty × 해당 기종 보유 대수 ]
       - interval_hours가 0(순수 날짜주기)인 정비유형은 12/interval_months(연 횟수)로 계산
       - aircraft_model / maintenance_type은 functions.constants의 정규화 함수로
         bom 표준 코드와 매칭 (routers/maintenance.py, routers/components.py와 동일 기준)
    2. 일평균 소요량 = 연간 소요량 / 365
    3. 안전재고(safety_stock) = ceil(일평균 소요량 × lead_time_days)
       - lead_time_days: reorder_points 기존값이 있으면 그 값 사용,
         없거나 0이면 DEFAULT_LEAD_TIME_DAYS(30일) 가정 사용
    4. 최소재고(minimum_qty) = safety_stock
    5. 재주문수량(reorder_qty) = ceil(일평균 소요량 × DEFAULT_REORDER_CYCLE_DAYS(90일))
    6. 최대재고(maximum_qty) = minimum_qty + reorder_qty

    ⚠ 가정치: DEFAULT_LEAD_TIME_DAYS=30, DEFAULT_REORDER_CYCLE_DAYS=90은 팀 협의 전
    임시값이다. suppliers/reorder_points에 실제 리드타임이 채워지면 자동으로 그 값이
    우선 사용된다 (lead_time_source="reorder_points"로 표시됨).

    Parameters
    ----------
    part_id : int | None
        특정 부품만 계산하려면 지정. None이면 bom에 등장하는 전체 부품 대상.

    Returns
    -------
    list[dict]
        [
            {
                "part_id": int,
                "annual_usage_qty": float,
                "daily_usage_qty": float,
                "lead_time_days": int,
                "lead_time_source": str,   # "reorder_points" | "default"
                "minimum_qty": int,
                "maximum_qty": int,
                "safety_stock": int,
                "reorder_qty": int,
            }, ...
        ]
        정비주기/기종 정보가 없어 계산 불가한 부품은 결과에서 제외된다(수동 확인 필요).

    Raises
    ------
    RuntimeError
        DB 조회 실패 시
    """
    client = get_client()

    # ── 기종별 보유 대수
    try:
        aircraft_rows = client.table("aircraft").select("id, model").execute().data or []
    except Exception as e:
        raise RuntimeError(f"aircraft 테이블 조회 실패: {e}")

    fleet_count: dict[str, int] = {}
    for a in aircraft_rows:
        model = normalize_aircraft_model(a.get("model"))
        if model:
            fleet_count[model] = fleet_count.get(model, 0) + 1

    # ── 정비유형별 주기 (동일 정비유형은 기종 무관 동일 주기 가정 — 상이하면 별도 확인 필요)
    try:
        sched_rows = client.table("maintenance_schedule").select(
            "maintenance_type, interval_hours, interval_months"
        ).execute().data or []
    except Exception as e:
        raise RuntimeError(f"maintenance_schedule 테이블 조회 실패: {e}")

    interval_map: dict[str, dict] = {}
    for s in sched_rows:
        mtype = normalize_maintenance_type(s.get("maintenance_type"))
        if mtype and mtype not in interval_map:
            interval_map[mtype] = {
                "interval_hours": s.get("interval_hours") or 0,
                "interval_months": s.get("interval_months"),
            }

    # ── BOM 조회
    bom_q = client.table("bom").select("part_id, maintenance_type, aircraft_model, required_qty")
    if part_id is not None:
        bom_q = bom_q.eq("part_id", part_id)
    try:
        bom_rows = bom_q.execute().data or []
    except Exception as e:
        raise RuntimeError(f"bom 테이블 조회 실패: {e}")

    # ── 부품별 연간 소요량 집계
    annual_usage: dict[int, float] = {}
    for r in bom_rows:
        pid = r.get("part_id")
        if pid is None:
            continue
        model = normalize_aircraft_model(r.get("aircraft_model"))
        mtype = normalize_maintenance_type(r.get("maintenance_type"))
        qty_per_event = r.get("required_qty") or 0
        n_aircraft = fleet_count.get(model, 0)
        interval = interval_map.get(mtype)

        if not interval or n_aircraft == 0 or qty_per_event == 0:
            continue

        interval_hours = interval["interval_hours"]
        interval_months = interval["interval_months"]

        if interval_hours and interval_hours > 0:
            events_per_year = ANNUAL_FLIGHT_HOURS / interval_hours
        elif interval_months and interval_months > 0:
            events_per_year = 12 / interval_months
        else:
            continue  # 주기 정보 없으면 계산 불가 → 스킵 (수동 확인 필요)

        annual_usage[pid] = annual_usage.get(pid, 0.0) + events_per_year * qty_per_event * n_aircraft

    if not annual_usage:
        return []

    # ── 기존 reorder_points(lead_time_days) 조회
    try:
        rp_rows = client.table("reorder_points").select(
            "part_id, lead_time_days"
        ).in_("part_id", list(annual_usage.keys())).execute().data or []
    except Exception as e:
        raise RuntimeError(f"reorder_points 테이블 조회 실패: {e}")
    lead_time_map = {r["part_id"]: r.get("lead_time_days") for r in rp_rows}

    results: list[dict] = []
    for pid, annual_qty in annual_usage.items():
        daily_qty = annual_qty / 365
        lt = lead_time_map.get(pid)
        lt_source = "reorder_points"
        if not lt or lt <= 0:
            lt = DEFAULT_LEAD_TIME_DAYS
            lt_source = "default"

        safety_stock = math.ceil(daily_qty * lt)
        reorder_qty = math.ceil(daily_qty * DEFAULT_REORDER_CYCLE_DAYS)
        minimum_qty = safety_stock
        maximum_qty = minimum_qty + reorder_qty

        results.append({
            "part_id": pid,
            "annual_usage_qty": round(annual_qty, 2),
            "daily_usage_qty": round(daily_qty, 4),
            "lead_time_days": lt,
            "lead_time_source": lt_source,
            "minimum_qty": minimum_qty,
            "maximum_qty": maximum_qty,
            "safety_stock": safety_stock,
            "reorder_qty": reorder_qty,
        })

    return results


def apply_reorder_points(part_id: int | None = None) -> int:
    """calculate_reorder_points() 결과를 reorder_points 테이블에 UPDATE 반영한다.

    Parameters
    ----------
    part_id : int | None
        특정 부품만 반영하려면 지정. None이면 계산된 전체 부품 반영.

    Returns
    -------
    int
        업데이트된 행 수
    """
    client = get_client()
    calculated = calculate_reorder_points(part_id)
    updated = 0
    for row in calculated:
        client.table("reorder_points").update({
            "minimum_qty": row["minimum_qty"],
            "maximum_qty": row["maximum_qty"],
            "safety_stock": row["safety_stock"],
            "reorder_qty": row["reorder_qty"],
            "lead_time_days": row["lead_time_days"],
            "update_reason": "이슈#14: 비행시간+BOM 소요량 기반 자동계산 (2026-07-26)",
        }).eq("part_id", row["part_id"]).execute()
        updated += 1
    return updated


if __name__ == "__main__":
    # 실행 예: python -m functions.csc03.fn19_calculate_reorder_points
    rows = calculate_reorder_points()
    print(f"계산된 부품 수: {len(rows)}")
    default_lt_count = sum(1 for r in rows if r["lead_time_source"] == "default")
    print(f"리드타임 기본값(30일) 적용: {default_lt_count}건 — 실제 리드타임 확인 권장")
    n = apply_reorder_points()
    print(f"reorder_points 반영 완료: {n}건")


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-07-26  이슈#14 — 신규 작성
#       · 안전재고 산정: 연간비행시간(ANNUAL_FLIGHT_HOURS=800h) ÷ 정비주기(interval_hours)
#         로 연간 정비 도래횟수 산출 → BOM required_qty × 기종별 보유대수로 연간 소요량 집계
#       · 안전재고 = 일평균소요량 × lead_time_days (기존값 없으면 30일 가정)
#       · 재주문수량 = 일평균소요량 × 90일(분기 가정), 최대재고 = 최소재고 + 재주문수량
#       · calculate_reorder_points(): 계산만 수행 (검증용, DB 미반영)
#       · apply_reorder_points(): 계산 후 reorder_points 테이블에 실제 UPDATE
#
# 확인 필요 (가정치 — 팀 협의 후 조정)
#       · DEFAULT_LEAD_TIME_DAYS=30, DEFAULT_REORDER_CYCLE_DAYS=90
#       · 기종별 정비주기가 실제로 동일한지 확인 필요 (현재 정비유형명 기준 첫 값 사용)
#       · 순수 날짜주기(interval_hours=0) 부품은 interval_months 기반으로 계산
# =============================================================================
