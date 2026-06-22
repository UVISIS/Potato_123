"""fn4 get_inventory — 계약 고정 + 기지/카테고리/공용부품(매핑 테이블) 필터 + 상태 판정.

2026-06-20: component_aircraft 매핑 기준이 aircraft_id(개별 기체) → aircraft_model(기종)로
전환됨에 따라 테스트도 기종 기준으로 재작성.
"""
import pytest
from functions.csc02.fn4_get_inventory import get_inventory

FN4_ITEM_KEYS = {
    "part_id", "part_number", "nomenclature", "category",
    "quantity_on_hand", "location", "safety_stock", "status",
}


def _seed(db):
    db.seed("aircraft", [
        {"id": 1, "registration": "HL1176", "model": "Diamond DA40 NG"},   # DA-40NG
        {"id": 2, "registration": "HL1177", "model": "Diamond DA40 NG"},   # DA-40NG (동일 기종, 다른 기체)
        {"id": 3, "registration": "HL2046", "model": "Diamond DA42 NG"},   # DA-42NG
    ])
    db.seed("components", [
        {"id": 1, "part_number": "OF-1", "nomenclature": "OIL FILTER", "category": "Engine"},
        {"id": 2, "part_number": "SP-2", "nomenclature": "SPARK PLUG", "category": "Engine"},   # 공용 (매핑 없음)
        {"id": 3, "part_number": "TR-3", "nomenclature": "TIRE", "category": "Gear"},
        {"id": 4, "part_number": "BT-4", "nomenclature": "BOLT", "category": "Hardware"},       # DA-40NG+DA-42NG 공통 적용
    ])
    db.seed("component_aircraft", [
        {"id": 100, "component_id": 1, "aircraft_model": "DA40NG"},   # DA-40NG 전용
        {"id": 101, "component_id": 3, "aircraft_model": "DA42NG"},   # DA-42NG 전용
        {"id": 102, "component_id": 4, "aircraft_model": "DA40NG"},   # DA-40NG + DA-42NG
        {"id": 103, "component_id": 4, "aircraft_model": "DA42NG"},
    ])
    db.seed("parts_inventory", [
        {"id": 10, "part_id": 1, "quantity_on_hand": 5, "location": "청주"},
        {"id": 11, "part_id": 1, "quantity_on_hand": 3, "location": "무안"},
        {"id": 12, "part_id": 2, "quantity_on_hand": 1, "location": "청주"},
    ])
    db.seed("reorder_points", [
        {"id": 1, "part_id": 1, "safety_stock": 3},
        {"id": 2, "part_id": 2, "safety_stock": 8},
    ])


def test_contract_and_all_location_sum(db):
    _seed(db)
    rows = get_inventory()                       # 전체, all 합산
    assert len(rows) == 4
    for it in rows:
        assert set(it) == FN4_ITEM_KEYS
    oil = next(r for r in rows if r["part_id"] == 1)
    assert oil["quantity_on_hand"] == 8          # 청주5 + 무안3
    assert oil["location"] == "all"
    assert oil["status"] == "정상"               # 8 > 3*1.5


def test_location_filter(db):
    _seed(db)
    rows = get_inventory(location="청주")
    oil = next(r for r in rows if r["part_id"] == 1)
    assert oil["quantity_on_hand"] == 5          # 청주만


def test_aircraft_filter_includes_common(db):
    _seed(db)
    rows = get_inventory(aircraft_id=1)          # HL1176(DA-40NG): 전용(1) + 공용(2) + 다중매핑(4)
    ids = {r["part_id"] for r in rows}
    assert ids == {1, 2, 4}                      # 3(DA-42NG 전용)은 제외


def test_same_model_different_aircraft_sees_same_parts(db):
    """같은 기종(DA-40NG)의 다른 기체(HL1177)도 HL1176과 동일한 부품 목록을 봐야 한다."""
    _seed(db)
    ids_hl1176 = {r["part_id"] for r in get_inventory(aircraft_id=1)}
    ids_hl1177 = {r["part_id"] for r in get_inventory(aircraft_id=2)}
    assert ids_hl1176 == ids_hl1177 == {1, 2, 4}


def test_multi_model_mapping(db):
    """한 부품이 복수 기종에 매핑된 경우 양쪽 모두에서 조회되어야 한다."""
    _seed(db)
    ids_da40 = {r["part_id"] for r in get_inventory(aircraft_id=1)}   # DA-40NG
    ids_da42 = {r["part_id"] for r in get_inventory(aircraft_id=3)}   # DA-42NG
    assert 4 in ids_da40 and 4 in ids_da42        # BOLT 는 DA-40NG·DA-42NG 모두 적용
    assert 2 in ids_da40 and 2 in ids_da42        # 공용(매핑 없음)도 모두 포함
    assert 1 not in ids_da42 and 3 not in ids_da40  # 기종 전용 부품은 교차 제외


def test_no_mapping_rows_means_all_common(db):
    """component_aircraft 가 비어 있으면 모든 부품이 공용으로 간주된다."""
    db.seed("components", [
        {"id": 1, "part_number": "OF-1", "nomenclature": "OIL FILTER", "category": "Engine"},
    ])
    db.seed("component_aircraft", [])
    db.seed("parts_inventory", [])
    db.seed("reorder_points", [])
    rows = get_inventory(aircraft_id=99)          # 존재하지 않는 aircraft_id → 에러 아님, 공용만
    assert {r["part_id"] for r in rows} == {1}


def test_unknown_aircraft_id_falls_back_to_common_only(db):
    """존재하지 않는 aircraft_id 면 기종 조회가 안 돼서 공용 부품만 반환된다 (에러 아님)."""
    _seed(db)
    rows = get_inventory(aircraft_id=9999)
    ids = {r["part_id"] for r in rows}
    assert ids == {2}                             # 공용(매핑 없음)인 SPARK PLUG 만


def test_category_filter(db):
    _seed(db)
    rows = get_inventory(category="Gear")
    assert {r["part_id"] for r in rows} == {3}


def test_status_levels(db):
    _seed(db)
    rows = get_inventory()
    spark = next(r for r in rows if r["part_id"] == 2)
    assert spark["status"] == "부족"             # 1 <= 8
    tire = next(r for r in rows if r["part_id"] == 3)
    assert tire["safety_stock"] is None and tire["status"] == "기준없음"


def test_invalid_location(db):
    _seed(db)
    with pytest.raises(ValueError):
        get_inventory(location="서울")
