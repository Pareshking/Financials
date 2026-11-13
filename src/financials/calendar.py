"""Trading calendar.

Truth, in order of precedence:
1. a promoted bhavcopy for the date (`is_trading = TRUE`; overrides holiday rows),
2. a holiday row from NSE's holiday master (`is_trading = FALSE`),
3. for a year covered by a holiday master (`calendar_coverage`): Mon-Fri is trading, Sat/Sun not.
Outside covered years with no bhavcopy, the answer is unknown (None) — never guessed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from financials.parsers import ParseError


def parse_holiday_master(data: bytes, segment: str = "CM") -> list[tuple[date, str]]:
    """NSE `holiday-master?type=trading` JSON → [(date, description)] for one segment."""
    try:
        doc = json.loads(data.decode("utf-8"))
        rows = doc[segment]
        return [(datetime.strptime(r["tradingDate"], "%d-%b-%Y").date(), r["description"].strip()) for r in rows]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"holiday master: {exc}") from exc


def is_trading_day(con, exchange: str, d: date) -> bool | None:
    row = con.execute(
        "SELECT is_trading FROM trading_calendar WHERE exchange = ? AND cal_date = ?", [exchange, d]
    ).fetchone()
    if row is not None:
        return bool(row[0])
    covered = con.execute(
        "SELECT 1 FROM calendar_coverage WHERE exchange = ? AND cal_year = ?", [exchange, d.year]
    ).fetchone()
    if covered is None:
        return None
    return d.weekday() < 5


def next_trading_day(con, exchange: str, after: date, *, max_days: int = 15) -> date | None:
    """First trading day strictly after `after`; None if any day in between is unknown."""
    d = after
    for _ in range(max_days):
        d += timedelta(days=1)
        known = is_trading_day(con, exchange, d)
        if known is None:
            return None
        if known:
            return d
    return None
