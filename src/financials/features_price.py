"""Price, volume and technical columns of `screener_features` (ratio catalogue A8, B6; architecture §10.7).

Called from `features.compute_rows` after the other columns are built; reads the extra bar fields (high, low,
volume, turnover) and the Nifty 500 closes in one batched query each, never per security.

Price basis [C2, architecture §11.1]:
- Levels and indicators (returns, DMA, 52-week and since-data-start high / low, RSI, MACD, ATR, relative strength,
  beta, 20-day VWAP) use back-adjusted series: close, high and low × the product of accepted `price_factor`s with
  ex-date after the bar (splits, bonuses, rights bonus element, demergers; never dividends); volume ÷ the same
  product, so traded value is unchanged. Adjusted series stop at the first unresolved GAP and every adjusted column is
  NULL while today's bar is frozen (the `_momentum` rule).
- Same-day values that no factor touches use the raw bar: `volume`, `vwap`, `deliv_pct`, `deliv_pct_avg_20d`,
  `turnover_median_20d`.
- Windows are counted in stored bars. Market data starts at MIN_TRADE_DATE [C9]: a window longer than the bars held
  returns NULL, never a partial-window number (3/5/7/10-year returns switch on by themselves later).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise

PRICE_COLUMNS = (
    "return_1d", "return_1w", "return_3y", "return_5y", "return_7y", "return_10y",
    "volume", "volume_1w_avg", "volume_1m_avg", "volume_1y_avg",
    "high_52w", "low_52w", "dist_52w_low", "high_since_data_start", "low_since_data_start",
    "dma50", "dma200", "dma50_prev", "dma200_prev",
    "rsi_14", "rsi_14_prev", "macd", "macd_signal", "macd_prev", "macd_signal_prev",
    "atr_14_pct", "rs_nifty500_3m", "rs_nifty500_6m", "rs_nifty500_12m", "beta_1y_nifty500",
    "turnover_median_20d", "deliv_pct", "deliv_pct_avg_20d", "vwap", "vwap_20d",
)  # fmt: skip

RAW_COLUMNS = ("volume", "vwap", "deliv_pct", "deliv_pct_avg_20d", "turnover_median_20d")
# Cumulative (not annualised) adjusted-close returns over N stored bars.
RETURN_BARS = {"return_1d": 1, "return_1w": 5, "return_3y": 756, "return_5y": 1260, "return_7y": 1764,
               "return_10y": 2520}  # fmt: skip
VOLUME_BARS = {"volume_1w_avg": 5, "volume_1m_avg": 21, "volume_1y_avg": 252}
RS_BARS = {"rs_nifty500_3m": 63, "rs_nifty500_6m": 126, "rs_nifty500_12m": 252}
YEAR_BARS = 252
LIQUIDITY_BARS = 20
RSI_N = ATR_N = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
NIFTY500 = "NIFTY 500"
_P4 = Decimal("0.0001")


def load_bars(con, exchange: str, as_of: date, securities=None) -> dict[str, list[tuple]]:
    """(trade_date, close, high, low, volume, turnover_inr, deliv_qty) per security up to `as_of`; one query."""
    from financials.fundamentals import entity_filter

    only, only_p = entity_filter("security_id", securities)
    out: dict[str, list[tuple]] = defaultdict(list)
    for sec, *bar in con.execute(
        "SELECT security_id, trade_date, close, high, low, volume, turnover_inr, deliv_qty FROM ohlcv "
        "WHERE exchange = ? AND trade_date <= ?" + only + " ORDER BY security_id, trade_date",
        [exchange, as_of, *only_p],
    ).fetchall():
        out[sec].append(tuple(bar))
    return out


def index_closes(con, as_of: date, index_name: str = NIFTY500) -> dict[date, float]:
    """Daily closes of a price index from `index_ohlcv` [IDX9] up to `as_of` (name matched case-insensitively:
    the file says "Nifty 500"). A date filed twice keeps the latest-fetched filing's row."""
    return dict(
        con.execute(
            """SELECT trade_date, CAST(close AS DOUBLE) FROM (
                 SELECT i.trade_date, i.close, row_number() OVER (
                     PARTITION BY i.trade_date ORDER BY f.fetched_at DESC, i.filing_id DESC) AS rn
                 FROM index_ohlcv i JOIN filings f USING (filing_id)
                 WHERE upper(i.index_name) = ? AND i.trade_date <= ?) WHERE rn = 1""",
            [index_name.upper(), as_of],
        ).fetchall()
    )


