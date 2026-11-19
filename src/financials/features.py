"""Materialised `screener_features` (latest) and `screener_features_history` (one row per as_of_date; a view over
the event-sparse features_daily / features_events tables, features_store.py, architecture §4.1).

Runs inside the single writer process. Gates (architecture §12):
- G4 null-spike: a critical column's null rate may not rise > 1.5 percentage points vs the previous run. A TTM
  value that turns NULL because the company filed a newer quarter whose 4-quarter window reaches before the
  financials cutoff (C9: never a partial window) is expected, not a defect, and is not counted (rule G4_C9_WINDOW).
- G5 atomic swap: history rows for the date (features_store.write_day: the day's daily rows and the EVENT intervals
  it changes; on the last day of a run, the live table) are replaced in one transaction, only after the row count
  equals the universe size.

Prices: momentum uses back-adjusted closes (withheld after an unresolved gap); market cap uses the
raw close × share count rolled forward across later share-count actions (shares / eps_factor).
Fundamentals are read point-in-time at the end of `as_of_date` (IST).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from financials import (
    dirty,
    features_audit,
    features_bs,
    features_disclosures,
    features_extra,
    features_gems,
    features_more,
    features_peers,
    features_pl,
    features_rpt,
    features_store,
)
from financials.corp_actions import ACCEPTED_STATUSES
from financials.db import version_key
from financials.features_price import add_price_columns, refresh_breadth
from financials.fundamentals import (
    ANNUAL_COLUMNS,
    BANK_COLUMNS,
    CASH_CONVERSION_COLUMNS,
    CURRENT_VERSION,
    DQ_ATTRIBUTION,
    DQ_ATTRIBUTION_NCI,
    DQ_TAX_COPY,
    DQ_TTM_MISFILED,
    DQ_TTM_MIXED,
    DQ_YTD,
    INSURER_COLUMNS,
    NBFC_COLUMNS,
    RESTATEMENT_QUARTERS,
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
    nbfc_gearing,
    newgen_inputs,
    percentile_rank,
    prefetch_fundamentals,
    qoq_growth,
    quarter_opm,
    quarter_rev_ops,
    resolve_scope,
    reverse_dcf_implied_growth,
    roe_screener,
    safe_div,
    screener_convention_ratios,
    yoy_growth,
)
from financials.identity import UNIVERSE_SERIES
from financials.price_history import PriceHistory
from financials.price_history import legacy as legacy_materialize
from financials.run_memo import by_visibility, visibility_memo
from financials.scope import MIN_PERIOD_END_DATE, MIN_TRADE_DATE
from financials.timeutil import ist_to_utc, utc_now

# Reader version of materialised rows. Bump it whenever features.py, fundamentals.py (or another file pinned by
# tests/test_incremental_materialize.py) changes any output: `materialize --incremental` refuses days built by another
# version, because only a full run then reproduces the history.
FEATURES_VERSION = "2026.11.19-21L"  # -2: X106 restatement TTM bridge + flag, X107 PDF corrections
# -21A: core profit (fundamentals._core) quantized to the paisa (Arrow decimal256 on the expanded universe)
# -21B: gate G4 compares only securities present on the previous day (rule G4_NEW_ENTRANT; output unchanged)
# -21C: X173 YTD copies of a quarter withheld (TTM sums the quarters); X194 roce_screener needs positive capital
# -21D: X221 SHARES_REG31_OUTLIER (market cap uses NSE Issue Size when Reg. 31 alone disagrees; owner decision S)
# -21E: X226 no YTD bridge on a proven mis-filed YTD; X227 roe_screener; X228 NBFC debt/equity
# -21F: X250 segment features skip unallocated / elimination / total members; X260 rounding-only YTD bound
# -21G: X273 fixed-asset lines of a year end from one filing (decision T)
# -21H: X293 owners profit of a quarter derived from the owners YTD before falling back to total PAT
# -21I: X300 operating lines bridge through the YTD; X301 no mixed-basis bridge (4-quarter sum), owners TTM guarded
# -21J: X314 NBFC net fair-value line side (revenue break closed, quarters summed); X315 YTD copies prior year
# -21K: QS2 incremental speed-up (run-scoped slices, visibility memo, unchanged days skipped); same rows
# -21L: X334 IGAAP_CORP is its own accounting basis (QG Indian GAAP SME-era results)
# -3: QoQ sales / profit growth, NPM, interest coverage, OPM same quarter last year, dividend yield / payout,
#     promoter holding QoQ change (owner_requirements items 1, 3, 4)
# -4A: period P&L family (features_pl: quarter / fiscal-year lines, quarter YoY growth, result dates, history-gated
#     FY CAGR / median / averages), book value per share, trade-to-trade flag; opm_last_year_pct is now the last
#     fiscal year's OPM, the same-quarter value moved to opm_preceding_year_quarter_pct (ratio catalogue Batches 0-1)
# -4B: batch B price / volume / technicals (features_price.py) and the market_breadth table
# -5: batches A and B merged
# -6C: batch C balance sheet / working capital / cash flow / capital allocation (features_bs.py, ratio catalogue
#     Batches 2-3); `roa` is now also filled for industrial books
# -6D: batch D ownership (FII / DII / MF change QoQ, shareholder counts, insurance / retail holding) and hidden-gem
#      signals, hats and cross-sectional scores (features_gems.py, docs/hidden_gems.md)
# -7: batches C and D merged
# -8E: restatement_suspected also on discontinued operations and a logged merger / demerger (X108, X109)
# -8H: batch H industry / peers (features_peers.py): NSE 4-level classification (PIT from its first fetch), industry
#      and basic-industry medians of PE / PB / ROCE / sales growth, premiums, peer ranks; industry_group_* fallback
# -9: batches E and H merged
# -8G: batch G remaining Phase 2 ratios (features_extra.py: margin acceleration, cost shares, perimeter, leakage,
#      absorption, KPI valuation, Reg. 30 red flags, raw numerators / denominators)
# -10: batch G merged with E and H
# -11I: batch I last catalogue rows (features_more.py: Beneish / Piotroski components, original Altman Z, accruals,
#       depreciation rate, days changes, PB / P/S / EV/S percentiles, RS rank, volatility, drawdown, PEAD, index and
#       corporate-action recency, segment mix, industry earnings breadth)
# -12J: batch J related-party leak (features_rpt.py: rpt_leak_pct, purchases / royalty to sales, loans given to net
#       worth, from the Reg. 34 related-party schedule [X113])
# -12K: batch K per-share PDF corrections (fact_corrections.value_other: EPS / face value ranked like rupee
#       corrections in the FactBook and in the EPS result-date visibility of features_pl)
# -13: batches J and K merged
# -14P: run-level materialisation (price_history.py, FundamentalsCache; architecture §11.11): identical rows, version
#       bumped because the pinned files changed
# -15P: deterministic reads that depended on DuckDB's scan order (found by scripts/compare_materialize.py on the live
#       database): paid-up share count (latest period end, STANDALONE first, count > 0), segment members sharing a
#       label add up, audit-opinion ties broken by filing_id
# -16S: storage (architecture §4.1): a run rewrites the live screener_features table once, in its last day's
#       transaction (materialize_days), instead of every day; identical rows, bumped because features.py changed
# -17E: event-sparse history (features_store.py, architecture §4.1): screener_features_history is a view over
#       features_daily (DAILY columns, every day) and features_events (EVENT columns, one row per interval of identical
#       values); identical rows, bumped because the pinned files changed
# -18D: disclosure_facts columns (features_disclosures.py): insider receivables (X117), Reg. 31 declarations (X118),
#       Schedule III subsidiary contribution (X119)
# -20A: audit-opinion columns from audit_opinions (features_audit.py, X121-X124: the auditor's report text and the
#       Integrated Filing audit fields); rf_audit_qualified and forensic_clean read them (text, not the checkbox)

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
    snapshot_due: bool = False  # published with snapshot=False although the live table would have been rewritten


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


# Rule SHARES_REG31_OUTLIER [X221] (owner decision S, 2026-11-18): when the results filing and NSE agree and Reg. 31
# does not, use NSE's count. Same 0.5% tolerance as the share cross-check (promoter.SHARE_CROSS_CHECK_TOLERANCE, X18,
# X133): on the snapshot of 2026-11-17, where paid-up / face value agrees with Issue Size, |Reg. 31 / Issue Size - 1|
# is <= 0.5% on 578,285 of 590,011 rows and the remainder spreads evenly to > 5% (no second mode to put a wider bar
# at); paid-up stated in rounded lakhs or crores (TCS) stays inside 0.5%.
SHARES_REG31_OUTLIER_TOLERANCE = Decimal("0.005")
ISSUE_SIZE_MAX_AGE_DAYS = 14  # PR-zip mcap files are weekly (gaps of 5 to 9 days between files) plus quarter ends


def reg31_outlier(
    reg31: tuple[Decimal, date] | None,
    paid_up: tuple[Decimal, date] | None,
    issue: tuple[Decimal, date] | None,
    factors: list[tuple[date, Decimal, Decimal]],
    *,
    partly_paid: bool = False,
    entity_listings: int = 1,
    trust_shares: Decimal | None = None,
) -> str | None:
    """Rule SHARES_REG31_OUTLIER [X221]: compare the three share counts visible at as-of, the Reg. 31 total (pattern
    date R), the results filing's paid-up / face value (period end P) and NSE's Issue Size (latest PR-zip mcap file,
    trade date I). "REG31_OUTLIER" when Reg. 31 differs from Issue Size by more than the tolerance while paid-up /
    face value agrees with it; "ALL_DIFFER" when no two of the three agree (keep Reg. 31: HMT, and the share cross-
    check keeps its CROSS_CHECK_FAILED finding open, Reg. 31 vs paid-up of the same date); None otherwise. Compared
    only like with like: P == R (the results speak to the pattern's own date; a later allotment explains a Reg. 31
    pattern newer than the results, an earlier one a stale pattern), no accepted share-count action with ex-date in
    (R, I] (Issue Size moves on the ex-date), no partly-paid shares (Reg. 31 counts them, NSE lists them as a
    separate security, paid-up / face value is not a share count [X18]) and one listed EQ / BE / BZ security of the
    entity in the file (a Reg. 31 total of two listed classes is not one Issue Size). A Reg. 31 total that agrees
    with paid-up / face value once employee-trust shares are deducted (X103: treasury shares, out of share capital,
    in the total and listed) is explained, never an outlier."""
    if reg31 is None or paid_up is None or issue is None or partly_paid or entity_listings != 1:
        return None
    (r, r_date), (p, p_date), (i, i_date) = reg31, paid_up, issue
    if p_date != r_date or not r or not i or any(r_date < ex <= i_date for ex, _, _ in factors):
        return None
    tol = SHARES_REG31_OUTLIER_TOLERANCE
    if abs(r - i) <= tol * i or any(abs(t - p) <= tol * p for t in (r, r - (trust_shares or 0))):
        return None  # agrees with NSE, or with the results (Issue Size lags an allotment or a buy-back, X133)
    return "REG31_OUTLIER" if abs(p - i) <= tol * i else "ALL_DIFFER"


def _trust_shares(shp: dict) -> Decimal | None:
    t = shp.get("EMPLOYEE_TRUSTS", (None, None))[1]
    return None if t is None else Decimal(t)


def market_cap_shares(
    reg31: tuple[Decimal, date] | None,
    paid_up: tuple[Decimal, date] | None,
    factors: list[tuple[date, Decimal, Decimal]],
    as_of: date,
    issue: tuple[Decimal, date] | None = None,
    *,
    partly_paid: bool = False,
    entity_listings: int = 1,
    trust_shares: Decimal | None = None,
) -> tuple[Decimal | None, date | None, str | None]:
    """Share count for market cap, in order [X18, X53, X61, X221]:
    1. the Reg. 31 total of the latest visible shareholding pattern (REG31), unless rule SHARES_REG31_OUTLIER
       (`reg31_outlier`) finds it the outlier against NSE's Issue Size and the results' paid-up / face value of the
       same date: then the Issue Size (ISSUE_SIZE);
    2. else the results filing's paid-up capital / face value (PAID_UP). The parser withholds it when no filed EPS
       implies a share count within 10x (Kotak Q2 FY27 tags FaceValue = 994.79: SHARES_FROM_PAID_UP_WITHHELD), so a
       withheld count never reaches here; promotion cross-checks it against Reg. 31 (> 0.5% -> quarantine);
    3. then divided by the EPS factor of every accepted share-count action with ex-date in (count date, as_of]
       (a 1:5 split after the count multiplies shares by 5).
    `issue` is (Issue Size, file trade date), already limited to ISSUE_SIZE_MAX_AGE_DAYS before as_of.
    Returns (shares, count date, source), all None when neither count exists."""
    if reg31 is not None:
        verdict = reg31_outlier(reg31, paid_up, issue, factors, partly_paid=partly_paid,
                                entity_listings=entity_listings, trust_shares=trust_shares)  # fmt: skip
        if verdict == "REG31_OUTLIER":
            (shares, counted), source = issue, "ISSUE_SIZE"
        else:
            (shares, counted), source = reg31, "REG31"
    elif paid_up is not None:
        (shares, counted), source = paid_up, "PAID_UP"
    else:
        return None, None, None
    for ex, _, eps_factor in factors:
        if counted < ex <= as_of:
            shares = shares / eps_factor
    return shares, counted, source


def issue_sizes(con, as_of: date, exchange: str = "NSE", entities=None) -> dict[str, tuple[Decimal, date, int]]:
    """Per security: (Issue Size, trade date, listed EQ / BE / BZ securities of its entity in that file) of the latest
    PR-zip mcap file [X130-X133] with trade date in (as_of - ISSUE_SIZE_MAX_AGE_DAYS, as_of]. The file of a trade
    date is published after the close of that day (EOD_RULE), as the day's bars. One query (no per-security read);
    of several fetches of one trade date the latest fetched file is read, as in `universe.issue_size_check`."""
    only, only_p = entity_filter("s.entity_id", entities)
    rows = con.execute(
        """WITH f AS (
             SELECT m.trade_date, arg_max(m.filing_id, (fi.fetched_at, m.filing_id)) AS filing_id
             FROM (SELECT DISTINCT trade_date, filing_id FROM raw_nse_mcap
                   WHERE exchange = ? AND trade_date <= ? AND trade_date > ?) m
             JOIN filings fi USING (filing_id) GROUP BY 1),
           r AS (
             SELECT h.security_id, s.entity_id, m.trade_date, m.issue_size
             FROM raw_nse_mcap m JOIN f USING (trade_date, filing_id)
             JOIN security_identifier_history h ON h.exchange = m.exchange AND h.symbol = m.symbol
                  AND h.series = m.series AND h.valid_from <= m.trade_date
                  AND (h.valid_to IS NULL OR h.valid_to > m.trade_date)
             JOIN securities s ON s.security_id = h.security_id
             WHERE m.series IN (SELECT unnest(?))"""
        + only
        + """ QUALIFY row_number() OVER (PARTITION BY h.security_id ORDER BY m.trade_date DESC) = 1)
           SELECT security_id, trade_date, issue_size, count(*) OVER (PARTITION BY entity_id, trade_date) FROM r""",
        [exchange, as_of, as_of - timedelta(days=ISSUE_SIZE_MAX_AGE_DAYS), sorted(UNIVERSE_SERIES), *only_p],
    ).fetchall()
    return {sec: (Decimal(n), d, listings) for sec, d, n, listings in rows}


KPI_COLUMNS = ("vnb_margin", "embedded_value", "ape_growth", "gov", "take_rate", "contribution_margin", "nrr",
               "cac_payback")  # fmt: skip
_KPI_RUPEES = ("embedded_value", "gov")


@by_visibility  # read once per visibility interval of an incremental run (run_memo)
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


@by_visibility  # read once per visibility interval of an incremental run (run_memo)
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
                  m.promoter_pledged_shares, m.promoter_encumbered_shares, m.has_partly_paid
           FROM r JOIN shareholding_observations o USING (filing_id, parser_version)
           JOIN shareholding_meta m USING (filing_id, parser_version)
           WHERE r.r <= 2""",
        [as_of_ts, *only_p],
    ).fetchall()
    shp: dict[str, dict] = defaultdict(dict)
    for ent, d, rank, cat, pct, shares, pledged, encumbered, partly_paid in shp_rows:
        if rank == 1:
            shp[ent][cat] = (pct, shares)
            shp[ent]["_as_of"] = d
            shp[ent]["_pledged"], shp[ent]["_encumbered"] = pledged, encumbered
            shp[ent]["_partly_paid"] = bool(partly_paid)
        else:
            shp[ent].setdefault("_prev", {})[cat] = (pct, shares)
            shp[ent]["_prev_as_of"] = d
    paid_up = dict(
        (ent, (Decimal(v), d))
        for ent, v, d in con.execute(
            # Latest period end; at one end the STANDALONE count (the issuer's own share capital; consolidated and
            # standalone filings of one quarter can differ in the rounding of the capital), then the latest visible,
            # then filing_id: a deterministic pick (an unbroken tie took whichever row the scan met). A count <= 0 is
            # not a share count (a consolidated filing tagged paid-up capital 0): never used.
            """SELECT entity_id, arg_max(value_other, (period_end, scope = 'STANDALONE', visible_from_ts, filing_id)),
                      max(period_end) FROM fact_observations
               WHERE canonical_tag = 'shares_from_paid_up' AND value_other > 0 AND visible_from_ts <= ?"""
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
           FROM features_daily
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
    con,
    as_of: date,
    exchange: str = "NSE",
    *,
    knowledge: str = "valid",
    entities: frozenset[str] | None = None,
    prices: PriceHistory | None = None,
) -> list[dict]:
    """Feature rows for `as_of`. `knowledge` selects how price adjustments and gap freezes are read (see
    `_price_inputs`); materialised history always uses the default "valid" knowledge. `entities` computes only the
    rows of those entities' securities, through the same batched reads restricted to them: a row depends only on
    its own security's and entity's inputs (and its own earlier rows), so the rows are identical (§11.10).

    Price columns ("valid" knowledge) come from a `PriceHistory` (read once per run, sliced per day; `prices`, or one
    read here for this day); FINANCIALS_MATERIALIZE_LEGACY=1 (and knowledge="system") re-read and recompute the
    whole history per day instead. Both give identical rows (tests/test_materialize_fast_path.py)."""
    as_of_ts = ist_to_utc(as_of + timedelta(days=1), time(0, 0))  # end of as_of day, IST
    universe = _universe(con, exchange, as_of, entities)
    if entities is not None and not universe:
        return []
    secs = None if entities is None else {u[0] for u in universe}
    if knowledge != "valid" or legacy_materialize():
        prices = None
        bars, factors, frozen = _price_inputs(con, exchange, as_of, knowledge, as_of_ts, secs)
    else:
        if prices is None or not prices.covers(exchange, as_of):
            prices = PriceHistory(con, exchange, as_of, secs)
        bars, factors, frozen = prices.inputs(as_of, secs)
    nifty = {
        s
        for (s,) in con.execute(
            "SELECT security_id FROM index_constituents_history WHERE index_name = 'NIFTY 500' AND valid_from <= ? "
            "AND (valid_to IS NULL OR valid_to > ?)",
            [as_of, as_of],
        ).fetchall()
    }
    shp_all, paid_up, quarter_end = _preload(con, as_of_ts, entities)
    issues = issue_sizes(con, as_of, exchange, entities)  # rule SHARES_REG31_OUTLIER [X221]
    dividends = _dividends(con, as_of, knowledge, as_of_ts, secs)
    events = _event_counts(con, as_of, as_of_ts, entities)
    findings = open_findings(con, as_of_ts, entities)  # X325 OPEN_FINDING flags
    kpis = supplemental_kpi_columns(con, as_of_ts, entities)
    run_cache = prices.fundamentals if prices is not None else None
    if run_cache is not None:  # one read per quarter of the run (it reads only days before the quarter)
        history = run_cache.per_quarter("valuation", as_of, secs, lambda: _valuation_history(con, as_of, secs))
    else:
        history = _valuation_history(con, as_of, secs)
    curated = _curated_archetypes()
    arch_override = dict(con.execute("SELECT entity_id, valuation_archetype FROM entity_archetype_override").fetchall())
    fundamentals_cache: dict[str, dict] = {}
    rows = []
    keys: dict[str, tuple] = {}
    stale = entities
    if run_cache is not None:  # reuse the entities' blocks of an earlier day of the run when no input changed
        keys = {e: run_cache.key(e, as_of, as_of_ts, quarter_end[e]) for (_, e, _, _) in universe if e in quarter_end}
        fundamentals_cache.update(run_cache.hits(keys))
        stale = frozenset(keys.keys() - fundamentals_cache.keys())
    if stale is None or stale:  # nothing to prefetch when every entity's block is reused
        prefetch_fundamentals(con, as_of_ts, stale)  # one pass instead of a per-entity scan [benchmarks]
        features_pl.prefetch(con, as_of_ts, stale)
    features_bs.prefetch(con, as_of_ts, entities)
    try:
        rows = _rows(con, as_of, as_of_ts, universe, bars, factors, frozen, nifty, shp_all, paid_up, quarter_end,
                     events, kpis, history, curated, arch_override, fundamentals_cache, dividends, prices,
                     issues, findings)  # fmt: skip
        if run_cache is not None:
            run_cache.store({e: (k, fundamentals_cache[e]) for e, k in keys.items() if e in stale})
    finally:
        clear_prefetch(con, as_of_ts)
        features_pl.clear(con, as_of_ts)
        features_bs.clear(con, as_of_ts)
    add_price_columns(con, rows, as_of, exchange, factors, frozen, secs, prices)  # batch B (price/technicals)
    features_audit.add_columns(con, rows, as_of_ts, entities)  # 20A (audit opinions, X121; before forensic_clean)
    features_gems.add_columns(con, rows, as_of, as_of_ts, fundamentals_cache, entities)  # batch D (hidden gems)
    features_peers.add_columns(con, rows, as_of, as_of_ts, entities)  # batch H (industry / peers)
    features_extra.add_columns(con, rows, as_of, as_of_ts, fundamentals_cache, factors, entities)  # batch G
    features_more.add_columns(
        con, rows, as_of, as_of_ts, fundamentals_cache, factors, frozen, entities, prices=prices
    )  # batch I
    features_rpt.add_columns(con, rows, as_of_ts, entities)  # batch J (related-party leak, X113)
    features_disclosures.add_columns(con, rows, as_of_ts, entities)  # 18D (disclosure_facts, X116-X119)
    return rows


def _rows(con, as_of, as_of_ts, universe, bars, factors, frozen, nifty, shp_all, paid_up, quarter_end, events, kpis,
          history, curated, arch_override, fundamentals_cache, dividends=None, prices=None,
          issues=None, findings=None) -> list[dict]:  # fmt: skip
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
        row.update(prices.momentum(sec, as_of) if prices else _momentum(b, factors.get(sec, []), frozen.get(sec)))
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
        iss = (issues or {}).get(sec)
        shares, _counted, source = market_cap_shares(
            reg31, paid_up.get(ent), factors.get(sec, []), as_of, None if iss is None else iss[:2],
            partly_paid=shp.get("_partly_paid", False), entity_listings=1 if iss is None else iss[2],
            trust_shares=_trust_shares(shp),
        )  # fmt: skip
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
        row.update(dq_columns(fund, (findings or {}).get(ent, ()), frozen.get(sec), as_of))
        rows.append(row)
    return rows


# X325 (rule SHOW_AND_FLAG, owner decision V): an open finding flags the rows whose fundamentals window it concerns.
# The window is the restatement window (fundamentals.RESTATEMENT_QUARTERS: the 4 TTM quarters and the year-ago
# quarter they are compared with), on the row's scope when the finding names one.
DQ_FINDING_MONTHS = 3 * RESTATEMENT_QUARTERS
DQ_PRICE_GAP = "PRICE_GAP_UNRESOLVED"  # an open GAP finding freezes the back-adjusted series (returns stay NULL)
DQ_CODES = (DQ_ATTRIBUTION, DQ_ATTRIBUTION_NCI, DQ_YTD, DQ_TAX_COPY, DQ_TTM_MISFILED, DQ_TTM_MIXED, DQ_PRICE_GAP)
# Reasons of the non-blocking findings that carry an entity (the DSL names one alias per reason; a flag is written
# for any open entity finding, named or not).
DQ_FINDING_REASONS = (
    "YTD_QUARTER_MISMATCH", "ANNUAL_PRIOR_YEAR_DIFFERS", "ATTRIBUTION_WITHHELD", "CROSS_CHECK_FAILED",
    "ANNUAL_SHARE_COUNT_DIFFERS", "TAX_COPIED_FROM_PRIOR_YEAR",
)  # fmt: skip


def open_findings(con, as_of_ts: datetime, entities=None) -> dict[str, list[tuple[str, str | None, date | None]]]:
    """X325: open (unresolved) findings attributed to an entity, as (reason_code, scope or None, period end), whose
    filing (if any) is visible at `as_of_ts`. The period end is the finding's own period (YTD period, period,
    share-count date) or its filing's period end. Read with today's resolution state ("valid" knowledge, as the GAP
    freeze and PDF corrections): a finding resolved later flags no as-of date, an open one flags every as-of date
    from its filing's visibility, so a rebuilt history shows what is known now about each date's filings."""
    only, params = entity_filter("q.entity_id", entities)
    out: dict[str, list] = defaultdict(list)
    for ent, reason, scope, end in con.execute(
        "SELECT q.entity_id, q.reason_code, coalesce(json_extract_string(q.details, '$.scope'), fm.scope), "
        + dirty.FINDING_PERIOD_END_SQL
        + " FROM quarantine_queue q "
        + dirty.FINDING_FILING_JOIN
        + " WHERE "
        + dirty.OPEN_ENTITY_FINDING
        + " AND (q.filing_id IS NULL OR fm.vis <= ?)"
        + only
        + " ORDER BY 1, 2, 3, 4",
        [as_of_ts, *params],
    ).fetchall():
        out[ent].append((reason, scope, end))
    return out


def dq_columns(fund: dict, findings, frozen_from: date | None, as_of: date) -> dict:
    """X325: `dq_flags` = sorted, comma-separated codes of the row (NULL when none); `dq_suspect` = any flag.
    Codes: the as-filed values the fundamentals block used (fundamentals.DQ_*), OPEN_FINDING:<reason> for each open
    finding of the entity whose period end lies in the row's window (on the row's scope when the finding names
    one), PRICE_GAP_UNRESOLVED while an open GAP finding freezes the price series."""
    codes = set(fund.get("_dq", ()))
    end, scope = fund.get("fundamentals_end"), fund.get("scope_used")
    for reason, f_scope, f_end in findings:
        if f_end is None or end is None or not (_add_months(end, -DQ_FINDING_MONTHS) < f_end <= end):
            continue
        if f_scope is not None and scope is not None and f_scope != scope:
            continue
        codes.add(f"OPEN_FINDING:{reason}")
    if frozen_from is not None and frozen_from <= as_of:
        codes.add(DQ_PRICE_GAP)
    return {"dq_suspect": bool(codes), "dq_flags": ",".join(sorted(codes)) or None}


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
    "opm_preceding_year_quarter_pct": None, "roe_screener": None,
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
    book.fill_as_filed = True  # X325 SHOW_AND_FLAG: validated values first, else as filed (flagged in book.dq)
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
        "roe_screener": _f(roe_screener(book, end)),  # X227: Screener's FY ROE on average equity, beside `roe`
        "core_profit_ttm": b["core_continuing_profit"],
        "_equity_owners": b["equity_owners"], "_minority": b["minority_interest"],
        **_quarterly_columns(book, end),
        "interest_coverage": _f(interest_coverage(b["pbt"], b["finance_costs"])),
    } | _lender_overrides(book, end)  # fmt: skip
    if out.get("is_lending_nbfc") is True and "interest_expended" not in book.durations:
        out["debt_to_equity"] = _f(nbfc_gearing(book, end))  # X228: NBFC gearing; banks and insurers stay NULL
    # NPM on the row's own sales (interest earned for banks, premium for insurers) and owners' TTM profit [X42]
    out["npm_pct"] = _f(safe_div(b["pat_owners"], out["sales_ttm"]))
    out["_pl"] = features_pl.period_values(con, book, end, as_of_ts)  # period P&L family (ratio catalogue Batch 1)
    out["_bs"] = features_bs.period_values(book, end, b)  # balance sheet / cash flow (ratio catalogue Batches 2-3)
    out["_gems"] = features_gems.period_values(book, end, b)  # batch D: core profit, TTM core earnings, stability
    out["_extra"] = features_extra.period_values(con, book, end, b, as_of_ts)  # batch G (remaining Phase 2 ratios)
    out["_more"] = features_more.period_values(book, end, b, industrial)  # batch I (last catalogue rows)
    out["_dq"] = tuple(sorted(book.dq))  # X325: as-filed values this block used
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


