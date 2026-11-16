"""The last BUILDABLE NOW rows of docs/ratio_catalogue.md (batch I), for `features.py`.

Three stages, all batched (never a query per security):
1. `period_values(book, end, b, industrial)` per entity, from the row's own scope book [C18]: Beneish and Piotroski
   components (the inputs behind `beneish_m` / `piotroski_f`, same fiscal years), original Altman Z inputs,
   balance-sheet accruals, depreciation rate / asset age, FY and half-year days changes.
2. `add_columns(...)` per security row (the `features.compute_rows` hook, after batch G): valuation percentiles vs
   own quarter-end history, volatility / drawdown, 52-week high on a delivery spike, the PEAD tracker, index
   inclusion / exclusion, corporate-action recency, segment mix; then the day's cross-section.
3. `refresh_cross_section(con, as_of)` inside the materialize transaction (like features_gems / features_peers):
   the RS rank of 12M-1M momentum and the industry earnings breadth over every stored row of the day.

Definitions (fractions as DOUBLE, `_pp` = fraction points, days as DOUBLE):
- Beneish (B1.2): DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI, TATA exactly as `fundamentals.beneish_components` on the
  latest fiscal year vs the one before (FY26 vs FY25 today); all eight or none, industrial books only (as
  `beneish_m`). Piotroski (B1.3): the nine tests of `fundamentals.piotroski_signals`, BOOLEAN, all or none.
- original Altman Z (B1.5) = 1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + 1.0 Sales/TA on the latest balance
  sheet and TTM EBIT / sales (`building_blocks`, the Z'' inputs; RE = other equity, the Z'' proxy), MVE = market
  cap. "Manufacturer" = an industrial book whose materials + purchases are >= 10% of sales (the C6 guard that
  defines gross profit); NULL otherwise.
- balance-sheet accruals (B1.7) = (NOA(FY) - NOA(FY-1)) / average total assets, NOA = equity + debt + leases -
  liquid cash (`fundamentals.invested_capital_at`; operating assets - operating liabilities, Richardson et al.).
- depreciation rate (B2.12) = FY D&A / average gross block (Reg. 34 FY and FY-1 ends); asset age proxy =
  accumulated depreciation / gross block at the FY end.
- days changes (B3.2) = debtor days and cash conversion cycle (Screener convention, `features_bs._days`) of the
  last FY minus the preceding FY. Half-year days (B3.3): on the latest balance sheet that is not a fiscal-year end
  (within 12 months of the row's quarter), receivables / (H1 sales x 2 / 365) and inventory / (H1 COGS x 2 / 365)
  (COGS >= 1% of sales, as the FY form); YoY = minus the same 12 months earlier.
- valuation percentiles (B5.2, B5.3): pb, price_to_sales and ev_to_sales vs the security's own last materialised
  value of every prior quarter (the `pe_percentile` method [C20], >= 4 quarters).
- momentum_12m_1m = (1 + return_12m) / (1 + return_1m) - 1; rs_rank_12m_1m = share of the day's other rows with a
  lower value (1 = strongest, B6.3). volatility_1y = sample std of the last 252 daily log returns x sqrt(252);
  max_drawdown_1y = worst close / running-max - 1 over the last 252 bars (B6.4). Adjusted closes (the `_momentum`
  rule); NULL while today's bar is frozen by an unexplained gap or with fewer bars [C9].
- high_52w_on_delivery_spike (B6.11, G283): today's adjusted close is the 252-bar high AND today's delivered
  quantity > 2 x the median of the 20 bars before (share-count adjusted). FALSE when it is not a new high.
- PEAD (B6.14, G151): event = the latest results' first broadcast (`last_result_date`, IST); T+0 = first bar on or
  after it, base = the bar before. pead_ar_tK = stock close(T+K) / close(base) - Nifty 500 close(T+K) /
  close(base) (index_ohlcv; NULL when either index close is missing); pead_relvol_tK = volume(T+K) / mean volume of
  the 20 bars before T+0. NULL until T+K has traded.
- index events (B8.4): NIFTY 500 `valid_from` (not the index's first stored snapshot, which is not an event) /
  `valid_to` in the last 90 days; NULL while the stored history does not cover the whole window.
- corporate actions (B8.5): dividend / bonus / split ex-date in the last 365 days (NULL when the window starts
  before MIN_TRADE_DATE, C9); days to the next ex-date and its type(s), only from listings visible at the as-of
  (filing broadcast, else fetch time); retired actions (SUPERSEDED / REJECTED) never count.
- segments (B9.1, B9.2): BUSINESS-axis SEGMENT members of the latest filed segment period (`load_segments` point in
  time rule, batched), the row's scope; count, largest revenue / sum of segment revenue (before eliminations),
  fastest-growing segment vs the same period a year earlier (matched by filed label within the entity, base > 0)
  and the largest segment's margin (RESULT / REVENUE) change YoY.
- industry earnings breadth (B4.9, G205) = share of the NSE industry's companies (one per company) reporting the
  industry's latest quarter whose core profit grew YoY (`core_profit_yoy_latest_q` > 0); >= 3 companies.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from financials.fundamentals import (
    COGS_MIN_SHARE,
    PIOTROSKI_SIGNALS,
    SEGMENT_CURRENT_VERSION,
    _add_months,
    _year,
    beneish_components,
    entity_filter,
    invested_capital_at,
    latest_fiscal_year,
    percentile_rank,
    piotroski_signals,
    safe_div,
)
from financials.scope import MIN_TRADE_DATE

# ── columns (schema order: `-- batch I (last catalogue rows)` in db/schema.sql) ───────────────────────────────────

BENEISH_KEYS = ("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA")
BENEISH_COLUMNS = tuple(f"beneish_{k.lower()}" for k in BENEISH_KEYS)
PIOTROSKI_COLUMNS = tuple(f"piotroski_{s}" for s in PIOTROSKI_SIGNALS)
FORENSIC_COLUMNS = ("altman_z_original", "bs_accruals", "depreciation_rate", "asset_age_proxy")
DAYS_COLUMNS = ("debtor_days_change_yoy", "ccc_change_yoy", "h1_bs_as_of", "debtor_days_h1", "inventory_days_h1",
                "debtor_days_h1_change_yoy", "inventory_days_h1_change_yoy")  # fmt: skip
PERCENTILES = {"pb_percentile": "pb", "price_to_sales_percentile": "price_to_sales",
               "ev_to_sales_percentile": "ev_to_sales"}  # fmt: skip
PEAD_DAYS = (0, 1, 5, 20)
PRICE_COLUMNS = ("momentum_12m_1m", "volatility_1y", "max_drawdown_1y", "high_52w_on_delivery_spike")
PEAD_COLUMNS = ("pead_event_date", *(f"pead_ar_t{k}" for k in PEAD_DAYS), *(f"pead_relvol_t{k}" for k in PEAD_DAYS))
EVENT_COLUMNS = ("nifty500_inclusion_90d", "nifty500_exclusion_90d", "days_to_next_ex_date", "next_ex_date_action",
                 "dividend_365d", "bonus_365d", "split_365d")  # fmt: skip
SEGMENT_COLUMNS = ("segment_period_end", "segment_count", "largest_segment_revenue_share", "fastest_growing_segment",
                   "fastest_growing_segment_growth_yoy", "largest_segment_margin_change_yoy_pp")  # fmt: skip
CROSS_COLUMNS = ("rs_rank_12m_1m", "industry_earnings_breadth", "industry_earnings_breadth_n")
MORE_COLUMNS = (
    *BENEISH_COLUMNS, *PIOTROSKI_COLUMNS, *FORENSIC_COLUMNS, *DAYS_COLUMNS, *PERCENTILES, *PRICE_COLUMNS,
    *PEAD_COLUMNS, *EVENT_COLUMNS, *SEGMENT_COLUMNS, *CROSS_COLUMNS,
)  # fmt: skip

# Meaningless for lenders and insurers (no gross margin, inventory or debtor cycle; Beneish / Piotroski / Altman are
# industrial models, as for beneish_m / piotroski_f).
INDUSTRIAL_ONLY = frozenset({*BENEISH_COLUMNS, *PIOTROSKI_COLUMNS, *FORENSIC_COLUMNS, *DAYS_COLUMNS})
FINANCIAL_ARCHETYPES = frozenset({"FINANCIAL_LENDING", "INSURANCE"})

YEAR_BARS = 252
SPIKE_BARS = 20
SPIKE_MULTIPLE = 2
PEAD_BASE_BARS = 20
EVENT_WINDOW_DAYS = 90
ACTION_WINDOW_DAYS = 365
BAR_LOOKBACK_DAYS = 450  # calendar days of bars read: 253 bars for the 1Y windows, PEAD base + T+20
MIN_PEERS = 3
NIFTY500 = "NIFTY 500"
ALTMAN = (Decimal("1.2"), Decimal("1.4"), Decimal("3.3"), Decimal("0.6"), Decimal("1.0"))
ZERO = Decimal(0)


def _f(x) -> float | None:
    return None if x is None else float(x)


# ── stage 1: per entity, from the scope book ──────────────────────────────────────────────────────────────────────


def annual_years(book, end: date) -> tuple[dict, dict] | None:
    """(last FY, preceding FY) inputs exactly as `fundamentals.annual_ratios` builds them for beneish_m."""
    fy = latest_fiscal_year(book, end)
    if fy is None:
        return None
    prior = (_add_months(fy[0], -12), _add_months(fy[1], -12))
    if latest_fiscal_year(book, prior[1]) != prior:
        return None
    return _year(book, fy), _year(book, prior)


def forensic_components(book, end: date) -> dict:
    out = dict.fromkeys((*BENEISH_COLUMNS, *PIOTROSKI_COLUMNS))
    years = annual_years(book, end)
    if years is None:
        return out
    idx = beneish_components(*years)
    if idx is not None:
        out |= {f"beneish_{k.lower()}": float(idx[k]) for k in BENEISH_KEYS}
    signals = piotroski_signals(*years)
    if signals is not None:
        out |= dict(zip(PIOTROSKI_COLUMNS, (bool(s) for s in signals), strict=True))
    return out


def altman_inputs(b: dict) -> tuple | None:
    """(WC, RE, EBIT, TA, TL, sales) of a manufacturer (the C6 guard holds: gross profit is defined), else None."""
    if b.get("gross_profit") is None:
        return None
    ca, cl = b.get("current_assets"), b.get("current_liabilities")
    vals = (None if ca is None or cl is None else ca - cl, b.get("other_equity"), b.get("ebit"),
            b.get("total_assets"), b.get("total_liabilities"), b.get("rev_ops"))  # fmt: skip
    return None if None in vals or not vals[3] or not vals[4] else vals


def altman_z_original(inputs: tuple | None, market_cap) -> Decimal | None:
    if inputs is None or market_cap is None:
        return None
    wc, re_, ebit, ta, tl, sales = inputs
    x = (wc / ta, re_ / ta, ebit / ta, Decimal(market_cap) / tl, sales / ta)
    return sum((w * v for w, v in zip(ALTMAN, x, strict=True)), ZERO)


def bs_accruals(book, fy_end: date) -> Decimal | None:
    """(NOA at the FY end - NOA a year earlier) / average total assets of the two dates (B1.7)."""
    prev = _add_months(fy_end, -12)
    n1, n0 = invested_capital_at(book, fy_end), invested_capital_at(book, prev)
    a1, a0 = (book.instants.get("total_assets", {}).get(d) for d in (fy_end, prev))
    if None in (n1, n0, a1, a0) or a1 + a0 <= 0:
        return None
    return (n1 - n0) / ((a1 + a0) / 2)


def depreciation_ratios(book, fy: tuple[date, date]) -> tuple[Decimal | None, Decimal | None]:
    """(FY D&A / average gross block, accumulated depreciation / gross block at the FY end) (B2.12)."""
    at = lambda t, d: book.instants.get(t, {}).get(d)  # noqa: E731
    gb1, gb0 = at("ppe_gross_block", fy[1]), at("ppe_gross_block", _add_months(fy[1], -12))
    dep = book.durations.get("depreciation_amortisation", {}).get(fy)
    rate = None if None in (dep, gb1, gb0) or gb1 + gb0 <= 0 else dep / ((gb1 + gb0) / 2)
    acc = at("ppe_accumulated_depreciation", fy[1])
    return rate, (safe_div(acc, gb1) if gb1 and gb1 > 0 else None)


def _fy_ends(book) -> set[date]:
    from financials.parsers.indas_corp import period_months

    return {p[1] for p in book.durations.get("pat", {}) if period_months(*p) == 12}


def half_year_days(book, d: date) -> tuple[Decimal | None, Decimal | None]:
    """(debtor days, inventory days) on balance-sheet date `d` with H1 sales / COGS annualised (x 2)."""
    from financials import features_pl

    if book.instants.get("total_assets", {}).get(d) is None:
        return None, None
    sales_tag = features_pl._tags(book)["sales"]
    qs = (d, _add_months(d, -3))
    sales = [book.quarter(sales_tag, q) for q in qs]
    if None in sales or sum(sales, ZERO) <= 0:
        return None, None
    h1 = sum(sales, ZERO)
    at = lambda t: book.instants.get(t, {}).get(d) or ZERO  # noqa: E731  (Schedule III omits nil lines [C23])
    debtor = (at("trade_receivables_current") + at("trade_receivables_noncurrent")) * 365 / (2 * h1)
    cogs = sum((book.quarter(t, q) or ZERO for t in ("cost_of_materials_consumed", "purchases_of_stock_in_trade",
                                                     "changes_in_inventories") for q in qs), ZERO)  # fmt: skip
    inv = at("inventories") * 365 / (2 * cogs) if cogs > 0 and cogs >= COGS_MIN_SHARE * h1 else None
    return debtor, inv


def days_columns(book, end: date, fy) -> dict:
    from financials.features_bs import _days

    out = dict.fromkeys(DAYS_COLUMNS)
    if fy is not None:
        now, before = _days(book, fy[1]), _days(book, _add_months(fy[1], -12))
        for col, key in (("debtor_days_change_yoy", "debtor_days"), ("ccc_change_yoy", "cash_conversion_cycle")):
            a, b = now.get(key), before.get(key)
            out[col] = None if a is None or b is None else float(a - b)
    fy_ends = _fy_ends(book)
    oldest = _add_months(end, -12)
    halves = [d for d in book.instants.get("total_assets", {}) if oldest < d <= end and d not in fy_ends]
    if halves:
        d = max(halves)
        out["h1_bs_as_of"] = d
        debtor, inv = half_year_days(book, d)
        debtor0, inv0 = half_year_days(book, _add_months(d, -12))
        out["debtor_days_h1"], out["inventory_days_h1"] = _f(debtor), _f(inv)
        out["debtor_days_h1_change_yoy"] = None if debtor is None or debtor0 is None else float(debtor - debtor0)
        out["inventory_days_h1_change_yoy"] = None if inv is None or inv0 is None else float(inv - inv0)
    return out


def period_values(book, end: date, b: dict, industrial: bool = True) -> dict:
    """Stage 1 (one per entity and scope book). `b` = fundamentals.building_blocks(book, end)."""
    out: dict = {}
    if not industrial:
        return out
    out |= forensic_components(book, end)
    out["_altman"] = altman_inputs(b)
    fy = latest_fiscal_year(book, end)
    if fy is not None:
        out["bs_accruals"] = _f(bs_accruals(book, fy[1]))
        rate, age = depreciation_ratios(book, fy)
        out["depreciation_rate"], out["asset_age_proxy"] = _f(rate), _f(age)
    out |= days_columns(book, end, fy)
    return out


# ── stage 2: batched reads ────────────────────────────────────────────────────────────────────────────────────────


def valuation_history(con, as_of: date, securities=None) -> dict[str, dict[str, list[float]]]:
    """Each security's pb / price_to_sales / ev_to_sales at the last materialised date of every prior quarter."""
    only, only_p = entity_filter("security_id", securities)
    cols = list(dict.fromkeys(PERCENTILES.values()))
    rows = con.execute(
        "SELECT security_id, date_trunc('quarter', as_of_date) AS q, "
        + ", ".join(f"arg_max({c}, as_of_date)" for c in cols)
        + " FROM screener_features_history WHERE as_of_date < date_trunc('quarter', CAST(? AS DATE))"
        + only
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        [as_of, *only_p],
    ).fetchall()
    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: {c: [] for c in cols})
    for sec, _, *vals in rows:
        for c, v in zip(cols, vals, strict=True):
            out[sec][c].append(v)
    return out


