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
def get_components(aircraft_id: Optional[int] = None, category: Optional[str] = None):
    """전체 부품 목록 조회"""
    query = supabase.table("components").select("*")
    if aircraft_id:
        query = query.eq("aircraft_id", aircraft_id)
    if category:
        query = query.eq("category", category)
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