"""
CSC-02 · CSU-02-01  |  fn4: get_inventory()

부품 재고 현황 조회 — 기지별/전체, 카테고리·기체별 필터 + 안전재고 대비 상태 판정.

호출 테이블:
    components      (SELECT) — part_number, nomenclature, category, aircraft_id
    parts_inventory (SELECT) — quantity_on_hand (기지별 또는 합산)
    reorder_points  (SELECT) — safety_stock (상태 판정 기준)

수정 이력:
    2026-06-10 (6월2주차) — 신규 작성
        · P2 해제(components.aircraft_id NULL 허용) 반영
          → aircraft_id 지정 시 "해당 기체 전용 부품 + 공통 부품(aircraft_id NULL)" 함께 조회
        · location: "청주"|"무안" → 해당 기지 재고 / "all" → 양 기지 합산(1행/부품)
        · 안전재고(reorder_points.safety_stock) 대비 부족/경고/정상 상태 판정

⚠️  주의:
    · components.quantity(text)는 사용하지 않음. 실재고는 parts_inventory.quantity_on_hand(int).
    · reorder_points 데이터가 없는 부품은 safety_stock=None, status="기준없음".
"""

from __future__ import annotations
from functions.db import get_client


WARNING_RATIO = 1.5   # safety_stock × 1.5 이하 → 경고 (fn7 과 동일 기준)
_VALID_LOC = {"청주", "무안", "all"}


def get_inventory(
    aircraft_id: int | None = None,
    location: str = "all",
    category: str | None = None,
) -> list[dict]:
    """
    부품 재고 현황을 조회한다.

    Parameters
    ----------
    aircraft_id : int | None
        특정 기체 전용 부품 + 공통 부품(aircraft_id NULL)만 조회.
        None 이면 전체 부품.
    location : str
        "청주" | "무안" → 해당 기지 재고. "all"(기본) → 양 기지 합산.
    category : str | None
        components.category 필터 (예: "Engine"). None 이면 전체.

    Returns
    -------
    list[dict]
        부품별 1행. nomenclature 오름차순 정렬.
        [
            {
                "part_id"          : int,
                "part_number"      : str | None,
                "nomenclature"     : str | None,
                "category"         : str | None,
                "quantity_on_hand" : int,        # location 범위 합산
                "location"         : str,        # 조회 범위 ("청주"|"무안"|"all")
                "safety_stock"     : int | None, # reorder_points 기준 (없으면 None)
                "status"           : str,        # "부족"|"경고"|"정상"|"기준없음"
            }, ...
        ]
        조건에 맞는 부품이 없으면 빈 리스트.

    Raises
    ------
    ValueError
        · location 이 "청주"|"무안"|"all" 외
    """
    if location not in _VALID_LOC:
        raise ValueError(
            f"location 은 '청주' | '무안' | 'all' 이어야 합니다. 입력값: '{location}'"
        )

    client = get_client()

    # ── components 조회 (category 는 DB-side, aircraft_id 는 Python-side 필터)
    comp_q = client.table("components").select(
        "id, part_number, nomenclature, category, aircraft_id"
    )
    if category is not None:
        comp_q = comp_q.eq("category", category)
    comps = comp_q.execute()
    comp_rows = comps.data or []

    # aircraft_id 지정 시: 해당 기체 전용 + 공통(aircraft_id NULL)
    if aircraft_id is not None:
        comp_rows = [
            c for c in comp_rows
            if c.get("aircraft_id") == aircraft_id or c.get("aircraft_id") is None
        ]

    if not comp_rows:
        return []

    part_ids = [c["id"] for c in comp_rows]

    # ── parts_inventory 조회 (part_id IN, location 필터)
    inv_q = client.table("parts_inventory").select(
        "part_id, quantity_on_hand, location"
    ).in_("part_id", part_ids)
    if location != "all":
        inv_q = inv_q.eq("location", location)
    inv_rows = (inv_q.execute().data) or []

    # part_id → 합산 재고
    qty_map: dict[int, int] = {}
    for r in inv_rows:
        pid = r.get("part_id")
        if pid is not None:
            qty_map[pid] = qty_map.get(pid, 0) + int(r.get("quantity_on_hand") or 0)

    # ── reorder_points 조회 (part_id → safety_stock)
    rp_rows = (
        client.table("reorder_points")
        .select("part_id, safety_stock")
        .in_("part_id", part_ids)
        .execute()
        .data
    ) or []
    safety_map: dict[int, int] = {
        r["part_id"]: r["safety_stock"]
        for r in rp_rows
        if r.get("part_id") is not None and r.get("safety_stock") is not None
    }

    # ── 결과 조립
    result: list[dict] = []
    for c in comp_rows:
        pid = c["id"]
        qty = qty_map.get(pid, 0)
        ss  = safety_map.get(pid)

        if ss is None:
            status = "기준없음"
        elif qty <= ss:
            status = "부족"
        elif qty <= ss * WARNING_RATIO:
            status = "경고"
        else:
            status = "정상"

        result.append({
            "part_id":          pid,
            "part_number":      c.get("part_number"),
            "nomenclature":     c.get("nomenclature"),
            "category":         c.get("category"),
            "quantity_on_hand": qty,
            "location":         location,
            "safety_stock":     ss,
            "status":           status,
        })

    result.sort(key=lambda x: (x["nomenclature"] is None, x["nomenclature"] or ""))
    return result


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-10  6월2주차 — 신규 작성
#       · P2 해제(components.aircraft_id NULL 허용) 반영 — 공통 부품 단일 레코드 처리
#       · aircraft_id 지정 시 전용 부품 + 공통 부품 함께 조회 (Python-side 필터)
#       · location "all" 합산 / 기지별 분리, part_id IN 단일 조회로 N+1 회피
#       · reorder_points.safety_stock 대비 부족/경고/정상/기준없음 상태 판정
#         (fn7 과 동일한 WARNING_RATIO=1.5 기준)
#
# 향후 변경 예정
#       · location="all" 일 때 기지별 분해 뷰(청주 N / 무안 M) 옵션 추가 검토
#       · category 다중 선택(list) 지원 검토
# =============================================================================