def adjust(bars, factors, frozen_from: date | None) -> list[tuple]:
    """Back-adjusted (date, close, high, low, volume) for bars before `frozen_from`. `factors` are the accepted
    (ex_date, price_factor, eps_factor) with ex_date <= as-of; a bar's factor is the product of those with
    ex_date > bar date. Prices stay Decimal; volume becomes Decimal (shares on today's basis)."""
    kept = [b for b in bars if frozen_from is None or b[0] < frozen_from]
    pending = sorted(((ex, pf) for ex, pf, _ in factors), reverse=True)
    out: list[tuple] = []
    f, i = Decimal(1), 0
    for b in reversed(kept):
        while i < len(pending) and pending[i][0] > b[0]:
            f *= pending[i][1]
            i += 1
        d, close, high, low, volume = b[0], b[1], b[2], b[3], b[4]
        out.append((
            d, close * f, None if high is None else high * f, None if low is None else low * f,
            None if volume is None else Decimal(volume) / f,
        ))  # fmt: skip
    out.reverse()
    return out


def _ret(xs, n: int) -> float | None:
    return float(xs[-1] / xs[-1 - n] - 1) if len(xs) > n and xs[-1 - n] else None


def sma(xs, n: int, lag: int = 0) -> Decimal | None:
    """Mean of the n values ending `lag` bars before the last; NULL without n of them."""
    if len(xs) < n + lag:
        return None
    window = xs[len(xs) - n - lag : len(xs) - lag]
    return sum(window, Decimal(0)) / n


def ema_series(xs: list[float], n: int) -> list[float | None]:
    """EMA with alpha 2/(n+1), seeded by the simple mean of the first n values (defined from index n-1)."""
    out: list[float | None] = [None] * len(xs)
    if len(xs) < n:
        return out
    s = sum(xs[:n]) / n
    out[n - 1] = s
    k = 2 / (n + 1)
    for i in range(n, len(xs)):
        s = xs[i] * k + s * (1 - k)
        out[i] = s
    return out