def _g4_compared_rows(con, prev: date, rows: list[dict]) -> list[dict]:
    """Rule G4_NEW_ENTRANT: the null-rate gate compares like with like, the securities that also had a row on `prev`.
    A security first trading today (an IPO, or 156 Permitted BSE-listed securities on 2026-04-20) brings its own NULLs
    (no fundamentals yet); that is new coverage, not lost coverage. With no overlap at all, every row counts."""
    before = {r[0] for r in con.execute(
        "SELECT security_id FROM screener_features_history WHERE as_of_date = ?", [prev]
    ).fetchall()}  # fmt: skip
    return [r for r in rows if r["security_id"] in before] or rows


def materialize(
    con,
    as_of: date,
    exchange: str = "NSE",
    *,
    entities: frozenset[str] | None = None,
    prices: PriceHistory | None = None,
    snapshot: bool = True,
    snapshot_due: bool = False,
    rows: list[dict] | None = None,
) -> MaterializeResult:
    """Compute, gate and atomically publish features for `as_of`. Caller must be the single writer.

    `entities` (incremental, §11.10): recompute only those entities' rows and merge them with the day's other rows
    already stored; G5 and G4 are then checked on the merged day, and only the recomputed rows are replaced.
    `prices`: the run's PriceHistory (`materialize_run`), so a multi-day run reads the bars once.
    `snapshot=False` (every day of a run but the last, `materialize_days`): the live `screener_features` table is not
    rewritten; the result's `snapshot_due` says whether it would have been. `snapshot_due=True` (the run's last day):
    an earlier day of the run deferred it, so this day's transaction rewrites it in any case (architecture §11.11).
    `rows`: the day's rows already computed by `compute_rows` with the same `entities` (`materialize_incremental`)."""
    if rows is None:
        rows = compute_rows(con, as_of, exchange, entities=entities, prices=prices)
        if prices is not None:
            prices.settle()
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

    prev = con.execute("SELECT max(as_of_date) FROM features_daily WHERE as_of_date < ?", [as_of]).fetchone()[0]
    if prev is not None:
        cols = ", ".join(f"avg(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)" for c in CRITICAL_COLUMNS)
        before = dict(zip(CRITICAL_COLUMNS, con.execute(
            f"SELECT {cols} FROM screener_features_history WHERE as_of_date = ?", [prev]
        ).fetchone(), strict=True))  # fmt: skip
        same = _g4_compared_rows(con, prev, merged)
        now = _null_rates(same, _c9_expected_nulls(con, prev, same))
        spikes = {c: (before[c], now[c]) for c in CRITICAL_COLUMNS if now[c] - before[c] > G4_MAX_NULL_RISE}
        if spikes:
            return MaterializeResult("ABORTED", as_of, len(merged), "G4", f"null-rate spike vs {prev}: {spikes}")

    rows = [{c: r.get(c) for c in features_store.COLUMNS} for r in rows]
    con.execute("BEGIN TRANSACTION")
    try:
        features_store.write_day(con, as_of, rows, entities=entities)  # event-sparse (architecture §4.1)
        refresh_breadth(con, as_of)  # batch B: market-level breadth from the day's stored rows
        features_gems.refresh_cross_section(con, as_of)  # batch D: ranks / scores / hats over the stored day
        features_peers.refresh_cross_section(con, as_of)  # batch H: industry medians / peer ranks over the stored day
        features_more.refresh_cross_section(con, as_of)  # batch I: RS rank / industry earnings breadth
        latest = con.execute("SELECT max(as_of_date) FROM features_daily").fetchone()[0]
        due = latest == as_of or entities is None
        if snapshot and (due or snapshot_due):
            _write_snapshot(con)
        con.execute(
            "INSERT OR REPLACE INTO features_meta VALUES (?, ?, ?, ?, ?)",
            [as_of, FEATURES_VERSION, "FULL" if entities is None else "INCREMENTAL", len(merged), utc_now()],
        )
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return MaterializeResult("PROMOTED", as_of, len(merged), snapshot_due=due and not snapshot)


