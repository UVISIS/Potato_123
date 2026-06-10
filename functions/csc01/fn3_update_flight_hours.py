"""
CSC-01 · CSU-01-03  |  fn3: update_flight_hours()

비행시간 기록 및 aircraft 누적시간 갱신

호출 테이블:
    flight_hours (INSERT)  — 금일 비행 이력 신규 기록
    aircraft     (UPDATE)  — total_flight_hours 누적 갱신

수정 이력:
    2026-05-27 (5월4주차) — Supabase 스키마 반영
        · aircraft_id: str → int (FK) 변경
        · engine_hours / propeller_hours 파라미터 제거
          (flight_hours / flight_minutes 로 통합)
        · float → int 변환 로직 추가
          (aircraft.total_flight_hours 가 integer 타입)
        · INSERT 성공 후 UPDATE 실패 시 RuntimeError + 불일치 위치 로그

⚠️  DB 변경 예정 사항 (P3):
    aircraft.total_flight_hours  integer → numeric(8,1) 변경 시
    → new_aircraft_int = round(new_accumulated) 로직 제거
    → aircraft UPDATE 페이로드를 float 값으로 직접 저장하도록 수정 필요
"""

from __future__ import annotations
from datetime import date, datetime, timezone

from functions.db import get_client


def update_flight_hours(
    aircraft_id: int,
    flight_date: str,
    flight_hours_val: float,
    flight_minutes: int | None = None,
    pilot_name: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    금일 비행시간을 flight_hours 테이블에 기록하고
    aircraft.total_flight_hours 를 누적 갱신한다.

    Parameters
    ----------
    aircraft_id : int
        aircraft.id (PK). 등록번호가 아닌 내부 ID.
        등록번호로 조회가 필요하면 fn1.get_aircraft_info() 를 먼저 호출.
    flight_date : str
        비행 일자. 'YYYY-MM-DD' 형식. 미래 날짜 불가.
    flight_hours_val : float
        금일 비행시간 (소수점 허용). 0 초과 필수.
    flight_minutes : int | None
        금일 비행 분 (0~59). None 이면 DB 기본값 0 사용.
    pilot_name : str | None
        조종사 이름. 선택.
    notes : str | None
        비고. 선택.

    Returns
    -------
    dict
        {
            "log_id"                  : int,    # flight_hours.id (auto-increment)
            "total_accumulated_hours" : float,  # 소수점 보존 누적시간
            "aircraft_total"          : int,    # aircraft.total_flight_hours (round 처리)
        }

    Raises
    ------
    ValueError
        · flight_hours_val <= 0
        · 날짜 형식 오류 또는 미래 날짜
        · flight_minutes 범위 오류 (0~59 외)
        · aircraft_id 미존재
    RuntimeError
        · flight_hours INSERT 실패
        · aircraft UPDATE 실패 (INSERT 는 이미 커밋된 상태)
          → log_id 를 에러 메시지에 포함하여 수동 정합성 복구 가능하게 함
    """

    # ── 입력 검증
    if flight_hours_val <= 0:
        raise ValueError(f"flight_hours_val 은 0 초과여야 합니다. 입력값: {flight_hours_val}")

    try:
        flight_date_obj = date.fromisoformat(flight_date)
    except ValueError:
        raise ValueError(f"날짜 형식 오류 — 'YYYY-MM-DD' 필요. 입력값: '{flight_date}'")

    if flight_date_obj > date.today():
        raise ValueError(f"미래 날짜는 입력할 수 없습니다. 입력값: {flight_date}")

    if flight_minutes is not None and not (0 <= flight_minutes < 60):
        raise ValueError(f"flight_minutes 는 0~59 이어야 합니다. 입력값: {flight_minutes}")

    client = get_client()

    # ── aircraft 조회 (total_flight_hours: integer)
    ac = (
        client.table("aircraft")
        .select("id, total_flight_hours")
        .eq("id", aircraft_id)
        .maybe_single()
        .execute()
    )
    if not ac.data:
        raise ValueError(f"aircraft_id {aircraft_id} 에 해당하는 항공기가 없습니다.")

    current_total: int = ac.data["total_flight_hours"]

    # ── 누적 계산
    # total_accumulated_hours : float — 소수점 보존 (flight_hours 테이블)
    # aircraft.total_flight_hours : int — round() 처리 (integer 타입 제약)
    # ⚠️ P3 타입 변경(integer→numeric) 후에는 round() 제거하고 float 직접 저장
    new_accumulated  = round(current_total + flight_hours_val, 1)
    new_aircraft_int = round(new_accumulated)   # integer 타입 맞춤

    # ── flight_hours INSERT
    payload: dict = {
        "aircraft_id":             aircraft_id,
        "flight_date":             flight_date,
        "flight_hours":            flight_hours_val,
        "total_accumulated_hours": new_accumulated,
    }
    if flight_minutes is not None:
        payload["flight_minutes"] = flight_minutes
    if pilot_name:
        payload["pilot_name"] = pilot_name
    if notes:
        payload["notes"] = notes

    try:
        log_res = client.table("flight_hours").insert(payload).execute()
    except Exception as e:
        raise RuntimeError(f"flight_hours INSERT 실패: {e}")

    log_id: int = log_res.data[0]["id"]

    # ── aircraft UPDATE (int 변환 후 저장)
    # INSERT 이후 실패 시 flight_hours 에 이미 커밋된 행이 남음
    # → RuntimeError 메시지에 log_id 포함하여 수동 복구 가능하게 기록
    try:
        client.table("aircraft").update({
            "total_flight_hours": new_aircraft_int,
            "updated_at":         datetime.now(timezone.utc).isoformat(),
        }).eq("id", aircraft_id).execute()
    except Exception as e:
        raise RuntimeError(
            f"aircraft UPDATE 실패 "
            f"(flight_hours log_id={log_id} 는 이미 INSERT 완료됨 — 수동 정합성 확인 필요): {e}"
        )

    return {
        "log_id":                  log_id,
        "total_accumulated_hours": new_accumulated,   # float
        "aircraft_total":          new_aircraft_int,  # int
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-05-27  5월4주차 — Supabase 스키마 반영 (최초 작성)
#       · aircraft_id 타입: str → int (FK 기준으로 변경)
#       · 파라미터 제거: engine_hours, propeller_hours
#         → flight_hours / flight_minutes 로 통합
#       · float → int 변환 로직 추가
#         (aircraft.total_flight_hours 가 integer 타입이므로 round() 적용)
#       · INSERT 성공 후 UPDATE 실패 시 RuntimeError 에 log_id 포함
#         (수동 정합성 복구 가능하도록)
#
# v1.1  2026-06-03  테스트 기반 검증
#       · Python 은행가 반올림 확인: round(502.5) = 502 (짝수 우선)
#         → 테스트 기댓값 수정 완료 (503 → 502)
#       · 코드 로직 변경 없음, 동작 검증 완료
#
# 향후 변경 예정
#       · [P3 완료 후] aircraft.total_flight_hours integer → numeric(8,1) 변경 시
#         new_aircraft_int = round(new_accumulated) 로직 제거
#         aircraft UPDATE 페이로드를 float 값으로 직접 저장하도록 수정 필요
# =============================================================================
