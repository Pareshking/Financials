"""Materialised `screener_features` (latest) and `screener_features_history` (one row per as_of_date).

Runs inside the single writer process. Gates (architecture §12):
- G4 null-spike: a critical column's null rate may not rise > 1.5 percentage points vs the previous run.
- G5 atomic swap: history rows for the date and the live table are replaced in one transaction,
  only after the row count equals the universe size.

Prices: momentum uses back-adjusted closes (withheld after an unresolved gap); market cap uses the
raw close × share count rolled forward across later share-count actions (shares / eps_factor).
Fundamentals are read point-in-time at the end of `as_of_date` (IST).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from financials.corp_actions import ACCEPTED_STATUSES
from financials.db import insert_rows, table_columns
from financials.fundamentals import (
    altman_z_double_prime,
    building_blocks,
    choose_scope,
    load_factbook,
    safe_div,
    yoy_growth,
)
from financials.timeutil import ist_to_utc

CRITICAL_COLUMNS = ("close", "market_cap", "sales_ttm", "pat_ttm", "total_equity")
G4_MAX_NULL_RISE = 0.015
UNIVERSE_LOOKBACK_DAYS = 15


class FeatureGateFailure(Exception):
    def __init__(self, gate: str, message: str) -> None:
        super().__init__(f"{gate}: {message}")
        self.gate = gate


@dataclass
class MaterializeResult:
    status: str  # PROMOTED | ABORTED
    as_of_date: date
    rows: int = 0
    gate: str | None = None
    message: str = ""


def _f(x) -> float | None:
    return None if x is None else float(x)


def _universe(con, exchange: str, as_of: date) -> list[tuple[str, str, str, str]]:
    """(security_id, entity_id, symbol, series) with a bar in the lookback window and a valid identifier."""
    return con.execute(
        """SELECT DISTINCT o.security_id, s.entity_id, h.symbol, h.series
           FROM ohlcv o JOIN securities s USING (security_id)
           JOIN security_identifier_history h
             ON h.security_id = o.security_id AND h.exchange = o.exchange
            AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)
           WHERE o.exchange = ? AND o.trade_date <= ? AND o.trade_date > ?
           ORDER BY 1""",
        [as_of, as_of, exchange, as_of, as_of - timedelta(days=UNIVERSE_LOOKBACK_DAYS)],
    ).fetchall()


def _price_inputs(con, exchange: str, as_of: date):
    bars: dict[str, list[tuple[date, Decimal, int | None]]] = defaultdict(list)
    for sec, d, close, deliv in con.execute(
        "SELECT security_id, trade_date, close, deliv_qty FROM ohlcv WHERE exchange = ? AND trade_date <= ? "
        "ORDER BY security_id, trade_date",
        [exchange, as_of],
    ).fetchall():
        bars[sec].append((d, close, deliv))
    factors: dict[str, list[tuple[date, Decimal, Decimal]]] = defaultdict(list)
    for sec, ex, pf, ef, status in con.execute(
        "SELECT security_id, ex_date, price_factor, eps_factor, status FROM corp_actions WHERE ex_date <= ?", [as_of]
    ).fetchall():
        if status in ACCEPTED_STATUSES and pf is not None:
            factors[sec].append((ex, Decimal(str(pf)), Decimal(str(ef if ef is not None else 1))))
    frozen = dict(
        con.execute(
            "SELECT security_id, min(CAST(json_extract_string(details, '$.trade_date') AS DATE)) FROM quarantine_queue "
            "WHERE stage = 'GAP' AND resolved_at IS NULL GROUP BY security_id"
        ).fetchall()
    )
    return bars, factors, frozen


def _momentum(bars, actions, frozen_from: date | None) -> dict[str, float | None]:
    adj = []
    for d, close, _ in bars:
        if frozen_from is not None and d >= frozen_from:
            break
        f = Decimal(1)
        for ex, pf, _ in actions:
            if ex > d:
                f *= pf
        adj.append(close * f)
    out: dict[str, float | None] = {}
    last = adj[-1] if adj else None
    for name, n in (("return_1m", 21), ("return_3m", 63), ("return_6m", 126), ("return_12m", 252)):
        out[name] = _f(last / adj[-1 - n] - 1) if len(adj) > n and adj[-1 - n] else None
    for name, n in (("price_to_dma50", 50), ("price_to_dma200", 200)):
        out[name] = _f(last / (sum(adj[-n:]) / n)) if len(adj) >= n else None
    out["dist_52w_high"] = _f(last / max(adj[-252:]) - 1) if len(adj) >= 252 else None
    if frozen_from is not None and bars and bars[-1][0] >= frozen_from:
        # Today's adjusted price is unknown until the gap is explained: no stale momentum.
        out = dict.fromkeys(out)
    return out


def _delivery(bars) -> dict[str, float | None]:
    def avg(n):
        tail = [b[2] for b in bars[-n:]]
        return statistics.fmean(tail) if len(tail) == n and None not in tail else None

    a5, a20 = avg(5), avg(20)
    return {
        "deliv_avg_5d": a5,
        "deliv_avg_20d": a20,
        "delivery_velocity": a5 / a20 if a5 is not None and a20 else None,
    }


def _preload(con, as_of_ts: datetime):
    """Bulk point-in-time lookups keyed by entity (avoids per-security queries)."""
    shp_rows = con.execute(
        """SELECT entity_id, as_of_date, category, pct, shares FROM (
               SELECT *, dense_rank() OVER (PARTITION BY entity_id ORDER BY as_of_date DESC) AS r
               FROM shareholding_observations WHERE visible_from_ts <= ?) WHERE r = 1""",
        [as_of_ts],
    ).fetchall()
    shp: dict[str, dict] = defaultdict(dict)
    for ent, d, cat, pct, shares in shp_rows:
        shp[ent][cat] = (pct, shares)
        shp[ent]["_as_of"] = d
    paid_up = dict(
        (ent, (Decimal(v), d))
        for ent, v, d in con.execute(
            """SELECT entity_id, arg_max(value_other, period_end), max(period_end) FROM fact_observations
               WHERE canonical_tag = 'shares_from_paid_up' AND visible_from_ts <= ? GROUP BY entity_id""",
            [as_of_ts],
        ).fetchall()
    )
    quarter_end = dict(
        con.execute(
            """SELECT entity_id, max(period_end) FROM fact_observations WHERE canonical_tag = 'revenue_from_operations'
               AND period_type = 'DURATION' AND visible_from_ts <= ? GROUP BY entity_id""",
            [as_of_ts],
        ).fetchall()
    )
    return shp, paid_up, quarter_end


def compute_rows(con, as_of: date, exchange: str = "NSE") -> list[dict]:
    as_of_ts = ist_to_utc(as_of + timedelta(days=1), time(0, 0))  # end of as_of day, IST
    universe = _universe(con, exchange, as_of)
    bars, factors, frozen = _price_inputs(con, exchange, as_of)
    nifty = {
        s
        for (s,) in con.execute(
            "SELECT security_id FROM index_constituents_history WHERE index_name = 'NIFTY 500' AND valid_from <= ? "
            "AND (valid_to IS NULL OR valid_to > ?)",
            [as_of, as_of],
        ).fetchall()
    }
    shp_all, paid_up, quarter_end = _preload(con, as_of_ts)
    fundamentals_cache: dict[str, dict] = {}
    rows = []
    for sec, ent, symbol, series in universe:
        b = bars.get(sec, [])
        price_date, close = (b[-1][0], b[-1][1]) if b else (None, None)
        row: dict = {
            "as_of_date": as_of, "security_id": sec, "entity_id": ent, "symbol": symbol, "series": series,
            "price_date": price_date, "close": close, "piotroski_f": None, "beneish_m": None,
            "in_nifty500": sec in nifty,
        }  # fmt: skip
        row.update(_momentum(b, factors.get(sec, []), frozen.get(sec)))
        row.update(_delivery(b))

        if ent not in fundamentals_cache:
            fundamentals_cache[ent] = (
                _fundamentals(con, ent, as_of_ts, quarter_end[ent]) if ent in quarter_end else _EMPTY_FUNDAMENTALS
            )
        fund = fundamentals_cache[ent]
        row.update({k: v for k, v in fund.items() if not k.startswith("_")})

        shp = shp_all.get(ent, {})
        if "TOTAL" in shp:
            shares, shares_as_of, source = Decimal(shp["TOTAL"][1]), shp["_as_of"], "REG31"
        elif ent in paid_up:
            (shares, shares_as_of), source = paid_up[ent], "PAID_UP"
        else:
            shares = shares_as_of = source = None
        if shares is not None:
            for ex, _, ef in factors.get(sec, []):
                if shares_as_of < ex <= as_of:
                    shares = shares / ef
        mcap = close * shares if close is not None and shares is not None else None
        ev = (
            mcap + fund["_net_debt"] + (fund["_minority"] or 0)
            if mcap is not None and fund["_net_debt"] is not None
            else None
        )
        row.update({
            "shares": None if shares is None else int(shares), "shares_source": source,
            "market_cap": None if mcap is None else mcap.quantize(Decimal("0.01")),
            "enterprise_value": None if ev is None else ev.quantize(Decimal("0.01")),
            "pe": _f(safe_div(mcap, fund["_pat_owners"])),
            "pb": _f(safe_div(mcap, fund["_equity_owners"])),
            "ev_ebitda": _f(safe_div(ev, fund["ebitda_ttm"])),
            "fcff_yield": _f(safe_div(fund["_fcff"], ev)),
            "promoter_pct": _f(shp.get("PROMOTER", (None, None))[0]),
            "fii_pct": _f(shp.get("FII", (None, None))[0]),
            "dii_pct": _f(shp.get("DII", (None, None))[0]),
            "shp_as_of": shp.get("_as_of"),
        })  # fmt: skip
        public = shp.get("PUBLIC", (None, None))[1]
        a5 = row["deliv_avg_5d"]
        row["float_turnover_pct"] = a5 / public * 100 if a5 is not None and public else None
        rows.append(row)
    return rows


_EMPTY_FUNDAMENTALS: dict = {
    "sales_ttm": None, "ebitda_ttm": None, "pat_ttm": None, "fcf_ttm": None, "net_debt": None,
    "total_equity": None, "opm": None, "sales_growth_yoy": None, "profit_growth_yoy": None, "roe": None,
    "roce": None, "roic": None, "croic": None, "debt_to_equity": None, "other_income_to_pbt": None,
    "altman_z_dd": None, "scope_used": None, "fundamentals_end": None, "bs_as_of": None, "cf_as_of": None,
    "_net_debt": None, "_fcff": None, "_pat_owners": None, "_equity_owners": None, "_minority": None,
}  # fmt: skip


def _fundamentals(con, entity_id: str, as_of_ts: datetime, end: date) -> dict:
    empty = dict(_EMPTY_FUNDAMENTALS)
    chosen = choose_scope(con, entity_id, as_of_ts, end)
    if chosen is None:
        # No TTM window yet: balance-sheet ratios still apply (consolidated first).
        for scope in ("CONSOLIDATED", "STANDALONE"):
            book = load_factbook(con, entity_id, scope, as_of_ts)
            if book.latest_instant("total_assets", end) is not None:
                chosen = (scope, book)
                break
    if chosen is None:
        return {**empty, "fundamentals_end": end}
    scope, book = chosen
    b = building_blocks(book, end)
    eq, debt = b["total_equity"], b["total_debt"]
    capital = eq + debt if eq is not None and debt is not None else None
    return {
        "sales_ttm": b["rev_ops"], "ebitda_ttm": b["ebitda"], "pat_ttm": b["pat"], "fcf_ttm": b["fcf"],
        "net_debt": b["net_debt"], "total_equity": eq,
        "opm": _f(safe_div(b["ebitda"], b["rev_ops"])),
        "sales_growth_yoy": _f(yoy_growth(book, "revenue_from_operations", end)),
        "profit_growth_yoy": _f(yoy_growth(book, "pat", end)),
        "roe": _f(safe_div(b["pat_owners"], b["equity_owners"])),
        "roce": _f(safe_div(b["ebit"], capital)),
        "roic": _f(safe_div(b["nopat"], b["invested_capital"])),
        "croic": _f(safe_div(b["fcf"], b["invested_capital"])),
        "debt_to_equity": _f(safe_div(debt, eq)),
        "other_income_to_pbt": _f(safe_div(b["other_income"], b["pbt"])),
        "altman_z_dd": _f(altman_z_double_prime(b)),
        "scope_used": scope, "fundamentals_end": end, "bs_as_of": b["bs_as_of"], "cf_as_of": b["cf_as_of"],
        "_net_debt": b["net_debt"], "_fcff": b["fcff"], "_pat_owners": b["pat_owners"],
        "_equity_owners": b["equity_owners"], "_minority": b["minority_interest"],
    }  # fmt: skip


def _null_rates(rows: list[dict]) -> dict[str, float]:
    n = len(rows) or 1
    return {c: sum(r.get(c) is None for r in rows) / n for c in CRITICAL_COLUMNS}


def materialize(con, as_of: date, exchange: str = "NSE") -> MaterializeResult:
    """Compute, gate and atomically publish features for `as_of`. Caller must be the single writer."""
    rows = compute_rows(con, as_of, exchange)
    universe_size = len(_universe(con, exchange, as_of))
    if len(rows) != universe_size or not rows:
        return MaterializeResult("ABORTED", as_of, len(rows), "G5", f"{len(rows)} rows vs universe {universe_size}")

    prev = con.execute(
        "SELECT max(as_of_date) FROM screener_features_history WHERE as_of_date < ?", [as_of]
    ).fetchone()[0]
    if prev is not None:
        cols = ", ".join(f"avg(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)" for c in CRITICAL_COLUMNS)
        before = dict(zip(CRITICAL_COLUMNS, con.execute(
            f"SELECT {cols} FROM screener_features_history WHERE as_of_date = ?", [prev]
        ).fetchone(), strict=True))  # fmt: skip
        now = _null_rates(rows)
        spikes = {c: (before[c], now[c]) for c in CRITICAL_COLUMNS if now[c] - before[c] > G4_MAX_NULL_RISE}
        if spikes:
            return MaterializeResult("ABORTED", as_of, len(rows), "G4", f"null-rate spike vs {prev}: {spikes}")

    columns = table_columns(con, "screener_features_history")
    rows = [{c: r.get(c) for c in columns} for r in rows]
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM screener_features_history WHERE as_of_date = ?", [as_of])
        insert_rows(con, "screener_features_history", rows)
        latest = con.execute("SELECT max(as_of_date) FROM screener_features_history").fetchone()[0]
        con.execute("DELETE FROM screener_features")
        con.execute("INSERT INTO screener_features SELECT * FROM screener_features_history WHERE as_of_date = ?",
                    [latest])  # fmt: skip
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return MaterializeResult("PROMOTED", as_of, len(rows))
