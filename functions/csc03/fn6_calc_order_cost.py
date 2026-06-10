"""
CSC-03 · CSU-03-03  |  fn6: calc_order_cost()

발주 비용 산출 — 부품 단가(EUR) × 수량 → EUR 합계 → 적용환율 → KRW 합계
선택적으로 purchase_orders 발주서 행을 생성한다.

호출 테이블:
    components      (SELECT) — unit_price_eur, nomenclature (단가 미지정 시 자동 조회)
    currency_rates  (SELECT) — 최신 EUR/KRW 환율 (환율 미지정 시 자동 조회)
    purchase_orders (INSERT) — create_order=True 일 때 발주서 생성

수정 이력:
    2026-06-10 (6월2주차) — 신규 작성
        · P1 해제(purchase_orders 신설, components.unit_price_eur, exchange_rate 컬럼) 반영
        · 단가/환율 미지정 시 DB 자동 조회 (파라미터 우선)
        · 순수 "발주 원가"만 계산 — 운임/관세/VAT 는 fn8 영역(여기서 제외)

⚠️  주의:
    · 환율 자동 조회는 currency_rates 에서 (currency_code='EUR', base_currency='KRW')
      update_date 최신 1건을 사용. 데이터가 없으면 exchange_rate 파라미터 필수.
    · total_krw 는 소수점 0자리 반올림(원 단위). total_eur 는 소수점 2자리.
"""

from __future__ import annotations
from functions.db import get_client


