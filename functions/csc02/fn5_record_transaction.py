from __future__ import annotations
from functions.db import get_client


# 입고(+) / 출고(-) / 조정(절대값 세팅) 분류
_IN_TYPES     = {"입고", "IN", "in", "RECEIVE", "receipt"}
_OUT_TYPES    = {"출고", "OUT", "out", "ISSUE", "consume"}
_ADJUST_TYPES = {"조정", "ADJUST", "adjust", "SET"}


def record_transaction(
    part_id: int,
    transaction_type: str,
    quantity: int,
    location: str | None = None,
    aircraft_id: int | None = None,
    handled_by: str | None = None,
    notes: str | None = None,
    reference_number: str | None = None,
    supplier_id: int | None = None,
    unit_price_eur: float | None = None,
    exchange_rate_applied: float | None = None,
    maintenance_type: str | None = None,
    maintenance_history_id: int | None = None,
    destination: str | None = None,
    allow_negative: bool = False,
) -> dict:
    """
    부품 입출고를 기록하고 재고를 갱신한 뒤 변동 이력을 남긴다.

    Parameters
    ----------
    part_id : int
        components.id (PK)
    transaction_type : str
        "입고"|"출고"|"조정" 또는 "IN"|"OUT"|"ADJUST".
        입고 → 현재고 +quantity / 출고 → -quantity / 조정 → 현재고를 quantity 로 세팅.
    quantity : int
        변동 수량(0 이상). 조정의 경우 목표 수량.
    location : str | None
        [하위호환 별칭] destination 미지정 시 목적지로 사용. 단일 중앙창고 모델에서는
        재고 행 선택에 더 이상 사용되지 않는다(중앙 단일행에서 차감).
    aircraft_id, handled_by, notes, reference_number, supplier_id,
    unit_price_eur, exchange_rate_applied, maintenance_type, maintenance_history_id
        parts_transactions 부가 정보(모두 선택).
    destination : str | None
        출고 목적지 비행교육원("청주"|"무안"). parts_transactions.location 및
        inventory_history.location 에 기록된다. (입고/조정은 보통 None)
    allow_negative : bool
        True 이면 출고 시 현재고 초과를 허용(음수 재고 가능). 기본 False(초과 시 ValueError).

    Returns
    -------
    dict
        {
            "transaction_id"  : int,
            "part_id"         : int,
            "transaction_type": str,   # 정규화된 표기 ("입고"|"출고"|"조정")
            "quantity"        : int,
            "quantity_before" : int,
            "quantity_changed": int,   # 부호 포함 (+/-)
            "quantity_after"  : int,
            "location"        : str | None,
            "inventory_id"    : int,
            "history_id"      : int,
        }

    Raises
    ------
    ValueError
        · quantity < 0
        · transaction_type 미인식
        · part_id 미존재
        · location 다중 재고 행 존재(대상 모호)
        · 출고 초과(allow_negative=False)
    RuntimeError
        · parts_transactions / parts_inventory / inventory_history 반영 실패
    """

    # ── 입력 검증
    if quantity < 0:
        raise ValueError(f"quantity 는 0 이상이어야 합니다. 입력값: {quantity}")

    if transaction_type in _IN_TYPES:
        norm_type, sign = "입고", +1
    elif transaction_type in _OUT_TYPES:
        norm_type, sign = "출고", -1
    elif transaction_type in _ADJUST_TYPES:
        norm_type, sign = "조정", 0
    else:
        raise ValueError(
            f"transaction_type 미인식: '{transaction_type}' "
            f"(허용: 입고/출고/조정 또는 IN/OUT/ADJUST)"
        )

    client = get_client()

    # 단일 중앙창고 모델 (2026-06-13 결정):
    #   · 재고 차감은 부품당 '중앙창고 단일 행'에서 수행 (location 필터 안 함)
    #   · destination = 출고 목적지 비행교육원(청주/무안) → parts_transactions.location 에 기록
    #   · location 파라미터는 destination 의 하위호환 별칭 (destination 미지정 시 사용)
    dest = destination if destination is not None else location

    # ── 부품 존재 확인
    comp = (
        client.table("components")
        .select("id")
        .eq("id", part_id)
        .maybe_single()
        .execute()
    )
    if not comp.data:
        raise ValueError(f"part_id {part_id} 에 해당하는 부품이 없습니다.")

    # ── 현재 재고 행 조회 (part_id 기준 중앙 단일행 — location 필터 없음)
    inv = client.table("parts_inventory").select("id, quantity_on_hand, location").eq("part_id", part_id).execute()
    inv_rows = inv.data or []

    if len(inv_rows) > 1:
        raise ValueError(
            f"part_id {part_id} 의 재고 행이 {len(inv_rows)}개입니다. "
            f"단일 중앙창고 모델에서는 부품당 재고 행이 1개여야 합니다 "
            f"(parts_inventory 청주/무안 분리 행을 합산·단일화 필요 — DB 작업)."
        )

    inv_row        = inv_rows[0] if inv_rows else None
    quantity_before = int(inv_row["quantity_on_hand"]) if inv_row else 0

    # ── 변동 계산
    if norm_type == "조정":
        quantity_after   = quantity
        quantity_changed = quantity_after - quantity_before
    else:
        quantity_changed = sign * quantity
        quantity_after   = quantity_before + quantity_changed

    if quantity_after < 0 and not allow_negative:
        raise ValueError(
            f"출고 수량({quantity})이 현재고({quantity_before})를 초과합니다. "
            f"allow_negative=True 로 호출하면 음수 재고를 허용합니다."
        )

    # ── 1) parts_transactions INSERT
    tx_payload = {
        "part_id":                part_id,
        "transaction_type":       norm_type,
        "quantity":               quantity,
        "location":               dest,       # 출고 목적지 비행교육원 (청주/무안)
        "aircraft_id":            aircraft_id,
        "handled_by":             handled_by,
        "notes":                  notes,
        "reference_number":       reference_number,
        "supplier_id":            supplier_id,
        "unit_price_eur":         unit_price_eur,
        "exchange_rate_applied":  exchange_rate_applied,
        "maintenance_type":       maintenance_type,
        "maintenance_history_id": maintenance_history_id,
    }
    # None 값은 제거(DB 기본값/NULL 처리에 위임)
    tx_payload = {k: v for k, v in tx_payload.items() if v is not None}

    try:
        tx_res = client.table("parts_transactions").insert(tx_payload).execute()
        transaction_id = _extract_id(tx_res.data)
        if transaction_id is None:
            raise RuntimeError("parts_transactions INSERT 결과에서 id 를 얻지 못했습니다.")
    except Exception as e:
        raise RuntimeError(f"parts_transactions 기록 실패: {e}")

    # ── 2) parts_inventory UPDATE(기존) / INSERT(신규)
    try:
        if inv_row:
            inventory_id = inv_row["id"]
            client.table("parts_inventory").update(
                {"quantity_on_hand": quantity_after}
            ).eq("id", inventory_id).execute()
        else:
            new_inv = {"part_id": part_id, "quantity_on_hand": quantity_after}
            inv_ins = client.table("parts_inventory").insert(new_inv).execute()
            inventory_id = _extract_id(inv_ins.data)
    except Exception as e:
        raise RuntimeError(f"parts_inventory 갱신 실패: {e}")

    # ── 3) inventory_history INSERT
    hist_payload = {
        "part_id":          part_id,
        "transaction_id":   transaction_id,
        "transaction_type": norm_type,
        "quantity_changed": quantity_changed,
        "quantity_before":  quantity_before,
        "quantity_after":   quantity_after,
        "location":         dest,
        "aircraft_id":      aircraft_id,
        "handled_by":       handled_by,
        "notes":            notes,
    }
    hist_payload = {k: v for k, v in hist_payload.items() if v is not None}

    try:
        hist_res = client.table("inventory_history").insert(hist_payload).execute()
        history_id = _extract_id(hist_res.data)
    except Exception as e:
        raise RuntimeError(f"inventory_history 적재 실패: {e}")

    return {
        "transaction_id":   transaction_id,
        "part_id":          part_id,
        "transaction_type": norm_type,
        "quantity":         quantity,
        "quantity_before":  quantity_before,
        "quantity_changed": quantity_changed,
        "quantity_after":   quantity_after,
        "location":         dest,
        "inventory_id":     inventory_id,
        "history_id":       history_id,
    }


