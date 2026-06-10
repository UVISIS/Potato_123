"""fn15 refresh_dashboard_metrics — 계약 고정 + 지표 집계 + 캐시."""
import pytest
from functions.csc05.fn15_refresh_dashboard_metrics import refresh_dashboard_metrics

FN15_KEYS = {"refreshed", "metrics", "updated_at", "upsert_count"}
EXPECTED_METRICS = {
    "aircraft_total", "aircraft_operational", "aircraft_grounded",
    "maintenance_overdue", "maintenance_critical", "maintenance_warning",
    "alarm_active", "alarm_critical", "stock_shortage", "stock_warning",
    "flight_hours_this_month", "maintenance_done_this_month",
}


def _seed(db):
    db.seed("aircraft", [
        {"id": 1, "status": "operational"},
        {"id": 2, "status": "grounded"},
    ])
    db.seed("d_time_counter", [
        {"id": 1, "hours_remaining": -2.0},   # overdue
        {"id": 2, "hours_remaining": 5.0},    # critical
        {"id": 3, "hours_remaining": 20.0},   # warning
    ])
    db.seed("maintenance_alarms", [
        {"id": 1, "severity": "critical", "status": "active"},
    ])
    db.seed("parts_inventory", [{"id": 1, "part_id": 1, "quantity_on_hand": 2}])
    db.seed("reorder_points", [{"id": 1, "part_id": 1, "safety_stock": 5}])


def test_contract_and_metrics(db):
    _seed(db)
    r = refresh_dashboard_metrics(force=True)
    assert set(r) == FN15_KEYS
    assert r["refreshed"] is True
    assert EXPECTED_METRICS.issubset(set(r["metrics"]))
    assert r["metrics"]["aircraft_total"] == 2.0
    assert r["metrics"]["maintenance_overdue"] == 1.0
    assert r["metrics"]["maintenance_critical"] == 1.0
    assert r["metrics"]["stock_shortage"] == 1.0        # 2 <= 5
    assert r["upsert_count"] == len(r["metrics"])


def test_cache_hit_skips_refresh(db):
    _seed(db)
    refresh_dashboard_metrics(force=True)               # 최초 갱신 (update_time=now)
    r2 = refresh_dashboard_metrics(force=False)         # 5분 내 → 캐시 hit
    assert r2["refreshed"] is False
    assert r2["upsert_count"] == 0
