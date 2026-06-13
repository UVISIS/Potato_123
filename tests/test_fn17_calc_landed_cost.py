"""fn17 calc_landed_cost — 관부과세·운임·학술감면·직구절감 검증."""
import pytest
from functions.csc03.fn17_calc_landed_cost import calc_landed_cost

KEYS = {
    "order_qty", "unit_price_eur", "exchange_rate",
    "fob_eur", "freight_eur", "insurance_eur", "cif_eur", "cif_krw",
    "customs_duty_rate", "is_academic", "academic_reduction_rate",
    "duty_krw", "duty_krw_no_reduction", "vat_rate", "vat_krw",
    "total_landed_krw", "agent_markup_rate", "agent_total_krw",
    "direct_total_krw", "savings_krw", "savings_pct",
    "freight_basis", "assumptions_note",
}


def test_contract_keys():
    r = calc_landed_cost(unit_price_eur=100, order_qty=10, exchange_rate=1700)
    assert set(r) == KEYS


def test_academic_reduction_applied():
    # 관세율 8% 가정 → 학술감면 80% → 관세의 20%만
    r = calc_landed_cost(
        unit_price_eur=100, order_qty=10, exchange_rate=1700,
        customs_duty_rate=0.08, is_academic=True,
    )
    # CIF = (1000 + 보험 1000*0.5%=5) * 1700 = 1005 * 1700 = 1,708,500
    assert r["cif_krw"] == 1708500
    full_duty = round(1708500 * 0.08, 0)               # 136,680
    assert r["duty_krw_no_reduction"] == full_duty
    assert r["duty_krw"] == round(full_duty * 0.2, 0)  # 감면 후 20%


def test_academic_vs_general_duty():
    base = dict(unit_price_eur=100, order_qty=10, exchange_rate=1700, customs_duty_rate=0.08)
    academic = calc_landed_cost(is_academic=True, **base)
    general  = calc_landed_cost(is_academic=False, **base)
    assert academic["duty_krw"] < general["duty_krw"]
    assert general["duty_krw"] == general["duty_krw_no_reduction"]


def test_freight_per_pallet():
    r = calc_landed_cost(
        unit_price_eur=100, order_qty=10, exchange_rate=1700,
        freight_per_pallet_eur=500, pallets=2,
    )
    assert r["freight_basis"] == "per_pallet"
    assert r["freight_eur"] == 1000.0


def test_freight_per_kg():
    r = calc_landed_cost(
        unit_price_eur=100, order_qty=10, exchange_rate=1700,
        freight_per_kg_eur=5, weight_kg=40,
    )
    assert r["freight_basis"] == "per_kg"
    assert r["freight_eur"] == 200.0


def test_direct_savings_positive():
    # 대행 수수료가 있으면 직구가 더 저렴(절감 > 0)
    r = calc_landed_cost(
        unit_price_eur=100, order_qty=10, exchange_rate=1700,
        customs_duty_rate=0.08, agent_markup_rate=0.12,
    )
    assert r["savings_krw"] > 0
    assert r["direct_total_krw"] < r["agent_total_krw"]


def test_invalid_inputs():
    with pytest.raises(ValueError):
        calc_landed_cost(unit_price_eur=100, order_qty=0)
    with pytest.raises(ValueError):
        calc_landed_cost(unit_price_eur=-1, order_qty=1)
    with pytest.raises(ValueError):
        calc_landed_cost(unit_price_eur=100, order_qty=1, exchange_rate=0)