def _extract_id(raw) -> int | None:
    """INSERT 결과(res.data)에서 id 추출. Supabase(list[dict]) / Mock(list|dict|None) 모두 대응."""
    if isinstance(raw, list) and raw:
        return raw[0].get("id")
    if isinstance(raw, dict):
        return raw.get("id")
    return None


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-10  6월2주차 — 신규 작성
#       · P1 해제(inventory_history 신설, parts_transactions 컬럼 확장) 반영
#       · 입고/출고/조정 3종 트랜잭션 통합 처리
#       · 트랜잭션 → 재고 갱신 → 이력 적재 3단계를 단일 함수로 묶음
#       · 출고 초과 방어(allow_negative 옵션), None 페이로드 자동 정리
#       · INSERT 결과 id 추출 헬퍼(_extract_id) — Mock 테스트 호환
#
# 향후 변경 예정
#       · inventory_history 자동적재 트리거 도입 시 수동 INSERT 단계 제거
#       · parts_inventory 동시성(낙관적 락) 보강 — 현재는 last-write-wins
#
# v1.1  2026-06-13  단일 중앙창고 모델 반영 (디커플링)
#       · location(재고 행 필터) / destination(출고 목적지) 역할 분리
#         - 재고 차감: 부품당 중앙 단일행에서 수행 (location 필터 제거)
#         - destination: 목적지 비행교육원(청주/무안) → parts_transactions.location 기록
#       · destination 파라미터 신설, location 은 하위호환 별칭으로 유지
#       · 재고 행 2개 이상이면 단일화 안내 메시지로 ValueError
#         ⚠️ 의존: B담당 parts_inventory 청주/무안 분리행 → 부품당 1행 단일화(합산) 필요
# =============================================================================
