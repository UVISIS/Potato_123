"""fn9 get_required_parts / fn10 check_parts_availability — 계약 고정 + 부족 감지."""
import pytest
from functions.csc04.fn9_fn10_parts_check import (
    get_required_parts, check_parts_availability,
)

FN9_ITEM_KEYS = {"part_id", "nomenclature", "part_number", "required_qty", "unit", "unit_price_eur"}
FN10_KEYS = {
    "maintenance_type", "aircraft_model", "location",
    "can_proceed", "total_items", "shortage_items", "items",
}
FN10_ITEM_KEYS = {"part_id", "nomenclature", "required_qty", "on_hand_qty", "shortage_qty", "status"}


def _seed(db):
    db.seed("components", [
        {"id": 1, "nomenclature": "OIL FILTER", "part_number": "OF-1", "unit_price_eur": 25.0},
        {"id": 2, "nomenclature": "SPARK PLUG", "part_number": "SP-2", "unit_price_eur": 12.5},
    ])
    db.seed("bom", [
        {"id": 1, "maintenance_type": "100hr", "aircraft_model": "DA40NG", "part_id": 1, "required_qty": 2, "unit": "ea"},
        {"id": 2, "maintenance_type": "100hr", "aircraft_model": "DA40NG", "part_id": 2, "required_qty": 4, "unit": "ea"},
    ])
    db.seed("parts_inventory", [
        {"id": 10, "part_id": 1, "quantity_on_hand": 5, "location": "청주"},
        {"id": 11, "part_id": 2, "quantity_on_hand": 1, "location": "청주"},
    ])


def test_fn9_contract(db):
    _seed(db)
    rows = get_required_parts("100hr", "DA40NG")
    assert len(rows) == 2
    for it in rows:
        assert set(it) == FN9_ITEM_KEYS


def test_fn9_empty_when_no_bom(db):
    _seed(db)
    assert get_required_parts("Annual", "DA40NG") == []


def test_fn9_empty_maintenance_type_raises(db):
    with pytest.raises(ValueError):
        get_required_parts("  ")


def test_fn10_contract_and_shortage(db):
    _seed(db)
    r = check_parts_availability("100hr", "DA40NG", location="청주")
    assert set(r) == FN10_KEYS
    for it in r["items"]:
        assert set(it) == FN10_ITEM_KEYS
    assert r["total_items"] == 2
    assert r["shortage_items"] == 1          # spark plug 4 필요 / 1 보유
    assert r["can_proceed"] is False


def test_fn10_invalid_location(db):
    _seed(db)
    with pytest.raises(ValueError):
        check_parts_availability("100hr", "DA40NG", location="서울")