def _write_snapshot(con) -> None:
    """The live table = the latest materialised day of the history (inside the caller's transaction)."""
    con.execute("DELETE FROM screener_features")
    con.execute("INSERT INTO screener_features BY NAME SELECT * FROM screener_features_history WHERE as_of_date = "
                "(SELECT max(as_of_date) FROM features_daily)")  # fmt: skip


def publish_snapshot(con) -> None:
    """Rewrite the live table from the latest materialised day in its own transaction (a run that stopped early)."""
    con.execute("BEGIN TRANSACTION")
    try:
        _write_snapshot(con)
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def materialize_days(
    con,
    days,
    exchange: str = "NSE",
    *,
    prices: PriceHistory | None = None,
    entities_for=None,
    report=None,
) -> list[MaterializeResult]:
    """`materialize` each of `days` in order (one run: `materialize --from/--to`, `--incremental`, `rebuild-market`),
    stopping at the first day that does not publish. The live `screener_features` table is rewritten once, in the
    transaction of the run's last day (architecture §11.11): rewriting it every day only replaced it with the same
    latest day again and left the deleted copies as dead blocks in the file. When the run stops early (a failed
    gate, an error) after a day that deferred it, it is rewritten on its own, so the tables end exactly as the
    day-by-day publish left them. `entities_for(day)`: the entities to recompute on that day (None = all);
    `report(result)`: called after each day."""
    days = list(days)
    results: list[MaterializeResult] = []
    due = False
    try:
        for i, d in enumerate(days):
            ents = entities_for(d) if entities_for is not None else None
            r = materialize(con, d, exchange, entities=ents, prices=prices, snapshot=i == len(days) - 1,
                            snapshot_due=due)  # fmt: skip
            results.append(r)
            if report is not None:
                report(r)
            if r.status != "PROMOTED":
                break
            due = (due or r.snapshot_due) and i < len(days) - 1  # the last day's transaction wrote it
    finally:
        if due:  # the last day did not publish (or raised): the days before it did, as day-by-day would have shown
            publish_snapshot(con)
    return results