def load_bars(con, exchange: str, as_of: date, securities=None) -> dict[str, list[tuple]]:
    """(trade_date, close, volume, deliv_qty) per security over the last BAR_LOOKBACK_DAYS; one query."""
    only, only_p = entity_filter("security_id", securities)
    out: dict[str, list[tuple]] = defaultdict(list)
    for sec, *bar in con.execute(
        "SELECT security_id, trade_date, close, volume, deliv_qty FROM ohlcv WHERE exchange = ? AND trade_date > ? "
        "AND trade_date <= ?" + only + " ORDER BY security_id, trade_date",
        [exchange, as_of - timedelta(days=BAR_LOOKBACK_DAYS), as_of, *only_p],
    ).fetchall():
        out[sec].append(tuple(bar))
    return out


def adjust(bars, factors, frozen_from: date | None) -> list[tuple]:
    """(date, adjusted close, adjusted volume, adjusted delivery) before `frozen_from` (the `_momentum` rule: x the
    product of accepted price factors with ex-date after the bar; quantities / the same product)."""
    pending = sorted(((ex, Decimal(pf)) for ex, pf, _ in factors), reverse=True)
    out: list[tuple] = []
    f, i = Decimal(1), 0
    kept = [b for b in bars if frozen_from is None or b[0] < frozen_from]
    for d, close, vol, deliv in reversed(kept):
        while i < len(pending) and pending[i][0] > d:
            f *= pending[i][1]
            i += 1
        out.append((d, float(close * f), None if vol is None else float(vol / f),
                    None if deliv is None else float(deliv / f)))  # fmt: skip
    out.reverse()
    return out


