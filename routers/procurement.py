from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from routers.errors import component_not_found, db_error
# fn 연동
from functions.csc03.fn6_calc_order_cost import calc_order_cost

router = APIRouter(prefix="/procurement", tags=["CSC-03 발주 관리"])


# ── 요청 모델 ──────────────────────────────────

class OrderCostRequest(BaseModel):
    part_id: int
    order_qty: int
    unit_price_eur: Optional[float] = None      # 미입력 시 components DB 자동 조회
    exchange_rate: Optional[float] = None        # 미입력 시 currency_rates 최신값 자동 조회
    supplier_id: Optional[int] = None
    order_year: Optional[int] = None
    order_month: Optional[int] = None
    notes: Optional[str] = None
    create_order: Optional[bool] = False         # True 면 purchase_orders INSERT


# ── 발주 관리 ──────────────────────────────────

@router.post("/order-cost")
def calculate_order_cost(data: OrderCostRequest):
    """발주 비용 산출 (fn6 래핑)

    - unit_price_eur 미입력 시 components.unit_price_eur 자동 조회
    - exchange_rate 미입력 시 currency_rates 최신 환율 자동 조회
    - create_order=True 시 purchase_orders 테이블에 '발주예정' 행 생성
    """
    try:
        return calc_order_cost(
            part_id=data.part_id,
            order_qty=data.order_qty,
            unit_price_eur=data.unit_price_eur,
            exchange_rate=data.exchange_rate,
            supplier_id=data.supplier_id,
            order_year=data.order_year,
            order_month=data.order_month,
            notes=data.notes,
            create_order=data.create_order,
        )
    except ValueError as e:
        return {"error": str(e)}, 422
    except RuntimeError as e:
        return {"error": str(e)}, 500
    except Exception as e:
        return {"error": str(e)}, 500


@router.get("/purchase-orders")
def get_purchase_orders(
    order_year: Optional[int] = None,
    order_month: Optional[int] = None,
    status: Optional[str] = None,
):
    """발주 이력 조회"""
    from database import supabase
    query = supabase.table("purchase_orders").select("*, components(nomenclature, part_number)")
    if order_year:
        query = query.eq("order_year", order_year)
    if order_month:
        query = query.eq("order_month", order_month)
    if status:
        query = query.eq("status", status)
    return query.order("id", desc=True).execute().data


@router.get("/purchase-orders/{order_id}")
def get_purchase_order(order_id: int):
    """특정 발주 이력 조회"""
    from database import supabase
    response = supabase.table("purchase_orders")\
        .select("*, components(nomenclature, part_number)")\
        .eq("id", order_id).execute()
    if not response.data:
        return {"error": f"발주 ID {order_id}를 찾을 수 없습니다."}, 404
    return response.data[0]