class FundamentalsCache:
    """Per-entity fundamental blocks (`_fundamentals`: the scope decision, TTM / annual / lender / insurer ratios and
    the period values of features_pl / _bs / _gems / _extra / _more) reused across the days of one materialize run
    while none of the entity's inputs changes (architecture §11.11).

    `_fundamentals(con, e, as_of_ts, end)` reads, for entity e, only rows filtered `visible_from_ts <= as_of_ts`
    (fact_observations, filing_meta; fact_corrections through their filing's visibility; the features_pl result
    dates), MERGER / DEMERGER ledger rows with ex_date <= as_of (the restatement flag, X109) and the static
    entity_scope_override; `end` (the latest visible quarter) is read the same way. Nothing else of the as-of enters
    it. A run does not change those tables, so between two days the block can only change when one of e's
    visibility timestamps or structural ex-dates falls in between: the key is (end, number of e's visibility
    timestamps <= as_of_ts, number of its structural ex-dates <= as_of), from one read of the event dates for the
    run. A day recomputes (and prefetches) only the entities whose key moved; everything that depends on the price,
    the share count or the day (market cap, PE, yields, percentiles, ranks) is computed from the block every day."""

    def __init__(self, con, through: date, entities=None) -> None:
        import bisect

        from financials.fundamentals import _CURRENT_FILING, _structural_actions

        self._bisect = bisect.bisect_right
        through_ts = ist_to_utc(through + timedelta(days=1), time(0, 0))
        only, only_p = entity_filter("entity_id", entities)
        vis: dict[str, list[datetime]] = defaultdict(list)
        for ent, ts in con.execute(
            "SELECT DISTINCT entity_id, ts FROM ("
            "SELECT entity_id, visible_from_ts AS ts FROM fact_observations UNION ALL "
            "SELECT entity_id, visible_from_ts FROM filing_meta UNION ALL "
            "SELECT c.entity_id, m.vis FROM fact_corrections c JOIN " + _CURRENT_FILING + " m USING (filing_id)) "
            "WHERE ts <= ?" + only + " ORDER BY 1, 2",
            [through_ts, *only_p],
        ).fetchall():
            vis[ent].append(ts)
        self._vis = dict(vis)
        structural = _structural_actions(con, through_ts, only.replace("entity_id", "e"), only_p)
        self._structural = {e: [d for d, _ in v] for e, v in structural.items()}
        self._blocks: dict[str, tuple[tuple, dict]] = {}
        self._quarterly: dict[tuple, object] = {}

    def key(self, entity_id: str, as_of: date, as_of_ts: datetime, end: date) -> tuple:
        return (end, self._bisect(self._vis.get(entity_id, ()), as_of_ts),
                self._bisect(self._structural.get(entity_id, ()), as_of))  # fmt: skip

    def hits(self, keys: dict[str, tuple]) -> dict[str, dict]:
        out = {}
        for e, k in keys.items():
            cached = self._blocks.get(e)
            if cached is not None and cached[0] == k:
                out[e] = cached[1]
        return out

    def store(self, blocks: dict[str, tuple[tuple, dict]]) -> None:
        self._blocks.update(blocks)

    def per_quarter(self, name: str, as_of: date, securities, read):
        """`read()` once per (name, calendar quarter of as_of, securities) in the run, for the valuation-history
        reads (`_valuation_history`, `features_more.valuation_history`): they read only stored days before the
        quarter of as_of. A run materialises its days ascending and writes only the day it publishes, so those
        days are final before the run's first day of the quarter reads them. The result is shared: read only."""
        key = (name, date(as_of.year, 3 * ((as_of.month - 1) // 3) + 1, 1),
               None if securities is None else frozenset(securities))  # fmt: skip
        if key not in self._quarterly:
            self._quarterly[key] = read()
        return self._quarterly[key]


# Checkpoint threshold for the length of a materialize run. Each day commits ~30 MB of WAL (the day's rows and the
# cross-section updates); at DuckDB's default 16 MB every commit checkpointed, rewriting the history table's open
# row groups: ~3-4 s of a 4-5 s day. Storage only: the rows and the per-day atomic publish are unchanged.
RUN_CHECKPOINT_THRESHOLD = "512MB"


@contextmanager
def materialize_run(con, days, exchange: str = "NSE", entities=None) -> Iterator[PriceHistory | None]:
    """The state shared by the days of one run (`materialize --from/--to`, `--incremental`, `rebuild-market`;
    architecture §11.11): yields a PriceHistory read through the last day (restricted to the securities of `entities`
    when given) carrying the run's FundamentalsCache, its heap frozen for the run (`PriceHistory.frozen_heap`); None
    on the legacy per-day path (FINANCIALS_MATERIALIZE_LEGACY=1) or without days. Raises DuckDB's checkpoint
    threshold for the run (RUN_CHECKPOINT_THRESHOLD) and checkpoints at the end."""
    old = con.execute("SELECT current_setting('checkpoint_threshold')").fetchone()[0]
    con.execute(f"SET checkpoint_threshold = '{RUN_CHECKPOINT_THRESHOLD}'")
    done = False
    try:
        if legacy_materialize() or not days:
            yield None
        else:
            secs = None
            if entities is not None:
                sql, params = in_list("entity_id", entities)
                secs = {s for (s,) in con.execute("SELECT security_id FROM securities WHERE " + sql, params).fetchall()}
            prices = PriceHistory(con, exchange, max(days), secs)
            if len(days) > 1:  # nothing to reuse within one day
                prices.fundamentals = FundamentalsCache(con, max(days), entities)
            with prices.frozen_heap():
                yield prices
        done = True
    finally:
        con.execute(f"SET checkpoint_threshold = '{old}'")
        if done and len(days) > 1:  # a run ends checkpointed (one day: DuckDB's usual threshold decides)
            con.execute("CHECKPOINT")


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
           FROM (SELECT DISTINCT as_of_date FROM features_daily) h
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
        and con.execute("SELECT count(*) FROM features_daily WHERE as_of_date > ?", [hi]).fetchone()[0] > 0
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
        "SELECT DISTINCT as_of_date FROM features_daily WHERE as_of_date BETWEEN ? AND ?", [lo, hi]
    ).fetchall()}  # fmt: skip
    if not stored <= set(days):
        return 0
    prev = con.execute("SELECT max(as_of_date) FROM features_daily WHERE as_of_date < ?", [lo]).fetchone()[0]
    last = con.execute("SELECT max(as_of_date) FROM features_daily").fetchone()[0]
    if prev is None and last is not None and last <= hi:  # X325: every stored row now reflects today's findings
        dirty.store_finding_state(con)
    return settle_dirty(con, _dirty_rows(con), None if prev is None else prev + timedelta(days=1), hi)