def volatility(closes: list[float]) -> float | None:
    if len(closes) < YEAR_BARS + 1:
        return None
    tail = closes[-YEAR_BARS - 1 :]
    rets = [math.log(b / a) for a, b in pairwise(tail)]
    return statistics.stdev(rets) * math.sqrt(YEAR_BARS)


def max_drawdown(closes: list[float]) -> float | None:
    if len(closes) < YEAR_BARS:
        return None
    peak, worst = 0.0, 0.0
    for c in closes[-YEAR_BARS:]:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1)
    return worst


def delivery_spike_high(adj: list[tuple]) -> bool | None:
    closes = [b[1] for b in adj]
    if len(closes) < YEAR_BARS:
        return None
    if closes[-1] < max(closes[-YEAR_BARS:]):
        return False
    deliv = [b[3] for b in adj[-SPIKE_BARS - 1 :]]
    if len(deliv) < SPIKE_BARS + 1 or None in deliv:
        return None
    return deliv[-1] > SPIKE_MULTIPLE * statistics.median(deliv[:-1])


def pead(adj: list[tuple], event: date | None, index: dict[date, float]) -> dict:
    out = dict.fromkeys(PEAD_COLUMNS)
    if event is None or not adj:
        return out
    i0 = next((i for i, b in enumerate(adj) if b[0] >= event), None)
    if i0 is None or i0 == 0:
        return out
    out["pead_event_date"] = event
    base_d, base_c = adj[i0 - 1][0], adj[i0 - 1][1]
    vols = [b[2] for b in adj[max(0, i0 - PEAD_BASE_BARS) : i0]]
    base_vol = statistics.fmean(vols) if len(vols) == PEAD_BASE_BARS and None not in vols else None
    for k in PEAD_DAYS:
        if i0 + k >= len(adj):
            continue
        d, c, v, _ = adj[i0 + k]
        if base_d in index and d in index and base_c:
            out[f"pead_ar_t{k}"] = c / base_c - index[d] / index[base_d]
        if base_vol and v is not None:
            out[f"pead_relvol_t{k}"] = v / base_vol
    return out


