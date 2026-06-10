from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import inventory_not_found, insufficient_stock, db_error

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
    """입고/출고 등록 (팝업C/D)"""
    # 1. 재고 현황 조회
    inventory = supabase.table("parts_inventory")\
        .select("quantity_on_hand")\
        .eq("part_id", data.part_id).execute()

    if not inventory.data:
        inventory_not_found(data.part_id)

    current_qty = inventory.data[0]["quantity_on_hand"]

    # 2. 출고 시 재고 부족 체크
    if data.transaction_type == "출고":
        if current_qty < data.quantity:
            insufficient_stock(data.part_id, current_qty, data.quantity)

    # 3. 거래 기록 INSERT
    record = data.dict(exclude_none=True)
    response = supabase.table("parts_transactions").insert(record).execute()
    transaction_id = response.data[0]["id"]

    # 4. 재고 수량 자동 갱신
    if data.transaction_type == "입고":
        new_qty = current_qty + data.quantity
    else:
        new_qty = current_qty - data.quantity

    supabase.table("parts_inventory")\
        .update({"quantity_on_hand": new_qty})\
        .eq("part_id", data.part_id).execute()

    # 5. 출고 후 안전재고 미달 경고
    warning = None
    if data.transaction_type == "출고":
        reorder = supabase.table("reorder_points")\
            .select("safety_stock")\
            .eq("part_id", data.part_id).execute()
        if reorder.data:
            safety_stock = reorder.data[0]["safety_stock"]
            if new_qty <= safety_stock:
                warning = f"⚠️ 안전재고 미달! 발주가 필요합니다 (현재: {new_qty}개, 안전재고: {safety_stock}개)"

    return {
        "message": f"{data.transaction_type} 처리 완료",
        "transaction_id": transaction_id,
        "remaining_qty": new_qty,
        "warning": warning
    }

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