# Tables that compute_rows (and the run's FundamentalsCache) reads only for the requested entities: every read is
# restricted by an entity_id filter, or reaches rows through the filing_id of such rows (current parser version,
# the filing's basis, its REG34_ANNUAL profile, the disclosure / RPT denominators of the same filing). An
# incremental run reads them through run-scoped slices (`entity_slices`).
SLICED_TABLES = (
    "filing_meta", "fact_observations", "fact_corrections", "disclosure_facts", "segment_observations",
    "related_party_transactions", "audit_opinions", "shareholding_meta", "shareholding_observations",
    "shareholding_line_items", "shareholding_major_holders",
)  # fmt: skip
_VISIBLE = frozenset(SLICED_TABLES) - {"fact_corrections"}  # with a visible_from_ts (corrections: their filing's)


@contextmanager
def entity_slices(con, entities) -> Iterator[None]:
    """Run-scoped slices of SLICED_TABLES for an incremental run over `entities` (architecture §11.10): a TEMP table
    of the same name holding every row of those entities plus every row of a filing any of them has a row in (so a
    filing whose versions moved between entities, X83, keeps all its versions). DuckDB resolves an unqualified name
    to the temp table first, so compute_rows reads the slice; its reads are restricted to the same entities, so they
    return exactly the rows they return from the full tables, from a few thousand rows instead of millions (each of
    a day's ~60 reads used to scan the full table: a fixed ~0.6 s a day whatever the number of entities). Nothing
    in the run writes these tables (the run writes only the feature tables). The slices are dropped when the run
    ends, by their catalog-qualified name. While they are held fixed, the run's visibility memo (`run_memo`) is
    active: a reader that depends on the as-of only through visibility is read once per visibility interval.
    `entities=None` (a FULL marker): no slices, no memo."""
    if entities is None:
        yield
        return
    db = con.execute("SELECT current_database()").fetchone()[0].replace('"', '""')
    sql, params = in_list("entity_id", entities)
    created: list[str] = []
    try:
        con.execute(
            "CREATE TEMP TABLE _slice_filings AS SELECT DISTINCT filing_id FROM ("
            + " UNION ALL ".join(f'SELECT filing_id FROM "{db}".main.{t} WHERE {sql}' for t in SLICED_TABLES)
            + ")",
            params * len(SLICED_TABLES),
        )
        created.append("_slice_filings")
        for t in SLICED_TABLES:
            con.execute(
                f'CREATE TEMP TABLE {t} AS SELECT * FROM "{db}".main.{t} '
                f"WHERE {sql} OR filing_id IN (SELECT filing_id FROM temp.main._slice_filings)",
                params,
            )
            created.append(t)
        # Per entity, every visibility timestamp the run's readers filter on (run_memo): of its rows in the slices,
        # of the other rows of its filings, of its KPIs.
        own = " UNION ".join(f"SELECT entity_id, filing_id FROM temp.main.{t}" for t in SLICED_TABLES)
        stamps: dict[str, list[datetime]] = defaultdict(list)
        for ent, ts in con.execute(
            f"WITH fe AS (SELECT DISTINCT entity_id, filing_id FROM ({own}) WHERE {sql}) "
            + " UNION ".join(
                f"SELECT entity_id, visible_from_ts FROM temp.main.{t} WHERE {sql} UNION "
                f"SELECT fe.entity_id, x.visible_from_ts FROM temp.main.{t} x JOIN fe USING (filing_id)"
                for t in SLICED_TABLES
                if t in _VISIBLE
            )
            + f' UNION SELECT entity_id, visible_from_ts FROM "{db}".main.supplemental_kpis WHERE {sql}',
            params * (2 + len(_VISIBLE)),
        ).fetchall():
            stamps[ent].append(ts)
        with visibility_memo(con, stamps):
            yield
    finally:
        for t in reversed(created):
            con.execute(f"DROP TABLE IF EXISTS temp.main.{t}")