def price_columns(row: dict, bars, factors, frozen_from: date | None, index: dict[date, float]) -> dict:
    out = dict.fromkeys((*PRICE_COLUMNS, *PEAD_COLUMNS))
    r12, r1 = row.get("return_12m"), row.get("return_1m")
    if r12 is not None and r1 is not None and r1 > -1:
        out["momentum_12m_1m"] = (1 + r12) / (1 + r1) - 1
    if not bars or (frozen_from is not None and bars[-1][0] >= frozen_from):
        return out  # today's adjusted price is unknown until the gap is explained
    adj = adjust(bars, factors, frozen_from)
    closes = [b[1] for b in adj]
    out["volatility_1y"] = volatility(closes)
    out["max_drawdown_1y"] = max_drawdown(closes)
    out["high_52w_on_delivery_spike"] = delivery_spike_high(adj)
    out |= pead(adj, row.get("last_result_date"), index)
    return out


def index_events(con, as_of: date, securities=None) -> tuple[bool, dict[str, tuple[bool, bool]]]:
    """(window covered, security -> (included, excluded) in the last EVENT_WINDOW_DAYS) for NIFTY 500. An interval
    that starts where the same security's previous one ends (a MANUAL_BACKFILL row handing over to the first
    SNAPSHOT) is a continuation, not an inclusion; nor is the index's first stored date."""
    start = as_of - timedelta(days=EVENT_WINDOW_DAYS)
    only, only_p = entity_filter("security_id", securities)
    rows = con.execute(
        "SELECT security_id, valid_from, valid_to FROM index_constituents_history WHERE index_name = ? "
        "AND valid_from <= ?" + only,
        [NIFTY500, as_of, *only_p],
    ).fetchall()
    first = con.execute(
        "SELECT min(valid_from) FROM index_constituents_history WHERE index_name = ?", [NIFTY500]
    ).fetchone()[0]
    if first is None or first > start:
        return False, {}
    ends: dict[str, set[date]] = defaultdict(set)
    starts: dict[str, set[date]] = defaultdict(set)
    for sec, vf, vt in rows:
        starts[sec].add(vf)
        if vt is not None:
            ends[sec].add(vt)
    out: dict[str, tuple[bool, bool]] = {}
    for sec, vf, vt in rows:
        inc = start < vf <= as_of and vf > first and vf not in ends[sec]
        exc = vt is not None and start < vt <= as_of and vt not in starts[sec]
        before = out.get(sec, (False, False))
        out[sec] = (before[0] or inc, before[1] or exc)
    return True, out


