from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import inventory_not_found, insufficient_stock, db_error
# fn 연동
from functions.csc02.fn5_record_transaction import record_transaction

router = APIRouter(prefix="/transactions", tags=["CSC-02 입출고 관리"])


# ── 요청 모델 ──────────────────────────────────

class TransactionCreate(BaseModel):
    part_id: int
    transaction_type: str               # 입고 / 출고
    quantity: int
    transaction_date: str
    batch_no: Optional[int] = None      # 1=1월(상반기), 2=7월(하반기)
    order_year: Optional[int] = None    # 발주 연도
    unit_price_eur: Optional[float] = None          # 입고 당시 단가 (선택)
    exchange_rate_applied: Optional[float] = None   # 입고 당시 환율 (선택)
    aircraft_id: Optional[int] = None   # 출고 시 기체 연결
    location: Optional[str] = None      # 출고 지역 (청주/무안)
    maintenance_type: Optional[str] = None          # 정비종류
    handled_by: Optional[str] = None    # 담당 정비사
    maintenance_history_id: Optional[int] = None    # 정비이력 연결
    notes: Optional[str] = None


# ── 입출고 관리 ────────────────────────────────

@router.post("")
def create_transaction(data: TransactionCreate):
    """입고/출고 등록 (fn5 래핑)"""
    try:
        return record_transaction(
            part_id=data.part_id,
            transaction_type=data.transaction_type,
            quantity=data.quantity,
            location=data.location,
            aircraft_id=data.aircraft_id,
            handled_by=data.handled_by,
            notes=data.notes,
            unit_price_eur=data.unit_price_eur,
            exchange_rate_applied=data.exchange_rate_applied,
            maintenance_type=data.maintenance_type,
            maintenance_history_id=data.maintenance_history_id
        )
    except ValueError as e:
        insufficient_stock(data.part_id, 0, data.quantity)
    except Exception as e:
        return {"error": str(e)}

@router.get("")
def get_transactions(
    transaction_type: Optional[str] = None,  # 입고 / 출고
    batch_no: Optional[int] = None,          # 1 또는 2
    order_year: Optional[int] = None,        # 연도
    part_id: Optional[int] = None            # 특정 부품
):
    """입출고 이력 조회 (발주회차/유형 필터)"""
    query = supabase.table("parts_transactions").select("*")
    if transaction_type:
        query = query.eq("transaction_type", transaction_type)
    if batch_no:
        query = query.eq("batch_no", batch_no)
    if order_year:
        query = query.eq("order_year", order_year)
    if part_id:
        query = query.eq("part_id", part_id)
    return query.order("transaction_date", desc=True).execute().data

@router.get("/{transaction_id}")
def get_transaction_by_id(transaction_id: int):
    """특정 거래 이력 조회"""
    response = supabase.table("parts_transactions")\
        .select("*").eq("id", transaction_id).execute()
    if not response.data:
    # errors.py에 transaction_not_found 추가 필요 → 일단 이렇게
        from routers.errors import error_response, ErrorCode
        error_response(404, ErrorCode.ORDER_NOT_FOUND, f"거래 이력 ID {transaction_id}를 찾을 수 없습니다")
    return response.data[0]