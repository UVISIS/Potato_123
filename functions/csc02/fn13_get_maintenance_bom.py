"""
CSC-02 · CSU-02-04  |  fn13: get_maintenance_bom()

정비 BOM 명세서 조회 — 정비 유형별 소요 부품 정의 + 라인별/총 예상 비용(EUR) 집계.

fn9(get_required_parts)와의 구분:
    · fn9  : 가용성 점검용 "소요 수량" 중심 평면 리스트 (CSC-04 카운터/스케줄러 입력)
    · fn13 : 자재관리용 "비용 명세" 중심 — 라인별 단가×수량, 총 예상비용 롤업 (CSC-02 조달계획)
    ※ 두 함수가 동일 bom 을 읽으므로 역할 경계는 팀 확인 권장(아래 보고서 참조).

호출 테이블:
    bom        (SELECT) — maintenance_type(+aircraft_model) 별 소요 부품/수량/단위
    components (SELECT) — nomenclature, part_number, category, unit_price_eur 병합

수정 이력:
    2026-06-10 (6월2주차) — 신규 작성
        · P2 해제(bom 테이블 신설) 반영
        · 라인별 line_cost_eur = required_qty × unit_price_eur, 총합 롤업
        · 단가 누락(unit_price_eur=None) 라인은 비용 0 처리 + missing_price 플래그

⚠️  주의:
    · 총 예상비용은 EUR 기준. KRW 환산은 fn6(calc_order_cost)/fn8 환율 적용 영역.
    · 단가 없는 부품이 1개 이상이면 total_estimated_eur 는 과소추정 → has_missing_price=True 로 표기.
"""

from __future__ import annotations
from functions.db import get_client


def get_maintenance_bom(
    maintenance_type: str,
    aircraft_model: str | None = None,
) -> dict:
    """
    정비 유형별 BOM 명세와 예상 비용을 집계해 반환한다.

    Parameters
    ----------
    maintenance_type : str
        정비 유형 (예: "100hr", "Annual"). bom.maintenance_type 와 매칭.
    aircraft_model : str | None
        기종 ("DA40NG"|"DA42NG"). None 이면 해당 정비유형 전체.

    Returns
    -------
    dict
        {
            "maintenance_type"    : str,
            "aircraft_model"      : str | None,
            "line_count"          : int,
            "total_required_qty"  : int,
            "total_estimated_eur" : float,   # 단가 있는 라인 합계 (소수점 2자리)
            "has_missing_price"   : bool,     # 단가 누락 라인 존재 여부
            "items"               : [
                {
                    "part_id"       : int,
                    "nomenclature"  : str | None,
                    "part_number"   : str | None,
                    "category"      : str | None,
                    "required_qty"  : int,
                    "unit"          : str | None,
                    "unit_price_eur": float | None,
                    "line_cost_eur" : float,   # 단가 없으면 0.0
                    "missing_price" : bool,
                }, ...
            ],
        }
        해당 BOM 이 없으면 items=[], line_count=0, total_estimated_eur=0.0.

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
        "part_id, required_qty, unit, maintenance_type, aircraft_model, notes"
    ).eq("maintenance_type", maintenance_type)
    if aircraft_model is not None:
        bom_q = bom_q.eq("aircraft_model", aircraft_model)
    bom = bom_q.execute()
    bom_rows = bom.data or []

    if not bom_rows:
        return {
            "maintenance_type":    maintenance_type,
            "aircraft_model":      aircraft_model,
            "line_count":          0,
            "total_required_qty":  0,
            "total_estimated_eur": 0.0,
            "has_missing_price":   False,
            "items":               [],
        }

    # ── components 병합
    part_ids = [r["part_id"] for r in bom_rows if r.get("part_id") is not None]
    comp_map: dict[int, dict] = {}
    if part_ids:
        comps = (
            client.table("components")
            .select("id, nomenclature, part_number, category, unit_price_eur")
            .in_("id", part_ids)
            .execute()
        )
        comp_map = {c["id"]: c for c in (comps.data or [])}

    items: list[dict] = []
    total_required_qty  = 0
    total_estimated_eur = 0.0
    has_missing_price   = False

    for r in bom_rows:
        pid          = r.get("part_id")
        comp         = comp_map.get(pid, {})
        required_qty = int(r.get("required_qty") or 0)
        price_raw    = comp.get("unit_price_eur")

        if price_raw is None:
            unit_price    = None
            line_cost     = 0.0
            missing_price = True
            has_missing_price = True
        else:
            unit_price    = float(price_raw)
            line_cost     = round(unit_price * required_qty, 2)
            missing_price = False

        total_required_qty  += required_qty
        total_estimated_eur += line_cost

        items.append({
            "part_id":        pid,
            "nomenclature":   comp.get("nomenclature"),
            "part_number":    comp.get("part_number"),
            "category":       comp.get("category"),
            "required_qty":   required_qty,
            "unit":           r.get("unit"),
            "unit_price_eur": unit_price,
            "line_cost_eur":  line_cost,
            "missing_price":  missing_price,
        })

    return {
        "maintenance_type":    maintenance_type,
        "aircraft_model":      aircraft_model,
        "line_count":          len(items),
        "total_required_qty":  total_required_qty,
        "total_estimated_eur": round(total_estimated_eur, 2),
        "has_missing_price":   has_missing_price,
        "items":               items,
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-10  6월2주차 — 신규 작성
#       · P2 해제(bom 신설) 반영, components 단가 병합
#       · 라인별 line_cost_eur + 총 예상비용(total_estimated_eur) 롤업
#       · 단가 누락 라인 missing_price 플래그 + has_missing_price 종합 표기
#       · fn9 와의 역할 구분(수량 중심 vs 비용 중심) docstring 명시
#
# 향후 변경 예정
#       · total_estimated_krw 필드 추가(fn6/fn8 환율 연계) 검토
#       · bom.notes(대체 부품/주기 메모) 노출 여부 팀 확인
# =============================================================================