def action_inputs(con, as_of: date, as_of_ts: datetime, securities=None) -> dict[str, list[tuple]]:
    """(ex_date, action_type, accepted, visible) of every non-retired action with ex-date after as_of - 365 days."""
    from financials.corp_actions import ACCEPTED_STATUSES, RETIRED_STATUSES

    only, only_p = entity_filter("a.security_id", securities)
    retired = ", ".join(f"'{s}'" for s in sorted(RETIRED_STATUSES))
    out: dict[str, list[tuple]] = defaultdict(list)
    for sec, ex, kind, status, visible in con.execute(
        "SELECT a.security_id, a.ex_date, a.action_type, a.status, coalesce(f.broadcast_ts, f.fetched_at) <= ? "
        f"FROM corp_actions a JOIN filings f ON f.filing_id = a.source_filing_id WHERE a.status NOT IN ({retired}) "
        "AND a.ex_date > ?" + only,
        [as_of_ts, as_of - timedelta(days=ACTION_WINDOW_DAYS), *only_p],
    ).fetchall():
        out[sec].append((ex, kind, status in ACCEPTED_STATUSES, bool(visible)))
    return out


def action_columns(actions: list[tuple], as_of: date) -> dict:
    """Past flags count accepted actions only (the dividend-yield rule); the next ex-date any announced one."""
    out = dict.fromkeys(EVENT_COLUMNS[2:])
    if as_of - timedelta(days=ACTION_WINDOW_DAYS - 1) >= MIN_TRADE_DATE:
        past = {kind for ex, kind, accepted, _ in actions if ex <= as_of and accepted}
        out["dividend_365d"], out["bonus_365d"], out["split_365d"] = (k in past for k in ("DIVIDEND", "BONUS", "SPLIT"))
    future = [(ex, kind) for ex, kind, _, visible in actions if ex > as_of and visible]
    if future:
        nxt = min(ex for ex, _ in future)
        out["days_to_next_ex_date"] = (nxt - as_of).days
        out["next_ex_date_action"] = "+".join(sorted({k for ex, k in future if ex == nxt}))
    return out


