"""
CSC-03 · CSU-03-01  |  fn7: analyze_safety_stock()

안전재고 분석 — 부족 여부 및 발주 필요 판단

호출 테이블:
    components       (SELECT) — nomenclature 조회
    parts_inventory  (SELECT) — quantity_on_hand (기지별 또는 전체 합산)
    reorder_points   (SELECT) — safety_stock 자동 조회 (safety_stock_qty=None 시)

수정 이력:
    2026-05-27 (5월4주차) — Supabase 스키마 반영 (신규 작성)
    2026-06-03 (수정) — reorder_points 연동 추가
        · safety_stock_qty=None 이면 reorder_points.safety_stock 자동 조회
          (기존: 무조건 외부 파라미터 수신)
        · reorder_points 에 데이터 없고 safety_stock_qty 도 None 이면 ValueError

⚠️  DB 변경 예정 사항:
    inventory_history 테이블 신설 (P1) 후:
        · avg_daily_usage 외부 파라미터 → DB 자동 계산으로 전환
        · 최근 30일 출고 이력에서 일평균 소모량 자동 집계 예정
        · 파라미터 avg_daily_usage 제거 또는 optional 유지 협의 필요
"""

from __future__ import annotations
from functions.db import get_client


WARNING_RATIO = 1.5   # safety_stock × 1.5 이하 → 경고


