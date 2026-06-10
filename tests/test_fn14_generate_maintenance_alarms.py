"""fn14 generate_maintenance_alarms — 계약 고정 + 임박분류 + 중복 방지."""
import pytest
from functions.csc04.fn14_generate_maintenance_alarms import generate_maintenance_alarms

FN14_KEYS = {"evaluated", "created", "skipped_existing", "alarms"}
ALARM_KEYS = {"alarm_id", "aircraft_id", "maintenance_schedule_id", "alarm_type", "severity", "message"}


def _seed(db):
    db.seed("d_time_counter", [
        {"id": 1, "aircraft_id": 1, "maintenance_schedule_id": 1, "hours_remaining": 5.0, "days_remaining": 2},
        {"id": 2, "aircraft_id": 1, "maintenance_schedule_id": 2, "hours_remaining": -3.0, "days_remaining": 0},
        {"id": 3, "aircraft_id": 1, "maintenance_schedule_id": 3, "hours_remaining": 500.0, "days_remaining": 99},
    ])
    db.seed("maintenance_schedule", [
        {"id": 1, "maintenance_type": "100hr"},
        {"id": 2, "maintenance_type": "Annual"},
        {"id": 3, "maintenance_type": "200hr"},
    ])


def test_contract_and_classification(db):
    _seed(db)
    r = generate_maintenance_alarms()
    assert set(r) == FN14_KEYS
    for a in r["alarms"]:
        assert set(a) == ALARM_KEYS
    assert r["evaluated"] == 3
    assert r["created"] == 2          # 5h→임박, -3h→초과, 500h→알람없음
    types = {a["alarm_type"] for a in r["alarms"]}
    assert types == {"정비임박", "정비초과"}
    # 알림 로그도 적재됨
    assert len(db.rows("notification_logs")) == 2


def test_dedup_existing_active_alarm(db):
    _seed(db)
    # sched 1 에 이미 활성 '정비임박' 알람 존재 → 중복 생성 스킵
    db.seed("maintenance_alarms", [
        {"id": 50, "aircraft_id": 1, "maintenance_schedule_id": 1, "alarm_type": "정비임박", "status": "active"},
    ])
    r = generate_maintenance_alarms()
    assert r["skipped_existing"] >= 1
    assert r["created"] == 1          # 초과(sched 2)만 신규


def test_no_notifications_flag(db):
    _seed(db)
    r = generate_maintenance_alarms(create_notifications=False)
    assert len(db.rows("notification_logs")) == 0
    assert r["created"] == 2


def test_invalid_thresholds(db):
    with pytest.raises(ValueError):
        generate_maintenance_alarms(warning_hours=30, info_hours=10)
