from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import aircraft_not_found, invalid_input, db_error

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


# ── 기체 CRUD ──────────────────────────────────

@router.get("")
def get_aircraft():
    """전체 기체 목록 조회"""
    response = supabase.table("aircraft").select("*").execute()
    return response.data

@router.get("/{aircraft_id}")
def get_aircraft_by_id(aircraft_id: int):
    """특정 기체 정보 조회"""
    response = supabase.table("aircraft").select("*").eq("id", aircraft_id).execute()
    if not response.data:
        aircraft_not_found(aircraft_id)
    return response.data[0]

@router.post("")
def create_aircraft(data: AircraftCreate):
    """새 기체 추가"""
    response = supabase.table("aircraft").insert(data.dict()).execute()
    return response.data[0]

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
    """비행시간 기록 추가 (매 비행마다)"""
    # flight_hours 테이블에 기록 추가
    record = data.dict()
    record["aircraft_id"] = aircraft_id
    response = supabase.table("flight_hours").insert(record).execute()

    # aircraft 누적 비행시간 업데이트
    aircraft = supabase.table("aircraft").select("total_flight_hours").eq("id", aircraft_id).execute()
    current_hours = aircraft.data[0]["total_flight_hours"] or 0
    new_hours = current_hours + data.flight_hours
    supabase.table("aircraft").update({"total_flight_hours": new_hours}).eq("id", aircraft_id).execute()

    return {"message": "비행시간이 입력되었습니다", "total_flight_hours": new_hours}

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