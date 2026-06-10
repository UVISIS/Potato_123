from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import maintenance_not_found, schedule_not_found, db_error
# fn 연동
from functions.csc04.fn11_calc_next_maintenance import calc_next_maintenance
from functions.csc04.fn12_calc_d_time import calc_d_time
from functions.csc04.fn9_fn10_parts_check import get_required_parts, check_parts_availability as fn10_check
from functions.csc04.fn14_generate_maintenance_alarms import generate_maintenance_alarms


router = APIRouter(prefix="/maintenance", tags=["CSC-04 주기정비 관리"])


# ── 요청 모델 ──────────────────────────────────

class MaintenancePart(BaseModel):
    part_id: int
    quantity: int

class MaintenanceHistoryCreate(BaseModel):
    aircraft_id: int
    maintenance_date: str
    maintenance_type: str               # 기체100HRS / 엔진300HRS / MSB 등
    hours_at_maintenance: float         # 정비 당시 누적 비행시간
    next_due_date: Optional[str] = None
    handled_by: str                     # 담당 정비사
    parts_used: Optional[List[MaintenancePart]] = []  # 교체 부품 목록
    notes: Optional[str] = None

class MaintenanceScheduleUpdate(BaseModel):
    due_hours: Optional[float] = None
    due_date: Optional[str] = None
    status: Optional[str] = None

# ── 요청 모델 추가 ─────────────────────────────

class AlertCreate(BaseModel):
    aircraft_id: int
    alarm_type: str
    severity: str        # critical / warning / info
    message: str
    maintenance_schedule_id: Optional[int] = None
    user_id: Optional[str] = None

# ── 정비 이력 관리 ─────────────────────────────

@router.post("/history")
def create_maintenance_history(data: MaintenanceHistoryCreate):
    """정비 이력 등록 (팝업F) - 정비 기록 + 부품 출고 자동 처리"""
    # 1. maintenance_history INSERT
    history_data = {
        "aircraft_id": data.aircraft_id,
        "maintenance_date": data.maintenance_date,
        "maintenance_type": data.maintenance_type,
        "hours_at_maintenance": data.hours_at_maintenance,
        "next_due_date": data.next_due_date,
        "handled_by": data.handled_by,
        "work_description": data.notes
    }
    history = supabase.table("maintenance_history").insert(history_data).execute()
    history_id = history.data[0]["id"]

    # 2. d_time_counter 갱신
    supabase.table("d_time_counter")\
        .update({
            "current_hours": data.hours_at_maintenance,
            "last_updated": "now()"
        })\
        .eq("aircraft_id", data.aircraft_id).execute()

    # 3. maintenance_schedule 다음 주기 업데이트
    supabase.table("maintenance_schedule")\
        .update({"status": "completed"})\
        .eq("aircraft_id", data.aircraft_id)\
        .eq("maintenance_type", data.maintenance_type).execute()

    # 4. 교체 부품 출고 자동 처리
    parts_warning = []
    for part in data.parts_used:
        # parts_transactions INSERT (출고)
        supabase.table("parts_transactions").insert({
            "part_id": part.part_id,
            "transaction_type": "출고",
            "quantity": part.quantity,
            "transaction_date": data.maintenance_date,
            "aircraft_id": data.aircraft_id,
            "maintenance_type": data.maintenance_type,
            "handled_by": data.handled_by,
            "maintenance_history_id": history_id
        }).execute()

        # parts_inventory 차감
        inventory = supabase.table("parts_inventory")\
            .select("quantity_on_hand")\
            .eq("part_id", part.part_id).execute()

        if inventory.data:
            current_qty = inventory.data[0]["quantity_on_hand"]
            new_qty = current_qty - part.quantity
            supabase.table("parts_inventory")\
                .update({"quantity_on_hand": new_qty})\
                .eq("part_id", part.part_id).execute()

            # 안전재고 미달 체크
            reorder = supabase.table("reorder_points")\
                .select("safety_stock")\
                .eq("part_id", part.part_id).execute()
            if reorder.data and new_qty <= reorder.data[0]["safety_stock"]:
                parts_warning.append(f"부품 ID {part.part_id}: 안전재고 미달 (잔여: {new_qty}개)")

    return {
        "message": "정비 이력이 등록되었습니다",
        "history_id": history_id,
        "warnings": parts_warning if parts_warning else None
    }

@router.get("/history")
def get_maintenance_history(
    aircraft_id: Optional[int] = None,
    maintenance_type: Optional[str] = None
):
    """정비 이력 조회 (기체번호/정비종류 필터)"""
    query = supabase.table("maintenance_history").select("*")
    if aircraft_id:
        query = query.eq("aircraft_id", aircraft_id)
    if maintenance_type:
        query = query.eq("maintenance_type", maintenance_type)
    return query.order("maintenance_date", desc=True).execute().data

@router.get("/history/{history_id}")
def get_maintenance_history_by_id(history_id: int):
    """특정 정비 이력 조회"""
    response = supabase.table("maintenance_history")\
        .select("*").eq("id", history_id).execute()
    if not response.data:
        maintenance_not_found(history_id)
    return response.data[0]


# ── 주기정비 현황 ──────────────────────────────

@router.get("/schedule")
def get_maintenance_schedule(aircraft_id: Optional[int] = None):
    """주기정비 일정 조회"""
    query = supabase.table("maintenance_schedule").select("*")
    if aircraft_id:
        query = query.eq("aircraft_id", aircraft_id)
    return query.execute().data

@router.get("/d-time")
def get_d_time(aircraft_id: Optional[int] = None):
    """D-Time 카운터 조회 (다음 정비까지 남은 시간)"""
    query = supabase.table("d_time_counter").select("*")
    if aircraft_id:
        query = query.eq("aircraft_id", aircraft_id)
    return query.execute().data

# ── CSC-04 추가 엔드포인트 ──────────────────────

@router.get("/next/{aircraft_id}")
def get_next_maintenance(aircraft_id: int):
    """다음 정비 도래시점 조회 (fn11 래핑)"""
    try:
        return calc_next_maintenance(aircraft_id)
    except LookupError:
        schedule_not_found(aircraft_id)
    except Exception as e:
        return {"error": str(e)}

@router.get("/d-time/{aircraft_id}")
def get_d_time_by_aircraft(aircraft_id: int):
    """D-Time 카운터 조회 (fn12 래핑)"""
    try:
        return calc_d_time(aircraft_id)
    except LookupError:
        schedule_not_found(aircraft_id)
    except Exception as e:
        return {"error": str(e)}

@router.get("/required-parts/{aircraft_id}")
def get_required_parts_api(aircraft_id: int, maintenance_type: str):
    """정비 유형별 필요 부품 목록 (fn9 래핑)"""
    try:
        return get_required_parts(str(aircraft_id), maintenance_type)
    except Exception as e:
        return {"error": str(e)}

@router.get("/parts-check/{aircraft_id}")
def check_parts_availability(aircraft_id: int, maintenance_type: str):
    """정비 전 부품 재고 충족 여부 확인 (fn10 래핑)"""
    try:
        return fn10_check(aircraft_id, maintenance_type)
    except Exception as e:
        return {"error": str(e)}

@router.post("/alerts")
def create_alert(data: AlertCreate):
    """정비/재고 알람 생성 (fn14 래핑)"""
    try:
        return generate_maintenance_alarms(
            aircraft_id=data.aircraft_id,
            create_notifications=True,
            notify_user_id=data.user_id
        )
    except Exception as e:
        return {"error": str(e)}