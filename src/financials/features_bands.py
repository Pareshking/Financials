"""Circuit-day columns from the PR-zip price-band file [X359] (features 2026.11.24-24C), for `features.py`: one
batched read per materialised day (never a query per security).

Over the last WINDOW NSE sessions up to the as-of date (the market's trading days in `ohlcv`):
- band_hit_days_20d: sessions on which the security touched its price band (a `raw_price_band_hits` row, H or L);
- upper_circuit_days_20d: sessions it touched the upper band (H) and closed at the day's high;
- lower_circuit_days_20d: sessions it touched the lower band (L) and closed at the day's low.
"Closed at the band" is read from our own bar (close = high / low): the file says only that the band was touched.
Rows resolve to securities by symbol and series through `security_identifier_history` on the trade date (invariant 3).
NULL when any of the window's sessions has no band file loaded (genuine absence, not zero). All DAILY columns.
"""

from __future__ import annotations

from datetime import date

WINDOW = 20
COLUMNS = ("band_hit_days_20d", "upper_circuit_days_20d", "lower_circuit_days_20d")


def counts(con, as_of: date, exchange: str = "NSE") -> dict[str, tuple[int, int, int]] | None:
    """{security_id: (hit days, upper-circuit days, lower-circuit days)} over the window; None when the window is not
    fully covered by band files (or the market has fewer than WINDOW sessions)."""
    days = [d for (d,) in con.execute(
        "SELECT DISTINCT trade_date FROM ohlcv WHERE exchange = ? AND trade_date <= ? ORDER BY 1 DESC LIMIT ?",
        [exchange, as_of, WINDOW]).fetchall()]  # fmt: skip
    if len(days) < WINDOW:
        return None
    covered = con.execute(
        "SELECT count(DISTINCT trade_date) FROM raw_price_band_hits WHERE exchange = ? AND trade_date IN "
        "(SELECT unnest(?))", [exchange, days]).fetchone()[0]  # fmt: skip
    if covered < WINDOW:
        return None
    found = con.execute(
        """SELECT s.security_id,
                  count(DISTINCT h.trade_date),
                  count(DISTINCT CASE WHEN h.band = 'H' AND o.close = o.high THEN h.trade_date END),
                  count(DISTINCT CASE WHEN h.band = 'L' AND o.close = o.low THEN h.trade_date END)
           FROM raw_price_band_hits h
           JOIN security_identifier_history s
             ON s.exchange = h.exchange AND s.symbol = h.symbol AND s.series = h.series
            AND s.valid_from <= h.trade_date AND (s.valid_to IS NULL OR s.valid_to > h.trade_date)
           LEFT JOIN ohlcv o
             ON o.security_id = s.security_id AND o.exchange = h.exchange AND o.trade_date = h.trade_date
           WHERE h.exchange = ? AND h.trade_date IN (SELECT unnest(?))
           GROUP BY 1""",
        [exchange, days],
    ).fetchall()
    return {sec: (a, b, c) for sec, a, b, c in found}


def add_columns(con, rows: list[dict], as_of: date, exchange: str = "NSE") -> None:
    c = counts(con, as_of, exchange)
    for row in rows:
        if c is None:
            row.update(dict.fromkeys(COLUMNS))
        else:
            row.update(zip(COLUMNS, c.get(row["security_id"], (0, 0, 0)), strict=True))
