from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from routers.errors import component_not_found, db_error
# fn 연동
from functions.csc03.fn6_calc_order_cost import calc_order_cost
from functions.csc03.fn17_calc_landed_cost import calc_landed_cost
from functions.csc03.fn18_forecast_purchase_timing import forecast_purchase_timing

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

# ── 수입 총원가 / 직구 절감 (fn17 래핑) ─────────────

class LandedCostRequest(BaseModel):
    unit_price_eur: float
    order_qty: int
    exchange_rate: Optional[float] = None            # 미입력 시 fn17 기본 고정 대략치
    customs_duty_rate: Optional[float] = 0.0         # HS코드별 관세율(민간항공기 부품 다수 0%)
    is_academic: Optional[bool] = True               # 학술연구용품 감면(관세법 제90조)
    vat_rate: Optional[float] = 0.10
    # 항공운임: 총액 / kg당+중량 / 팔레트당+팔레트수 중 하나
    freight_total_eur: Optional[float] = None
    freight_per_kg_eur: Optional[float] = None
    weight_kg: Optional[float] = None
    freight_per_pallet_eur: Optional[float] = None
    pallets: Optional[int] = None
    agent_markup_rate: Optional[float] = None        # 기존 대행 수수료율(절감 비교용)


@router.post("/landed-cost")
def calculate_landed_cost(data: LandedCostRequest):
    """수입 총원가(관부과세·운임 포함) + 직구 절감 효과 (fn17 래핑)

    - 학술연구용품 감면(관세법 제90조, 관세의 80% 감면) 적용 옵션
    - 환율/운임/대행수수료는 미입력 시 함수 기본 대략치 사용(확정 데이터로 교체 필요)
    """
    kwargs = {k: v for k, v in data.dict().items() if v is not None}
    try:
        return calc_landed_cost(**kwargs)
    except ValueError as e:
        return {"error": str(e)}, 422
    except Exception as e:
        return {"error": str(e)}, 500


# ── 비행시간 기반 구매시기 예측 (fn18 래핑) ──────────

@router.get("/forecast/{aircraft_id}")
def forecast_timing(
    aircraft_id: int,
    annual_flight_hours: float = 725.0,
    horizon_days: int = 365,
    default_lead_time_days: int = 30,
):
    """비행시간 기반 부품 구매/도입 시기 예측 (fn18 래핑)

    - 연간 비행시간(기본 725h, 안전 고려 700~750 중앙값) 기준으로
      정비 도래일을 환산하고 BOM·재고·리드타임을 결합해 발주 시기 산출
    """
    try:
        return forecast_purchase_timing(
            aircraft_id=aircraft_id,
            annual_flight_hours=annual_flight_hours,
            horizon_days=horizon_days,
            default_lead_time_days=default_lead_time_days,
        )
    except ValueError as e:
        return {"error": str(e)}, 422
    except Exception as e:
        return {"error": str(e)}, 500
