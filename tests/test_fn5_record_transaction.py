"""fn5 record_transaction — 계약 고정 + 입고/출고/조정/초과 방어."""
import pytest
from functions.csc02.fn5_record_transaction import record_transaction

FN5_KEYS = {
    "transaction_id", "part_id", "transaction_type", "quantity",
    "quantity_before", "quantity_changed", "quantity_after",
    "location", "inventory_id", "history_id",
}


def _seed(db):
    db.seed("components", [{"id": 1, "nomenclature": "OIL FILTER"}])
    db.seed("parts_inventory", [{"id": 10, "part_id": 1, "quantity_on_hand": 5, "location": "청주"}])


def test_contract_and_outbound(db):
    _seed(db)
    r = record_transaction(1, "출고", 3, location="청주", handled_by="세은")
    assert set(r) == FN5_KEYS
    assert r["transaction_type"] == "출고"
    assert (r["quantity_before"], r["quantity_changed"], r["quantity_after"]) == (5, -3, 2)
    # 부수효과 3종: 원장 + 재고 갱신 + 이력
    assert len(db.rows("parts_transactions")) == 1
    assert db.rows("parts_inventory")[0]["quantity_on_hand"] == 2
    assert len(db.rows("inventory_history")) == 1


def test_inbound_increases_stock(db):
    _seed(db)
    r = record_transaction(1, "입고", 10, location="청주")
    assert r["quantity_after"] == 15


def test_adjust_sets_absolute(db):
    _seed(db)
    r = record_transaction(1, "조정", 8, location="청주")
    assert r["quantity_after"] == 8
    assert r["quantity_changed"] == 3


def test_oversell_blocked(db):
    _seed(db)
    with pytest.raises(ValueError):
        record_transaction(1, "출고", 99, location="청주")


def test_oversell_allowed_with_flag(db):
    _seed(db)
    r = record_transaction(1, "출고", 99, location="청주", allow_negative=True)
    assert r["quantity_after"] == 5 - 99


def test_unknown_type_rejected(db):
    _seed(db)
    with pytest.raises(ValueError):
        record_transaction(1, "이동", 1, location="청주")


# ── 단일 중앙창고 모델 (2026-06-13 디커플링) ──────────────────

def test_destination_recorded_central_stock(db):
    """destination = 목적지 비행교육원이 parts_transactions.location 에 기록되고,
    재고는 중앙 단일행에서 차감된다 (location 필터 없음)."""
    db.seed("components", [{"id": 1, "nomenclature": "OIL FILTER"}])
    # 중앙창고 단일행 (location=None)
    db.seed("parts_inventory", [{"id": 10, "part_id": 1, "quantity_on_hand": 5, "location": None}])
    r = record_transaction(1, "출고", 2, destination="무안", handled_by="세은")
    assert r["quantity_after"] == 3
    assert r["location"] == "무안"                       # 목적지 기록
    assert db.rows("parts_transactions")[0]["location"] == "무안"
    assert db.rows("inventory_history")[0]["location"] == "무안"


def test_multiple_inventory_rows_blocked(db):
    """부품당 재고 행이 2개(청주/무안 분리 잔존)면 단일화 안내와 함께 ValueError."""
    db.seed("components", [{"id": 1, "nomenclature": "OIL FILTER"}])
    db.seed("parts_inventory", [
        {"id": 10, "part_id": 1, "quantity_on_hand": 3, "location": "청주"},
        {"id": 11, "part_id": 1, "quantity_on_hand": 2, "location": "무안"},
    ])
    with pytest.raises(ValueError):
        record_transaction(1, "출고", 1, destination="청주")
