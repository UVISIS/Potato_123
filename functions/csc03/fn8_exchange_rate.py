"""
CSC-03 · CSU-03-02  |  fn8: 환율 관련 함수 모음

포함 함수:
    seed_historical_rates()    — 5년치 실제 EUR/KRW 초기 데이터 일괄 INSERT
    record_exchange_rate()     — 사용자 입력 환율 저장 (→ 이동평균 자동 반영)
    get_exchange_rate()        — 최신 환율 조회 + stale 판정
    get_rolling_average()      — 최근 N개 기준 이동평균 조회
    evaluate_purchase_timing() — Z-Score 기반 구매 시점 판단 (부품 원가 미포함)

핵심 설계 원칙:
    - 부품 원가는 미포함 — 동일 수량 기준 순수 환율 저렴도만 판단
    - 사용자가 새 환율 입력(record_exchange_rate) 즉시 이동평균에 반영
    - window=60 기본 (최근 60개 = 월 1회 입력 시 5년치)
    - 데이터가 60개 미만이면 있는 것 전부 사용, 최소 2건 필요

호출 테이블:
    currency_rates  (INSERT / SELECT)

수정 이력:
    2026-06-08 (6월2주차) 초기 작성
    2026-06-08 (6월2주차 수정) — 전면 개선
        · seed_historical_rates 추가 (5년치 실제 데이터 초기 적재)
        · get_rolling_average 분리 (이동평균 단독 조회 가능)
        · evaluate_purchase_timing 부품 원가 제거, 환율 저렴도만 판단
        · record_exchange_rate 호출 후 rolling average 자동 반영 확인값 반환

실제 데이터 출처:
    exchange-rates.org: 2021 연평균 1,353.70 / 2025 연평균 1,605.68 검증
    coincodex: 2021~2025 분기별 수익률 교차 검증
    역산: 2020년말 1,323.54 기준 → 분기 수익률 월별 선형 보간 (60개)
    연간 변동률 오차 0%, 연평균 오차 < 0.7%

⚠️  DB 변경 예정:
    currency_rates 자동 갱신 배치(P3) 연동 후 is_stale 로직 제거 가능
"""

import functions.db as _db
from datetime import datetime, timezone
from statistics import mean, stdev


# 상수
WINDOW_DEFAULT = 60          # 기본 이동평균 기준 개수 (월 1회 입력 시 ≒ 5년)
STALE_HOURS    = 24 * 7      # 7일 초과 시 stale 경고
Z_BUY          = -1.0        # Z ≤ -1.0 → 구매 적기
Z_WAIT         =  1.0        # Z ≥ +1.0 → 구매 보류

# 5년치 EUR/KRW 월별 데이터(최신순, 출처: exchange-rates.org + coincodex 역산)
_HISTORICAL_RATES = [
    ("2025-12-01", 1685.09), ("2025-11-01", 1669.40), ("2025-10-01", 1653.71),
    ("2025-09-01", 1636.98), ("2025-08-01", 1619.19), ("2025-07-01", 1601.41),
    ("2025-06-01", 1592.73), ("2025-05-01", 1593.16), ("2025-04-01", 1593.58),
    ("2025-03-01", 1582.96), ("2025-02-01", 1561.31), ("2025-01-01", 1539.65),
    ("2024-12-01", 1518.45), ("2024-11-01", 1497.73), ("2024-10-01", 1477.00),
    ("2024-09-01", 1469.38), ("2024-08-01", 1474.86), ("2024-07-01", 1480.35),
    ("2024-06-01", 1478.11), ("2024-05-01", 1468.13), ("2024-04-01", 1458.15),
    ("2024-03-01", 1449.11), ("2024-02-01", 1441.02), ("2024-01-01", 1432.92),
    ("2023-12-01", 1429.06), ("2023-11-01", 1429.44), ("2023-10-01", 1429.82),
    ("2023-09-01", 1431.00), ("2023-08-01", 1432.96), ("2023-07-01", 1434.92),
    ("2023-06-01", 1430.96), ("2023-05-01", 1421.07), ("2023-04-01", 1411.18),
    ("2023-03-01", 1397.13), ("2023-02-01", 1378.93), ("2023-01-01", 1360.73),
    ("2022-12-01", 1360.04), ("2022-11-01", 1376.86), ("2022-10-01", 1393.69),
    ("2022-09-01", 1392.68), ("2022-08-01", 1373.84), ("2022-07-01", 1355.00),
    ("2022-06-01", 1345.43), ("2022-05-01", 1345.11), ("2022-04-01", 1344.80),
    ("2022-03-01", 1346.18), ("2022-02-01", 1349.25), ("2022-01-01", 1352.32),
    ("2021-12-01", 1356.57), ("2021-11-01", 1362.00), ("2021-10-01", 1367.44),
    ("2021-09-01", 1365.90), ("2021-08-01", 1357.38), ("2021-07-01", 1348.87),
    ("2021-06-01", 1341.36), ("2021-05-01", 1334.87), ("2021-04-01", 1328.37),
    ("2021-03-01", 1324.86), ("2021-02-01", 1324.33), ("2021-01-01", 1323.80),
]


