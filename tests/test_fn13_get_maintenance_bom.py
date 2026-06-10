"""fn13 get_maintenance_bom — 계약 고정 + 예상비용 롤업 + 단가누락 플래그."""
import pytest
from functions.csc02.fn13_get_maintenance_bom import get_maintenance_bom

FN13_KEYS = {
    "maintenance_type", "aircraft_model", "line_count", "total_required_qty",
    "total_estimated_eur", "has_missing_price", "items",
}
FN13_ITEM_KEYS = {
    "part_id", "nomenclature", "part_number", "category", "required_qty",
    "unit", "unit_price_eur", "line_cost_eur", "missing_price",
}


def test_contract_and_rollup(db):
    db.seed("components", [
        {"id": 1, "nomenclature": "OIL FILTER", "part_number": "OF-1", "category": "Engine", "unit_price_eur": 25.0},
        {"id": 2, "nomenclature": "SPARK PLUG", "part_number": "SP-2", "category": "Engine", "unit_price_eur": 12.5},
    ])
    db.seed("bom", [
        {"id": 1, "maintenance_type": "100hr", "aircraft_model": "DA40NG", "part_id": 1, "required_qty": 2, "unit": "ea"},
        {"id": 2, "maintenance_type": "100hr", "aircraft_model": "DA40NG", "part_id": 2, "required_qty": 4, "unit": "ea"},
    ])
    r = get_maintenance_bom("100hr", "DA40NG")
    assert set(r) == FN13_KEYS
    for it in r["items"]:
        assert set(it) == FN13_ITEM_KEYS
    assert r["line_count"] == 2
    assert r["total_required_qty"] == 6
    assert r["total_estimated_eur"] == 100.0          # 2*25 + 4*12.5
    assert r["has_missing_price"] is False


def test_missing_price_flag(db):
    db.seed("components", [{"id": 1, "nomenclature": "MYSTERY", "part_number": None, "category": None, "unit_price_eur": None}])
    db.seed("bom", [{"id": 1, "maintenance_type": "X", "aircraft_model": None, "part_id": 1, "required_qty": 3, "unit": "ea"}])
    r = get_maintenance_bom("X")
    assert r["has_missing_price"] is True
    assert r["items"][0]["line_cost_eur"] == 0.0


def test_empty_bom(db):
    r = get_maintenance_bom("NONE")
    assert r["line_count"] == 0 and r["items"] == [] and r["total_estimated_eur"] == 0.0


def test_empty_type_raises(db):
    with pytest.raises(ValueError):
        get_maintenance_bom("")