def segment_inputs(con, as_of_ts: datetime, entities=None) -> dict[tuple[str, str], list[tuple]]:
    """(entity, scope) -> [(metric, period, months, key, label, value, member)] of BUSINESS SEGMENT members, point in
    time (the `load_segments` rule: per axis / element / period, every member of the latest visible filing), in a
    fixed order (metric, period, axis, element, member) so `segment_columns` never depends on the scan order."""
    only, only_p = entity_filter("entity_id", entities)
    out: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for ent, scope, metric, start, end, months, member, label, value, axis in con.execute(
        """SELECT entity_id, scope, canonical_metric, period_start, period_end, period_months, member, label, value_inr,
                  axis
           FROM segment_observations
           WHERE visible_from_ts <= ? AND axis_kind = 'BUSINESS' AND period_type = 'DURATION'
             AND member_role = 'SEGMENT' AND canonical_metric IN ('REVENUE', 'RESULT') AND """
        + SEGMENT_CURRENT_VERSION
        + only
        + """ QUALIFY dense_rank() OVER (
               PARTITION BY entity_id, scope, axis_kind, axis, element, period_start, period_end
               ORDER BY visible_from_ts DESC, filing_id DESC) = 1
           ORDER BY entity_id, scope, canonical_metric, period_end, period_start, axis, element, member""",
        [as_of_ts, *only_p],
    ).fetchall():
        out[(ent, scope)].append((metric, (start, end), months, (label or member.split(":")[-1]).strip().lower(),
                                  label or member.split(":")[-1], Decimal(value), (axis, member)))  # fmt: skip
    return out


def segment_columns(rows: list[tuple] | None) -> dict:
    out = dict.fromkeys(SEGMENT_COLUMNS)
    if not rows:
        return out
    # Segments are matched by filed label. Two members filed under one label (two "Others" lines) are one segment:
    # their values add up. A member reported twice (by two elements) counts once: the first row, in the fixed order
    # of `segment_inputs`. [Before: the last row of an unordered scan won, so the value depended on the scan.]
    members: dict[tuple, dict[tuple, dict]] = defaultdict(lambda: defaultdict(dict))
    labels: dict[tuple, str] = {}
    for metric, period, months, key, label, value, *member in rows:
        per = members[metric][(period, months, key)]
        per.setdefault(member[0] if member else key, value)
        labels.setdefault((period, months, key), label)
    rev: dict[tuple, dict[str, tuple[str, Decimal]]] = defaultdict(dict)
    res: dict[tuple, dict[str, Decimal]] = defaultdict(dict)
    for (period, months, key), per in members["REVENUE"].items():
        rev[(period, months)][key] = (labels[(period, months, key)], sum(per.values(), ZERO))
    for (period, months, key), per in members["RESULT"].items():
        res[(period, months)][key] = sum(per.values(), ZERO)
    if not rev:
        return out
    # latest period end; at that end the shortest period (the quarter of a quarterly filing, else the FY)
    (period, months) = max(rev, key=lambda pm: (pm[0][1], -pm[1]))
    now = rev[(period, months)]
    total = sum((v for _, v in now.values()), ZERO)
    out["segment_period_end"] = period[1]
    out["segment_count"] = len(now)
    largest = max(now, key=lambda k: (now[k][1], k))
    out["largest_segment_revenue_share"] = _f(safe_div(now[largest][1], total)) if total > 0 else None
    before_p = (_add_months(period[0], -12), _add_months(period[1], -12))
    before = rev.get((before_p, months), {})
    growth = {k: now[k][1] / before[k][1] - 1 for k in now if k in before and before[k][1] > 0}
    if growth:
        best = max(growth, key=lambda k: (growth[k], k))
        out["fastest_growing_segment"], out["fastest_growing_segment_growth_yoy"] = now[best][0], float(growth[best])
    m_now = safe_div(res.get((period, months), {}).get(largest), now[largest][1])
    m_before = safe_div(res.get((before_p, months), {}).get(largest), before.get(largest, (None, None))[1])
    if m_now is not None and m_before is not None and before[largest][1] > 0:
        out["largest_segment_margin_change_yoy_pp"] = float(m_now - m_before)
    return out


# ── stage 2: per row, then the day's cross-section ────────────────────────────────────────────────────────────────


