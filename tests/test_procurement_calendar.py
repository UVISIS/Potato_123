"""procurement_calendar.next_order_date — 1월/7월 발주일 계산."""
from functions.csc03.procurement_calendar import next_order_date


def test_before_july_returns_july():
    r = next_order_date("2026-06-13")
    assert r["next_order_date"] == "2026-07-01"
    assert r["batch"] == 7
    assert r["days_remaining"] == 18


def test_after_july_returns_next_jan():
    r = next_order_date("2026-08-01")
    assert r["next_order_date"] == "2027-01-01"
    assert r["batch"] == 1


def test_on_july_first_returns_july():
    r = next_order_date("2026-07-01")
    assert r["next_order_date"] == "2026-07-01"
    assert r["days_remaining"] == 0


def test_january_start_returns_jan():
    r = next_order_date("2026-01-01")
    assert r["next_order_date"] == "2026-01-01"
    assert r["batch"] == 1
