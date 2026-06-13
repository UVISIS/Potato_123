"""fn16 정비 스케줄 시딩 — 동일기종 복사 + 신규기종 수동등록."""
import pytest
from functions.csc04.fn16_seed_maintenance_schedule import (
    copy_maintenance_schedule,
    register_maintenance_schedule,
)

COPY_KEYS = {"target_aircraft_id", "source_aircraft_id", "copied", "schedule_ids"}
REG_KEYS = {"aircraft_id", "registered", "schedule_ids"}


def _seed_two_aircraft(db):
    # 동일 기종(DA42NG) 2대: id=1 원본(스케줄 보유), id=2 신규(스케줄 없음)
    db.seed("aircraft", [
        {"id": 1, "model": "DA42NG"},
        {"id": 2, "model": "DA42NG"},
    ])
    db.seed("maintenance_schedule", [
        {"id": 100, "aircraft_id": 1, "maintenance_type": "기체100HRS",
         "interval_hours": 100, "interval_months": None, "due_hours": 79, "status": "scheduled"},
        {"id": 101, "aircraft_id": 1, "maintenance_type": "엔진1000HRS",
         "interval_hours": 1000, "interval_months": None, "due_hours": 653, "status": "scheduled"},
    ])


def test_copy_same_model(db):
    _seed_two_aircraft(db)
    r = copy_maintenance_schedule(2)
    assert set(r) == COPY_KEYS
    assert r["source_aircraft_id"] == 1
    assert r["copied"] == 2
    # 신규 기체 스케줄 2건 생성 + 도래시점 초기화 확인
    new_rows = [s for s in db.rows("maintenance_schedule") if s["aircraft_id"] == 2]
    assert len(new_rows) == 2
    assert all(s["due_hours"] is None for s in new_rows)      # 초기화
    assert all(s["status"] == "scheduled" for s in new_rows)
    assert {s["maintenance_type"] for s in new_rows} == {"기체100HRS", "엔진1000HRS"}


def test_copy_no_same_model_raises_lookup(db):
    # 신규 기종 — 동일 기종 원본 없음
    db.seed("aircraft", [{"id": 5, "model": "NEW_TYPE"}])
    with pytest.raises(LookupError):
        copy_maintenance_schedule(5)


def test_copy_missing_target_raises_value(db):
    with pytest.raises(ValueError):
        copy_maintenance_schedule(999)


def test_register_manual(db):
    db.seed("aircraft", [{"id": 7, "model": "NEW_TYPE"}])
    r = register_maintenance_schedule(7, [
        {"maintenance_type": "기체100HRS", "interval_hours": 100},
        {"maintenance_type": "프로펠러", "interval_hours": 0, "interval_months": 72},
    ])
    assert set(r) == REG_KEYS
    assert r["registered"] == 2
    assert len([s for s in db.rows("maintenance_schedule") if s["aircraft_id"] == 7]) == 2


def test_register_empty_raises(db):
    db.seed("aircraft", [{"id": 7, "model": "NEW_TYPE"}])
    with pytest.raises(ValueError):
        register_maintenance_schedule(7, [])


def test_register_missing_field_raises(db):
    db.seed("aircraft", [{"id": 7, "model": "NEW_TYPE"}])
    with pytest.raises(ValueError):
        register_maintenance_schedule(7, [{"maintenance_type": "X"}])  # interval_hours 누락