def row_columns(row: dict, more: dict | None, hist: dict | None, bars, factors, frozen_from, index, events,
                actions, segments, prices=None) -> dict:  # fmt: skip
    out = dict.fromkeys(MORE_COLUMNS)
    more = more or {}
    out.update({k: v for k, v in more.items() if k in out})
    out["altman_z_original"] = _f(altman_z_original(more.get("_altman"), row.get("market_cap")))
    hist = hist or {}
    for col, src in PERCENTILES.items():
        out[col] = percentile_rank(_f(row.get(src)), hist.get(src, []))
    out |= (prices.more_price_columns(row, row["as_of_date"]) if prices is not None
            else price_columns(row, bars, factors, frozen_from, index))  # fmt: skip
    covered, inc_exc = events
    if covered:
        out["nifty500_inclusion_90d"], out["nifty500_exclusion_90d"] = inc_exc.get(row["security_id"], (False, False))
    out |= action_columns(actions or [], row["as_of_date"])
    out |= segment_columns(segments)
    if row.get("valuation_archetype") in FINANCIAL_ARCHETYPES:
        out.update(dict.fromkeys(INDUSTRIAL_ONLY))
    return out


def add_columns(con, rows: list[dict], as_of: date, as_of_ts: datetime, fundamentals: dict, factors, frozen,
                entities=None, exchange: str = "NSE", prices=None) -> None:  # fmt: skip
    """The features.compute_rows hook: batched reads, each row's columns, then the cross-section, in place. With the
    run's `price_history.PriceHistory` (`prices`) the price columns are sliced from it (the same values)."""
    from financials.features_price import index_closes

    secs = None if entities is None else {r["security_id"] for r in rows}
    hist = valuation_history(con, as_of, secs)
    bars = {} if prices is not None else load_bars(con, exchange, as_of, secs)
    index = prices.index if prices is not None else index_closes(con, as_of)
    events = index_events(con, as_of, secs)
    actions = action_inputs(con, as_of, as_of_ts, secs)
    segments = segment_inputs(con, as_of_ts, entities)
    for row in rows:
        ent, sec = row["entity_id"], row["security_id"]
        fund = fundamentals.get(ent) or {}
        row.update(row_columns(row, fund.get("_more"), hist.get(sec), bars.get(sec, []), factors.get(sec, []),
                               frozen.get(sec), index, events, actions.get(sec),
                               segments.get((ent, row.get("scope_used"))), prices))  # fmt: skip
    cross_section(rows)


def _representatives(rows: list[dict]) -> list[dict]:
    from financials.features_peers import _representatives

    return _representatives(rows)


def cross_section(rows: list[dict]) -> None:
    """rs_rank_12m_1m over every row with momentum; industry earnings breadth per NSE industry, in place."""
    mom = sorted(m for r in rows if (m := r.get("momentum_12m_1m")) is not None)
    n = len(mom)
    for r in rows:
        m = r.get("momentum_12m_1m")
        r["rs_rank_12m_1m"] = None if m is None or n < 2 else bisect.bisect_left(mom, m) / (n - 1)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in _representatives(rows):
        if r.get("nse_industry") is not None and r.get("core_profit_yoy_latest_q") is not None:
            groups[r["nse_industry"]].append(r)
    breadth: dict[str, tuple[float | None, int]] = {}
    for ind, members in groups.items():
        season = max(m["fundamentals_end"] for m in members if m.get("fundamentals_end") is not None) if any(
            m.get("fundamentals_end") is not None for m in members) else None  # fmt: skip
        current = [m for m in members if m.get("fundamentals_end") == season]
        k = len(current)
        breadth[ind] = (sum(1 for m in current if m["core_profit_yoy_latest_q"] > 0) / k if k >= MIN_PEERS else None, k)
    for r in rows:
        b = breadth.get(r.get("nse_industry"))
        r["industry_earnings_breadth"], r["industry_earnings_breadth_n"] = (None, None) if b is None else b


CROSS_INPUTS = ("security_id", "entity_id", "market_cap", "nse_industry", "core_profit_yoy_latest_q",
                "fundamentals_end", "momentum_12m_1m")  # fmt: skip


def refresh_cross_section(con, as_of: date) -> None:
    """Recompute CROSS_COLUMNS for every stored row of `as_of` (inside the materialize transaction, after the day's
    rows are written): one read, one UPDATE through Arrow."""
    import pyarrow as pa

    from financials.db import fetch_dicts

    rows = fetch_dicts(con, f"SELECT {', '.join(CROSS_INPUTS)} FROM screener_features_history WHERE as_of_date = ?",
                       [as_of])  # fmt: skip
    if not rows:
        return
    cross_section(rows)
    fields = [
        pa.field("security_id", pa.string()),
        pa.field("rs_rank_12m_1m", pa.float64()),
        pa.field("industry_earnings_breadth", pa.float64()),
        pa.field("industry_earnings_breadth_n", pa.int32()),
    ]
    table = pa.Table.from_pylist([{c: r[c] for c in ("security_id", *CROSS_COLUMNS)} for r in rows],
                                 schema=pa.schema(fields))  # fmt: skip
    con.register("_more_cross", table)
    try:
        sets = ", ".join(f"{c} = s.{c}" for c in CROSS_COLUMNS)
        con.execute(
            f"UPDATE screener_features_history h SET {sets} FROM _more_cross s "
            "WHERE h.as_of_date = ? AND h.security_id = s.security_id",
            [as_of],
        )
    finally:
        con.unregister("_more_cross")


