"""
CSC-03  |  fn17: calc_landed_cost()

수입 총원가(Landed Cost) 산출 — 관세·부가세·항공운임·환율 반영 +
직구 전환에 따른 비용 절감 효과 비교.

법적/계산 기준 (2026-06-13 조사):
    · 관세 = CIF(FOB + 운임 + 보험) × 관세율           (관세법 제15·30조)
    · 부가세 = (CIF + 관세) × 10%                       (부가가치세법 제29조②, 표준 10%)
    · 학술연구용품 감면: 학교 등에서 학술연구·교육·실험실습용으로 수입하는 물품은
      "해당 물품에 실제로 적용되는 관세율의 100분의 80"을 감면 → 관세의 20%만 납부
      (관세법 제90조 / 시행규칙 제37조). 청주대 부설 비행교육원이 학교에 해당하므로
      academic 감면 대상으로 본다.
      ⚠️ 실제 적용은 수입신고 시 용도 증빙·사후관리 요건 충족 전제. 본 계산은 '예상치'.
    · 민간항공기 부품은 「민간항공기 무역에 관한 협정」(관세법 제89·90조)으로
      기본 관세율 0%인 품목이 많음 → customs_duty_rate 는 HS코드별 파라미터로 둠(기본 0).
    · 직구 절감: 기존 대행(JCA오토노머스 등) 방식은 대행 수수료 + (학교 감면 미적용)로
      추정. 직구 전환 시 ① 대행 수수료 제거 ② 학교 명의 학술감면 적용으로 절감 발생.
      대행 수수료율(agent_markup_rate)은 실제 계약 데이터로 교체 필요 — 기본값은 placeholder.

⚠️ 환율/운임/수수료 기본값은 '계산이 작동하도록' 넣은 대략치(placeholder)이며,
   확정 데이터로 교체 전까지 절대 수치를 신뢰하지 말 것.
"""

from __future__ import annotations

# ── 기본 파라미터 (placeholder — 확정 데이터로 교체 필요) ─────────────
DEFAULT_EXCHANGE_RATE   = 1685.0   # EUR→KRW 고정 대략치 (fn8 최신값으로 대체 권장)
DEFAULT_VAT_RATE        = 0.10     # 수입 부가세 10%
ACADEMIC_REDUCTION_RATE = 0.80     # 관세법 제90조 학술연구용품 감면율 (관세의 80% 감면)
DEFAULT_INSURANCE_RATE  = 0.005    # CIF 산정용 보험료 ≒ FOB의 0.5% (대략치)
DEFAULT_AGENT_MARKUP    = 0.12     # 기존 대행 수수료율 추정치 (확정 데이터 필요) — placeholder