def calc_order_cost(
    part_id: int,
    order_qty: int,
    unit_price_eur: float | None = None,
    exchange_rate: float | None = None,
    supplier_id: int | None = None,
    order_year: int | None = None,
    order_month: int | None = None,
    notes: str | None = None,
    create_order: bool = False,
) -> dict:
    """
    부품 발주 비용을 EUR/KRW 로 산출한다. create_order=True 면 발주서도 생성한다.

    Parameters
    ----------
    part_id : int
        components.id (PK)
    order_qty : int
        발주 수량(1 이상)
    unit_price_eur : float | None
        단가(EUR). None 이면 components.unit_price_eur 자동 조회.
    exchange_rate : float | None
        적용 환율(EUR→KRW). None 이면 currency_rates 최신값 자동 조회.
    supplier_id, order_year, order_month, notes
        발주서 생성 시 기록할 부가 정보(선택).
        order_year/month 미지정 시 현재 연/월 사용.
    create_order : bool
        True 면 purchase_orders 에 status='발주예정' 행을 INSERT.

    Returns
    -------
    dict
        {
            "part_id"            : int,
            "nomenclature"       : str,
            "order_qty"          : int,
            "unit_price_eur"     : float,
            "unit_price_source"  : str,   # "parameter" | "components"
            "exchange_rate"      : float,
            "exchange_rate_source": str,  # "parameter" | "currency_rates"
            "total_eur"          : float, # 소수점 2자리
            "total_krw"          : float, # 원 단위 반올림
            "purchase_order_id"  : int | None,  # create_order=True 일 때만
            "status"             : str | None,
        }

    Raises
    ------
    ValueError
        · order_qty < 1
        · part_id 미존재
        · 단가를 파라미터/DB 어디서도 얻지 못함
        · 환율을 파라미터/DB 어디서도 얻지 못함
    RuntimeError
        · purchase_orders INSERT 실패
    """

    # ── 입력 검증
    if order_qty < 1:
        raise ValueError(f"order_qty 는 1 이상이어야 합니다. 입력값: {order_qty}")

    client = get_client()

    # ── 부품 존재 확인 + 단가 자동 조회
    comp = (
        client.table("components")
        .select("id, nomenclature, unit_price_eur")
        .eq("id", part_id)
        .maybe_single()
        .execute()
    )
    if not comp.data:
        raise ValueError(f"part_id {part_id} 에 해당하는 부품이 없습니다.")
    nomenclature = comp.data.get("nomenclature")

    # ── 단가 결정 (파라미터 우선)
    if unit_price_eur is not None:
        unit_price_source = "parameter"
    else:
        db_price = comp.data.get("unit_price_eur")
        if db_price is None:
            raise ValueError(
                f"part_id {part_id} 의 단가가 없습니다. "
                f"unit_price_eur 파라미터를 직접 전달하거나 components.unit_price_eur 를 입력하세요."
            )
        unit_price_eur    = float(db_price)
        unit_price_source = "components"

    if unit_price_eur < 0:
        raise ValueError(f"unit_price_eur 는 0 이상이어야 합니다. 입력값: {unit_price_eur}")

    # ── 환율 결정 (파라미터 우선)
    if exchange_rate is not None:
        exchange_rate_source = "parameter"
    else:
        rate = (
            client.table("currency_rates")
            .select("exchange_rate, update_date")
            .eq("currency_code", "EUR")
            .eq("base_currency", "KRW")
            .order("update_date", desc=True)
            .limit(1)
            .execute()
        )
        rate_rows = rate.data or []
        if not rate_rows or rate_rows[0].get("exchange_rate") is None:
            raise ValueError(
                "currency_rates 에 EUR/KRW 환율 데이터가 없습니다. "
                "exchange_rate 파라미터를 직접 전달하거나 fn8(record_exchange_rate)로 환율을 적재하세요."
            )
        exchange_rate        = float(rate_rows[0]["exchange_rate"])
        exchange_rate_source = "currency_rates"

    if exchange_rate <= 0:
        raise ValueError(f"exchange_rate 는 0 보다 커야 합니다. 입력값: {exchange_rate}")

    # ── 비용 계산
    total_eur = round(unit_price_eur * order_qty, 2)
    total_krw = round(total_eur * exchange_rate, 0)

    purchase_order_id = None
    status            = None

    # ── 발주서 생성 (선택)
    if create_order:
        from datetime import date
        today = date.today()
        po_payload = {
            "part_id":        part_id,
            "supplier_id":    supplier_id,
            "order_qty":      order_qty,
            "unit_price_eur": unit_price_eur,
            "total_eur":      total_eur,
            "exchange_rate":  exchange_rate,
            "total_krw":      total_krw,
            "order_year":     order_year  if order_year  is not None else today.year,
            "order_month":    order_month if order_month is not None else today.month,
            "notes":          notes,
            "status":         "발주예정",
        }
        po_payload = {k: v for k, v in po_payload.items() if v is not None}
        try:
            po_res = client.table("purchase_orders").insert(po_payload).execute()
            purchase_order_id = _extract_id(po_res.data)
            status = "발주예정"
        except Exception as e:
            raise RuntimeError(f"purchase_orders 생성 실패: {e}")

    return {
        "part_id":              part_id,
        "nomenclature":         nomenclature,
        "order_qty":            order_qty,
        "unit_price_eur":       unit_price_eur,
        "unit_price_source":    unit_price_source,
        "exchange_rate":        exchange_rate,
        "exchange_rate_source": exchange_rate_source,
        "total_eur":            total_eur,
        "total_krw":            total_krw,
        "purchase_order_id":    purchase_order_id,
        "status":               status,
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
#       · P1 해제(purchase_orders 신설, unit_price_eur/exchange_rate 컬럼) 반영
#       · 단가/환율 파라미터 우선 → 미지정 시 components / currency_rates 자동 조회
#       · total_eur(2자리) / total_krw(원 단위) 분리 반올림
#       · create_order 플래그로 비용계산 전용 / 발주서 생성 모드 분기
#       · 운임·관세·VAT 는 fn8 영역으로 분리(본 함수는 순수 발주원가만)
#
# 향후 변경 예정
#       · fn8(evaluate_purchase_timing)와 연계해 "지금 발주 vs 대기" 판단을
#         발주서 status('발주대기')에 반영하는 옵션 추가 검토
#       · 다건 일괄 발주(BOM 단위) 지원 — fn13 결과를 입력으로 받는 래퍼 함수
# =============================================================================
