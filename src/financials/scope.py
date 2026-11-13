"""v1 data scope (references C9, a CHOICE, not a regulatory claim).

Market data, corporate actions and index snapshots start at MIN_TRADE_DATE (UDiFF era);
financial statements and shareholding start at MIN_PERIOD_END_DATE (Q4 FY25, the first Integrated
Filing quarter observed [X38]). Filters use the period **end**, so the Q4 FY25 filing's full-year
FY25 YTD (Apr 2024-Mar 2025) is kept. No pre-Integrated-Filing (legacy) results format is parsed.
Out-of-scope inputs are vaulted as evidence but never parsed into canonical tables.
"""

from __future__ import annotations

from datetime import date

MIN_TRADE_DATE = date(2024, 10, 1)
MIN_PERIOD_END_DATE = date(2025, 3, 31)


def market_in_scope(d: date) -> bool:
    return d >= MIN_TRADE_DATE


def financials_in_scope(period_end: date) -> bool:
    return period_end >= MIN_PERIOD_END_DATE