def calc_landed_cost(
    unit_price_eur: float,
    order_qty: int,
    exchange_rate: float = DEFAULT_EXCHANGE_RATE,
    customs_duty_rate: float = 0.0,
    is_academic: bool = True,
    academic_reduction_rate: float = ACADEMIC_REDUCTION_RATE,
    vat_rate: float = DEFAULT_VAT_RATE,
    # 항공운임: 아래 중 하나로 전달 (우선순위: 총액 > kg당 > 팔레트당)
    freight_total_eur: float | None = None,
    freight_per_kg_eur: float | None = None,
    weight_kg: float | None = None,
    freight_per_pallet_eur: float | None = None,
    pallets: int | None = None,
    insurance_rate: float = DEFAULT_INSURANCE_RATE,
    agent_markup_rate: float = DEFAULT_AGENT_MARKUP,
) -> dict:
    """
    수입 총원가(KRW)를 관세·부가세·운임 포함으로 산출하고,
    직구 vs 기존 대행 방식의 예상 비용 차이를 함께 반환한다.

    Parameters
    ----------
    unit_price_eur : float
        부품 단가(EUR, FOB 기준). 0 이상.
    order_qty : int
        발주 수량(1 이상).
    exchange_rate : float
        EUR→KRW 환율. 기본 고정 대략치(DEFAULT_EXCHANGE_RATE).
        fn8.get_exchange_rate()['exchange_rate'] 를 넘겨 최신값 사용 권장.
    customs_duty_rate : float
        기본 관세율(HS코드별). 민간항공기 부품은 0%인 경우가 많음(기본 0.0).
    is_academic : bool
        학술연구용품 감면 적용 여부(기본 True — 학교 부설 교육원).
    academic_reduction_rate : float
        감면율(기본 0.80 = 관세의 80% 감면). is_academic=True 일 때만 적용.
    vat_rate : float
        수입 부가세율(기본 0.10).
    freight_total_eur / freight_per_kg_eur+weight_kg / freight_per_pallet_eur+pallets
        항공운임. 셋 중 하나로 전달. 모두 없으면 운임 0 처리.
        (kg당 책정이 모호하면 팔레트당으로 조사해 freight_per_pallet_eur 사용)
    insurance_rate : float
        보험료율(FOB 대비, CIF 산정용). 기본 0.5%.
    agent_markup_rate : float
        기존 대행 방식 수수료율(직구 절감 비교용). 기본 placeholder 0.12.

    Returns
    -------
    dict
        {
            "order_qty", "unit_price_eur", "exchange_rate",
            "fob_eur", "freight_eur", "insurance_eur", "cif_eur",
            "cif_krw",
            "customs_duty_rate", "is_academic", "academic_reduction_rate",
            "duty_krw",            # 학술감면 적용 후 관세
            "duty_krw_no_reduction",  # 감면 미적용 시 관세(비교용)
            "vat_rate", "vat_krw",
            "total_landed_krw",    # 직구 총원가 (CIF + 관세 + 부가세)
            # 직구 절감 비교
            "agent_markup_rate",
            "agent_total_krw",     # 기존 대행 방식 예상 총액
            "direct_total_krw",    # 직구 방식 예상 총액(=total_landed_krw)
            "savings_krw",         # 절감액 (agent - direct)
            "savings_pct",         # 절감률 %
            "freight_basis",       # "total" | "per_kg" | "per_pallet" | "none"
            "assumptions_note",
        }

    Raises
    ------
    ValueError
        · order_qty < 1 / unit_price_eur < 0 / exchange_rate <= 0
        · 각종 율(rate) 음수
    """
    if order_qty < 1:
        raise ValueError(f"order_qty 는 1 이상이어야 합니다. 입력값: {order_qty}")
    if unit_price_eur < 0:
        raise ValueError(f"unit_price_eur 는 0 이상이어야 합니다. 입력값: {unit_price_eur}")
    if exchange_rate <= 0:
        raise ValueError(f"exchange_rate 는 0 보다 커야 합니다. 입력값: {exchange_rate}")
    for name, val in (
        ("customs_duty_rate", customs_duty_rate),
        ("academic_reduction_rate", academic_reduction_rate),
        ("vat_rate", vat_rate),
        ("insurance_rate", insurance_rate),
        ("agent_markup_rate", agent_markup_rate),
    ):
        if val < 0:
            raise ValueError(f"{name} 는 0 이상이어야 합니다. 입력값: {val}")

    # ── FOB / 운임 / 보험 → CIF (EUR)
    fob_eur = round(unit_price_eur * order_qty, 2)

    if freight_total_eur is not None:
        freight_eur = float(freight_total_eur)
        freight_basis = "total"
    elif freight_per_kg_eur is not None and weight_kg is not None:
        freight_eur = round(freight_per_kg_eur * weight_kg, 2)
        freight_basis = "per_kg"
    elif freight_per_pallet_eur is not None and pallets is not None:
        freight_eur = round(freight_per_pallet_eur * pallets, 2)
        freight_basis = "per_pallet"
    else:
        freight_eur = 0.0
        freight_basis = "none"

    insurance_eur = round(fob_eur * insurance_rate, 2)
    cif_eur = round(fob_eur + freight_eur + insurance_eur, 2)
    cif_krw = round(cif_eur * exchange_rate, 0)

    # ── 관세 (학술감면 적용/미적용)
    duty_full = cif_krw * customs_duty_rate
    if is_academic:
        duty_krw = round(duty_full * (1 - academic_reduction_rate), 0)
    else:
        duty_krw = round(duty_full, 0)
    duty_krw_no_reduction = round(duty_full, 0)

    # ── 부가세 = (CIF + 관세) × vat_rate
    vat_krw = round((cif_krw + duty_krw) * vat_rate, 0)

    # ── 직구 총원가
    direct_total_krw = round(cif_krw + duty_krw + vat_krw, 0)

    # ── 기존 대행(JCA) 방식 예상 총액
    #    가정: 대행은 학교 학술감면 미적용(대행사 명의 수입) + 대행 수수료(markup)
    agent_duty = duty_krw_no_reduction
    agent_vat  = round((cif_krw + agent_duty) * vat_rate, 0)
    agent_base = cif_krw + agent_duty + agent_vat
    agent_total_krw = round(agent_base * (1 + agent_markup_rate), 0)

    savings_krw = round(agent_total_krw - direct_total_krw, 0)
    savings_pct = round(savings_krw / agent_total_krw * 100, 2) if agent_total_krw else 0.0

    return {
        "order_qty":               order_qty,
        "unit_price_eur":          unit_price_eur,
        "exchange_rate":           exchange_rate,
        "fob_eur":                 fob_eur,
        "freight_eur":             freight_eur,
        "insurance_eur":           insurance_eur,
        "cif_eur":                 cif_eur,
        "cif_krw":                 cif_krw,
        "customs_duty_rate":       customs_duty_rate,
        "is_academic":             is_academic,
        "academic_reduction_rate": academic_reduction_rate if is_academic else 0.0,
        "duty_krw":                duty_krw,
        "duty_krw_no_reduction":   duty_krw_no_reduction,
        "vat_rate":                vat_rate,
        "vat_krw":                 vat_krw,
        "total_landed_krw":        direct_total_krw,
        "agent_markup_rate":       agent_markup_rate,
        "agent_total_krw":         agent_total_krw,
        "direct_total_krw":        direct_total_krw,
        "savings_krw":             savings_krw,
        "savings_pct":             savings_pct,
        "freight_basis":           freight_basis,
        "assumptions_note":        (
            "환율·운임·대행수수료·감면율은 조사 기반 대략치(placeholder). "
            "확정 데이터(실 환율·실 운임·JCA 수수료·HS코드별 관세율)로 교체 필요. "
            "학술감면은 관세법 제90조(관세의 80% 감면) 기준, 용도 증빙 전제의 예상치."
        ),
    }


# =============================================================================
# 변경 이력 (Change Log)
# =============================================================================
# v1.0  2026-06-13  신규 작성 (피드백 반영)
#       · 관세·부가세·항공운임·보험 포함 수입 총원가(landed cost) 산출
#       · 학술연구용품 감면(관세법 제90조, 관세의 80% 감면) 적용 옵션
#       · 운임: 총액 / kg당 / 팔레트당 3방식 지원
#       · 직구 vs 기존 대행 방식 비용 비교(절감액·절감률)
#       · 환율 기본 고정 대략치 — fn8 최신값 주입 가능
# 향후 변경 예정
#       · HS코드별 실 관세율 테이블 연동 (현재 customs_duty_rate 파라미터)
#       · JCA 대행 수수료 실데이터 반영 (agent_markup_rate placeholder 교체)
# =============================================================================
