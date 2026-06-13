"""fn18 forecast_purchase_timing — 비행시간 기반 발주시기 예측 검증."""
import pytest
from functions.csc03.fn18_forecast_purchase_timing import forecast_purchase_timing

KEYS = {
    "aircraft_id", "model", "current_flight_hours", "annual_flight_hours",
    "hours_per_calendar_day", "horizon_days", "as_of", "items", "summary",
}


def _seed(db, due_hours=100):
    db.seed("aircraft", [{"id": 1, "model": "DA42NG", "total_flight_hours": 50}])
    db.seed("maintenance_schedule", [
        {"id": 10, "aircraft_id": 1, "maintenance_type": "기체100HRS",
         "interval_hours": 100, "due_hours": due_hours, "status": "scheduled"},
    ])
    db.seed("bom", [
        {"id": 1, "maintenance_type": "기체100HRS", "aircraft_model": "DA42NG",
         "part_id": 500, "required_qty": 2},
    ])
    db.seed("components", [{"id": 500, "nomenclature": "OIL FILTER"}])
    db.seed("parts_inventory", [{"id": 1, "part_id": 500, "quantity_on_hand": 1, "location": None}])
    db.seed("reorder_points", [{"id": 1, "part_id": 500, "safety_stock": 2, "lead_time_days": 30}])


def test_contract_and_projection(db):
    _seed(db, due_hours=100)
    # 현재 50h, due 100h → 잔여 50h. 연 725h/365 ≒ 1.986h/일 → 약 26일 후 도래
    r = forecast_purchase_timing(1, annual_flight_hours=725, today="2026-06-13")
    assert set(r) == KEYS
    assert r["current_flight_hours"] == 50
    assert len(r["items"]) == 1
    item = r["items"][0]
    assert item["remaining_hours"] == 50.0
    assert item["days_until_due"] == 26          # ceil(50 / 1.9863)
    assert item["due_date"] == "2026-07-09"      # 2026-06-13 + 26d
    assert item["part_id"] == 500
    assert item["required_qty"] == 2
    assert item["current_stock"] == 1
    assert item["shortfall"] == 1
    # 도래 7/9 - 리드타임 30일 = 6/9 (이미 지남) → 지금발주
    assert item["order_by_date"] == "2026-06-09"
    assert item["recommendation"] == "지금발주"


def test_overdue_immediate(db):
    # due 40h < 현재 50h → 잔여 음수 → 초과(즉시발주)
    _seed(db, due_hours=40)
    r = forecast_purchase_timing(1, annual_flight_hours=725, today="2026-06-13")
    assert r["items"][0]["recommendation"] == "초과(즉시발주)"
    assert r["summary"]["즉시발주"] == 1


def test_beyond_horizon_excluded(db):
    # due 700h → 잔여 650h ≒ 327일 후, horizon 30일 → 결과 제외
    _seed(db, due_hours=700)
    r = forecast_purchase_timing(1, annual_flight_hours=725, horizon_days=30, today="2026-06-13")
    assert r["items"] == []


def test_missing_aircraft_raises(db):
    with pytest.raises(ValueError):
        forecast_purchase_timing(999)


def test_invalid_annual_hours(db):
    _seed(db)
    with pytest.raises(ValueError):
        forecast_purchase_timing(1, annual_flight_hours=0)