# 0. seed_historical_rates
def seed_historical_rates(
    currency_code: str = "EUR",
    base_currency: str = "KRW",
    skip_if_exists: bool = True,
) -> dict:
    """
    5년치 실제 EUR/KRW 월별 데이터를 currency_rates에 일괄 INSERT.
    시스템 최초 가동 시 1회만 실행.

    Args:
        currency_code  : 통화 코드 (기본 "EUR")
        base_currency  : 기준 통화 (기본 "KRW")
        skip_if_exists : True면 이미 데이터 있으면 스킵 (기본 True)

    Returns:
        {
            "inserted"  : int,   실제 INSERT된 건수
            "skipped"   : bool,  이미 존재해서 스킵 여부
            "total_rows": int,   INSERT 후 DB 총 건수
        }
    """
    supabase = _db.get_client()

    # 기존 데이터 확인
    if skip_if_exists:
        check = (
            supabase.table("currency_rates")
            .select("exchange_rate", count="exact")
            .eq("currency_code", currency_code)
            .eq("base_currency", base_currency)
            .execute()
        )
        existing_count = check.count or 0
        if existing_count >= 60:
            return {"inserted": 0, "skipped": True, "total_rows": existing_count}

    # 오래된 것부터 INSERT (update_date 오름차순)
    rows_to_insert = [
        {
            "currency_code": currency_code,
            "base_currency": base_currency,
            "exchange_rate": rate,
            "update_date":   f"{date}T00:00:00+00:00",
        }
        for date, rate in reversed(_HISTORICAL_RATES)  # 오래된 것부터
    ]

    result = (
        supabase.table("currency_rates")
        .insert(rows_to_insert)
        .execute()
    )

    inserted = len(result.data) if result.data else 0

    return {
        "inserted":   inserted,
        "skipped":    False,
        "total_rows": inserted,
    }