def analyze_safety_stock(
    part_id: int,
    avg_daily_usage: float,
    safety_stock_qty: int | None = None,
    location: str = "all",
) -> dict:
    """
    특정 부품의 안전재고 충족 여부를 분석하고 발주 필요 여부를 반환한다.

    Parameters
    ----------
    part_id : int
        components.id (PK)
    avg_daily_usage : float
        일평균 소모량.
        inventory_history 테이블 신설 전까지 외부에서 직접 전달.
        0 이면 days_until_stockout = ∞ (예외 아님).
    safety_stock_qty : int | None
        안전재고 기준 수량.
        None 이면 reorder_points.safety_stock 에서 자동 조회.
        값을 직접 전달하면 DB 조회 없이 해당 값 사용 (파라미터 우선).
    location : str
        재고 조회 기지 범위.
        "청주" | "무안" | "all" (기본: "all" — 양 기지 합산)

    Returns
    -------
    dict
        {
            "part_id"             : int,
            "nomenclature"        : str,
            "current_qty"         : int,    # 조회 기지 기준 합산 재고
            "safety_stock_qty"    : int,    # 적용된 안전재고 기준
            "safety_stock_source" : str,    # "parameter" | "reorder_points"
            "status"              : str,    # "부족" | "경고" | "정상"
            "shortage_qty"        : int,    # 부족 수량 (정상=0)
            "order_required"      : bool,
            "days_until_stockout" : float,  # 소진 예상 일수 (usage=0 → inf)
        }

    Raises
    ------
    ValueError
        · safety_stock_qty < 0
        · avg_daily_usage < 0
        · location 이 "청주" | "무안" | "all" 외
        · part_id 미존재
        · reorder_points 데이터 없고 safety_stock_qty 도 None
        · 해당 조건의 재고 행 없음
    """

    # ── 입력 검증
    if safety_stock_qty is not None and safety_stock_qty < 0:
        raise ValueError(f"safety_stock_qty 는 0 이상이어야 합니다. 입력값: {safety_stock_qty}")
    if avg_daily_usage < 0:
        raise ValueError(f"avg_daily_usage 는 0 이상이어야 합니다. 입력값: {avg_daily_usage}")
    if location not in {"청주", "무안", "all"}:
        raise ValueError(
            f"location 은 '청주' | '무안' | 'all' 이어야 합니다. 입력값: '{location}'"
        )

    client = get_client()

    # ── 부품 존재 확인
    comp = (
        client.table("components")
        .select("id, nomenclature")
        .eq("id", part_id)
        .maybe_single()
        .execute()
    )
    if not comp.data:
        raise ValueError(f"part_id {part_id} 에 해당하는 부품이 없습니다.")
    nomenclature: str = comp.data["nomenclature"]

    # ── safety_stock_qty 결정
    # 파라미터로 직접 전달된 경우 DB 조회 없이 사용
    # None 이면 reorder_points.safety_stock 자동 조회
    safety_stock_source: str
    if safety_stock_qty is not None:
        safety_stock_source = "parameter"
    else:
        rp = (
            client.table("reorder_points")
            .select("safety_stock")
            .eq("part_id", part_id)
            .maybe_single()
            .execute()
        )
        if not rp.data or rp.data.get("safety_stock") is None:
            raise ValueError(
                f"part_id {part_id} 의 reorder_points 데이터가 없습니다. "
                f"safety_stock_qty 파라미터를 직접 전달하거나 reorder_points 에 데이터를 추가하세요."
            )
        safety_stock_qty   = int(rp.data["safety_stock"])
        safety_stock_source = "reorder_points"

    # ── 재고 조회 (기지 합산 or 단일 기지)
    # ⚠️ components.quantity 는 text 타입 ('10 pcs', '1 set' 등) → 수량 계산 불가
    #    실재고는 parts_inventory.quantity_on_hand (integer) 사용
    inv_q = (
        client.table("parts_inventory")
        .select("quantity_on_hand, location")
        .eq("part_id", part_id)
    )
    if location != "all":
        inv_q = inv_q.eq("location", location)
    inv = inv_q.execute()

    if not inv.data:
        raise ValueError(
            f"part_id={part_id}, location='{location}' 에 해당하는 재고 데이터가 없습니다."
        )

    current_qty: int = sum(r["quantity_on_hand"] for r in inv.data)

    # ── 소진 예상 일수
    days_until_stockout: float = (
        float("inf") if avg_daily_usage == 0
        else round(current_qty / avg_daily_usage, 1)
    )

    # ── 상태 판정
    # 부족: current_qty ≤ safety_stock_qty         → order_required=True
    # 경고: current_qty ≤ safety_stock_qty × 1.5   → order_required=False, 선제 발주 고려
    # 정상: current_qty > safety_stock_qty × 1.5
    shortage_qty:   int  = max(0, safety_stock_qty - current_qty)
    order_required: bool = current_qty <= safety_stock_qty

    if current_qty <= safety_stock_qty:
        status = "부족"
    elif current_qty <= safety_stock_qty * WARNING_RATIO:
        status = "경고"
    else:
        status = "정상"

    return {
        "part_id":              part_id,
        "nomenclature":         nomenclature,
        "current_qty":          current_qty,
        "safety_stock_qty":     safety_stock_qty,
        "safety_stock_source":  safety_stock_source,
        "status":               status,
        "shortage_qty":         shortage_qty,
        "order_required":       order_required,
        "days_until_stockout":  days_until_stockout,
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-05-27  5월4주차 — 신규 작성
#       · location 파라미터: "청주" | "무안" | "all" 세 가지 기지 조회 지원
#       · avg_daily_usage: 외부에서 직접 전달 (일평균 소모량)
#       · safety_stock_qty: 외부 파라미터로만 수신
#
# v1.1  2026-06-03  reorder_points 연동 추가
#       · safety_stock_qty=None 이면 reorder_points.safety_stock 자동 조회
#         (기존: 무조건 외부 파라미터 수신 → 호출 시 매번 값 전달 필요했음)
#       · 반환값에 safety_stock_source 필드 추가
#         ("parameter" | "reorder_points") — 어디서 기준값을 가져왔는지 추적
#       · 기존 파라미터 직접 전달 방식 하위 호환 유지
#
# 향후 변경 예정
#       · [inventory_history 신설 (P1) 후]
#         avg_daily_usage 파라미터 → DB 자동 계산으로 전환
#         최근 30일 출고 이력 기반 일평균 소모량 자동 집계 예정
#         파라미터 avg_daily_usage 제거 또는 optional 유지 팀 협의 필요
# =============================================================================
