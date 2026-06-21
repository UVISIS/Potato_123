"""
fn_rate_forecast.py — EUR/KRW 계절적 저점 예측

currency_rates 월별 데이터(2021-07~현재)의 계절성을 분석하여
앞으로 12개월 내 상반기/하반기 환율 저점 예상일과 예상 환율을 반환한다.

계절 지수 (2022~2025 4개년 평균, 연간평균 대비 편차):
  Jan=-42.9  Feb=-31.9  Mar=-20.7  Apr=-12.4  May=-7.7  Jun=-2.7
  Jul=+3.3   Aug=+10.3  Sep=+18.1  Oct=+24.1  Nov=+28.8  Dec=+33.6
"""

from __future__ import annotations
from datetime import date, timedelta
from functions.db import get_client

# 2022~2025년 4개년 실측 기반 계절 지수 (연간평균 대비 평균 편차, 원)
SEASONAL_INDEX = {
    1: -42.9, 2: -31.9, 3: -20.7, 4: -12.4, 5: -7.7,  6: -2.7,
    7:  +3.3, 8: +10.3, 9: +18.1, 10: +24.1, 11: +28.8, 12: +33.6,
}


def _load_eur_rates() -> list[tuple[date, float]]:
    """currency_rates에서 EUR/KRW 월별 데이터를 시간순으로 반환."""
    rows = (
        get_client()
        .table("currency_rates")
        .select("exchange_rate, update_date")
        .eq("currency_code", "EUR")
        .order("update_date", desc=False)
        .execute()
    ).data or []
    result = []
    for r in rows:
        try:
            d = date.fromisoformat(str(r["update_date"])[:10])
            v = float(r["exchange_rate"])
            result.append((d, v))
        except Exception:
            pass
    return result


def _linear_slope(rates: list[tuple[date, float]], n: int = 6) -> float:
    """최근 n개월 데이터로 월별 추세(기울기, 원/월)를 계산."""
    pts = rates[-n:]
    if len(pts) < 2:
        return 0.0
    xs = list(range(len(pts)))
    ys = [v for _, v in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def predict_low_rate_dates(today: date | None = None) -> dict:
    """
    앞으로 12개월 내 상반기·하반기 EUR/KRW 저점 예상일을 반환한다.

    Returns
    -------
    dict
        {
          "current_rate"  : float,
          "trend_per_month": float,        # 최근 6개월 추세 (원/월)
          "h1_low_month"  : int,           # 상반기 저점 예상 월 (1~6)
          "h1_low_date"   : str,           # YYYY-MM-01
          "h1_low_rate"   : float,
          "h2_low_month"  : int,           # 하반기 저점 예상 월 (7~12)
          "h2_low_date"   : str,           # YYYY-MM-01
          "h2_low_rate"   : float,
          "note"          : str,
        }
    """
    today = today or date.today()
    rates = _load_eur_rates()
    if not rates:
        return {}

    current_rate = rates[-1][1]
    slope = _linear_slope(rates, n=6)

    # 앞으로 12개월 투영
    last_date = rates[-1][0]
    months_ahead = []
    for i in range(1, 13):
        m = (last_date.month - 1 + i) % 12 + 1
        y = last_date.year + (last_date.month - 1 + i) // 12
        proj = current_rate + slope * i + SEASONAL_INDEX[m] - SEASONAL_INDEX[last_date.month]
        months_ahead.append((date(y, m, 1), m, round(proj, 1)))

    # 상반기 저점 (월 1~6)
    h1 = [(d, m, r) for d, m, r in months_ahead if 1 <= m <= 6]
    # 하반기 저점 (월 7~12)
    h2 = [(d, m, r) for d, m, r in months_ahead if 7 <= m <= 12]

    h1_best = min(h1, key=lambda x: x[2]) if h1 else None
    h2_best = min(h2, key=lambda x: x[2]) if h2 else None

    trend_desc = "상승" if slope > 2 else "하락" if slope < -2 else "보합"
    note = (
        f"최근 6개월 추세 {slope:+.1f}원/월({trend_desc}). "
        f"계절적으로 상반기는 1월, 하반기는 7월이 저점 경향."
    )

    return {
        "current_rate":    current_rate,
        "trend_per_month": round(slope, 2),
        "h1_low_month":    h1_best[1] if h1_best else None,
        "h1_low_date":     h1_best[0].isoformat() if h1_best else None,
        "h1_low_rate":     h1_best[2] if h1_best else None,
        "h2_low_month":    h2_best[1] if h2_best else None,
        "h2_low_date":     h2_best[0].isoformat() if h2_best else None,
        "h2_low_rate":     h2_best[2] if h2_best else None,
        "note":            note,
    }


def rate_timing_tag(order_by_date: str, forecast: dict, today: date | None = None) -> str:
    """
    발주 기준일과 환율 저점 예상일을 비교하여 구매 시기 권고 태그를 반환.

    Tags (3종)
    ----------
    긴급구매필요   : 발주 기준일이 이미 지났거나 오늘 — 즉시 발주 필요
    하반기구매필요 : 가장 가까운 저점이 하반기(7월) — 7월 저점 전에 구매
    상반기구매예정 : 가장 가까운 저점이 내년 상반기(1월) — 여유 있음, 상반기 저점 활용 가능
    """
    if not order_by_date or not forecast:
        return "-"

    today = today or date.today()
    try:
        obd = date.fromisoformat(order_by_date)
    except ValueError:
        return "-"

    # 발주 기준일이 오늘 이하면 긴급
    if obd <= today:
        return "긴급구매필요"

    # 가장 가까운 저점 선택
    low_dates = []
    for key in ("h2_low_date", "h1_low_date"):
        if forecast.get(key):
            low_dates.append((key, date.fromisoformat(forecast[key])))
    if not low_dates:
        return "-"

    nearest_key, nearest = min(low_dates, key=lambda x: abs((x[1] - obd).days))

    if nearest_key == "h2_low_date":
        return f"하반기구매필요({nearest.strftime('%m월')}저점)"
    else:
        return f"상반기구매예정({nearest.strftime('%m월')}저점)"