# 1. record_exchange_rate
def record_exchange_rate(
    exchange_rate: float,
    currency_code: str = "EUR",
    base_currency: str = "KRW",
    update_date:   str | None = None,
) -> dict:
    """
    사용자가 입력한 환율을 currency_rates에 INSERT.
    INSERT 즉시 이동평균(최근 60개)이 새 값을 포함해 자동 갱신됨.

    Args:
        exchange_rate : EUR/KRW 환율 (예: 1720.00)
        currency_code : 통화 코드 (기본 "EUR")
        base_currency : 기준 통화 (기본 "KRW")
        update_date   : 기준일 ISO 8601 문자열, None이면 현재 시각

    Returns:
        {
            "saved"          : dict,   저장된 row
            "rolling_avg_60" : float,  저장 후 갱신된 이동평균(최근 60개)
            "data_count"     : int,    현재 총 데이터 수 (최대 window 기준)
        }

    Raises:
        ValueError: exchange_rate <= 0
    """
    if exchange_rate <= 0:
        raise ValueError(f"환율은 양수여야 합니다. 입력값: {exchange_rate}")

    if update_date is None:
        update_date = datetime.now(timezone.utc).isoformat()

    supabase = _db.get_client()

    result = (
        supabase.table("currency_rates")
        .insert({
            "currency_code": currency_code,
            "base_currency": base_currency,
            "exchange_rate": exchange_rate,
            "update_date":   update_date,
        })
        .execute()
    )

    if not result.data:
        raise RuntimeError("currency_rates INSERT 실패")

    # INSERT 직후 이동평균 즉시 재계산
    avg_info = get_rolling_average(
        currency_code=currency_code,
        base_currency=base_currency,
        window=WINDOW_DEFAULT,
    )

    return {
        "saved":           result.data[0],
        "rolling_avg_60":  avg_info["rolling_avg"],
        "data_count":      avg_info["data_count"],
    }


