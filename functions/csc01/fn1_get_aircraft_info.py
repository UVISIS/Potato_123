"""
CSC-01 · CSU-01-01  |  fn1: get_aircraft_info()

항공기 기본 정보 조회

호출 테이블:
    aircraft (SELECT) — 기체 기본 정보
    flight_hours (SELECT) — 최근 비행 이력
    maintenance_schedule (SELECT) — 활성 정비 스케줄 수

⚠️  DB 변경 영향 없음 — 안정 함수
"""

from __future__ import annotations
from functions.db import get_client


# ── 조회 모드 상수
LOOKUP_BY_ID           = "id"           # aircraft.id (PK)
LOOKUP_BY_REGISTRATION = "registration" # 등록번호 (예: HL1254)


def get_aircraft_info(
    value: int | str,
    lookup_by: str = LOOKUP_BY_ID,
    include_recent_flights: bool = False,
    recent_flight_limit: int = 5,
) -> dict:
    """
    항공기 기본 정보를 조회한다.

    Parameters
    ----------
    value : int | str
        조회 기준값.
        - lookup_by="id"           → aircraft.id (int)
        - lookup_by="registration" → 등록번호 문자열 (str)
    lookup_by : str
        조회 기준 컬럼. "id" 또는 "registration" (기본: "id")
    include_recent_flights : bool
        True 이면 최근 비행 이력을 result["recent_flights"] 에 포함 (기본: False)
    recent_flight_limit : int
        최근 비행 이력 조회 건수 (기본: 5, 최대: 20)

    Returns
    -------
    dict
        {
            "aircraft_id"          : int,
            "registration"         : str,   # 등록번호 (HL1254 등)
            "model"                : str,   # Diamond DA40 NG 등
            "category"             : str,   # DA-40 NG / DA-42 NG
            "status"               : str,   # operational / grounded 등
            "serial_number"        : str | None,
            "manufacture_year"     : int | None,
            "total_flight_hours"   : int,   # aircraft 테이블 기준 (누적 정수)
            "accumulated_hours"    : float | None,  # flight_hours 기준 소수점 누적
            "last_inspection_date" : str | None,   # YYYY-MM-DD
            "active_schedule_count": int,   # 진행 중인 정비 스케줄 수
            "recent_flights"       : list[dict] | None,  # include_recent_flights=True 시
        }

    Raises
    ------
    ValueError
        lookup_by 값이 유효하지 않을 때
        해당 항공기가 존재하지 않을 때
    """

    # ── 입력 검증
    if lookup_by not in {LOOKUP_BY_ID, LOOKUP_BY_REGISTRATION}:
        raise ValueError(
            f"lookup_by는 '{LOOKUP_BY_ID}' 또는 '{LOOKUP_BY_REGISTRATION}' 이어야 합니다. "
            f"입력값: '{lookup_by}'"
        )

    if lookup_by == LOOKUP_BY_ID and not isinstance(value, int):
        raise ValueError(f"lookup_by='id' 일 때 value는 int 이어야 합니다. 입력값: {value!r}")

    if lookup_by == LOOKUP_BY_REGISTRATION and not isinstance(value, str):
        raise ValueError(
            f"lookup_by='registration' 일 때 value는 str 이어야 합니다. 입력값: {value!r}"
        )

    recent_flight_limit = min(max(1, recent_flight_limit), 20)

    client = get_client()

    # ── aircraft 조회
    q = client.table("aircraft").select(
        "id, registration, model, category, status, "
        "serial_number, manufacture_year, "
        "total_flight_hours, last_inspection_date"
    )

    if lookup_by == LOOKUP_BY_ID:
        q = q.eq("id", value)
    else:
        q = q.eq("registration", value)

    ac = q.maybe_single().execute()

    if not ac.data:
        field = "aircraft.id" if lookup_by == LOOKUP_BY_ID else "registration"
        raise ValueError(f"항공기를 찾을 수 없습니다. [{field} = {value!r}]")

    data = ac.data
    aircraft_id: int = data["id"]

    # aircraft.total_flight_hours는 integer로 소수점 손실 — flight_hours에서 정밀값 조회
    latest_log = (
        client.table("flight_hours")
        .select("total_accumulated_hours")
        .eq("aircraft_id", aircraft_id)
        .order("flight_date", desc=True)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    accumulated_hours: float | None = None
    if latest_log.data:
        raw = latest_log.data[0].get("total_accumulated_hours")
        if raw is not None:
            accumulated_hours = float(raw)

    # ── 활성 정비 스케줄 수 (status = 'scheduled' 또는 'overdue')
    active_schedules = (
        client.table("maintenance_schedule")
        .select("id", count="exact")
        .eq("aircraft_id", aircraft_id)
        .in_("status", ["scheduled", "overdue"])
        .execute()
    )
    active_schedule_count: int = active_schedules.count or 0

    # ── 최근 비행 이력 (옵션)
    recent_flights: list[dict] | None = None
    if include_recent_flights:
        logs = (
            client.table("flight_hours")
            .select("id, flight_date, flight_hours, flight_minutes, "
                    "total_accumulated_hours, pilot_name, notes")
            .eq("aircraft_id", aircraft_id)
            .order("flight_date", desc=True)
            .order("id", desc=True)
            .limit(recent_flight_limit)
            .execute()
        )
        recent_flights = [
            {
                "log_id":                  r["id"],
                "flight_date":             r["flight_date"],
                "flight_hours":            float(r["flight_hours"]),
                "flight_minutes":          r.get("flight_minutes"),
                "total_accumulated_hours": (
                    float(r["total_accumulated_hours"])
                    if r.get("total_accumulated_hours") is not None else None
                ),
                "pilot_name":              r.get("pilot_name"),
                "notes":                   r.get("notes"),
            }
            for r in (logs.data or [])
        ]

    # ── 결과 반환
    return {
        "aircraft_id":           aircraft_id,
        "registration":          data["registration"],
        "model":                 data.get("model"),
        "category":              data.get("category"),
        "status":                data.get("status"),
        "serial_number":         data.get("serial_number"),
        "manufacture_year":      data.get("manufacture_year"),
        "total_flight_hours":    data["total_flight_hours"],      # int (aircraft 기준)
        "accumulated_hours":     accumulated_hours,               # float | None (정밀값)
        "last_inspection_date":  (
            str(data["last_inspection_date"])
            if data.get("last_inspection_date") else None
        ),
        "active_schedule_count": active_schedule_count,
        "recent_flights":        recent_flights,
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-03  최초 작성
#       · aircraft.id 및 등록번호(registration) 두 가지 방식으로 조회 지원
#       · include_recent_flights=True 시 최근 비행 이력 포함 반환
#       · flight_hours.total_accumulated_hours 로 소수점 정밀 누적시간 별도 제공
#         (aircraft.total_flight_hours 는 integer 타입으로 소수점 손실 있음)
#       · active_schedule_count: maintenance_schedule 에서 scheduled/overdue 자동 집계
#
# 향후 변경 예정
#       · [P3 완료 후] aircraft.total_flight_hours → numeric(8,1) 변경되면
#         total_flight_hours 반환값도 float 으로 변경 가능
#         (현재는 integer 반환하여 프론트와 타입 불일치 없음)
#       · DB 변경 영향 없음 — 안정 함수
# =============================================================================