# ── DSL ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def dsl_aliases() -> dict[str, tuple[str, str]]:
    """Screener-style names for every column of this module (fractions shown x100, flags 1/0)."""
    pp = "percentage points"
    out: dict[str, tuple[str, str]] = {
        "altman z original": ("altman_z_original", "x, 1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + Sales/TA"),
        "altman z score": ("altman_z_original", "x, original Z (manufacturers)"),
        "balance sheet accruals": ("(bs_accruals * 100)", "%, change in NOA / avg total assets, last FY"),
        "depreciation rate": ("(depreciation_rate * 100)", "%, FY D&A / avg gross block"),
        "asset age": ("(asset_age_proxy * 100)", "%, accumulated depreciation / gross block"),
        "change in debtor days": ("debtor_days_change_yoy", "days, last FY - preceding FY"),
        "change in cash conversion cycle": ("ccc_change_yoy", "days, last FY - preceding FY"),
        "debtor days half year": ("debtor_days_h1", "days, H1 balance sheet, H1 sales annualised"),
        "inventory days half year": ("inventory_days_h1", "days, H1 balance sheet, H1 COGS annualised"),
        "change in debtor days half year": ("debtor_days_h1_change_yoy", "days, vs the H1 a year earlier"),
        "change in inventory days half year": ("inventory_days_h1_change_yoy", "days, vs the H1 a year earlier"),
        "pb percentile": ("(pb_percentile * 100)", "percentile of own prior quarter-ends"),
        "price to sales percentile": ("(price_to_sales_percentile * 100)", "percentile of own prior quarter-ends"),
        "ev to sales percentile": ("(ev_to_sales_percentile * 100)", "percentile of own prior quarter-ends"),
        "momentum 12m 1m": ("(momentum_12m_1m * 100)", "%, 12-month return excluding the last month"),
        "rs rank": ("(rs_rank_12m_1m * 100)", "percentile of 12M-1M momentum in the day's universe (100 = best)"),
        "volatility 1year": ("(volatility_1y * 100)", "%, annualised std of daily log returns"),
        "max drawdown 1year": ("(max_drawdown_1y * 100)", "%, worst fall from a running high (<= 0)"),
        "new high on delivery": ("CAST(high_52w_on_delivery_spike AS INTEGER)",
                                 "1/0, 52W high with delivery > 2x 20D median"),
        "days since half year balance sheet": ("date_diff('day', h1_bs_as_of, as_of_date)", "days"),
        "days since segment period": ("date_diff('day', segment_period_end, as_of_date)", "days"),
        "days since result event": ("date_diff('day', pead_event_date, as_of_date)", "days, PEAD event"),
        "nifty 500 inclusion 90days": ("CAST(nifty500_inclusion_90d AS INTEGER)", "1/0"),
        "nifty 500 exclusion 90days": ("CAST(nifty500_exclusion_90d AS INTEGER)", "1/0"),
        "days to next ex date": ("days_to_next_ex_date", "days, announced actions only"),
        "dividend in last 365 days": ("CAST(dividend_365d AS INTEGER)", "1/0, ex-date in the last 365 days"),
        "bonus in last 365 days": ("CAST(bonus_365d AS INTEGER)", "1/0, ex-date in the last 365 days"),
        "split in last 365 days": ("CAST(split_365d AS INTEGER)", "1/0, ex-date in the last 365 days"),
        "number of segments": ("segment_count", "count, reportable business segments"),
        "largest segment share": ("(largest_segment_revenue_share * 100)", "% of segment revenue"),
        "fastest segment growth": ("(fastest_growing_segment_growth_yoy * 100)", "% YoY, same period"),
        "segment margin change": ("(largest_segment_margin_change_yoy_pp * 100)", f"{pp}, largest segment"),
        "industry earnings breadth": ("(industry_earnings_breadth * 100)",
                                      "% of the NSE industry with core profit up YoY"),
        "industry earnings breadth count": ("industry_earnings_breadth_n", "companies measured"),
    }  # fmt: skip
    for k in BENEISH_KEYS:
        out[f"beneish {k.lower()}"] = (f"beneish_{k.lower()}", "x, Beneish index, last FY vs preceding FY")
    for s in PIOTROSKI_SIGNALS:
        out[f"piotroski {s.replace('_', ' ')}"] = (f"CAST(piotroski_{s} AS INTEGER)", "1/0, Piotroski test")
    for k in PEAD_DAYS:
        out[f"pead abnormal return t{k}"] = (f"(pead_ar_t{k} * 100)", "%, vs Nifty 500 since the pre-results close")
        out[f"pead relative volume t{k}"] = (f"pead_relvol_t{k}", "x, vs 20-bar mean volume before results")
    return out
