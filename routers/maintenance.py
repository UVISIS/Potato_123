from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import maintenance_not_found, schedule_not_found, db_error

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
    response = supabase.table("maintenance_schedule")\
        .select("*")\
        .eq("aircraft_id", aircraft_id)\
        .order("due_hours").execute()
    if not response.data:
        schedule_not_found(aircraft_id)
    return response.data

@router.get("/d-time/{aircraft_id}")
def get_d_time_by_aircraft(aircraft_id: int):
    """D-Time 카운터 조회 (fn12 래핑)"""
    response = supabase.table("d_time_counter")\
        .select("*, maintenance_schedule(*)")\
        .eq("aircraft_id", aircraft_id).execute()
    if not response.data:
        schedule_not_found(aircraft_id)
    return response.data

@router.get("/required-parts/{aircraft_id}")
def get_required_parts(aircraft_id: int, maintenance_type: str):
    """정비 유형별 필요 부품 목록 (fn9 래핑)"""
    response = supabase.table("components")\
        .select("*, parts_inventory(*)")\
        .eq("inspection_interval", maintenance_type).execute()
    return response.data

@router.get("/parts-check/{aircraft_id}")
def check_parts_availability(aircraft_id: int, maintenance_type: str):
    """정비 전 부품 재고 충족 여부 확인 (fn10 래핑)"""
    parts = supabase.table("components")\
        .select("*, parts_inventory(*)")\
        .eq("inspection_interval", maintenance_type).execute()

    shortage = []
    for part in parts.data:
        inventory = part.get("parts_inventory")
        if inventory and isinstance(inventory, list):
            qty = inventory[0].get("quantity_on_hand", 0) if inventory else 0
        elif inventory:
            qty = inventory.get("quantity_on_hand", 0)
        else:
            qty = 0
        if qty <= 0:
            shortage.append({
                "part_id": part["id"],
                "nomenclature": part["nomenclature"],
                "part_number": part["part_number"],
                "current_stock": qty
            })

    return {
        "available": len(shortage) == 0,
        "shortage_items": shortage
    }

@router.post("/alerts")
def create_alert(data: AlertCreate):
    """정비/재고 알람 생성 (fn14 래핑)"""
    # maintenance_alarms INSERT
    alarm = supabase.table("maintenance_alarms").insert({
        "aircraft_id": data.aircraft_id,
        "alarm_type": data.alarm_type,
        "severity": data.severity,
        "message": data.message,
        "maintenance_schedule_id": data.maintenance_schedule_id,
        "status": "active"
    }).execute()
    alarm_id = alarm.data[0]["id"]

    # notification_logs INSERT
    notification_id = None
    if data.user_id:
        notif = supabase.table("notification_logs").insert({
            "user_id": data.user_id,
            "notification_type": data.alarm_type,
            "message": data.message,
            "is_read": False
        }).execute()
        notification_id = notif.data[0]["id"]

    return {
        "alarm_id": alarm_id,
        "notification_id": notification_id,
        "alarm_type": data.alarm_type,
        "severity": data.severity
    }