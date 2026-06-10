"""fn4 get_inventory — 계약 고정 + 기지/카테고리/공통부품 필터 + 상태 판정."""
import pytest
from functions.csc02.fn4_get_inventory import get_inventory

FN4_ITEM_KEYS = {
    "part_id", "part_number", "nomenclature", "category",
    "quantity_on_hand", "location", "safety_stock", "status",
}


def _seed(db):
    db.seed("components", [
        {"id": 1, "part_number": "OF-1", "nomenclature": "OIL FILTER", "category": "Engine", "aircraft_id": 1},
        {"id": 2, "part_number": "SP-2", "nomenclature": "SPARK PLUG", "category": "Engine", "aircraft_id": None},   # 공통
        {"id": 3, "part_number": "TR-3", "nomenclature": "TIRE", "category": "Gear", "aircraft_id": 2},               # 다른 기체
    ])
    db.seed("parts_inventory", [
        {"id": 10, "part_id": 1, "quantity_on_hand": 5, "location": "청주"},
        {"id": 11, "part_id": 1, "quantity_on_hand": 3, "location": "무안"},
        {"id": 12, "part_id": 2, "quantity_on_hand": 1, "location": "청주"},
    ])
    db.seed("reorder_points", [
        {"id": 1, "part_id": 1, "safety_stock": 3},
        {"id": 2, "part_id": 2, "safety_stock": 8},
    ])


def test_contract_and_all_location_sum(db):
    _seed(db)
    rows = get_inventory()                       # 전체, all 합산
    assert len(rows) == 3
    for it in rows:
        assert set(it) == FN4_ITEM_KEYS
    oil = next(r for r in rows if r["part_id"] == 1)
    assert oil["quantity_on_hand"] == 8          # 청주5 + 무안3
    assert oil["location"] == "all"
    assert oil["status"] == "정상"               # 8 > 3*1.5


def test_location_filter(db):
    _seed(db)
    rows = get_inventory(location="청주")
    oil = next(r for r in rows if r["part_id"] == 1)
    assert oil["quantity_on_hand"] == 5          # 청주만


def test_aircraft_filter_includes_common(db):
    _seed(db)
    rows = get_inventory(aircraft_id=1)          # 기체1 전용 + 공통(NULL)
    ids = {r["part_id"] for r in rows}
    assert ids == {1, 2}                         # 3(기체2 전용)은 제외


def test_category_filter(db):
    _seed(db)
    rows = get_inventory(category="Gear")
    assert {r["part_id"] for r in rows} == {3}


def test_status_levels(db):
    _seed(db)
    rows = get_inventory()
    spark = next(r for r in rows if r["part_id"] == 2)
    assert spark["status"] == "부족"             # 1 <= 8
    tire = next(r for r in rows if r["part_id"] == 3)
    assert tire["safety_stock"] is None and tire["status"] == "기준없음"


def test_invalid_location(db):
    _seed(db)
    with pytest.raises(ValueError):
        get_inventory(location="서울")