PUBLISHED = ("PROMOTED", "UNCHANGED")  # day statuses of a successful incremental run
# Columns set by the cross-section refresh after a day's rows are written (from the day's stored rows): never
# computed by compute_rows, so not compared.
_CROSS = (
    frozenset(features_gems.CROSS_COLUMNS)
    | frozenset(features_peers.CROSS_COLUMNS)
    | frozenset(features_more.CROSS_COLUMNS)
)


class _StoredRows:
    """The stored rows an incremental run may replace, for `equal`: the daily rows of the run's entities and their
    securities, read in chunks of STORED_CHUNK_DAYS days, and those securities' EVENT intervals, read once (one
    query per chunk instead of a read per day). Read ahead of the writes, they stay valid: the run handles its days
    ascending and publishing day D' replaces only D''s daily rows and the EVENT values on [D', the security's next
    materialised day), so the rows of a later day are untouched until that day itself is published."""

    def __init__(self, con, days: list[date], entities: frozenset[str]) -> None:
        self._con, self._days = con, days
        self._daily = [c for c in features_store.DAILY_COLUMNS if c not in _CROSS and c != "security_id"]
        self._ent_pos = self._daily.index("entity_id")
        by_ent = in_list("entity_id", entities)
        self._secs = {s for (s,) in con.execute(
            "SELECT security_id FROM securities WHERE " + by_ent[0] + " UNION "
            "SELECT DISTINCT security_id FROM features_daily WHERE as_of_date >= ? AND " + by_ent[0],
            [*by_ent[1], days[0], *by_ent[1]],
        ).fetchall()}  # fmt: skip
        self._filter = in_list("security_id", self._secs)
        self._chunk: dict[date, dict[str, tuple]] = {}
        self._events: dict[str, list[tuple]] = defaultdict(list)
        for sec, start, end, *vals in con.execute(
            "SELECT security_id, valid_from_date, coalesce(valid_to_date, DATE '9999-12-31'), "
            + ", ".join(features_store.EVENT_COLUMNS)
            + " FROM features_events WHERE "
            + self._filter[0]
            + " AND coalesce(valid_to_date, DATE '9999-12-31') > ? ORDER BY 1, 2",
            [*self._filter[1], days[0]],
        ).fetchall():
            self._events[sec].append((start, end, tuple(vals)))

    def _day(self, d: date) -> dict[str, tuple]:
        if d not in self._chunk:
            i = self._days.index(d)
            chunk = self._days[i : i + STORED_CHUNK_DAYS]
            self._chunk = {x: {} for x in chunk}
            for sec, day, *vals in self._con.execute(
                "SELECT security_id, as_of_date, " + ", ".join(self._daily) + " FROM features_daily "
                "WHERE as_of_date >= ? AND as_of_date <= ? AND " + self._filter[0],
                [chunk[0], chunk[-1], *self._filter[1]],
            ).fetchall():
                if day in self._chunk:
                    self._chunk[day][sec] = tuple(vals)
        return self._chunk[d]

    def _event_values(self, sec: str, d: date) -> tuple | None:
        for start, end, vals in self._events.get(sec, ()):
            if start <= d < end:
                return vals
        return None

    def equal(self, d: date, entities: frozenset[str], rows: list[dict]) -> bool:
        """True when publishing `rows` for `entities` on `d` would store exactly the rows already stored: the rows
        `features_store.write_day` would replace (the day's rows of those entities and of the rows' securities)
        are the same securities with equal values in every column compute_rows sets (not the cross-section
        columns, which the publish recomputes from those values). Equal is value equality (NaN equals NaN); a value
        that would be cast on storage (a Decimal with more places than its column) compares unequal, so the day is
        published: a False only costs the publish."""
        secs = {r["security_id"] for r in rows}
        if len(rows) != len(secs) or not secs <= self._secs:
            return False
        day = self._day(d)
        replaced = {s for s, v in day.items() if v[self._ent_pos] in entities or s in secs}
        if replaced != secs:
            return False
        none = (None,) * len(features_store.EVENT_COLUMNS)
        for r in rows:
            sec = r["security_id"]
            events = self._event_values(sec, d)
            for cols, vals in ((self._daily, day[sec]), (features_store.EVENT_COLUMNS, events or none)):
                for c, v in zip(cols, vals, strict=True):
                    w = r.get(c)
                    if w is v:
                        continue
                    if w is None or v is None or not (w == v or (w != w and v != v)):
                        return False
        return True


