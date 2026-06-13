from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import aircraft_not_found, invalid_input, db_error, error_response, ErrorCode

# fn 연동
from functions.csc01.fn1_get_aircraft_info import get_aircraft_info
from functions.csc01.fn3_update_flight_hours import update_flight_hours as fn3_update_flight_hours
from functions.csc04.fn16_seed_maintenance_schedule import (
    copy_maintenance_schedule,
    register_maintenance_schedule,
)

router = APIRouter(prefix="/aircraft", tags=["CSC-01 항공기 관리"])


# ── 요청 모델 ──────────────────────────────────

class AircraftCreate(BaseModel):
    category: str
    registration: str
    model: str
    serial_number: str
    manufacture_year: Optional[int] = None
    total_flight_hours: Optional[float] = 0
    status: Optional[str] = "operational"

class FlightHoursCreate(BaseModel):
    flight_date: str
    flight_hours: float
    flight_minutes: Optional[int] = 0
    pilot_name: Optional[str] = None
    notes: Optional[str] = None

class FlightHoursUpdate(BaseModel):
    total_flight_hours: float

class ScheduleItem(BaseModel):
    maintenance_type: str
    interval_hours: float                # 시간기반(0이면 순수 날짜주기)
    interval_months: Optional[int] = None

class ScheduleRegister(BaseModel):
    schedules: list[ScheduleItem]


# ── 기체 CRUD ──────────────────────────────────

@router.get("")
def get_aircraft():
    """전체 기체 목록 조회"""
    response = supabase.table("aircraft").select("*").execute()
    return response.data

@router.get("/{aircraft_id}")
def get_aircraft_by_id(aircraft_id: int):
    """특정 기체 정보 조회 (fn1 래핑)"""
    try:
        return get_aircraft_info(aircraft_id)
    except LookupError:
        aircraft_not_found(aircraft_id)

@router.post("")
def create_aircraft(data: AircraftCreate):
    """새 기체 추가 + 정비 스케줄 후처리

    등록 직후 동일 기종 기존 기체가 있으면 정비 스케줄을 자동 복사한다.
    동일 기종이 없으면(신규 기종) 복사하지 않고, 작업자가
    POST /aircraft/{id}/maintenance-schedule 로 수동 등록하도록 안내한다.
    """
    response = supabase.table("aircraft").insert(data.dict()).execute()
    new_aircraft = response.data[0]
    aircraft_id = new_aircraft["id"]

    # 정비 스케줄 자동 복사 (동일 기종 존재 시)
    try:
        schedule_result = copy_maintenance_schedule(aircraft_id)
    except LookupError:
        schedule_result = {
            "copied": 0,
            "needs_manual_registration": True,
            "note": "동일 기종 기준 기체가 없습니다(신규 기종). "
                    "POST /aircraft/{id}/maintenance-schedule 로 정비 스케줄을 등록하세요.",
        }
    except Exception as e:
        schedule_result = {"copied": 0, "error": str(e)}

    return {"aircraft": new_aircraft, "maintenance_schedule": schedule_result}

@router.put("/{aircraft_id}")
def update_aircraft(aircraft_id: int, data: AircraftCreate):
    """기체 정보 수정"""
    response = supabase.table("aircraft").update(data.dict()).eq("id", aircraft_id).execute()
    if not response.data:
        aircraft_not_found(aircraft_id)
    return response.data[0]

@router.delete("/{aircraft_id}")
def delete_aircraft(aircraft_id: int):
    """기체 삭제"""
    response = supabase.table("aircraft").delete().eq("id", aircraft_id).execute()
    if not response.data:
        aircraft_not_found(aircraft_id)
    return {"message": "기체가 삭제되었습니다"}


# ── 비행시간 관리 ──────────────────────────────

@router.post("/{aircraft_id}/flight-hours")
def add_flight_hours(aircraft_id: int, data: FlightHoursCreate):
    """비행시간 기록 추가 (매 비행마다) — fn3 래핑

    flight_hours INSERT + aircraft.total_flight_hours 누적 갱신을
    fn3(update_flight_hours)로 원자적 처리. 입력 검증/미래날짜/분 범위
    체크가 함수 내부에서 일괄 수행된다.
    """
    try:
        result = fn3_update_flight_hours(
            aircraft_id=aircraft_id,
            flight_date=data.flight_date,
            flight_hours_val=data.flight_hours,
            flight_minutes=data.flight_minutes,
            pilot_name=data.pilot_name,
            notes=data.notes,
        )
        return {
            "message": "비행시간이 입력되었습니다",
            "log_id": result["log_id"],
            "total_flight_hours": result["aircraft_total"],
            "total_accumulated_hours": result["total_accumulated_hours"],
        }
    except ValueError as e:
        invalid_input(str(e))
    except Exception as e:
        return {"error": str(e)}

@router.get("/{aircraft_id}/flight-hours")
def get_flight_hours(aircraft_id: int):
    """비행시간 이력 조회"""
    response = supabase.table("flight_hours").select("*").eq("aircraft_id", aircraft_id).execute()
    return response.data

@router.put("/{aircraft_id}/flight-hours")
def update_flight_hours(aircraft_id: int, data: FlightHoursUpdate):
    """비행시간 직접 갱신 (대시보드 갱신 버튼)"""
    # aircraft 테이블 업데이트
    supabase.table("aircraft")\
        .update({"total_flight_hours": data.total_flight_hours})\
        .eq("id", aircraft_id).execute()

    # d_time_counter 업데이트
    supabase.table("d_time_counter")\
        .update({"current_hours": data.total_flight_hours})\
        .eq("aircraft_id", aircraft_id).execute()

    return {"message": "비행시간이 갱신되었습니다", "total_flight_hours": data.total_flight_hours}

# ── 정비 스케줄 시딩 (신규 기종 수동 등록 / 복사 재시도) ──────

@router.post("/{aircraft_id}/maintenance-schedule")
def register_schedule(aircraft_id: int, data: ScheduleRegister):
    """신규 기종 기체 정비 스케줄 수동 등록 (fn16 register 래핑)

    동일 기종이 없어 자동 복사가 안 된 신규 기종 기체에 대해
    작업자가 정비 주기를 직접 정의해 등록한다.
    """
    try:
        return register_maintenance_schedule(
            aircraft_id,
            [s.dict() for s in data.schedules],
        )
    except ValueError as e:
        invalid_input(str(e))
    except Exception as e:
        return {"error": str(e)}

@router.post("/{aircraft_id}/maintenance-schedule/copy")
def copy_schedule(aircraft_id: int, source_aircraft_id: Optional[int] = None):
    """동일 기종 기체에서 정비 스케줄 복사 (fn16 copy 래핑)

    create_aircraft 자동 복사가 누락됐거나, 원본 기체를 명시 지정해
    다시 복사하고 싶을 때 사용. source_aircraft_id 미지정 시 동일 기종 자동 탐색.
    """
    try:
        return copy_maintenance_schedule(aircraft_id, source_aircraft_id)
    except LookupError as e:
        error_response(404, ErrorCode.SCHEDULE_NOT_FOUND, str(e))
    except ValueError as e:
        invalid_input(str(e))
    except Exception as e:
        return {"error": str(e)}
