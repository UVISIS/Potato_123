from __future__ import annotations
from functions.db import get_client


def get_required_parts(
    maintenance_type: str,
    aircraft_model: str | None = None,
) -> list[dict]:
    """
    특정 정비 유형(BOM)에 필요한 부품 목록과 소요 수량을 반환한다.

    Parameters
    ----------
    maintenance_type : str
        정비 유형 (예: "100hr", "Annual", "Prop Overhaul"). bom.maintenance_type 와 매칭.
    aircraft_model : str | None
        기종 (예: "DA40NG"|"DA42NG"). None 이면 해당 정비유형 전체.

    Returns
    -------
    list[dict]
        [
            {
                "part_id"       : int,
                "nomenclature"  : str | None,
                "part_number"   : str | None,
                "required_qty"  : int,
                "unit"          : str | None,
                "unit_price_eur": float | None,
            }, ...
        ]
        해당 BOM 이 없으면 빈 리스트.

    Raises
    ------
    ValueError
        · maintenance_type 가 빈 문자열
    """
    if not maintenance_type or not maintenance_type.strip():
        raise ValueError("maintenance_type 은 비어 있을 수 없습니다.")

    client = get_client()

    # ── BOM 조회
    bom_q = client.table("bom").select(
        "part_id, required_qty, unit, maintenance_type, aircraft_model"
    ).eq("maintenance_type", maintenance_type)
    if aircraft_model is not None:
        bom_q = bom_q.eq("aircraft_model", aircraft_model)
    bom = bom_q.execute()
    bom_rows = bom.data or []

    if not bom_rows:
        return []

    # ── components 병합 (part_id IN (...) 단일 조회)
    part_ids = [r["part_id"] for r in bom_rows if r.get("part_id") is not None]
    comp_map: dict[int, dict] = {}
    if part_ids:
        comps = (
            client.table("components")
            .select("id, nomenclature, part_number, unit_price_eur")
            .in_("id", part_ids)
            .execute()
        )
        comp_map = {c["id"]: c for c in (comps.data or [])}

    result: list[dict] = []
    for r in bom_rows:
        pid  = r.get("part_id")
        comp = comp_map.get(pid, {})
        price = comp.get("unit_price_eur")
        result.append({
            "part_id":        pid,
            "nomenclature":   comp.get("nomenclature"),
            "part_number":    comp.get("part_number"),
            "required_qty":   int(r.get("required_qty") or 0),
            "unit":           r.get("unit"),
            "unit_price_eur": float(price) if price is not None else None,
        })
    return result


def check_parts_availability(
    maintenance_type: str,
    aircraft_model: str | None = None,
    location: str = "all",
) -> dict:
    """
    정비 유형별 소요 부품(fn9)을 현재고와 대조해 가용성/부족분을 판정한다.

    Parameters
    ----------
    maintenance_type : str
        정비 유형. fn9 와 동일.
    aircraft_model : str | None
        기종. fn9 와 동일.
    location : str
        재고 조회 기지 범위. "청주"|"무안"|"all"(기본, 양 기지 합산).

    Returns
    -------
    dict
        {
            "maintenance_type" : str,
            "aircraft_model"   : str | None,
            "location"         : str,
            "can_proceed"      : bool,      # 모든 부품 충족 시 True
            "total_items"      : int,
            "shortage_items"   : int,       # 부족 품목 수
            "items"            : [
                {
                    "part_id"      : int,
                    "nomenclature" : str | None,
                    "required_qty" : int,
                    "on_hand_qty"  : int,
                    "shortage_qty" : int,    # max(0, required - on_hand)
                    "status"       : str,    # "충족" | "부족"
                }, ...
            ],
        }

    Raises
    ------
    ValueError
        · location 이 "청주"|"무안"|"all" 외
        · maintenance_type 빈 문자열 (fn9 에서 검증)
    """
    if location not in {"청주", "무안", "all"}:
        raise ValueError(
            f"location 은 '청주' | '무안' | 'all' 이어야 합니다. 입력값: '{location}'"
        )

    required = get_required_parts(maintenance_type, aircraft_model)

    client = get_client()
    items: list[dict] = []
    shortage_items = 0

    for req in required:
        pid          = req["part_id"]
        required_qty = req["required_qty"]

        inv_q = client.table("parts_inventory").select("quantity_on_hand, location").eq("part_id", pid)
        if location != "all":
            inv_q = inv_q.eq("location", location)
        inv = inv_q.execute()
        on_hand_qty = sum(int(r["quantity_on_hand"]) for r in (inv.data or []))

        shortage_qty = max(0, required_qty - on_hand_qty)
        status = "부족" if shortage_qty > 0 else "충족"
        if shortage_qty > 0:
            shortage_items += 1

        items.append({
            "part_id":      pid,
            "nomenclature": req["nomenclature"],
            "required_qty": required_qty,
            "on_hand_qty":  on_hand_qty,
            "shortage_qty": shortage_qty,
            "status":       status,
        })

    return {
        "maintenance_type": maintenance_type,
        "aircraft_model":   aircraft_model,
        "location":         location,
        "can_proceed":      shortage_items == 0 and len(items) > 0,
        "total_items":      len(items),
        "shortage_items":   shortage_items,
        "items":            items,
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-10  6월2주차 — 신규 작성
#       · fn9/fn10 단일 파일(강한 의존성) — API import 경로 docstring 명시
#       · fn9: bom → components 병합(part_id IN 단일 조회로 N+1 회피)
#       · fn10: fn9 결과 재사용 + parts_inventory 대조 → can_proceed 종합 판정
#       · BOM rows=0 시 빈 결과 반환(예외 아님) — 데이터 적재 후 즉시 동작
#
# 향후 변경 예정
#       · can_proceed=False 시 fn6(calc_order_cost) 자동 호출해 부족분 발주 비용
#         견적까지 한 번에 반환하는 옵션 검토
#       · bom.aircraft_model 정규화(DA40NG/DA-40NG 표기 혼용) 확인 필요
# =============================================================================