STORED_CHUNK_DAYS = 32


def _incremental_days(con, days, exchange, prices, entities_for) -> list[MaterializeResult]:
    """The days of an incremental run, ascending. Each day computes its dirty rows (one batched compute_rows). A day
    whose rows equal the stored ones (a re-parse, a mirror or re-send of a filing, a revision that changed nothing
    these entities' rows read) is left as stored: publishing it would rewrite the same rows, recompute the same
    cross-section from the same inputs and pass the same gates as when it was published. Every other day is gated
    (G5, G4 on the merged day) and published as before, and so is the day after a published day, whose G4 compares
    with the changed previous day. The first day that fails a gate stops the run (the days before it stay
    published). The live table is rewritten as `materialize_days` does: once, by the run's last day."""
    results: list[MaterializeResult] = []
    changed_prev = due = False
    every = entities_for(days[-1]) if days else None  # the run's entities (the markers due by its last day)
    stored = _StoredRows(con, days, every) if every is not None else None
    try:
        for i, d in enumerate(days):
            last = i == len(days) - 1
            ents = entities_for(d)
            rows = compute_rows(con, d, exchange, entities=ents, prices=prices)
            if prices is not None:
                prices.settle()
            same = stored is not None and ents is not None and stored.equal(d, ents, rows)
            if same and not changed_prev:
                results.append(MaterializeResult("UNCHANGED", d, len(rows), message="dirty rows equal stored rows"))
                continue
            r = materialize(con, d, exchange, entities=ents, prices=prices, snapshot=last, snapshot_due=due,
                            rows=rows)  # fmt: skip
            results.append(r)
            if r.status != "PROMOTED":
                break
            changed_prev = not same
            due = (due or r.snapshot_due) and not last
    finally:
        if due:  # a deferred live-table rewrite the run's last day did not make
            publish_snapshot(con)
    return results


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
    dirty.mark_finding_changes(con)  # X325: findings opened / resolved since the rows were flagged
    rows = _dirty_rows(con)
    if not rows:
        dirty.store_finding_state(con)
        return IncrementalResult("NOTHING", [], "no dirty entities")
    if to is not None:
        rows = [r for r in rows if r[2] <= to]
        if not rows:
            return IncrementalResult("NOTHING", [], f"no dirty entities from on or before {to}")
    earliest = min(r[2] for r in rows)
    days = [d for (d,) in con.execute(
        "SELECT DISTINCT as_of_date FROM features_daily WHERE as_of_date >= ? AND as_of_date <= ? "
        "ORDER BY 1", [earliest, to or date.max]).fetchall()]  # fmt: skip
    every = None if any(r[1] == FULL for r in rows) else frozenset(r[1] for r in rows)

    def entities_for(d: date) -> frozenset[str] | None:
        due = [r for r in rows if r[2] <= d]
        return None if any(r[1] == FULL for r in due) else frozenset(r[1] for r in due)

    with entity_slices(con, every), materialize_run(con, days, exchange, every) as prices:
        results = _incremental_days(con, days, exchange, prices, entities_for)
    if results and results[-1].status not in PUBLISHED:
        r = results[-1]
        return IncrementalResult("ABORTED", results, f"{r.as_of_date}: {r.gate} {r.message}; dirty markers kept")
    settle_dirty(con, rows, None, to)
    dirty.store_finding_state(con)  # markers left after `to` keep those rows stale until a later run
    return IncrementalResult("DONE", results, f"{len(days)} day(s)", len({r[1] for r in rows}))
