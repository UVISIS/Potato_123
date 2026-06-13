from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import supabase
from routers.errors import component_not_found, inventory_not_found, reorder_not_found, insufficient_stock
# fn 연동
from functions.csc02.fn4_get_inventory import get_inventory as fn4_get_inventory
from functions.csc03.fn7_analyze_safety_stock import analyze_safety_stock
from functions.csc02.fn13_get_maintenance_bom import get_maintenance_bom

router = APIRouter(tags=["CSC-02 부품/자재 관리"])


# ── 요청 모델 ──────────────────────────────────

class ComponentCreate(BaseModel):
    aircraft_id: Optional[int] = None
    category: str
    nomenclature: str
    part_number: str
    inspection_interval: Optional[str] = None
    quantity: Optional[str] = None
    remark: Optional[str] = None

class ComponentUpdate(BaseModel):
    nomenclature: Optional[str] = None
    inspection_interval: Optional[str] = None
    remark: Optional[str] = None

class InventoryUpdate(BaseModel):
    quantity_on_hand: int
    location: Optional[str] = None

class ReorderPointCreate(BaseModel):
    safety_stock: int
    reorder_qty: Optional[int] = 0
    lead_time_days: Optional[int] = None

class ReorderPointUpdate(BaseModel):
    safety_stock: Optional[int] = None
    reorder_qty: Optional[int] = None
    lead_time_days: Optional[int] = None
    update_reason: Optional[str] = None


# ── 부품 관리 ──────────────────────────────────

@router.post("/components")
def create_component(data: ComponentCreate):
    """신규 부품 등록"""
    comp = supabase.table("components").insert(data.dict()).execute()
    component_id = comp.data[0]["id"]

    supabase.table("parts_inventory").insert({
        "part_id": component_id,
        "quantity_on_hand": 0,
        "location": None
    }).execute()

    supabase.table("reorder_points").insert({
        "part_id": component_id,
        "safety_stock": 0,
        "reorder_qty": 0,
        "minimum_qty": 0,
        "maximum_qty": 0
    }).execute()

    return {"message": "부품이 등록되었습니다", "component_id": component_id}

@router.get("/components")
def get_components(
    aircraft_id: Optional[int] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
):
    """전체 부품 목록 조회 (q: 부품번호/명칭 검색)"""
    query = supabase.table("components").select("*")
    if aircraft_id:
        query = query.eq("aircraft_id", aircraft_id)
    if category:
        query = query.eq("category", category)
    if q:
        # 부품번호 또는 명칭 부분일치 검색
        query = query.or_(f"part_number.ilike.%{q}%,nomenclature.ilike.%{q}%")
    return query.execute().data

@router.get("/components/{component_id}")
def get_component_by_id(component_id: int):
    """특정 부품 조회"""
    response = supabase.table("components").select("*").eq("id", component_id).execute()
    if not response.data:
        component_not_found(component_id)
    return response.data[0]

@router.patch("/components/{component_id}")
def update_component(component_id: int, data: ComponentUpdate):
    """부품 정보 수정"""
    response = supabase.table("components")\
        .update(data.dict(exclude_none=True))\
        .eq("id", component_id).execute()
    if not response.data:
        component_not_found(component_id)
    return response.data[0]


# ── 재고 관리 ──────────────────────────────────

@router.get("/inventory")
def get_inventory():
    """재고 전체 목록 조회 (fn4 래핑)"""
    try:
        return fn4_get_inventory()
    except Exception as e:
        return {"error": str(e)}

    result = []
    for item in inventory.data:
        part_id = item.get("part_id")
        reorder = supabase.table("reorder_points")\
            .select("*")\
            .eq("part_id", part_id).execute()
        item["reorder_points"] = reorder.data[0] if reorder.data else None
        result.append(item)

    return result

@router.get("/inventory/{part_id}")
def get_inventory_by_part(part_id: int):
    """특정 부품 재고 조회"""
    inventory = supabase.table("parts_inventory")\
        .select("*, components(*)")\
        .eq("part_id", part_id).execute()

    if not inventory.data:
        inventory_not_found(part_id)

    item = inventory.data[0]
    reorder = supabase.table("reorder_points")\
        .select("*")\
        .eq("part_id", part_id).execute()
    item["reorder_points"] = reorder.data[0] if reorder.data else None

    return item

@router.patch("/inventory/{part_id}")
def update_inventory(part_id: int, data: InventoryUpdate):
    """재고 수량/위치 수정"""
    response = supabase.table("parts_inventory")\
        .update(data.dict(exclude_none=True))\
        .eq("part_id", part_id).execute()
    if not response.data:
        inventory_not_found(part_id)
    return response.data[0]


# ── 안전재고 관리 ──────────────────────────────

