"""fn7 analyze_safety_stock — 계약 고정 + 부족/경고/정상 판정."""
import pytest
from functions.csc03.fn7_analyze_safety_stock import analyze_safety_stock

FN7_KEYS = {
    "part_id", "nomenclature", "current_qty", "safety_stock_qty",
    "safety_stock_source", "status", "shortage_qty", "order_required",
    "days_until_stockout",
}


def _seed(db, on_hand=5):
    db.seed("components", [{"id": 1, "nomenclature": "SPARK PLUG"}])
    db.seed("parts_inventory", [{"id": 10, "part_id": 1, "quantity_on_hand": on_hand, "location": "청주"}])


def test_contract_parameter_source(db):
    _seed(db, on_hand=5)
    r = analyze_safety_stock(1, avg_daily_usage=1.0, safety_stock_qty=10)
    assert set(r) == FN7_KEYS
    assert r["safety_stock_source"] == "parameter"
    assert r["status"] == "부족"           # 5 <= 10
    assert r["order_required"] is True
    assert r["shortage_qty"] == 5
    assert r["days_until_stockout"] == 5.0


def test_reorder_points_autolookup(db):
    _seed(db, on_hand=20)
    db.seed("reorder_points", [{"id": 1, "part_id": 1, "safety_stock": 10}])
    r = analyze_safety_stock(1, avg_daily_usage=0.0)   # usage 0 → inf
    assert r["safety_stock_source"] == "reorder_points"
    assert r["status"] == "정상"           # 20 > 10*1.5
    assert r["days_until_stockout"] is None  # usage=0 → JSON 직렬화상 None


def test_no_safety_source_raises(db):
    _seed(db, on_hand=5)
    with pytest.raises(ValueError):
        analyze_safety_stock(1, avg_daily_usage=1.0)   # 파라미터 없고 reorder_points 도 없음


def test_invalid_location(db):
    _seed(db)
    with pytest.raises(ValueError):
        analyze_safety_stock(1, avg_daily_usage=1.0, safety_stock_qty=1, location="서울")
