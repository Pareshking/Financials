"""Materialised `screener_features` (latest) and `screener_features_history` (one row per as_of_date).

Runs inside the single writer process. Gates (architecture §12):
- G4 null-spike: a critical column's null rate may not rise > 1.5 percentage points vs the previous run. A TTM
  value that turns NULL because the company filed a newer quarter whose 4-quarter window reaches before the
  financials cutoff (C9: never a partial window) is expected, not a defect, and is not counted (rule G4_C9_WINDOW).
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

from financials import features_bs, features_pl
from financials.corp_actions import ACCEPTED_STATUSES
from financials.db import insert_rows, table_columns, version_key
from financials.features_price import add_price_columns, refresh_breadth
from financials.fundamentals import (
    ANNUAL_COLUMNS,
    BANK_COLUMNS,
    CASH_CONVERSION_COLUMNS,
    CURRENT_VERSION,
    INSURER_COLUMNS,
    NBFC_COLUMNS,
    REVERSE_DCF_TERMINAL_G,
    REVERSE_DCF_WACC,
    SCREENER_CONVENTION_COLUMNS,
    _add_months,
    altman_z_double_prime,
    annual_ratios,
    bank_blocks,
    building_blocks,
    cash_conversion_blocks,
    clear_prefetch,
    entity_filter,
    in_list,
    insurer_basis,
    insurer_blocks,
    interest_coverage,
    load_factbook,
    nbfc_blocks,
    newgen_inputs,
    percentile_rank,
    prefetch_fundamentals,
    qoq_growth,
    quarter_opm,
    quarter_rev_ops,
    resolve_scope,
    reverse_dcf_implied_growth,
    safe_div,
    screener_convention_ratios,
    yoy_growth,
)
from financials.scope import MIN_PERIOD_END_DATE, MIN_TRADE_DATE
from financials.timeutil import ist_to_utc, utc_now

# Reader version of materialised rows. Bump it whenever features.py, fundamentals.py (or another file pinned by
# tests/test_incremental_materialize.py) changes any output: `materialize --incremental` refuses days built by another
# version, because only a full run then reproduces the history.
FEATURES_VERSION = "2026.11.15-6C"  # -2: X106 restatement TTM bridge + flag, X107 PDF corrections
# -3: QoQ sales / profit growth, NPM, interest coverage, OPM same quarter last year, dividend yield / payout,
#     promoter holding QoQ change (owner_requirements items 1, 3, 4)
# -4A: period P&L family (features_pl: quarter / fiscal-year lines, quarter YoY growth, result dates, history-gated
#     FY CAGR / median / averages), book value per share, trade-to-trade flag; opm_last_year_pct is now the last
#     fiscal year's OPM, the same-quarter value moved to opm_preceding_year_quarter_pct (ratio catalogue Batches 0-1)
# -4B: batch B price / volume / technicals (features_price.py) and the market_breadth table
# -5: batches A and B merged
# -6C: batch C balance sheet / working capital / cash flow / capital allocation (features_bs.py, ratio catalogue
#     Batches 2-3); `roa` is now also filled for industrial books

CRITICAL_COLUMNS = ("close", "market_cap", "sales_ttm", "pat_ttm", "total_equity")
G4_MAX_NULL_RISE = 0.015
TTM_COLUMNS = frozenset({"sales_ttm", "pat_ttm"})
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


def _universe(con, exchange: str, as_of: date, entities=None) -> list[tuple[str, str, str, str]]:
    """(security_id, entity_id, symbol, series) with a bar in the lookback window and a valid identifier."""
    only, only_p = entity_filter("s.entity_id", entities)
    return con.execute(
        """SELECT DISTINCT o.security_id, s.entity_id, h.symbol, h.series
           FROM ohlcv o JOIN securities s USING (security_id)
           JOIN security_identifier_history h
             ON h.security_id = o.security_id AND h.exchange = o.exchange
            AND h.valid_from <= ? AND (h.valid_to IS NULL OR h.valid_to > ?)
           WHERE o.exchange = ? AND o.trade_date <= ? AND o.trade_date > ?"""
        + only
        + " ORDER BY 1",
        [as_of, as_of, exchange, as_of, as_of - timedelta(days=UNIVERSE_LOOKBACK_DAYS), *only_p],
    ).fetchall()


def market_cap_shares(
    reg31: tuple[Decimal, date] | None,
    paid_up: tuple[Decimal, date] | None,
    factors: list[tuple[date, Decimal, Decimal]],
    as_of: date,
) -> tuple[Decimal | None, date | None, str | None]:
    """Share count for market cap, in order [X18, X53, X61]:
    1. the Reg. 31 total of the latest visible shareholding pattern (REG31);
    2. else the results filing's paid-up capital / face value (PAID_UP). The parser withholds it when no filed EPS
       implies a share count within 10x (Kotak Q2 FY27 tags FaceValue = 994.79: SHARES_FROM_PAID_UP_WITHHELD), so a
       withheld count never reaches here; promotion cross-checks it against Reg. 31 (> 0.5% -> quarantine);
    3. then divided by the EPS factor of every accepted share-count action with ex-date in (count date, as_of]
       (a 1:5 split after the count multiplies shares by 5).
    Returns (shares, count date, source), all None when neither count exists."""
    if reg31 is not None:
        (shares, counted), source = reg31, "REG31"
    elif paid_up is not None:
        (shares, counted), source = paid_up, "PAID_UP"
    else:
        return None, None, None
    for ex, _, eps_factor in factors:
        if counted < ex <= as_of:
            shares = shares / eps_factor
    return shares, counted, source


KPI_COLUMNS = ("vnb_margin", "embedded_value", "ape_growth", "gov", "take_rate", "contribution_margin", "nrr",
               "cac_payback")  # fmt: skip
_KPI_RUPEES = ("embedded_value", "gov")


def supplemental_kpi_columns(con, as_of_ts: datetime, entities=None) -> dict[str, dict]:
    """Per entity: each KPI for its latest period visible at `as_of_ts`, latest visible version (one query)."""
    only, only_p = entity_filter("entity_id", entities)
    rows = con.execute(
        """SELECT entity_id, kpi, value FROM (
             SELECT *, row_number() OVER (PARTITION BY entity_id, kpi
                                          ORDER BY period_end DESC, visible_from_ts DESC) AS rn
             FROM supplemental_kpis WHERE visible_from_ts <= ?"""
        + only
        + ") WHERE rn = 1",
        [as_of_ts, *only_p],
    ).fetchall()
    out: dict[str, dict] = defaultdict(dict)
    for ent, kpi, value in rows:
        out[ent][kpi] = Decimal(value).quantize(Decimal("0.01")) if kpi in _KPI_RUPEES else float(value)
    return out


KNOWLEDGE_MODES = ("valid", "system")


def _price_inputs(
    con, exchange: str, as_of: date, knowledge: str = "valid", as_of_ts: datetime | None = None, securities=None
):
    """Bars, accepted price factors and the first unresolved gap per security, as of `as_of` [P0-4].

    knowledge="valid" (default, backtests): what the market knew on `as_of`. A corporate action counts from its
    ex-date (it is public by then), and a GAP finding freezes the series until it is resolved, whenever that
    happened: fixing our pipeline (an unparsed split, a missed action) is a correction, not new information.
    knowledge="system": what this system had decided by `as_of_ts` (audit of past live output). An action counts
    only once `decided_at <= as_of_ts`; a GAP finding freezes if created by then and not resolved by then.
    `securities` restricts every read to those securities (incremental materialisation; same values for them)."""
    if knowledge not in KNOWLEDGE_MODES:
        raise ValueError(f"knowledge must be one of {KNOWLEDGE_MODES}")
    system = knowledge == "system"
    if system and as_of_ts is None:
        raise ValueError("knowledge='system' needs as_of_ts")
    only, only_p = entity_filter("security_id", securities)
    bars: dict[str, list[tuple[date, Decimal, int | None]]] = defaultdict(list)
    for sec, d, close, deliv in con.execute(
        "SELECT security_id, trade_date, close, deliv_qty FROM ohlcv WHERE exchange = ? AND trade_date <= ?"
        + only
        + " ORDER BY security_id, trade_date",
        [exchange, as_of, *only_p],
    ).fetchall():
        bars[sec].append((d, close, deliv))
    factors: dict[str, list[tuple[date, Decimal, Decimal]]] = defaultdict(list)
    for sec, ex, pf, ef, status in con.execute(
        "SELECT security_id, ex_date, price_factor, eps_factor, status FROM corp_actions WHERE ex_date <= ?"
        + (" AND decided_at <= ?" if system else "")
        + only,
        ([as_of, as_of_ts] if system else [as_of]) + only_p,
    ).fetchall():
        if status in ACCEPTED_STATUSES and pf is not None:
            factors[sec].append((ex, Decimal(str(pf)), Decimal(str(ef if ef is not None else 1))))
    frozen = dict(
        con.execute(
            "SELECT security_id, min(CAST(json_extract_string(details, '$.trade_date') AS DATE)) FROM quarantine_queue "
            "WHERE stage = 'GAP' AND "
            + ("created_at <= ? AND (resolved_at IS NULL OR resolved_at > ?)" if system else "resolved_at IS NULL")
            + only
            + " GROUP BY security_id",
            ([as_of_ts, as_of_ts] if system else []) + only_p,
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


DIVIDEND_WINDOW_DAYS = 365


def _dividends(con, as_of: date, knowledge: str = "valid", as_of_ts: datetime | None = None, securities=None):
    """Cash dividends per share with ex-date in (as_of - 365 days, as_of]: exactly the ledger rows the total-return
    index adds (accepted DIVIDEND actions, `returns.total_return_index`), one batched query. knowledge="system" also
    needs the decision by `as_of_ts`, as for price factors (`_price_inputs`)."""
    system = knowledge == "system"
    only, only_p = entity_filter("security_id", securities)
    rows = con.execute(
        "SELECT security_id, ex_date, cash_per_share, status FROM corp_actions WHERE action_type = 'DIVIDEND' "
        "AND ex_date > ? AND ex_date <= ? AND cash_per_share IS NOT NULL"
        + (" AND decided_at <= ?" if system else "")
        + only,
        [as_of - timedelta(days=DIVIDEND_WINDOW_DAYS), as_of, *([as_of_ts] if system else []), *only_p],
    ).fetchall()
    out: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for sec, ex, cash, status in rows:
        if status in ACCEPTED_STATUSES:
            out[sec].append((ex, Decimal(cash)))
    return out


def trailing_dividend_per_share(
    dividends: list[tuple[date, Decimal]], factors: list[tuple[date, Decimal, Decimal]], as_of: date
) -> Decimal | None:
    """Sum of the trailing-365-day cash dividends per share, each restated to today's share basis: multiplied by the
    EPS (share-count) factor of every accepted action with ex-date in (dividend ex-date, as_of] (Rs 1 before a 1:1
    bonus is Rs 0.50 per share held today). NULL when the window starts before MIN_TRADE_DATE: no corporate actions
    are held before it, so the sum would be a partial window [C9]. 0 when no dividend went ex in the window."""
    if as_of - timedelta(days=DIVIDEND_WINDOW_DAYS - 1) < MIN_TRADE_DATE:
        return None
    total = Decimal(0)
    for ex, cash in dividends:
        f = Decimal(1)
        for fx, _, eps_factor in factors:
            if ex < fx <= as_of:
                f *= eps_factor
        total += cash * f
    return total


SHAREHOLDING_COLUMNS = (
    "promoter_holding_pct", "promoter_pledge_pct", "promoter_encumbered_pct", "fii_holding_pct",
    "fpi_holding_pct", "dii_holding_pct", "public_holding_pct", "non_promoter_non_public_pct",
    "fii_dii_qoq_change_pct", "promoter_holding_change_qoq_pp",
)  # fmt: skip


def _stated(cats: dict, cat: str) -> float | None:
    return _f(cats.get(cat, (None, None))[0])


def _quarter_before(d: date) -> date:
    """Quarter end immediately before quarter end `d` (2026-09-30 -> 2026-06-30, 2026-03-31 -> 2025-12-31)."""
    m = d.month - 2  # first day of the quarter's first month, minus one day
    return (date(d.year, m, 1) if m >= 1 else date(d.year - 1, m + 12, 1)) - timedelta(days=1)


def shareholding_columns(shp: dict) -> dict:
    """Reg. 31 holdings as filed fractions [SHP9]; pledge and encumbrance as fractions of promoter shares
    [SHP10]. fii_dii_qoq_change_pct needs the filing for the immediately preceding quarter end, both
    visible at the as-of; otherwise NULL (never a longer-gap change)."""
    out = dict.fromkeys(SHAREHOLDING_COLUMNS)
    if "TOTAL" not in shp:
        return out
    promoter_shares = shp.get("PROMOTER", (None, None))[1]

    def of_promoter(qty):
        if qty is None or promoter_shares is None or promoter_shares <= 0:
            return None
        return float(Decimal(qty) / Decimal(promoter_shares))

    fpi = [shp[c][0] for c in ("FPI_CAT1", "FPI_CAT2") if c in shp and shp[c][0] is not None]
    total, npnp = shp["TOTAL"][1], shp.get("NON_PROMOTER_NON_PUBLIC", (None, 0))[1] or 0
    out.update(
        promoter_holding_pct=_stated(shp, "PROMOTER"),
        promoter_pledge_pct=of_promoter(shp.get("_pledged")),
        promoter_encumbered_pct=of_promoter(shp.get("_encumbered")),
        fii_holding_pct=_stated(shp, "FII"),
        # FPI = Category I + II only; Institutions (Foreign) also holds FDI and overseas depositories [SHP13].
        fpi_holding_pct=float(sum(Decimal(str(x)) for x in fpi)) if fpi and "FII" in shp else None,
        dii_holding_pct=_stated(shp, "DII"),
        public_holding_pct=_stated(shp, "PUBLIC"),
        # Share of total issued shares (NPNP rows carry no filed percentage [SHP9]).
        non_promoter_non_public_pct=float(Decimal(npnp) / Decimal(total)) if total else None,
    )
    prev = shp.get("_prev", {})
    adjacent = shp.get("_prev_as_of") is not None and shp["_prev_as_of"] == _quarter_before(shp["_as_of"])
    now_inst = [_stated(shp, "FII"), _stated(shp, "DII")]
    prev_inst = [_stated(prev, "FII"), _stated(prev, "DII")]
    if adjacent and None not in now_inst + prev_inst:
        out["fii_dii_qoq_change_pct"] = round(sum(now_inst) - sum(prev_inst), 6)
    # Promoter & promoter group: filed fractions of the two latest visible quarters, immediately adjacent (as for
    # FII + DII); stored in percentage points (0.5011 -> 0.5007 is -0.04). Exact in Decimal, then one float.
    now_p, prev_p = shp.get("PROMOTER", (None, None))[0], prev.get("PROMOTER", (None, None))[0]
    if adjacent and now_p is not None and prev_p is not None:
        out["promoter_holding_change_qoq_pp"] = float((Decimal(str(now_p)) - Decimal(str(prev_p))) * 100)
    return out


EVENT_COLUMNS = (
    "order_wins_90d", "order_value_90d", "kmp_resignations_90d", "auditor_resignations_90d", "fraud_or_default_90d",
    "penalties_90d",
)  # fmt: skip


def _event_counts(con, as_of: date, as_of_ts: datetime, entities=None) -> dict[str, dict]:
    """Reg. 30 events [E3-E7] visible at the as-of and disclosed (DateOfReport) in the 90 days to as-of; one batched
    query. The disclosure date, not the effective date: a resignation effective next month is news today [E5].
    KMP resignations: Key Managerial Personnel or directors leaving by resignation; auditors are counted apart.
    penalties_90d stays NULL: no penalty / regulatory-action filing has been observed (UNVERIFIED [E7])."""
    only, only_p = entity_filter("entity_id", entities)
    rows = con.execute(
        """SELECT entity_id,
                  count(*) FILTER (WHERE event_type = 'ORDER_WIN'),
                  sum(amount_inr) FILTER (WHERE event_type = 'ORDER_WIN'),
                  count(*) FILTER (WHERE event_type = 'MANAGEMENT_CHANGE' AND cessation_category = 'Resignation'
                                   AND (person_category = 'Key Managerial Personnel'
                                        OR person_category ILIKE 'Director%')),
                  count(*) FILTER (WHERE event_type = 'AUDITOR_CHANGE' AND cessation_category = 'Resignation'),
                  count(*) FILTER (WHERE event_type = 'FRAUD_OR_DEFAULT')
           FROM corporate_events
           WHERE visible_from_ts <= ? AND report_date > ? AND report_date <= ?"""
        + only
        + " GROUP BY entity_id",
        [as_of_ts, as_of - timedelta(days=90), as_of, *only_p],
    ).fetchall()
    return {
        ent: {"order_wins_90d": wins, "order_value_90d": value, "kmp_resignations_90d": kmp,
              "auditor_resignations_90d": aud, "fraud_or_default_90d": fraud, "penalties_90d": None}
        for ent, wins, value, kmp, aud, fraud in rows
    }  # fmt: skip


def _preload(con, as_of_ts: datetime, entities=None):
    """Bulk point-in-time lookups keyed by entity (avoids per-security queries)."""
    only, only_p = entity_filter("entity_id", entities)
    # One filing per (entity, as_of): the latest visible revision. Then the two latest as_of dates
    # (the second feeds the quarter-on-quarter change).
    shp_rows = con.execute(
        """WITH f AS (
               SELECT entity_id, as_of_date, filing_id, parser_version FROM (
                   SELECT entity_id, as_of_date, filing_id, parser_version, row_number() OVER (
                       PARTITION BY entity_id, as_of_date ORDER BY visible_from_ts DESC, """
        + version_key()
        + """ DESC,
                       filing_id DESC) AS rn
                   FROM shareholding_meta WHERE visible_from_ts <= ?"""
        + only
        + """) WHERE rn = 1),
           r AS (SELECT *, row_number() OVER (PARTITION BY entity_id ORDER BY as_of_date DESC) AS r FROM f)
           SELECT r.entity_id, r.as_of_date, r.r, o.category, o.pct, o.shares,
                  m.promoter_pledged_shares, m.promoter_encumbered_shares
           FROM r JOIN shareholding_observations o USING (filing_id, parser_version)
           JOIN shareholding_meta m USING (filing_id, parser_version)
           WHERE r.r <= 2""",
        [as_of_ts, *only_p],
    ).fetchall()
    shp: dict[str, dict] = defaultdict(dict)
    for ent, d, rank, cat, pct, shares, pledged, encumbered in shp_rows:
        if rank == 1:
            shp[ent][cat] = (pct, shares)
            shp[ent]["_as_of"] = d
            shp[ent]["_pledged"], shp[ent]["_encumbered"] = pledged, encumbered
        else:
            shp[ent].setdefault("_prev", {})[cat] = (pct, shares)
            shp[ent]["_prev_as_of"] = d
    paid_up = dict(
        (ent, (Decimal(v), d))
        for ent, v, d in con.execute(
            """SELECT entity_id, arg_max(value_other, period_end), max(period_end) FROM fact_observations
               WHERE canonical_tag = 'shares_from_paid_up' AND visible_from_ts <= ?"""
            + only
            + " AND "
            + CURRENT_VERSION
            + " GROUP BY entity_id",
            [as_of_ts, *only_p],
        ).fetchall()
    )
    quarter_end = dict(
        con.execute(
            """SELECT entity_id, max(period_end) FROM fact_observations WHERE canonical_tag IN ('pat',
               'revenue_from_operations') AND period_type = 'DURATION' AND visible_from_ts <= ?"""
            + only
            + " AND "
            + CURRENT_VERSION
            + " GROUP BY entity_id",
            [as_of_ts, *only_p],
        ).fetchall()
    )
    return shp, paid_up, quarter_end


ARCHETYPES = ("INDUSTRIAL_SERVICES", "FINANCIAL_LENDING", "INSURANCE", "NEW_GEN_TECH")


def _curated_archetypes() -> dict[str, str]:
    """reference/valuation_archetypes.csv: symbols classified NEW_GEN_TECH by decision (C21); XBRL cannot tell."""
    import csv

    from financials.sources import ROOT

    path = ROOT / "reference" / "valuation_archetypes.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {r["symbol"]: r["valuation_archetype"] for r in csv.DictReader(fh)}


def derived_archetype(book) -> str:
    """Profile-derived archetype: insurers INSURANCE; banks and lending NBFCs FINANCIAL_LENDING; otherwise
    INDUSTRIAL_SERVICES (NEW_GEN_TECH only by the curated list or an override, C21)."""
    if insurer_basis(book) is not None:
        return "INSURANCE"
    if "interest_expended" in book.durations:
        return "FINANCIAL_LENDING"
    if "interest_earned" in book.durations:
        from financials.fundamentals import nbfc_blocks

        return "FINANCIAL_LENDING" if nbfc_blocks(book, max(e for (_, e) in book.durations["interest_earned"]))[
            "is_lending_nbfc"] else "INDUSTRIAL_SERVICES"  # fmt: skip
    return "INDUSTRIAL_SERVICES"


def _valuation_history(con, as_of: date, securities=None) -> dict[str, dict[str, list[float]]]:
    """Each security's PE and EV/EBITDA at the last materialised date of every prior quarter (one query) [C20],
    oldest quarter first (the 20-quarter band of G240 takes the last 20)."""
    only, only_p = entity_filter("security_id", securities)
    rows = con.execute(
        """SELECT security_id, date_trunc('quarter', as_of_date) AS q, arg_max(pe, as_of_date),
                  arg_max(ev_ebitda, as_of_date)
           FROM screener_features_history
           WHERE as_of_date < date_trunc('quarter', CAST(? AS DATE))"""
        + only
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        [as_of, *only_p],
    ).fetchall()
    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"pe": [], "ev_ebitda": []})
    for sec, _, pe, eve in rows:
        out[sec]["pe"].append(pe)
        out[sec]["ev_ebitda"].append(eve)
    return out


def compute_rows(
    con, as_of: date, exchange: str = "NSE", *, knowledge: str = "valid", entities: frozenset[str] | None = None
) -> list[dict]:
    """Feature rows for `as_of`. `knowledge` selects how price adjustments and gap freezes are read (see
    `_price_inputs`); materialised history always uses the default "valid" knowledge. `entities` computes only the
    rows of those entities' securities, through the same batched reads restricted to them: a row depends only on
    its own security's and entity's inputs (and its own earlier rows), so the rows are identical (§11.10)."""
    as_of_ts = ist_to_utc(as_of + timedelta(days=1), time(0, 0))  # end of as_of day, IST
    universe = _universe(con, exchange, as_of, entities)
    if entities is not None and not universe:
        return []
    secs = None if entities is None else {u[0] for u in universe}
    bars, factors, frozen = _price_inputs(con, exchange, as_of, knowledge, as_of_ts, secs)
    nifty = {
        s
        for (s,) in con.execute(
            "SELECT security_id FROM index_constituents_history WHERE index_name = 'NIFTY 500' AND valid_from <= ? "
            "AND (valid_to IS NULL OR valid_to > ?)",
            [as_of, as_of],
        ).fetchall()
    }
    shp_all, paid_up, quarter_end = _preload(con, as_of_ts, entities)
    dividends = _dividends(con, as_of, knowledge, as_of_ts, secs)
    events = _event_counts(con, as_of, as_of_ts, entities)
    kpis = supplemental_kpi_columns(con, as_of_ts, entities)
    history = _valuation_history(con, as_of, secs)
    curated = _curated_archetypes()
    arch_override = dict(con.execute("SELECT entity_id, valuation_archetype FROM entity_archetype_override").fetchall())
    fundamentals_cache: dict[str, dict] = {}
    rows = []
    prefetch_fundamentals(con, as_of_ts, entities)  # one pass instead of a per-entity scan [benchmarks]
    features_pl.prefetch(con, as_of_ts, entities)
    features_bs.prefetch(con, as_of_ts, entities)
    try:
        rows = _rows(con, as_of, as_of_ts, universe, bars, factors, frozen, nifty, shp_all, paid_up, quarter_end,
                     events, kpis, history, curated, arch_override, fundamentals_cache, dividends)  # fmt: skip
    finally:
        clear_prefetch(con, as_of_ts)
        features_pl.clear(con, as_of_ts)
        features_bs.clear(con, as_of_ts)
    add_price_columns(con, rows, as_of, exchange, factors, frozen, secs)  # batch B (price/technicals)
    return rows


def _rows(con, as_of, as_of_ts, universe, bars, factors, frozen, nifty, shp_all, paid_up, quarter_end, events, kpis,
          history, curated, arch_override, fundamentals_cache, dividends=None) -> list[dict]:  # fmt: skip
    rows = []
    for sec, ent, symbol, series in universe:
        b = bars.get(sec, [])
        price_date, close = (b[-1][0], b[-1][1]) if b else (None, None)
        row: dict = {
            "as_of_date": as_of, "security_id": sec, "entity_id": ent, "symbol": symbol, "series": series,
            "price_date": price_date, "close": close, "in_nifty500": sec in nifty,
        }  # fmt: skip
        # No event visible in the window = 0 (an absence of filings), except penalties (no verified source).
        row.update(
            events.get(ent) or {**dict.fromkeys(EVENT_COLUMNS, 0), "order_value_90d": None, "penalties_90d": None}
        )
        row.update(_momentum(b, factors.get(sec, []), frozen.get(sec)))
        row.update(_delivery(b))

        if ent not in fundamentals_cache:
            fundamentals_cache[ent] = (
                _fundamentals(con, ent, as_of_ts, quarter_end[ent]) if ent in quarter_end else _EMPTY_FUNDAMENTALS
            )
        fund = fundamentals_cache[ent]
        row.update({k: v for k, v in fund.items() if not k.startswith("_")})
        kp = kpis.get(ent, {})
        row.update({k: kp.get(k) for k in KPI_COLUMNS})
        for k in ("persistency_13m", "persistency_61m"):  # filed in XBRL [X62] wins; a loaded KPI only fills NULL
            if row.get(k) is None and k in kp:
                row[k] = kp[k]

        shp = shp_all.get(ent, {})
        reg31 = (Decimal(shp["TOTAL"][1]), shp["_as_of"]) if "TOTAL" in shp else None
        shares, _counted, source = market_cap_shares(reg31, paid_up.get(ent), factors.get(sec, []), as_of)
        mcap = close * shares if close is not None and shares is not None else None
        ev = (
            mcap + fund["_net_debt"] + (fund["_minority"] or 0)
            if mcap is not None and fund["_net_debt"] is not None and not fund.get("_lender")
            else None
        )
        row.update({
            "shares": None if shares is None else int(shares), "shares_source": source,
            "market_cap": None if mcap is None else mcap.quantize(Decimal("0.01")),
            "enterprise_value": None if ev is None else ev.quantize(Decimal("0.01")),
            "pe": _f(safe_div(mcap, fund["_pe_earnings"])),
            "eps_ttm": _eps(fund["_pat_owners_total"], shares),
            "eps_continuing_ttm": _eps(fund["_pe_earnings"], shares),
            "pb": _f(safe_div(mcap, fund["_equity_owners"])),
            "ev_ebitda": _f(safe_div(ev, fund["ebitda_ttm"])),
            "fcff_yield": _f(safe_div(fund["_fcff"], ev)),
            "promoter_pct": _f(shp.get("PROMOTER", (None, None))[0]),
            "fii_pct": _f(shp.get("FII", (None, None))[0]),
            "dii_pct": _f(shp.get("DII", (None, None))[0]),
            "shp_as_of": shp.get("_as_of"),
            **shareholding_columns(shp),
        })  # fmt: skip
        archetype = arch_override.get(ent) or (
            curated.get(symbol) if fund.get("_archetype") == "INDUSTRIAL_SERVICES" and symbol in curated else None
        ) or fund.get("_archetype")  # fmt: skip
        row["valuation_archetype"] = archetype
        if archetype in ("FINANCIAL_LENDING", "INSURANCE"):
            row["interest_coverage"] = None  # finance costs are the lender's cost of goods, not a solvency charge
        row.update(_dividend_columns((dividends or {}).get(sec, []), factors.get(sec, []), as_of, b,
                                     frozen.get(sec), row["eps_ttm"]))  # fmt: skip
        row.update(features_pl.row_columns(fund.get("_pl"), row, fund, factors.get(sec, []), as_of, shares, b,
                                           frozen.get(sec)))  # fmt: skip
        row.update(features_bs.row_columns(con, as_of_ts, fund.get("_bs"), row, factors.get(sec, []), as_of))  # batch C
        row.update(_newgen_columns(fund.get("_newgen"), mcap, ev, fund))
        hist = history.get(sec, {"pe": [], "ev_ebitda": []})
        fcff = _f(fund["_fcff"]) if fund["_fcff"] is not None else None
        implied_g = reverse_dcf_implied_growth(_f(ev), fcff) if ev is not None and not fund.get("_lender") else None
        row.update(
            {
                "pe_percentile": percentile_rank(row["pe"], hist["pe"]),
                "ev_ebitda_percentile": percentile_rank(row["ev_ebitda"], hist["ev_ebitda"]),
                "ev_ebitda_percentile_20q": percentile_rank(
                    row["ev_ebitda"], hist["ev_ebitda"][-20:], min_periods_required=20
                ),  # G240 5Y band (C9 gated)
                "reverse_dcf_implied_g": implied_g,
                "reverse_dcf_wacc_used": REVERSE_DCF_WACC if implied_g is not None else None,
                "reverse_dcf_terminal_g": REVERSE_DCF_TERMINAL_G if implied_g is not None else None,
            }
        )
        public = shp.get("PUBLIC", (None, None))[1]
        a5 = row["deliv_avg_5d"]
        row["float_turnover_pct"] = a5 / public * 100 if a5 is not None and public else None
        rows.append(row)
    return rows


_EMPTY_FUNDAMENTALS: dict = {
    "sales_ttm": None, "ebitda_ttm": None, "pat_ttm": None, "fcf_ttm": None, "net_debt": None,
    "total_equity": None, "opm": None, "sales_growth_yoy": None, "profit_growth_yoy": None, "roe": None,
    "roce": None, "roic": None, "croic": None, "debt_to_equity": None, "other_income_to_pbt": None,
    "altman_z_dd": None, "scope_used": None, "scope_reason": None, "restatement_suspected": None,
    "default_quarterly_scope": None, "default_annual_scope": None, "fundamentals_end": None, "bs_as_of": None,
    "cf_as_of": None,
    "_net_debt": None, "_fcff": None, "_pat_owners": None, "_pe_earnings": None, "_equity_owners": None,
    "_minority": None, "roe_continuing": None, "core_profit_ttm": None, "_pat_owners_total": None,
    "sales_growth_qoq_pct": None, "profit_growth_qoq_pct": None, "npm_pct": None, "interest_coverage": None,
    "opm_preceding_year_quarter_pct": None,
    **dict.fromkeys(NBFC_COLUMNS + BANK_COLUMNS + INSURER_COLUMNS + CASH_CONVERSION_COLUMNS + ANNUAL_COLUMNS
                  + SCREENER_CONVENTION_COLUMNS),
}  # fmt: skip

# Industrial ratios that do not apply to lenders (architecture §10): NULL for INDAS_NBFC books.
_NOT_FOR_LENDERS = (
    "ebitda_ttm", "opm", "roce", "roic", "croic", "debt_to_equity", "altman_z_dd", "fcf_ttm", *CASH_CONVERSION_COLUMNS,
    "interest_coverage", "opm_preceding_year_quarter_pct",
)  # fmt: skip


NEWGEN_COLUMNS = (
    "ev_to_gross_profit", "ex_cash_pe", "ev_to_billings", "ev_to_esop_adj_ebitda", "price_to_cfo", "rule_of_40",
    "billings_growth_pct", "neg_working_capital_float_pct", "net_burn_multiple", "cash_runway_months", "esop_adj_fcf",
    "liquid_cash",
)  # fmt: skip


def _dividend_columns(divs, factors, as_of: date, bars, frozen_from: date | None, eps) -> dict:
    """dividend_yield_pct = trailing dividends per share (today's share basis) / today's raw close; NULL while an
    unexplained gap freezes the series (a missed split would mis-state both). dividend_payout_pct = the same
    dividends / eps_ttm (owners' TTM profit per current share); NULL when EPS <= 0. Fractions, like OPM."""
    out = {"dividend_yield_pct": None, "dividend_payout_pct": None}
    if not bars or (frozen_from is not None and bars[-1][0] >= frozen_from):
        return out
    dps = trailing_dividend_per_share(divs, factors, as_of)
    if dps is None:
        return out
    out["dividend_yield_pct"] = _pos_div(dps, bars[-1][1])
    out["dividend_payout_pct"] = _pos_div(dps, eps)
    return out


def _pos_div(a, b):
    return _f(safe_div(a, b)) if b is not None and b > 0 else None


def _newgen_columns(ng: dict | None, mcap, ev, fund: dict) -> dict:
    """New-gen tech ratios [C21]; inputs from fundamentals.newgen_inputs, NULL for lenders and insurers."""
    out = dict.fromkeys(NEWGEN_COLUMNS)
    if not ng or fund.get("_lender"):
        return out
    out["ev_to_gross_profit"] = _pos_div(ev, fund.get("_gross_profit"))
    if mcap is not None and ng["liquid_cash"] is not None:
        out["ex_cash_pe"] = _pos_div(mcap - ng["liquid_cash"], ng["ex_cash_earnings"])
    out["ev_to_billings"] = _pos_div(ev, ng["billings_ttm"])
    out["ev_to_esop_adj_ebitda"] = _pos_div(ev, ng["esop_adj_ebitda"])
    out["price_to_cfo"] = _pos_div(mcap, fund.get("_cfo"))
    for k in ("rule_of_40", "billings_growth_pct", "neg_working_capital_float_pct", "net_burn_multiple",
              "cash_runway_months"):  # fmt: skip
        out[k] = _f(ng[k])
    out["esop_adj_fcf"] = ng["esop_adj_fcf"]
    out["liquid_cash"] = ng["liquid_cash"]
    return out


def _eps(profit: Decimal | None, shares: Decimal | None) -> Decimal | None:
    if profit is None or not shares:
        return None
    return (profit / shares).quantize(Decimal("0.0001"))


def _fundamentals(con, entity_id: str, as_of_ts: datetime, end: date) -> dict:
    empty = dict(_EMPTY_FUNDAMENTALS)
    decision = resolve_scope(con, entity_id, as_of_ts, end)  # one scope per row, never mixed [C18]
    if decision is None:
        return {**empty, "fundamentals_end": end}
    scope, book = decision.scope, decision.book
    scope_cols = {
        "scope_reason": decision.reason,
        "restatement_suspected": decision.book.restatement_suspected(end),
        "default_quarterly_scope": decision.policy.default_quarterly_scope,
        "default_annual_scope": decision.policy.default_annual_scope,
    }
    b = building_blocks(book, end)
    eq, debt = b["total_equity"], b["total_debt"]
    capital = eq + debt if eq is not None and debt is not None else None
    regulatory = None
    if scope == "CONSOLIDATED" and "interest_expended" in book.durations:
        regulatory = load_factbook(con, entity_id, "STANDALONE", as_of_ts)  # standalone disclosures [X60]
    cash = {k: _f(v) for k, v in cash_conversion_blocks(book, end, b).items()}
    scope_cols["_archetype"] = derived_archetype(book)
    # Annual-statement ratios [C23]: industrial books only (Piotroski/Beneish are not defined for lenders/insurers).
    industrial = scope_cols["_archetype"] == "INDUSTRIAL_SERVICES"
    annual = annual_ratios(book, end) | screener_convention_ratios(book, end) if industrial else {}
    keep = ("annual_fy_end", "piotroski_f", "working_capital")  # date, integer, rupees (DECIMAL)
    scope_cols |= {k: (v if k in keep else _f(v)) for k, v in annual.items()}
    if annual.get("working_capital") is not None:
        scope_cols["working_capital"] = annual["working_capital"].quantize(Decimal("0.01"))
    scope_cols["_newgen"] = newgen_inputs(book, end, b)
    scope_cols["_gross_profit"] = b["gross_profit"]
    scope_cols["_cfo"] = b["cfo"]
    out = scope_cols | cash | _lender_columns(book, end, regulatory) | _insurer_columns(book, end) | {
        "sales_ttm": b["rev_ops"], "ebitda_ttm": b["ebitda"], "pat_ttm": b["pat"], "fcf_ttm": b["fcf"],
        "net_debt": b["net_debt"], "total_equity": eq,
        "opm": _f(safe_div(b["ebitda"], b["rev_ops"])),
        "sales_growth_yoy": _f(yoy_growth(book, "revenue_from_operations", end)),
        "profit_growth_yoy": _f(yoy_growth(book, "pat", end)),
        "roe": _f(safe_div(b["pat_owners"], b["equity_owners"])),
        "roce": _f(safe_div(b["ebit"], capital)),
        "roic": _f(safe_div(b["nopat"], b["avg_invested_capital"])),  # average IC [C16]
        "croic": _f(safe_div(b["fcf"], b["avg_invested_capital"])),  # average IC, like ROIC [C16]
        "debt_to_equity": _f(safe_div(debt, eq)),
        "other_income_to_pbt": _f(safe_div(b["other_income"], b["pbt"])),
        "altman_z_dd": _f(altman_z_double_prime(b)),
        "scope_used": scope, "fundamentals_end": end, "bs_as_of": b["bs_as_of"], "cf_as_of": b["cf_as_of"],
        "_net_debt": b["net_debt"], "_fcff": b["fcff"], "_pat_owners": b["pat_owners"],
        "_pe_earnings": b["pat_owners_continuing"], "_pat_owners_total": b["pat_owners"],
        "roe_continuing": _f(safe_div(b["pat_owners_continuing"], b["equity_owners"])),
        "core_profit_ttm": b["core_continuing_profit"],
        "_equity_owners": b["equity_owners"], "_minority": b["minority_interest"],
        **_quarterly_columns(book, end),
        "interest_coverage": _f(interest_coverage(b["pbt"], b["finance_costs"])),
    } | _lender_overrides(book, end)  # fmt: skip
    # NPM on the row's own sales (interest earned for banks, premium for insurers) and owners' TTM profit [X42]
    out["npm_pct"] = _f(safe_div(b["pat_owners"], out["sales_ttm"]))
    out["_pl"] = features_pl.period_values(con, book, end, as_of_ts)  # period P&L family (ratio catalogue Batch 1)
    out["_bs"] = features_bs.period_values(book, end, b)  # balance sheet / cash flow (ratio catalogue Batches 2-3)
    return out


def _sales_quarter(book, end: date) -> Decimal | None:
    """One quarter of the row's `sales_ttm` line: premium / insurance revenue for insurers, interest earned for banks
    (`_lender_overrides`), revenue from operations net of excise otherwise."""
    basis = insurer_basis(book)
    if basis is not None:
        return book.quarter("insurance_revenue" if basis == "INDAS117" else
                            "net_premium_earned" if basis == "IRDAI_GENERAL" else "net_premium", end)  # fmt: skip
    if "interest_expended" in book.durations:
        return book.quarter("interest_earned", end)
    return quarter_rev_ops(book, end)


def _quarterly_columns(book, end: date) -> dict:
    """Latest quarter vs the one before, same scope book (§6.4): sales and owners' profit (COALESCE(owners, PAT) per
    filing, as for PE [X42]); OPM of the same quarter a year earlier (opm_preceding_year_quarter_pct). NULL when a
    quarter is missing (never a longer-gap change) or the base is <= 0."""
    prev = _add_months(end, -3)
    owners = book.coalesced("pat_owners", "pat")
    return {
        "sales_growth_qoq_pct": _f(qoq_growth(_sales_quarter(book, end), _sales_quarter(book, prev))),
        "profit_growth_qoq_pct": _f(qoq_growth(book.quarter(owners, end), book.quarter(owners, prev))),
        "opm_preceding_year_quarter_pct": _f(quarter_opm(book, _add_months(end, -12))),
    }


_AMOUNTS = ("nii_ttm", "ppop_ttm", "loans", "net_premium_earned_ttm", "insurance_revenue_ttm", "investment_income_ttm")


def _lender_columns(book, end: date, regulatory=None) -> dict:
    """Lender columns: NBFC (Division III) or bank (RBI format); all NULL for other books."""
    nb = bank_blocks(book, end, regulatory) if "interest_expended" in book.durations else nbfc_blocks(book, end)
    nb = {k: nb.get(k) for k in NBFC_COLUMNS + BANK_COLUMNS} | {k: v for k, v in nb.items() if k.startswith("_")}
    return {k: (_f(v) if isinstance(v, Decimal) and k not in _AMOUNTS else v) for k, v in nb.items()}


def _insurer_columns(book, end: date) -> dict:
    ib = insurer_blocks(book, end)
    return {k: (_f(v) if isinstance(v, Decimal) and k not in _AMOUNTS else v) for k, v in ib.items()}


def _lender_overrides(book, end: date) -> dict:
    """Industrial ratios are NULL for lenders and insurers; `_lender` also suppresses EV in compute_rows."""
    from financials.fundamentals import insurer_basis

    basis = insurer_basis(book)
    if basis is not None:  # insurers: revenue = net premium earned (IRDAI) or insurance revenue (Ind AS 117)
        rev = book.ttm("insurance_revenue" if basis == "INDAS117" else
                       "net_premium_earned" if basis == "IRDAI_GENERAL" else "net_premium", end)  # fmt: skip
        return {**dict.fromkeys(_NOT_FOR_LENDERS), "_lender": True, "sales_ttm": rev}
    if "interest_earned" not in book.durations:
        return {}
    out = {**dict.fromkeys(_NOT_FOR_LENDERS), "_lender": True}
    if "interest_expended" in book.durations:  # banks: Screener's "Revenue" is interest earned [S4]
        out["sales_ttm"] = book.ttm("interest_earned", end)
    return out


def _null_rates(rows: list[dict], forgiven: set[tuple[str, str]] = frozenset()) -> dict[str, float]:
    n = len(rows) or 1
    return {
        c: sum(r.get(c) is None and (r["security_id"], c) not in forgiven for r in rows) / n for c in CRITICAL_COLUMNS
    }


def _window_reaches_before_cutoff(end: date | None) -> bool:
    """The 4-quarter window ending `end` starts with a quarter ending before MIN_PERIOD_END_DATE (C9)."""
    return end is not None and _add_months(end, -9) < MIN_PERIOD_END_DATE


def _c9_expected_nulls(con, prev: date, rows: list[dict]) -> set[tuple[str, str]]:
    """Rule G4_C9_WINDOW: (security, TTM column) pairs that were non-NULL on `prev` and are NULL now only because
    `fundamentals_end` moved to a newer quarter whose window needs pre-cutoff quarters. One query for all rows."""
    cols = ", ".join(f"{c} IS NULL" for c in sorted(TTM_COLUMNS))
    before = {r[0]: r[1:] for r in con.execute(
        f"SELECT security_id, fundamentals_end, {cols} FROM screener_features_history WHERE as_of_date = ?", [prev]
    ).fetchall()}  # fmt: skip
    out = set()
    for r in rows:
        b = before.get(r["security_id"])
        end = r.get("fundamentals_end")
        if b is None or b[0] is None or end is None or end <= b[0] or not _window_reaches_before_cutoff(end):
            continue
        for c, was_null in zip(sorted(TTM_COLUMNS), b[1:], strict=True):
            if r.get(c) is None and not was_null:
                out.add((r["security_id"], c))
    return out


def materialize(
    con, as_of: date, exchange: str = "NSE", *, entities: frozenset[str] | None = None
) -> MaterializeResult:
    """Compute, gate and atomically publish features for `as_of`. Caller must be the single writer.

    `entities` (incremental, §11.10): recompute only those entities' rows and merge them with the day's other rows
    already stored; G5 and G4 are then checked on the merged day, and only the recomputed rows are replaced."""
    rows = compute_rows(con, as_of, exchange, entities=entities)
    universe = _universe(con, exchange, as_of)
    merged = rows
    if entities is not None:
        recomputed = {r["security_id"] for r in rows}
        keep_cols = ["security_id", "entity_id", "fundamentals_end", *CRITICAL_COLUMNS, *sorted(TTM_COLUMNS)]
        cur = con.execute(
            f"SELECT {', '.join(dict.fromkeys(keep_cols))} FROM screener_features_history WHERE as_of_date = ?",
            [as_of],
        )
        names = [d[0] for d in cur.description]
        kept = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
        merged = [r for r in kept if r["entity_id"] not in entities and r["security_id"] not in recomputed] + rows
    if len(merged) != len(universe) or {r["security_id"] for r in merged} != {u[0] for u in universe} or not merged:
        return MaterializeResult("ABORTED", as_of, len(merged), "G5", f"{len(merged)} rows vs universe {len(universe)}")

    prev = con.execute(
        "SELECT max(as_of_date) FROM screener_features_history WHERE as_of_date < ?", [as_of]
    ).fetchone()[0]
    if prev is not None:
        cols = ", ".join(f"avg(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)" for c in CRITICAL_COLUMNS)
        before = dict(zip(CRITICAL_COLUMNS, con.execute(
            f"SELECT {cols} FROM screener_features_history WHERE as_of_date = ?", [prev]
        ).fetchone(), strict=True))  # fmt: skip
        now = _null_rates(merged, _c9_expected_nulls(con, prev, merged))
        spikes = {c: (before[c], now[c]) for c in CRITICAL_COLUMNS if now[c] - before[c] > G4_MAX_NULL_RISE}
        if spikes:
            return MaterializeResult("ABORTED", as_of, len(merged), "G4", f"null-rate spike vs {prev}: {spikes}")

    columns = table_columns(con, "screener_features_history")
    rows = [{c: r.get(c) for c in columns} for r in rows]
    con.execute("BEGIN TRANSACTION")
    try:
        if entities is None:
            con.execute("DELETE FROM screener_features_history WHERE as_of_date = ?", [as_of])
        else:
            by_ent, by_sec = in_list("entity_id", entities), in_list("security_id", {r["security_id"] for r in rows})
            con.execute(
                f"DELETE FROM screener_features_history WHERE as_of_date = ? AND ({by_ent[0]} OR {by_sec[0]})",
                [as_of, *by_ent[1], *by_sec[1]],
            )
        insert_rows(con, "screener_features_history", rows)
        refresh_breadth(con, as_of)  # batch B: market-level breadth from the day's stored rows
        latest = con.execute("SELECT max(as_of_date) FROM screener_features_history").fetchone()[0]
        if latest == as_of or entities is None:
            con.execute("DELETE FROM screener_features")
            con.execute("INSERT INTO screener_features SELECT * FROM screener_features_history WHERE as_of_date = ?",
                        [latest])  # fmt: skip
        con.execute(
            "INSERT OR REPLACE INTO features_meta VALUES (?, ?, ?, ?, ?)",
            [as_of, FEATURES_VERSION, "FULL" if entities is None else "INCREMENTAL", len(merged), utc_now()],
        )
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return MaterializeResult("PROMOTED", as_of, len(merged))


# ── incremental materialisation (§11.10) ──────────────────────────────────


@dataclass
class IncrementalResult:
    status: str  # DONE | NOTHING | REFUSED | ABORTED
    days: list[MaterializeResult]
    message: str = ""
    entities: int = 0  # distinct dirty entities consumed (FULL counts as one)


def version_mismatch(con) -> str | None:
    """None when every materialised day was built by FEATURES_VERSION; else why `--incremental` must not run."""
    rows = con.execute(
        """SELECT min(h.as_of_date), max(h.as_of_date), count(*), list(DISTINCT coalesce(m.features_version, 'unknown'))
           FROM (SELECT DISTINCT as_of_date FROM screener_features_history) h
           LEFT JOIN features_meta m USING (as_of_date)
           WHERE m.features_version IS DISTINCT FROM ?""",
        [FEATURES_VERSION],
    ).fetchone()
    if not rows[2]:
        return None
    return (
        f"{rows[2]} materialised day(s) {rows[0]}..{rows[1]} were built by features version {sorted(rows[3])}, the "
        f"code is {FEATURES_VERSION}: run a full `materialize --from {rows[0]} --to <last day>` instead"
    )


def _dirty_rows(con) -> list[tuple[str, str, date, str, str]]:
    return con.execute(
        "SELECT dirty_id, entity_id, from_date, reason, source_id FROM materialize_dirty ORDER BY from_date, dirty_id"
    ).fetchall()


def settle_dirty(con, rows, lo: date | None, hi: date | None) -> int:
    """After a successful run that recomputed, for every dirty entity in `rows`, every materialised day in [lo, hi]
    (None = unbounded): a marker whose from_date lies in [lo, hi] is consumed. When materialised days after `hi`
    exist, it moves to hi + 1 day (still stale there); otherwise it is deleted. Markers outside stay as they are.
    One transaction; returns the number of markers consumed."""
    from financials import dirty

    covered = [r for r in rows if (lo is None or r[2] >= lo) and (hi is None or r[2] <= hi)]
    if not covered:
        return 0
    later = (
        hi is not None
        and con.execute("SELECT count(*) FROM screener_features_history WHERE as_of_date > ?", [hi]).fetchone()[0] > 0
    )
    con.execute("BEGIN TRANSACTION")
    try:
        sql, params = in_list("dirty_id", {r[0] for r in covered})
        con.execute("DELETE FROM materialize_dirty WHERE " + sql, params)
        if later:
            for _, ent, _, reason, source in covered:
                dirty.mark(con, {ent: hi + timedelta(days=1)}, reason, source)
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return len(covered)


def settle_full_run(con, days: list[date]) -> int:
    """Markers consumed by a full materialisation of `days` (all entities): only when every materialised day in
    [min(days), max(days)] was among them. A marker dated after the last materialised day before min(days) (a
    weekend visibility, a holiday) has no stale day before min(days) either, so it counts as covered too."""
    if not days:
        return 0
    lo, hi = min(days), max(days)
    stored = {r[0] for r in con.execute(
        "SELECT DISTINCT as_of_date FROM screener_features_history WHERE as_of_date BETWEEN ? AND ?", [lo, hi]
    ).fetchall()}  # fmt: skip
    if not stored <= set(days):
        return 0
    prev = con.execute("SELECT max(as_of_date) FROM screener_features_history WHERE as_of_date < ?", [lo]).fetchone()[0]
    return settle_dirty(con, _dirty_rows(con), None if prev is None else prev + timedelta(days=1), hi)


def materialize_incremental(con, to: date | None = None, exchange: str = "NSE") -> IncrementalResult:
    """Recompute only the rows `materialize_dirty` marks, on every already-materialised day >= the earliest marker
    (<= `to`), ascending so each day's PE / EV-EBITDA percentile history sees the recomputed earlier days. Per day:
    the dirty entities whose from_date <= day (every entity if a FULL marker applies), one batched compute_rows,
    G5 and G4 on the merged day, atomic publish. Markers are consumed only after every day succeeded; a failed day
    stays as it was and the markers remain, so a rerun resumes. Refuses when any materialised day was built by
    another FEATURES_VERSION (reader rules changed: only a full run is equivalent)."""
    from financials.dirty import FULL

    msg = version_mismatch(con)
    if msg is not None:
        return IncrementalResult("REFUSED", [], msg)
    rows = _dirty_rows(con)
    if not rows:
        return IncrementalResult("NOTHING", [], "no dirty entities")
    if to is not None:
        rows = [r for r in rows if r[2] <= to]
        if not rows:
            return IncrementalResult("NOTHING", [], f"no dirty entities from on or before {to}")
    earliest = min(r[2] for r in rows)
    days = [d for (d,) in con.execute(
        "SELECT DISTINCT as_of_date FROM screener_features_history WHERE as_of_date >= ? AND as_of_date <= ? "
        "ORDER BY 1", [earliest, to or date.max]).fetchall()]  # fmt: skip
    results: list[MaterializeResult] = []
    for d in days:
        due = [r for r in rows if r[2] <= d]
        ents = None if any(r[1] == FULL for r in due) else frozenset(r[1] for r in due)
        r = materialize(con, d, exchange, entities=ents)
        results.append(r)
        if r.status != "PROMOTED":
            return IncrementalResult("ABORTED", results, f"{d}: {r.gate} {r.message}; dirty markers kept")
    settle_dirty(con, rows, None, to)
    return IncrementalResult("DONE", results, f"{len(days)} day(s)", len({r[1] for r in rows}))