@router.get("/reorder-points")
def get_reorder_points():
    """안전재고 현황 전체 조회"""
    reorders = supabase.table("reorder_points")\
        .select("*, components(*)")\
        .execute()

    result = []
    for item in reorders.data:
        part_id = item.get("part_id")
        inventory = supabase.table("parts_inventory")\
            .select("*")\
            .eq("part_id", part_id).execute()
        item["parts_inventory"] = inventory.data[0] if inventory.data else None
        result.append(item)

    return result

@router.patch("/reorder-points/{part_id}")
def update_reorder_point(part_id: int, data: ReorderPointUpdate):
    """안전재고 기준 수정"""
    response = supabase.table("reorder_points")\
        .update(data.dict(exclude_none=True))\
        .eq("part_id", part_id).execute()
    if not response.data:
        reorder_not_found(part_id)
    return response.data[0]

# ── BOM 조회 (fn13 래핑) ──────────────────────

@router.get("/bom/{maintenance_type}")
def get_bom(maintenance_type: str, aircraft_model: Optional[str] = None):
    """정비 유형별 BOM 및 예상 비용 조회 (fn13 래핑)

    - maintenance_type 예시: '100hr', '200hr', 'Annual'
    - aircraft_model 예시: 'DA40NG', 'DA42NG' (미입력 시 전 기종)
    """
    try:
        return get_maintenance_bom(
            maintenance_type=maintenance_type,
            aircraft_model=aircraft_model,
        )
    except ValueError as e:
        return {"error": str(e)}, 422
    except Exception as e:
        return {"error": str(e)}, 500

# ── 안전재고 상태 분석 (fn7 래핑) ──────────────

@router.get("/reorder-points/{part_id}/analysis")
def analyze_part_safety_stock(
    part_id: int,
    avg_daily_usage: float = 0.0,
    location: str = "all",
):
    """단일 부품 안전재고 상태 분석 (fn7 래핑)

    부족/경고/정상 상태, 부족수량, 소진 예상일수를 반환한다.
    - avg_daily_usage 미입력(0) 시 소진일수는 무한(inf)으로 처리되며
      상태 판정(부족/경고/정상)에는 영향이 없다.
    - safety_stock 기준은 reorder_points 에서 자동 조회.
    """
    try:
        return analyze_safety_stock(
            part_id=part_id,
            avg_daily_usage=avg_daily_usage,
            location=location,
        )
    except ValueError as e:
        return {"error": str(e)}, 422
    except Exception as e:
        return {"error": str(e)}, 500


@router.get("/reorder-points/analysis")
def analyze_all_safety_stock(location: str = "all"):
    """전체 부품 안전재고 상태 일괄 분석 (fn7 래핑)

    reorder_points 가 설정된 모든 부품에 대해 fn7 을 실행하여
    재고 상태(부족/경고/정상) 목록을 반환한다. 안전재고 관리 페이지용.
    소진 예상일수가 필요하면 단일 분석 엔드포인트에 avg_daily_usage 를 전달.
    """
    reorders = supabase.table("reorder_points").select("part_id").execute()
    results = []
    errors = []
    for row in (reorders.data or []):
        pid = row.get("part_id")
        if pid is None:
            continue
        try:
            results.append(
                analyze_safety_stock(part_id=pid, avg_daily_usage=0.0, location=location)
            )
        except Exception as e:
            errors.append({"part_id": pid, "error": str(e)})

    # 상태별 요약 (부족 → 경고 → 정상 순 정렬)
    order = {"부족": 0, "경고": 1, "정상": 2}
    results.sort(key=lambda r: order.get(r.get("status"), 9))
    summary = {
        "부족": sum(1 for r in results if r.get("status") == "부족"),
        "경고": sum(1 for r in results if r.get("status") == "경고"),
        "정상": sum(1 for r in results if r.get("status") == "정상"),
    }
    return {"summary": summary, "items": results, "errors": errors or None}


# ── 전 분기 단가(EUR) 조회 (Page4 안전재고) ──────

@router.get("/components/{component_id}/last-price")
def get_component_last_price(component_id: int):
    """부품 직전 단가(EUR) 조회

    1순위: parts_transactions 의 최근 입고 단가(unit_price_eur)
    2순위: components.unit_price_eur (등록 기준 단가)
    """
    comp = supabase.table("components").select("unit_price_eur, nomenclature")\
        .eq("id", component_id).execute().data
    if not comp:
        component_not_found(component_id)

    tx = supabase.table("parts_transactions")\
        .select("unit_price_eur, transaction_date")\
        .eq("part_id", component_id)\
        .eq("transaction_type", "입고")\
        .order("transaction_date", desc=True).limit(1).execute().data

    tx_price = tx[0]["unit_price_eur"] if tx and tx[0].get("unit_price_eur") is not None else None
    source = "parts_transactions" if tx_price is not None else "components"
    price = tx_price if tx_price is not None else comp[0].get("unit_price_eur")

    return {
        "component_id": component_id,
        "nomenclature": comp[0].get("nomenclature"),
        "last_unit_price_eur": price,
        "source": source,
    }
