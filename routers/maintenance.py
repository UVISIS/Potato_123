from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import maintenance_not_found, schedule_not_found, db_error, aircraft_not_found
# fn 연동
from functions.csc04.fn11_calc_next_maintenance import calc_next_maintenance
from functions.csc04.fn12_calc_d_time import calc_d_time
from functions.csc04.fn9_fn10_parts_check import get_required_parts, check_parts_availability as fn10_check
from functions.csc04.fn14_generate_maintenance_alarms import generate_maintenance_alarms
from functions.csc02.fn5_record_transaction import record_transaction


router = APIRouter(prefix="/maintenance", tags=["CSC-04 주기정비 관리"])


# ── 요청 모델 ──────────────────────────────────

class MaintenancePart(BaseModel):
    part_id: int
    quantity: int
    destination: Optional[str] = None    # 부품별 목적지 override (보통 정비 레벨 destination 사용)

class MaintenanceHistoryCreate(BaseModel):
    aircraft_id: int
    maintenance_date: str
    maintenance_type: str               # 기체100HRS / 엔진300HRS / MSB 등
    hours_at_maintenance: float         # 정비 당시 누적 비행시간
    next_due_date: Optional[str] = None
    handled_by: str                     # 담당 정비사
    destination: Optional[str] = None   # 정비 수행/부품 출고 목적지 비행교육원 (청주/무안)
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
    """정비 이력 등록 (팝업F) - 정비 기록 + 부품 출고 자동 처리

    후처리 체인:
      1. maintenance_history INSERT
      2. fn5(record_transaction) — 교체부품 출고: parts_transactions +
         parts_inventory 차감 + inventory_history 기록 (원자적, 재고초과 검증)
      3. maintenance_schedule status='completed' 갱신
      4. fn12(calc_d_time) — 해당 기체 정비 스케줄 D-Time 카운터 재계산
    """
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

    # 2. 교체 부품 출고 자동 처리 — fn5 래핑 (parts_transactions + inventory + 이력)
    parts_warning = []
    parts_issued = []
    for part in data.parts_used:
        try:
            tx = record_transaction(
                part_id=part.part_id,
                transaction_type="출고",
                quantity=part.quantity,
                destination=(part.destination or data.destination),
                aircraft_id=data.aircraft_id,
                handled_by=data.handled_by,
                maintenance_type=data.maintenance_type,
                maintenance_history_id=history_id,
                notes=f"정비 출고 (history_id={history_id})",
            )
            parts_issued.append({
                "part_id": part.part_id,
                "quantity": part.quantity,
                "quantity_after": tx["quantity_after"],
                "transaction_id": tx["transaction_id"],
            })
            # 안전재고 미달 체크
            reorder = supabase.table("reorder_points")\
                .select("safety_stock")\
                .eq("part_id", part.part_id).execute()
            if reorder.data and reorder.data[0]["safety_stock"] is not None \
                    and tx["quantity_after"] <= reorder.data[0]["safety_stock"]:
                parts_warning.append(
                    f"부품 ID {part.part_id}: 안전재고 미달 (잔여: {tx['quantity_after']}개)"
                )
        except ValueError as e:
            # 재고 부족/부품 미존재 등 — 해당 부품만 스킵하고 경고 누적
            parts_warning.append(f"부품 ID {part.part_id} 출고 실패: {e}")

    # 3. maintenance_schedule 완료 처리
    supabase.table("maintenance_schedule")\
        .update({"status": "completed"})\
        .eq("aircraft_id", data.aircraft_id)\
        .eq("maintenance_type", data.maintenance_type).execute()

    # 4. D-Time 카운터 재계산 — fn12 (해당 기체+정비종류 스케줄 대상)
    d_time_updated = []
    scheds = supabase.table("maintenance_schedule")\
        .select("id")\
        .eq("aircraft_id", data.aircraft_id)\
        .eq("maintenance_type", data.maintenance_type).execute()
    for sched in (scheds.data or []):
        try:
            calc_d_time(
                aircraft_id=data.aircraft_id,
                maintenance_schedule_id=sched["id"],
                current_flight_hours=data.hours_at_maintenance,
            )
            d_time_updated.append(sched["id"])
        except Exception as e:
            parts_warning.append(f"D-Time 재계산 실패 (schedule_id={sched['id']}): {e}")

    return {
        "message": "정비 이력이 등록되었습니다",
        "history_id": history_id,
        "parts_issued": parts_issued,
        "d_time_updated": d_time_updated,
        "warnings": parts_warning if parts_warning else None
    }

@router.get("/history")
def get_maintenance_history(
    aircraft_id: Optional[int] = None,
    maintenance_type: Optional[str] = None
):
    """정비 이력 조회 (기체번호/정비종류 필터)"""
    query = supabase.table("maintenance_history").select("*")        .eq("is_deleted", False)
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


# ── 주기정비 현황 통합 조회 (Page7) ─────────────

