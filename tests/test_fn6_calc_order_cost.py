"""fn6 calc_order_cost — 계약 고정 + 단가/환율 자동조회 + 발주서 생성."""
import pytest
from functions.csc03.fn6_calc_order_cost import calc_order_cost

FN6_KEYS = {
    "part_id", "nomenclature", "order_qty", "unit_price_eur", "unit_price_source",
    "exchange_rate", "exchange_rate_source", "total_eur", "total_krw",
    "purchase_order_id", "status",
}


def _seed(db):
    db.seed("components", [{"id": 1, "nomenclature": "OIL FILTER", "unit_price_eur": 25.0}])
    db.seed("currency_rates", [{
        "id": 1, "currency_code": "EUR", "base_currency": "KRW",
        "exchange_rate": 1450.0, "update_date": "2026-06-01T00:00:00Z",
    }])


def test_contract_auto_lookup(db):
    _seed(db)
    r = calc_order_cost(1, 10)
    assert set(r) == FN6_KEYS
    assert r["unit_price_source"] == "components"
    assert r["exchange_rate_source"] == "currency_rates"
    assert r["total_eur"] == 250.0
    assert r["total_krw"] == 362500.0
    assert r["purchase_order_id"] is None      # create_order=False


def test_parameter_priority(db):
    _seed(db)
    r = calc_order_cost(1, 2, unit_price_eur=100.0, exchange_rate=1500.0)
    assert r["unit_price_source"] == "parameter"
    assert r["exchange_rate_source"] == "parameter"
    assert r["total_eur"] == 200.0 and r["total_krw"] == 300000.0


def test_create_order_inserts_po(db):
    _seed(db)
    r = calc_order_cost(1, 4, create_order=True)
    assert r["purchase_order_id"] is not None
    assert r["status"] == "발주예정"
    assert len(db.rows("purchase_orders")) == 1


def test_invalid_qty(db):
    _seed(db)
    with pytest.raises(ValueError):
        calc_order_cost(1, 0)


def test_missing_rate_raises(db):
    db.seed("components", [{"id": 1, "nomenclature": "X", "unit_price_eur": 10.0}])
    # currency_rates 비어있고 환율 미지정 → ValueError
    with pytest.raises(ValueError):
        calc_order_cost(1, 1)
