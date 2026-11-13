"""v1 data scope (references C9, a CHOICE, not a regulatory claim).

Market data, corporate actions and index snapshots start at MIN_TRADE_DATE (UDiFF era);
financial statements and shareholding start at MIN_PERIOD_END_DATE (Q3 FY25). Filters use the
period **end**, so a Q3 FY25 nine-month YTD (Apr-Dec 2024) and FY25 (for Q4 = FY - 9M) are kept.
Out-of-scope inputs are vaulted as evidence but never parsed into canonical tables.
"""

from __future__ import annotations

from datetime import date

MIN_TRADE_DATE = date(2024, 10, 1)
MIN_PERIOD_END_DATE = date(2024, 12, 31)


def market_in_scope(d: date) -> bool:
    return d >= MIN_TRADE_DATE


def financials_in_scope(period_end: date) -> bool:
    return period_end >= MIN_PERIOD_END_DATE
