from fastapi import APIRouter
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import aircraft_not_found, exchange_rate_not_found, db_error, error_response, ErrorCode

def not_found(resource: str, resource_id):
    error_response(404, ErrorCode.MAINTENANCE_NOT_FOUND, f"{resource} ID {resource_id}를 찾을 수 없습니다")
# fn 연동
from functions.csc05.fn15_refresh_dashboard_metrics import refresh_dashboard_metrics
from functions.csc03.fn8_exchange_rate import get_exchange_rate, evaluate_purchase_timing

router = APIRouter(tags=["CSC-05/06 대시보드 & 인프라"])


# ── CSC-05: 대시보드 & 모니터링 ───────────────

@router.get("/metrics")
def get_dashboard_metrics():
    """대시보드 집계 지표 조회 (fn15 래핑)"""
    try:
        return refresh_dashboard_metrics()
    except Exception as e:
        return {"error": str(e)}

@router.get("/dashboard/alerts")
def get_active_alerts(aircraft_id: Optional[int] = None):
    """활성 알람 목록 조회"""
    query = supabase.table("maintenance_alarms")\
        .select("*")\
        .eq("status", "active")
    if aircraft_id:
        query = query.eq("aircraft_id", aircraft_id)
    return query.order("created_at", desc=True).execute().data

@router.get("/notifications")
def get_notifications(user_id: str, is_read: Optional[bool] = None):
    """사용자 알림 목록 조회"""
    query = supabase.table("notification_logs")\
        .select("*")\
        .eq("user_id", user_id)
    if is_read is not None:
        query = query.eq("is_read", is_read)
    return query.order("created_at", desc=True).execute().data

@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int):
    """알림 읽음 처리"""
    response = supabase.table("notification_logs")\
        .update({"is_read": True})\
        .eq("id", notification_id).execute()
    if not response.data:
        not_found("notification", notification_id)
    return {"message": "읽음 처리 완료"}


# ── CSC-06: 기술인프라 ─────────────────────────

@router.get("/users/{user_id}/role")
def get_user_role(user_id: str):
    """사용자 권한 조회"""
    response = supabase.table("user_roles")\
        .select("*")\
        .eq("user_id", user_id).execute()
    if not response.data:
        not_found("user_role", 0)
    return response.data[0]

@router.get("/users")
def list_users(role: Optional[str] = None):
    """사용자/담당 정비사 목록 조회 (role 필터)

    예) GET /users?role=mechanic → 담당 정비사 목록 (정비 이력 등록 드롭다운용)
    """
    query = supabase.table("user_roles").select("*")
    if role:
        query = query.eq("role", role)
    return query.order("id").execute().data

@router.get("/currency-rates")
def get_currency_rates():
    """환율 정보 조회 (fn8 래핑)"""
    try:
        rate = get_exchange_rate()
        timing = evaluate_purchase_timing()
        return {
            "exchange_rate": rate,
            "purchase_timing": timing
        }
    except Exception as e:
        return {"error": str(e)}