@router.get("/overview/{aircraft_id}")
def get_maintenance_overview(aircraft_id: int):
    """주기정비 현황 통합 조회 (schedule + d_time + bom + parts_inventory)

    기체별로 정비 스케줄마다 D-Time(잔여시간/일수)과 BOM 소요부품·현재고를
    한 번에 묶어 반환한다. (프론트 Page7 — 여러 호출 조합 대체)
    """
    ac = supabase.table("aircraft").select("id, registration, model, total_flight_hours")\
        .eq("id", aircraft_id).execute()
    if not ac.data:
        aircraft_not_found(aircraft_id)
    aircraft = ac.data[0]
    model = aircraft.get("model")

    scheds = supabase.table("maintenance_schedule").select("*")\
        .eq("aircraft_id", aircraft_id).execute().data or []
    dtimes = supabase.table("d_time_counter").select("*")\
        .eq("aircraft_id", aircraft_id).execute().data or []
    dtime_by_sched = {d.get("maintenance_schedule_id"): d for d in dtimes}

    items = []
    for s in scheds:
        # BOM 부품 (정비종류 + 기종 일치/전기종)
        bom_rows = supabase.table("bom").select("part_id, required_qty, aircraft_model")\
            .eq("maintenance_type", s["maintenance_type"]).execute().data or []
        bom_rows = [b for b in bom_rows if b.get("aircraft_model") in (None, model)]

        parts = []
        for b in bom_rows:
            pid = b["part_id"]
            comp = supabase.table("components").select("nomenclature, part_number")\
                .eq("id", pid).execute().data
            inv = supabase.table("parts_inventory").select("quantity_on_hand")\
                .eq("part_id", pid).execute().data or []
            stock = sum(int(r.get("quantity_on_hand") or 0) for r in inv)
            rp = supabase.table("reorder_points").select("safety_stock")\
                .eq("part_id", pid).execute().data
            safety = rp[0]["safety_stock"] if rp else None
            parts.append({
                "part_id": pid,
                "part_number": comp[0]["part_number"] if comp else None,
                "nomenclature": comp[0]["nomenclature"] if comp else None,
                "required_qty": b.get("required_qty"),
                "current_stock": stock,
                "safety_stock": safety,
            })

        dt = dtime_by_sched.get(s["id"], {})
        items.append({
            "maintenance_schedule_id": s["id"],
            "maintenance_type": s["maintenance_type"],
            "interval_hours": s.get("interval_hours"),
            "due_hours": s.get("due_hours"),
            "due_date": s.get("due_date"),
            "status": s.get("status"),
            "hours_remaining": dt.get("hours_remaining"),
            "days_remaining": dt.get("days_remaining"),
            "parts": parts,
        })

    return {
        "aircraft_id": aircraft_id,
        "registration": aircraft.get("registration"),
        "model": model,
        "total_flight_hours": aircraft.get("total_flight_hours"),
        "items": items,
    }


# ── 월별 정비 횟수 집계 (Page6 차트) ────────────

@router.get("/history/monthly")
def get_maintenance_monthly(aircraft_id: Optional[int] = None, year: Optional[int] = None):
    """월별 정비 횟수 집계 (정비이력 차트용)

    ⚠️ maintenance_history 데이터가 쌓여야 값이 나옴(현재 0행이면 빈 집계).
    """
    q = supabase.table("maintenance_history").select("maintenance_date, maintenance_type")
    if aircraft_id:
        q = q.eq("aircraft_id", aircraft_id)
    rows = q.execute().data or []

    counts = {m: 0 for m in range(1, 13)}
    for r in rows:
        md = str(r.get("maintenance_date") or "")
        if len(md) >= 7:
            yr, mo = md[:4], md[5:7]
            if year and yr != str(year):
                continue
            try:
                counts[int(mo)] += 1
            except (ValueError, KeyError):
                pass
    return {
        "aircraft_id": aircraft_id,
        "year": year,
        "monthly_counts": [{"month": m, "count": counts[m]} for m in range(1, 13)],
        "total": sum(counts.values()),
    }

# ── 정비 이력 Soft Delete ────────────────────────

@router.delete("/history/{history_id}")
def delete_maintenance_history(history_id: int):
    """정비 이력 soft delete (is_deleted = true)

    이력 데이터 보존이 핵심이므로 실제 행 삭제 없이 플래그만 변경.
    연결된 parts_transactions(출고 이력) FK 보존.
    복구: PATCH /maintenance/history/{id}/restore

    ⚠️ DB 선행 작업 필요:
      ALTER TABLE maintenance_history ADD COLUMN IF NOT EXISTS
        is_deleted boolean NOT NULL DEFAULT false;
      CREATE INDEX ON maintenance_history (is_deleted);
    → docs/DB_REQUEST.md 참고
    """
    res = supabase.table("maintenance_history")\
        .update({"is_deleted": True})\
        .eq("id", history_id).execute()
    if not res.data:
        maintenance_not_found(history_id)
    return {
        "message": f"정비 이력 {history_id}가 삭제 처리되었습니다. (is_deleted=true)",
        "history_id": history_id,
    }


@router.patch("/history/{history_id}/restore")
def restore_maintenance_history(history_id: int):
    """정비 이력 soft delete 복구 (is_deleted = false)"""
    res = supabase.table("maintenance_history")\
        .update({"is_deleted": False})\
        .eq("id", history_id).execute()
    if not res.data:
        maintenance_not_found(history_id)
    return {
        "message": f"정비 이력 {history_id}가 복구되었습니다. (is_deleted=false)",
        "history_id": history_id,
    }
