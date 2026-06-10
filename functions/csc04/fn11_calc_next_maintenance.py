from __future__ import annotations
from functions.db import get_client


CRITICAL_HOURS = 10.0   # 잔여시간 ≤ 10h → 임박
WARNING_HOURS  = 30.0   # 잔여시간 ≤ 30h → 주의

# maintenance_schedule.status 허용값
ACTIVE_STATUSES = ("scheduled", "overdue")


def calc_next_maintenance(
    aircraft_id: int,
    schedule_id: int | None = None,
    active_only: bool = True,
) -> list[dict]:
    """
    항공기의 다음 정비 도래시점을 계산하여 임박 순으로 반환한다.

    Parameters
    ----------
    aircraft_id : int
        aircraft.id (PK)
    schedule_id : int | None
        특정 스케줄만 조회할 때 지정.
        None 이면 해당 기체의 전체 스케줄 조회.
    active_only : bool
        True  → status IN ('scheduled','overdue') 인 스케줄만 조회 (기본)
        False → 완료(completed) 포함 전체 스케줄 조회

    Returns
    -------
    list[dict]
        remaining_hours 오름차순 정렬 (임박한 정비 먼저).
        날짜기반 스케줄은 remaining_hours=None 으로 리스트 뒤쪽에 위치.
        각 항목:
        {
            "schedule_id"      : int,
            "aircraft_id"      : int,
            "maintenance_type" : str,
            "interval_hours"   : float,
            "interval_months"  : int | None,
            "due_hours"        : float | None,
            "due_date"         : str | None,    # YYYY-MM-DD
            "current_hours"    : int,
            "remaining_hours"  : float | None,  # None = 날짜기반
            "status"           : str,           # 초과|임박|주의|정상|날짜기반
        }

    Raises
    ------
    ValueError
        aircraft_id 미존재
    LookupError
        조건에 맞는 스케줄 없음
    """

    client = get_client()

    # ── aircraft.total_flight_hours 조회 (integer)
    ac = (
        client.table("aircraft")
        .select("id, total_flight_hours")
        .eq("id", aircraft_id)
        .maybe_single()
        .execute()
    )
    if not ac.data:
        raise ValueError(f"aircraft_id {aircraft_id} 에 해당하는 항공기가 없습니다.")
    current_hours: int = ac.data["total_flight_hours"]

    # ── maintenance_schedule 조회
    q = (
        client.table("maintenance_schedule")
        .select(
            "id, aircraft_id, maintenance_type, "
            "interval_hours, interval_months, "
            "due_hours, due_date, status"
        )
        .eq("aircraft_id", aircraft_id)
    )
    if schedule_id is not None:
        q = q.eq("id", schedule_id)
    if active_only:
        q = q.in_("status", list(ACTIVE_STATUSES))

    scheds = q.execute()

    if not scheds.data:
        scope = f"schedule_id={schedule_id}" if schedule_id else "전체 스케줄"
        raise LookupError(
            f"aircraft_id={aircraft_id} 의 {scope} 에서 조건에 맞는 스케줄이 없습니다. "
            f"(active_only={active_only})"
        )

    results: list[dict] = []
    for s in scheds.data:
        due_hours_raw    = s.get("due_hours")
        interval_hours   = float(s["interval_hours"]) if s.get("interval_hours") else 0.0

        # due_hours=None(기산점 없음) 또는 interval_hours=0(날짜 주기)은 시간 계산 불가 → 날짜기반
        is_date_based = (due_hours_raw is None) or (interval_hours == 0.0)

        if is_date_based:
            remaining = None
            status    = "날짜기반"
        else:
            remaining = float(due_hours_raw) - float(current_hours)
            status    = _status(remaining)

        results.append({
            "schedule_id":      s["id"],
            "aircraft_id":      aircraft_id,
            "maintenance_type": s["maintenance_type"],
            "interval_hours":   interval_hours,
            "interval_months":  s.get("interval_months"),
            "due_hours":        float(due_hours_raw) if due_hours_raw is not None else None,
            "due_date":         str(s["due_date"]) if s.get("due_date") else None,
            "current_hours":    current_hours,
            "remaining_hours":  remaining,
            "status":           status,
        })

    # 잔여시간 오름차순 (임박한 정비 먼저, 날짜기반은 뒤로)
    results.sort(
        key=lambda x: x["remaining_hours"] if x["remaining_hours"] is not None else float("inf")
    )
    return results


def _status(remaining: float) -> str:
    if remaining < 0:
        return "초과"
    if remaining <= CRITICAL_HOURS:
        return f"임박(≤{int(CRITICAL_HOURS)}h)"
    if remaining <= WARNING_HOURS:
        return f"주의(≤{int(WARNING_HOURS)}h)"
    return "정상"


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-05-27  5월4주차 — 신규 작성
#       · due_hours=None 인 경우 "날짜기반"으로 분류
#       · 잔여시간 기준 임박/주의/초과/정상 4단계 상태 판정
#       · remaining_hours 오름차순 정렬 (임박한 정비 먼저)
#
# v1.1  2026-06-03  실제 DB 데이터 기반 보완
#       · interval_hours=0 인 순수 날짜 주기 스케줄 처리 추가
#         (예: V-Ribbed Belt 5년 교체 — 실제 DB에 6건 확인)
#         기존: due_hours=None 일 때만 "날짜기반" 분류
#         수정: interval_hours=0 케이스도 is_date_based 로 통합 처리
#         → ZeroDivisionError 및 잘못된 계산 방지
#       · active_only 파라미터 추가 (기본 True)
#         False 이면 완료(completed) 포함 전체 스케줄 조회 가능
#
# 향후 변경 예정
#       · 날짜기반(is_date_based=True) 스케줄의 due_date 기반 잔여 일수 계산
#         5주차 추가 예정
#       · [P3 완료 후] aircraft.total_flight_hours numeric 변경 시
#         float() 형변환 코드 단순화 가능
#       · [P3 트리거 추가 후] maintenance_schedule.status 자동 갱신 시
#         fn11 내부 status 판단값을 schedule status 에 직접 반영하는 로직 추가 가능
# =============================================================================