# 2. get_exchange_rate
def get_exchange_rate(
    currency_code: str = "EUR",
    base_currency: str = "KRW",
    stale_hours:   int = STALE_HOURS,
) -> dict:
    """
    currency_rates에서 최신 1건 조회.

    Returns:
        {
            "currency_code", "base_currency",
            "exchange_rate" : float,
            "update_date"   : str,
            "is_stale"      : bool,
        }

    Raises:
        ValueError: 데이터 없음
    """
    supabase = _db.get_client()

    result = (
        supabase.table("currency_rates")
        .select("currency_code, base_currency, exchange_rate, update_date")
        .eq("currency_code", currency_code)
        .eq("base_currency", base_currency)
        .order("update_date", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )

    if result.data is None:
        raise ValueError(f"currency_rates에 {currency_code}/{base_currency} 데이터 없음")

    row = result.data
    update_dt = datetime.fromisoformat(str(row["update_date"]))
    if update_dt.tzinfo is None:
        update_dt = update_dt.replace(tzinfo=timezone.utc)

    elapsed = (datetime.now(timezone.utc) - update_dt).total_seconds() / 3600

    return {
        "currency_code": row["currency_code"],
        "base_currency": row["base_currency"],
        "exchange_rate": float(row["exchange_rate"]),
        "update_date":   str(row["update_date"]),
        "is_stale":      elapsed > stale_hours,
    }


# 3. get_rolling_average
def get_rolling_average(
    currency_code: str = "EUR",
    base_currency: str = "KRW",
    window:        int = WINDOW_DEFAULT,
) -> dict:
    """
    최근 window개 환율의 이동평균과 통계 반환.
    사용자가 새 환율 입력 시 자동으로 호출되어 최신 평균 갱신.

    Args:
        window : 이동평균 기준 개수 (기본 60 = 5년치)

    Returns:
        {
            "rolling_avg"  : float,  최근 window개 평균
            "std_dev"      : float,  표준편차
            "data_count"   : int,    실제 사용된 데이터 수
            "window"       : int,    요청한 window
            "oldest_date"  : str,    포함된 가장 오래된 날짜
            "latest_date"  : str,    가장 최신 날짜
        }

    Raises:
        ValueError: 데이터 2건 미만
    """
    supabase = _db.get_client()

    result = (
        supabase.table("currency_rates")
        .select("exchange_rate, update_date")
        .eq("currency_code", currency_code)
        .eq("base_currency", base_currency)
        .order("update_date", desc=True)
        .limit(window)
        .execute()
    )

    rows = result.data or []
    if len(rows) < 2:
        raise ValueError(
            f"이동평균 계산에 최소 2건 필요. 현재 {len(rows)}건. "
            "seed_historical_rates() 또는 record_exchange_rate()로 먼저 입력하세요."
        )

    rates = [float(r["exchange_rate"]) for r in rows]
    dates = [str(r["update_date"]) for r in rows]

    return {
        "rolling_avg":  round(mean(rates), 2),
        "std_dev":      round(stdev(rates), 2),
        "data_count":   len(rates),
        "window":       window,
        "oldest_date":  dates[-1],
        "latest_date":  dates[0],
    }


# 4. evaluate_purchase_timing
def evaluate_purchase_timing(
    currency_code: str = "EUR",
    base_currency: str = "KRW",
    window:        int = WINDOW_DEFAULT,
) -> dict:
    """
    최근 window개 환율 이력을 기반으로 Z-Score 분석 후 구매 시점 판단.
    부품 원가 미포함 — 동일 수량 기준 순수 환율 저렴도만 비교.

    Z-Score 계산:
        Z = (현재 환율 - 이동평균) / 표준편차

        Z ≤ -1.0 → 평균보다 1σ 이상 낮음 → 구매 적기  (BUY)
        Z ≥ +1.0 → 평균보다 1σ 이상 높음 → 구매 보류  (WAIT)
        -1 < Z < 1 → 중립                              (NEUTRAL)

    사용자가 record_exchange_rate()로 새 환율 입력 시
    이동평균이 즉시 갱신되므로 다음 호출부터 반영됨.

    Args:
        currency_code : 통화 코드 (기본 "EUR")
        base_currency : 기준 통화 (기본 "KRW")
        window        : 이동평균 기준 개수 (기본 60)

    Returns:
        {
            "current_rate"   : float,  현재(최신) 환율
            "rolling_avg"    : float,  이동평균
            "std_dev"        : float,  표준편차
            "z_score"        : float,  Z-Score
            "pct_vs_avg"     : float,  평균 대비 % (음수=저점)
            "recommendation" : str,    "BUY" | "WAIT" | "NEUTRAL"
            "reason"         : str,    한국어 판단 근거
            "data_count"     : int,    사용된 데이터 수
            "oldest_date"    : str,    이동평균 기산 시작일
            "latest_date"    : str,    최신 데이터 날짜
        }

    Raises:
        ValueError: 데이터 2건 미만
    """
    avg_info = get_rolling_average(
        currency_code=currency_code,
        base_currency=base_currency,
        window=window,
    )

    current_info = get_exchange_rate(
        currency_code=currency_code,
        base_currency=base_currency,
    )

    current_rate = current_info["exchange_rate"]
    ma  = avg_info["rolling_avg"]
    sd  = avg_info["std_dev"]
    z   = round((current_rate - ma) / sd, 2)
    pct = round((current_rate - ma) / ma * 100, 2)
    n   = avg_info["data_count"]

    if z <= Z_BUY:
        rec = "BUY"
        reason = (
            f"현재 환율 {current_rate:,.1f}원이 "
            f"{n}개월 이동평균 {ma:,.1f}원 대비 {abs(pct):.1f}% 낮음 "
            f"(Z-Score {z:.2f}) → 저점 구간, 구매 적기"
        )
    elif z >= Z_WAIT:
        rec = "WAIT"
        reason = (
            f"현재 환율 {current_rate:,.1f}원이 "
            f"{n}개월 이동평균 {ma:,.1f}원 대비 {pct:.1f}% 높음 "
            f"(Z-Score {z:.2f}) → 고점 구간, 구매 보류 권고"
        )
    else:
        rec = "NEUTRAL"
        reason = (
            f"현재 환율 {current_rate:,.1f}원이 "
            f"{n}개월 이동평균 {ma:,.1f}원 대비 {pct:+.1f}% "
            f"(Z-Score {z:.2f}) → 중립 구간"
        )

    return {
        "current_rate":   current_rate,
        "rolling_avg":    ma,
        "std_dev":        sd,
        "z_score":        z,
        "pct_vs_avg":     pct,
        "recommendation": rec,
        "reason":         reason,
        "data_count":     n,
        "oldest_date":    avg_info["oldest_date"],
        "latest_date":    avg_info["latest_date"],
    }
