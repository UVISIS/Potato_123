"""fn3 update_flight_hours — 계약 고정 + 누적 갱신/은행가 반올림/예외."""
import pytest
from functions.csc01.fn3_update_flight_hours import update_flight_hours

FN3_KEYS = {"log_id", "total_accumulated_hours", "aircraft_total"}


def test_contract_and_accumulate(db):
    db.seed("aircraft", [{"id": 1, "total_flight_hours": 1000}])
    r = update_flight_hours(1, "2026-06-01", 2.5, pilot_name="kim")
    assert set(r) == FN3_KEYS
    assert r["total_accumulated_hours"] == 1002.5     # float 보존
    assert r["aircraft_total"] == 1002                # int 반올림(은행가: 1002.5→1002)
    # 부수효과: flight_hours 1행 적재 + aircraft 누적 갱신
    assert len(db.rows("flight_hours")) == 1
    assert db.rows("aircraft")[0]["total_flight_hours"] == 1002


def test_future_date_rejected(db):
    db.seed("aircraft", [{"id": 1, "total_flight_hours": 0}])
    with pytest.raises(ValueError):
        update_flight_hours(1, "2999-01-01", 1.0)


def test_nonpositive_hours_rejected(db):
    db.seed("aircraft", [{"id": 1, "total_flight_hours": 0}])
    with pytest.raises(ValueError):
        update_flight_hours(1, "2026-06-01", 0)


def test_aircraft_not_found(db):
    with pytest.raises(ValueError):
        update_flight_hours(999, "2026-06-01", 1.0)
