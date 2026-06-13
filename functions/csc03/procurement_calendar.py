"""
CSC-03  |  procurement_calendar: 다음 발주일 계산

발주는 연 2회 고정(1월 / 7월) 규칙. 기준일로부터 가장 가까운 다가오는 발주월의
1일을 반환한다. (안전재고 관리 페이지 '다음 발주일' 표시용)
"""

from __future__ import annotations
from datetime import date


def next_order_date(today: str | None = None) -> dict:
    """
    연 2회(1월/7월) 발주 규칙에서 다음 발주일을 계산.

    Parameters
    ----------
    today : str | None
        기준일 'YYYY-MM-DD'. None 이면 오늘.

    Returns
    -------
    dict
        {
            "today"           : "YYYY-MM-DD",
            "next_order_date" : "YYYY-MM-DD",   # 다가오는 1/1 또는 7/1
            "batch"           : 1 | 7,          # 발주 회차(월)
            "days_remaining"  : int,
            "rule"            : "연 2회 고정 발주 (1월/7월)",
        }
    """
    d = date.fromisoformat(today) if today else date.today()

    jul1 = date(d.year, 7, 1)
    jan1_next = date(d.year + 1, 1, 1)
    jan1_this = date(d.year, 1, 1)

    if d <= jan1_this:
        target, batch = jan1_this, 1
    elif d <= jul1:
        target, batch = jul1, 7
    else:
        target, batch = jan1_next, 1

    return {
        "today":           d.isoformat(),
        "next_order_date": target.isoformat(),
        "batch":           batch,
        "days_remaining":  (target - d).days,
        "rule":            "연 2회 고정 발주 (1월/7월)",
    }
