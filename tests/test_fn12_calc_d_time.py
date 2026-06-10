"""fn12 calc_d_time — 계약 고정 + INSERT/UPDATE 분기 + 날짜기반 방어."""
import pytest
from functions.csc04.fn12_calc_d_time import calc_d_time

FN12_KEYS = {
    "d_time_id", "aircraft_id", "current_hours", "hours_remaining",
    "days_remaining", "remaining_pct", "last_updated", "status",
}


def _seed_hours(db):
    db.seed("aircraft", [{"id": 1, "total_flight_hours": 1000}])
    db.seed("maintenance_schedule", [
        {"id": 1, "interval_hours": 100, "due_hours": 1005},   # 잔여 5h → 임박
    ])
    db.seed("flight_hours", [
        {"id": 1, "aircraft_id": 1, "flight_date": "2026-06-01", "flight_hours": 3.0},
    ])


def test_contract_and_insert(db):
    _seed_hours(db)
    r = calc_d_time(1, 1)
    assert set(r) == FN12_KEYS
    assert r["hours_remaining"] == 5.0
    assert "임박" in r["status"]
    assert len(db.rows("d_time_counter")) == 1     # 신규 INSERT


def test_update_existing_row(db):
    _seed_hours(db)
    db.seed("d_time_counter", [{"id": 99, "aircraft_id": 1, "maintenance_schedule_id": 1}])
    r = calc_d_time(1, 1)
    assert r["d_time_id"] == 99                     # 기존 행 UPDATE
    assert len(db.rows("d_time_counter")) == 1      # 새 행 추가 안 됨


def test_date_based_schedule(db):
    db.seed("aircraft", [{"id": 1, "total_flight_hours": 1000}])
    db.seed("maintenance_schedule", [{"id": 2, "interval_hours": 0, "due_hours": None}])
    r = calc_d_time(1, 2)
    assert r["status"] == "날짜기반"
    assert r["hours_remaining"] is None and r["remaining_pct"] is None


def test_aircraft_not_found(db):
    with pytest.raises(ValueError):
        calc_d_time(999, 1)
