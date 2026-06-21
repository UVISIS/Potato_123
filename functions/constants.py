"""
functions/constants.py — 시스템 공용 상수 모음

흩어진 임계치·비행시간 가정을 한 곳에서 관리한다.
각 함수 파일에서 직접 정의하던 중복 상수를 이 파일에서 import 하여 사용.

■ 비행시간 가정 근거 (2026-06-13 피드백)
  · 청주: 주 4일 운항 × 연 52주 = 208 운항일 × (800h / 365d) ≈ 주 6.15h/운항일
  · 무안: 주 7일 운항 × 연 52주 = 365 운항일 = 매일 운항
  · 연간 총비행시간 800h — 청주/무안 통합 단일 기준
  · 일평균 환산: 800h ÷ 365일 ≈ 2.19h/달력일 (fn12 기본값 사용)
  · 청주 운항일 기준 환산: 800h ÷ 208일 ≈ 3.85h/운항일 (참고용)

■ 임계치 근거
  · CRITICAL_HOURS(10h) / WARNING_HOURS(30h): 팀 자체 설정
  · WARNING_RATIO(1.5): UI 스펙("경고: 안전재고 × 1.5")과 동일
"""

from __future__ import annotations

# ── 비행시간 가정 ────────────────────────────────────────────────
ANNUAL_FLIGHT_HOURS     = 800.0   # 연간 총비행시간 (청주/무안 통합 기준)
DAILY_AVG_FLIGHT_HOURS  = round(ANNUAL_FLIGHT_HOURS / 365, 3)  # ≈ 2.192 h/달력일

# 기지별 운항일 기준 환산 (참고용 — 청주 주4일/무안 주7일)
CHEONGJU_OP_DAYS_PER_YEAR = 208   # 주 4일 × 52주
MUAN_OP_DAYS_PER_YEAR     = 365   # 주 7일 (매일)
CHEONGJU_DAILY_OP_HOURS   = round(ANNUAL_FLIGHT_HOURS / CHEONGJU_OP_DAYS_PER_YEAR, 3)  # ≈ 3.846
MUAN_DAILY_OP_HOURS       = round(ANNUAL_FLIGHT_HOURS / MUAN_OP_DAYS_PER_YEAR,     3)  # ≈ 2.192

# fn12 비행이력 없을 때 fallback (달력 기준)
DEFAULT_DAILY_FLIGHT_HOURS = DAILY_AVG_FLIGHT_HOURS   # ≈ 2.192 (구: 3.0h — 통일)

# ── 정비 임계치 ──────────────────────────────────────────────────
MAINTENANCE_CRITICAL_HOURS = 10.0   # 잔여 ≤ 10h → 임박
MAINTENANCE_WARNING_HOURS  = 30.0   # 잔여 ≤ 30h → 주의
MAINTENANCE_CRITICAL_PCT   = 0.10   # 잔여 비율 ≤ 10% → 임박

# fn14 알람 임계
ALARM_CRITICAL_HOURS = 0    # ≤ 0h  → 초과
ALARM_WARNING_HOURS  = 10   # ≤ 10h → 임박
ALARM_WARNING_DAYS   = 7    # 날짜기반 ≤ 7일
ALARM_INFO_DAYS      = 30   # 날짜기반 ≤ 30일

# ── 재고 임계치 ──────────────────────────────────────────────────
STOCK_WARNING_RATIO  = 1.5  # 재고 ≤ safety_stock × 1.5 → 경고 (UI 스펙 일치)

# ── 기종 정규화 (aircraft.model → 표준 모델 코드) ──────────────────
# bom.aircraft_model / component_aircraft.aircraft_model 과 동일한 표기로 통일.
# routers/maintenance.py, routers/components.py 의 _BOM_MODEL_MAP 과 동일 매핑.
AIRCRAFT_MODEL_MAP = {
    "Diamond DA40 NG": "DA40NG",
    "Diamond DA42 NG": "DA42NG",
    "DA-40NG": "DA40NG",
    "DA-42NG": "DA42NG",
}


def normalize_aircraft_model(model: str | None) -> str | None:
    """aircraft.model 표기를 component_aircraft/bom 기준 표준 코드로 변환."""
    if model is None:
        return None
    return AIRCRAFT_MODEL_MAP.get(model, model)


# ── 정비유형 정규화 (maintenance_schedule.maintenance_type → bom 표준 코드) ──
# maintenance_schedule 은 설명형 한글 라벨("항공기 100 HRS")을 쓰고,
# bom 은 압축 코드("100H")를 써서 서로 다른 체계를 사용한다.
# Governor/Propeller 등 이미 동일 표기인 항목은 매핑 불필요.
MAINTENANCE_TYPE_BOM_MAP = {
    "항공기 100 HRS": "100H",
    "항공기 200 HRS": "200H",
    "ENG' 100 HRS":  "Engine_100H",
    "ENG' 300 HRS":  "Engine_300H",
}


def normalize_maintenance_type(maintenance_type: str | None) -> str | None:
    """maintenance_schedule.maintenance_type 표기를 bom 기준 코드로 변환. 매핑 없으면 원본 유지."""
    if maintenance_type is None:
        return None
    return MAINTENANCE_TYPE_BOM_MAP.get(maintenance_type, maintenance_type)
