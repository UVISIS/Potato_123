from __future__ import annotations
from datetime import datetime, timezone, timedelta, date

from functions.db import get_client
from functions.constants import (
    DEFAULT_DAILY_FLIGHT_HOURS as DEFAULT_DAILY,
    MAINTENANCE_CRITICAL_PCT as CRITICAL_PCT,
)


# CRITICAL_PCT  = 0.10  → functions.constants.MAINTENANCE_CRITICAL_PCT 로 통합
# DEFAULT_DAILY = 3.0  → functions.constants.DEFAULT_DAILY_FLIGHT_HOURS 로 통합 (구:3.0 → 2.192)


def calc_d_time(
    aircraft_id: int,
    maintenance_schedule_id: int,
    current_flight_hours: float | None = None,
) -> dict:
    """
    특정 정비 스케줄에 대한 D-Time 카운터를 계산하고 d_time_counter 테이블을 갱신한다.
    기존 행이 있으면 UPDATE, 없으면 INSERT 분기 처리.

    Parameters
    ----------
    aircraft_id : int
        aircraft.id (PK)
    maintenance_schedule_id : int
        maintenance_schedule.id (PK).
        기존 component_type('engine'|'prop'|'airframe') 파라미터를 대체.
    current_flight_hours : float | None
        현재 누적 비행시간.
        None 이면 aircraft.total_flight_hours 에서 자동 조회.

    Returns
    -------
    dict
        {
            "d_time_id"        : int,
            "aircraft_id"      : int,
            "current_hours"    : float,
            "hours_remaining"  : float | None,   # 날짜기반 스케줄이면 None
            "days_remaining"   : int,
            "remaining_pct"    : float | None,   # 잔여 비율 0~1 (날짜기반=None)
            "last_updated"     : str,             # ISO 8601
            "status"           : str,             # 초과|임박|정상|날짜기반
        }

    Raises
    ------
    ValueError
        · aircraft_id 또는 maintenance_schedule_id 미존재
    RuntimeError
        · d_time_counter UPDATE/INSERT 실패
    """

    client  = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── aircraft 조회
    ac = (
        client.table("aircraft")
        .select("id, total_flight_hours")
        .eq("id", aircraft_id)
        .maybe_single()
        .execute()
    )
    if not ac.data:
        raise ValueError(f"aircraft_id {aircraft_id} 에 해당하는 항공기가 없습니다.")
    current_hours = float(
        current_flight_hours if current_flight_hours is not None
        else ac.data["total_flight_hours"]
    )

    # ── maintenance_schedule 조회
    sch = (
        client.table("maintenance_schedule")
        .select("id, interval_hours, due_hours")
        .eq("id", maintenance_schedule_id)
        .maybe_single()
        .execute()
    )
    if not sch.data:
        raise ValueError(
            f"maintenance_schedule_id {maintenance_schedule_id} 에 해당하는 스케줄이 없습니다."
        )

    interval_hours_raw = sch.data.get("interval_hours")
    interval_hours     = float(interval_hours_raw) if interval_hours_raw else 0.0
    due_hours_raw      = sch.data.get("due_hours")

    # ── 날짜기반 판별 (interval_hours=0이면 remaining_pct 나눗셈 시 ZeroDivisionError)
    is_date_based = (interval_hours == 0.0) or (due_hours_raw is None)

    if is_date_based:
        hours_remaining = None
        remaining_pct   = None
        days_remaining  = 9999          # 날짜기반: 시간 계산 불가 → 최대값 표기
        status          = "날짜기반"
    else:
        due_hours       = float(due_hours_raw) if due_hours_raw else current_hours + interval_hours
        hours_remaining = due_hours - current_hours
        remaining_pct   = round(hours_remaining / interval_hours, 4)
        days_remaining  = _estimate_days(client, aircraft_id, hours_remaining)
        status          = _status(hours_remaining, interval_hours)

    # ── d_time_counter: 기존 행 확인 → UPDATE / 없으면 INSERT
    existing = (
        client.table("d_time_counter")
        .select("id")
        .eq("aircraft_id", aircraft_id)
        .eq("maintenance_schedule_id", maintenance_schedule_id)
        .maybe_single()
        .execute()
    )

    payload: dict = {
        "current_hours":   current_hours,
        "hours_remaining": hours_remaining,   # None 허용 (날짜기반)
        "days_remaining":  days_remaining,
        "last_updated":    now_iso,
    }

    try:
        if existing and existing.data:
            d_id = existing.data["id"]
            client.table("d_time_counter").update(payload).eq("id", d_id).execute()
        else:
            payload.update({
                "aircraft_id":             aircraft_id,
                "maintenance_schedule_id": maintenance_schedule_id,
            })
            res = client.table("d_time_counter").insert(payload).execute()
            # INSERT 결과: Supabase SDK → list[dict], Mock → list or dict 모두 대응
            raw = res.data
            if isinstance(raw, list) and len(raw) > 0:
                d_id = raw[0]["id"]
            elif isinstance(raw, dict):
                d_id = raw.get("id")
            else:
                d_id = None
    except Exception as e:
        raise RuntimeError(f"d_time_counter 갱신 실패: {e}")

    return {
        "d_time_id":       d_id,
        "aircraft_id":     aircraft_id,
        "current_hours":   current_hours,
        "hours_remaining": hours_remaining,
        "days_remaining":  days_remaining,
        "remaining_pct":   remaining_pct,
        "last_updated":    now_iso,
        "status":          status,
    }