def rsi_series(closes: list[float], n: int = RSI_N) -> list[float | None]:
    """Wilder RSI: average gain / loss seeded by the simple mean of the first n changes, then
    avg = (avg × (n − 1) + x) / n. 100 when there are gains and no losses; NULL when the window is flat."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    ch = [b - a for a, b in pairwise(closes)]
    ag = sum(max(c, 0.0) for c in ch[:n]) / n
    al = sum(max(-c, 0.0) for c in ch[:n]) / n

    def value(g, lo):
        if lo == 0:
            return None if g == 0 else 100.0
        return 100 - 100 / (1 + g / lo)

    out[n] = value(ag, al)
    for i in range(n, len(ch)):
        ag = (ag * (n - 1) + max(ch[i], 0.0)) / n
        al = (al * (n - 1) + max(-ch[i], 0.0)) / n
        out[i + 1] = value(ag, al)
    return out


def macd_series(closes: list[float], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    """MACD = EMA(fast) − EMA(slow) (from bar `slow`); signal = EMA(signal) of MACD (from bar slow + signal − 1)."""
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    macd = [None if s is None else f - s for f, s in zip(ef, es, strict=True)]
    start = slow - 1
    sig: list[float | None] = [None] * len(closes)
    if len(closes) > start:
        sig[start:] = ema_series(macd[start:], signal)
    return macd, sig


def atr_series(highs, lows, closes, n: int = ATR_N) -> list[float | None]:
    """Wilder ATR: true range max(H − L, |H − C₋₁|, |L − C₋₁|) from the second bar; seeded by the mean of the first
    n true ranges, then (atr × (n − 1) + tr) / n."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    tr = [None] + [max(h - lo, abs(h - c0), abs(lo - c0))
                   for h, lo, c0 in zip(highs[1:], lows[1:], closes, strict=False)]  # fmt: skip
    a = sum(tr[1 : n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(closes)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def beta(stock: list[float], index: list[float]) -> float | None:
    """OLS beta of daily log returns of `stock` on `index` (two aligned level series)."""
    rs = [math.log(b / a) for a, b in pairwise(stock)]
    rm = [math.log(b / a) for a, b in pairwise(index)]
    if len(rs) < 2:
        return None
    ms, mm = statistics.fmean(rs), statistics.fmean(rm)
    var = sum((x - mm) ** 2 for x in rm)
    if var == 0:
        return None
    return sum((x - ms) * (y - mm) for x, y in zip(rs, rm, strict=True)) / var


def _last2(series) -> tuple:
    return (series[-1] if series else None, series[-2] if len(series) >= 2 else None)


def _q(x: Decimal | None) -> Decimal | None:
    return None if x is None else x.quantize(_P4)


def raw_columns(bars) -> dict:
    """Columns from the unadjusted bars: today's volume, VWAP (turnover / volume, = the delivery file's AVG_PRICE
    [P16]) and delivery % (deliv_qty / volume), the 20-day mean delivery % and the 20-day median traded value."""
    out = dict.fromkeys(RAW_COLUMNS)
    if not bars:
        return out
    _, _, _, _, vol, turnover, deliv = bars[-1]
    out["volume"] = vol
    if vol and turnover is not None:
        out["vwap"] = _q(Decimal(turnover) / vol)
    if vol and deliv is not None:
        out["deliv_pct"] = deliv / vol
    tail = bars[-LIQUIDITY_BARS:]
    if len(tail) == LIQUIDITY_BARS:
        pcts = [b[6] / b[4] if b[4] and b[6] is not None else None for b in tail]
        if None not in pcts:
            out["deliv_pct_avg_20d"] = statistics.fmean(pcts)
        values = [b[5] for b in tail]
        if None not in values:
            out["turnover_median_20d"] = Decimal(statistics.median(values)).quantize(Decimal("0.01"))
    return out


def adjusted_columns(adj, index: dict[date, float]) -> dict:
    """Columns from the adjusted series (see module doc). `index`: Nifty 500 closes by date."""
    out = dict.fromkeys(c for c in PRICE_COLUMNS if c not in RAW_COLUMNS)
    if not adj:
        return out
    closes = [b[1] for b in adj]
    last = closes[-1]
    for name, n in RETURN_BARS.items():
        out[name] = _ret(closes, n)
    for name, n in VOLUME_BARS.items():
        tail = [b[4] for b in adj[-n:]]
        out[name] = float(sum(tail) / n) if len(tail) == n and None not in tail else None
    if len(closes) >= YEAR_BARS:
        hi, lo = max(closes[-YEAR_BARS:]), min(closes[-YEAR_BARS:])
        out["high_52w"], out["low_52w"] = _q(hi), _q(lo)
        out["dist_52w_low"] = float(last / lo - 1) if lo else None
    out["high_since_data_start"], out["low_since_data_start"] = _q(max(closes)), _q(min(closes))
    for n in (50, 200):
        out[f"dma{n}"], out[f"dma{n}_prev"] = _q(sma(closes, n)), _q(sma(closes, n, lag=1))
    fl = [float(c) for c in closes]
    out["rsi_14"], out["rsi_14_prev"] = _last2(rsi_series(fl))
    macd, sig = macd_series(fl)
    out["macd"], out["macd_prev"] = _last2(macd)
    out["macd_signal"], out["macd_signal_prev"] = _last2(sig)
    # ATR on the tail after the last bar without a high or low (the recursion cannot bridge a hole).
    start = max((i + 1 for i, b in enumerate(adj) if b[2] is None or b[3] is None), default=0)
    seg = adj[start:]
    atr = atr_series([float(b[2]) for b in seg], [float(b[3]) for b in seg], [float(b[1]) for b in seg])
    out["atr_14_pct"] = atr[-1] / fl[-1] if atr and atr[-1] is not None and fl[-1] else None
    dates = [b[0] for b in adj]
    for name, n in RS_BARS.items():
        if len(closes) > n and dates[-1] in index and dates[-1 - n] in index and closes[-1 - n]:
            out[name] = float(last / closes[-1 - n]) - index[dates[-1]] / index[dates[-1 - n]]
    window = dates[-YEAR_BARS - 1 :]
    if len(window) == YEAR_BARS + 1 and all(d in index for d in window):
        out["beta_1y_nifty500"] = beta(fl[-YEAR_BARS - 1 :], [index[d] for d in window])
    return out


def price_columns(bars, factors, frozen_from: date | None, index: dict[date, float]) -> dict:
    """Every PRICE_COLUMNS value for one security (pure; `bars` from load_bars)."""
    out = raw_columns(bars)
    if bars and frozen_from is not None and bars[-1][0] >= frozen_from:
        return {**dict.fromkeys(PRICE_COLUMNS), **out}  # today's adjusted price is unknown until the gap is explained
    adj = adjust(bars, factors, frozen_from)
    out |= adjusted_columns(adj, index)
    # 20-day VWAP on today's share basis: traded value (no factor changes it) / adjusted volume.
    tail_adj, tail_raw = adj[-LIQUIDITY_BARS:], bars[-LIQUIDITY_BARS:]
    if len(tail_adj) == LIQUIDITY_BARS and None not in [b[4] for b in tail_adj] + [b[5] for b in tail_raw]:
        vol = sum((b[4] for b in tail_adj), Decimal(0))
        out["vwap_20d"] = _q(sum((Decimal(b[5]) for b in tail_raw), Decimal(0)) / vol) if vol else None
    return out


def add_price_columns(con, rows: list[dict], as_of: date, exchange: str, factors, frozen, securities=None,
                      prices=None) -> None:  # fmt: skip
    """Fill PRICE_COLUMNS into `rows` in place (the features.compute_rows hook): two batched reads, or slices of the
    run's `price_history.PriceHistory` (`prices`, the same values)."""
    if prices is not None:
        for row in rows:
            row.update(prices.price_columns(row["security_id"], as_of))
        return
    bars = load_bars(con, exchange, as_of, securities)
    index = index_closes(con, as_of)
    for row in rows:
        sec = row["security_id"]
        row.update(price_columns(bars.get(sec, []), factors.get(sec, []), frozen.get(sec), index))


def refresh_breadth(con, as_of: date) -> None:
    """Market breadth for `as_of` from the stored rows of the day (Nifty 500 members) [G208]; runs inside the
    materialize transaction after the day's rows are written, so a full or incremental run leaves it consistent."""
    con.execute("DELETE FROM market_breadth WHERE as_of_date = ?", [as_of])
    con.execute(
        """INSERT INTO market_breadth
           SELECT as_of_date, 'NIFTY 500', count(*),
                  count(*) FILTER (WHERE price_to_dma50 > 1) / nullif(count(price_to_dma50), 0),
                  count(*) FILTER (WHERE price_to_dma200 > 1) / nullif(count(price_to_dma200), 0),
                  count(*) FILTER (WHERE dist_52w_high = 0), count(*) FILTER (WHERE dist_52w_low = 0),
                  count(*) FILTER (WHERE dist_52w_high = 0) / nullif(count(*) FILTER (WHERE dist_52w_low = 0), 0),
                  count(*) FILTER (WHERE return_1d > 0), count(*) FILTER (WHERE return_1d < 0),
                  count(*) FILTER (WHERE return_1d = 0),
                  count(*) FILTER (WHERE return_1d > 0) / nullif(count(*) FILTER (WHERE return_1d < 0), 0)
           FROM screener_features_history WHERE as_of_date = ? AND in_nifty500 GROUP BY as_of_date""",
        [as_of],
    )
