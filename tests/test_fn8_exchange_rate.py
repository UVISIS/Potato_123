"""fn8 환율 모음 — 5개 함수 계약 고정 + seed/record/get/rolling/timing 동작·예외."""
import pytest
from datetime import datetime, timezone
from functions.csc03.fn8_exchange_rate import (
    seed_historical_rates,
    record_exchange_rate,
    get_exchange_rate,
    get_rolling_average,
    evaluate_purchase_timing,
)

SEED_KEYS   = {"inserted", "skipped", "total_rows"}
RECORD_KEYS = {"saved", "rolling_avg_60", "data_count"}
GET_KEYS    = {"currency_code", "base_currency", "exchange_rate", "update_date", "is_stale"}
ROLL_KEYS   = {"rolling_avg", "std_dev", "data_count", "window", "oldest_date", "latest_date"}
TIMING_KEYS = {
    "current_rate", "rolling_avg", "std_dev", "z_score", "pct_vs_avg",
    "recommendation", "reason", "data_count", "oldest_date", "latest_date",
}


def _seed_rows(db, rates_dates):
    db.seed("currency_rates", [
        {"currency_code": "EUR", "base_currency": "KRW", "exchange_rate": r,
         "update_date": d}
        for d, r in rates_dates
    ])


# ── seed_historical_rates ────────────────────────────────────────
def test_seed_contract_on_empty(db):
    r = seed_historical_rates()
    assert set(r) == SEED_KEYS
    assert r["skipped"] is False
    assert r["inserted"] == 60                 # 5년치 60개월
    assert r["total_rows"] == 60
    assert len(db.rows("currency_rates")) == 60


def test_seed_skips_when_exists(db):
    seed_historical_rates()                    # 1차 적재 60건
    r = seed_historical_rates()                # 2차 → 스킵
    assert r["skipped"] is True
    assert r["inserted"] == 0
    assert len(db.rows("currency_rates")) == 60


# ── record_exchange_rate ─────────────────────────────────────────
def test_record_contract_and_rolling_update(db):
    _seed_rows(db, [("2025-11-01T00:00:00+00:00", 1669.4),
                    ("2025-12-01T00:00:00+00:00", 1685.09)])
    r = record_exchange_rate(1720.0)
    assert set(r) == RECORD_KEYS
    assert r["data_count"] == 3                 # 기존 2 + 신규 1
    assert isinstance(r["rolling_avg_60"], float)
    assert len(db.rows("currency_rates")) == 3


def test_record_rejects_nonpositive(db):
    with pytest.raises(ValueError):
        record_exchange_rate(0)


# ── get_exchange_rate ────────────────────────────────────────────
def test_get_contract_latest_and_fresh(db):
    now = datetime.now(timezone.utc).isoformat()
    _seed_rows(db, [("2025-01-01T00:00:00+00:00", 1539.65), (now, 1700.0)])
    r = get_exchange_rate()
    assert set(r) == GET_KEYS
    assert r["exchange_rate"] == 1700.0         # 최신 1건
    assert r["is_stale"] is False               # 방금 입력 → 최신


def test_get_stale_flag(db):
    _seed_rows(db, [("2020-01-01T00:00:00+00:00", 1300.0)])
    r = get_exchange_rate()
    assert r["is_stale"] is True                # 7일 초과


def test_get_no_data_raises(db):
    with pytest.raises(ValueError):
        get_exchange_rate()


# ── get_rolling_average ──────────────────────────────────────────
def test_rolling_contract(db):
    _seed_rows(db, [("2025-10-01T00:00:00+00:00", 1653.71),
                    ("2025-11-01T00:00:00+00:00", 1669.40),
                    ("2025-12-01T00:00:00+00:00", 1685.09)])
    r = get_rolling_average()
    assert set(r) == ROLL_KEYS
    assert r["data_count"] == 3
    assert r["latest_date"].startswith("2025-12")
    assert r["oldest_date"].startswith("2025-10")


def test_rolling_needs_two(db):
    _seed_rows(db, [("2025-12-01T00:00:00+00:00", 1685.09)])
    with pytest.raises(ValueError):
        get_rolling_average()


# ── evaluate_purchase_timing ─────────────────────────────────────
def test_timing_contract(db):
    seed_historical_rates()                     # 60개 실제 데이터
    r = evaluate_purchase_timing()
    assert set(r) == TIMING_KEYS
    assert r["recommendation"] in {"BUY", "WAIT", "NEUTRAL"}
    assert isinstance(r["z_score"], float)
    assert isinstance(r["reason"], str) and r["reason"]


def test_timing_buy_signal_on_low_rate(db):
    # 평균보다 크게 낮은 최신값 → Z ≤ -1 → BUY
    rows = [(f"2025-{m:02d}-01T00:00:00+00:00", 1600.0 + m) for m in range(1, 12)]
    rows.append(("2025-12-01T00:00:00+00:00", 1300.0))   # 최신: 급락
    _seed_rows(db, rows)
    r = evaluate_purchase_timing()
    assert r["recommendation"] == "BUY"
    assert r["z_score"] <= -1.0


def test_timing_needs_two(db):
    _seed_rows(db, [("2025-12-01T00:00:00+00:00", 1685.09)])
    with pytest.raises(ValueError):
        evaluate_purchase_timing()