def _estimate_days(client, aircraft_id: int, hours_remaining: float) -> int:
    """최근 30일 실제 비행일수 기준 잔여 일수 추정. 이력 없으면 DEFAULT_DAILY 사용."""
    if hours_remaining <= 0:
        return 0

    try:
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        logs   = (
            client.table("flight_hours")
            .select("flight_date, flight_hours")
            .eq("aircraft_id", aircraft_id)
            .gte("flight_date", cutoff)
            .execute()
        )

        if not logs.data:
            return int(hours_remaining / DEFAULT_DAILY)

        total_hours  = sum(float(r["flight_hours"]) for r in logs.data)
        # 실제 비행이 기록된 날짜 수 (중복 제거) — 1 이상, 30 이하로 cap
        flight_days  = len({r["flight_date"] for r in logs.data})
        flight_days  = max(1, min(flight_days, 30))

        avg_per_day  = total_hours / flight_days
        if avg_per_day <= 0:
            return 9999

        return int(hours_remaining / avg_per_day)

    except Exception:
        # 조회 실패 시 기본값 사용
        return int(hours_remaining / DEFAULT_DAILY)


def _status(hours_remaining: float, interval_hours: float) -> str:
    if hours_remaining < 0:
        return "초과"
    # interval_hours=0 케이스는 호출 전에 is_date_based 로 분기했으므로 여기서는 0 불가
    if interval_hours > 0 and (hours_remaining / interval_hours) <= CRITICAL_PCT:
        return f"임박(≤{int(CRITICAL_PCT * 100)}%)"
    return "정상"


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-05-27  5월4주차 — Supabase 스키마 반영
#       · component_type 파라미터('engine'|'prop'|'airframe') 제거
#         → maintenance_schedule_id (FK) 로 대체 (더 명확한 연결)
#       · d_time_counter: 기존 행 확인 → UPDATE / 없으면 INSERT 분기 처리
#       · due_hours 없을 때 current + interval 로 추정
#       · days_remaining: 최근 30일 집계 → 일평균 계산, 없으면 3.0h/day
#
# v1.1  2026-06-03  테스트 기반 버그 3개 수정
#       · [버그 수정] interval_hours=0 → ZeroDivisionError 방어
#         기존: remaining_pct = hours_remaining / interval_hours → 0 나누기 오류
#         수정: interval_hours=0 이면 is_date_based=True, 계산 자체 스킵
#               status="날짜기반", hours_remaining=None, remaining_pct=None 반환
#
#       · [버그 수정] 날짜기반 스케줄에서 _estimate_days(inf) OverflowError
#         기존: float("inf")를 _estimate_days 에 전달 → int(inf/3.0) OverflowError
#         수정: is_date_based 이면 days_remaining=9999 고정값 반환
#               (_estimate_days 호출 자체를 하지 않음)
#
#       · [버그 수정] INSERT 결과 res.data[0]["id"] IndexError
#         기존: INSERT 결과가 빈 리스트로 오는 케이스에서 [0] 접근 시 IndexError
#         수정: list/dict/None 세 케이스 모두 안전하게 처리하는 로직으로 교체
#
#       · [개선] _estimate_days 일평균 계산 기준 수정
#         기존: 총비행시간 / 30.0 (고정 30일 나눗셈)
#              → 비행일 적을수록 일평균 과소 추정 (예: 10일간 25h → 0.83h/day)
#         수정: 총비행시간 / 실제비행일수 (1 ≤ 실비행일수 ≤ 30 으로 cap)
#              → 실제 비행 패턴 기반 정확도 향상
#
# 향후 변경 예정
#       · [P3 완료 후] aircraft.total_flight_hours numeric 변경 시
#         float() 형변환 단순화 가능
#       · [P3 트리거 추가 후] maintenance_schedule.status 자동 갱신 시
#         함수 내부 status 계산 결과를 트리거에 위임하는 방향으로 리팩토링 가능
# =============================================================================
