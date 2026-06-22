"""fn1 get_aircraft_info — 계약(반환 키) 고정 + 조회/예외 동작."""
import pytest
from functions.csc01.fn1_get_aircraft_info import get_aircraft_info

FN1_KEYS = {
    "aircraft_id", "registration", "model", "category", "status",
    "serial_number", "manufacture_year", "location", "total_flight_hours",
    "accumulated_hours", "last_inspection_date", "active_schedule_count",
    "recent_flights",
}


def _seed(db):
    db.seed("aircraft", [{
        "id": 1, "registration": "HL1254", "model": "Diamond DA40 NG",
        "category": "DA-40 NG", "status": "operational", "serial_number": "40N123",
        "manufacture_year": 2021, "total_flight_hours": 1200,
        "last_inspection_date": "2026-05-01",
    }])
    db.seed("flight_hours", [
        {"id": 1, "aircraft_id": 1, "flight_date": "2026-06-01",
         "flight_hours": 2.5, "flight_minutes": 30, "total_accumulated_hours": 1200.5,
         "pilot_name": "kim", "notes": None},
    ])
    db.seed("maintenance_schedule", [
        {"id": 1, "aircraft_id": 1, "status": "scheduled"},
        {"id": 2, "aircraft_id": 1, "status": "completed"},
    ])


def test_contract_keys(db):
    _seed(db)
    r = get_aircraft_info(1)
    assert set(r) == FN1_KEYS
    assert r["aircraft_id"] == 1
    assert r["registration"] == "HL1254"
    assert r["total_flight_hours"] == 1200            # int (aircraft 기준)
    assert r["accumulated_hours"] == 1200.5           # float (flight_hours 기준)
    assert r["active_schedule_count"] == 1            # scheduled 만 카운트
    assert r["recent_flights"] is None                # 기본 미포함


def test_lookup_by_registration_and_recent_flights(db):
    _seed(db)
    r = get_aircraft_info("HL1254", lookup_by="registration", include_recent_flights=True)
    assert r["aircraft_id"] == 1
    assert isinstance(r["recent_flights"], list) and len(r["recent_flights"]) == 1


def test_invalid_lookup_by(db):
    with pytest.raises(ValueError):
        get_aircraft_info(1, lookup_by="vin")


def test_not_found(db):
    db.seed("aircraft", [])
    with pytest.raises(ValueError):
        get_aircraft_info(999)
