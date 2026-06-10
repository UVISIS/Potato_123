"""fn11 calc_next_maintenance — 계약 고정 + 임박순 정렬/날짜기반/예외."""
import pytest
from functions.csc04.fn11_calc_next_maintenance import calc_next_maintenance

FN11_ITEM_KEYS = {
    "schedule_id", "aircraft_id", "maintenance_type", "interval_hours",
    "interval_months", "due_hours", "due_date", "current_hours",
    "remaining_hours", "status",
}


def _seed(db):
    db.seed("aircraft", [{"id": 1, "total_flight_hours": 1000}])
    db.seed("maintenance_schedule", [
        # 임박: 잔여 5h
        {"id": 1, "aircraft_id": 1, "maintenance_type": "100hr", "interval_hours": 100,
         "interval_months": None, "due_hours": 1005, "due_date": None, "status": "scheduled"},
        # 정상: 잔여 200h
        {"id": 2, "aircraft_id": 1, "maintenance_type": "200hr", "interval_hours": 200,
         "interval_months": None, "due_hours": 1200, "due_date": None, "status": "scheduled"},
        # 날짜기반: interval_hours=0
        {"id": 3, "aircraft_id": 1, "maintenance_type": "Belt 5yr", "interval_hours": 0,
         "interval_months": 60, "due_hours": None, "due_date": "2028-01-01", "status": "scheduled"},
    ])


def test_contract_and_sort(db):
    _seed(db)
    rows = calc_next_maintenance(1)
    assert len(rows) == 3
    for it in rows:
        assert set(it) == FN11_ITEM_KEYS
    # 임박(5h) 이 가장 앞, 날짜기반(remaining=None)은 맨 뒤
    assert rows[0]["schedule_id"] == 1
    assert rows[-1]["status"] == "날짜기반"
    assert rows[-1]["remaining_hours"] is None


def test_aircraft_not_found(db):
    with pytest.raises(ValueError):
        calc_next_maintenance(999)


def test_no_schedule_raises_lookuperror(db):
    db.seed("aircraft", [{"id": 1, "total_flight_hours": 0}])
    with pytest.raises(LookupError):
        calc_next_maintenance(1)
