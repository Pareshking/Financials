"""Period P&L family (ratio catalogue Batch 1, A4 / A5) and the Batch 0 row flags, for `features.py`.

Screener's gallery reads P&L lines for fixed periods: the latest quarter, the preceding quarter, the same quarter a
year earlier, 2 and 3 quarters back, the last full fiscal year and the one before it. One wide column per (line,
period); every value comes from the row's own scope book (one scope per row, never mixed [C18]), read point in time.

Line definitions are those of the TTM building blocks (architecture §8), applied to one period:
- sales = the row's `sales_ttm` line: revenue from operations net of labelled excise [X40]; interest earned for banks,
  premium / insurance revenue for insurers (as `_lender_overrides`);
- operating profit = EBITDA = profit before exceptional items and tax + finance costs + D&A - other income (as `opm`);
  EBIT = EBITDA - D&A; interest = finance costs; PBT, tax, PAT (total) and exceptional items as filed;
- net profit = owners' profit, COALESCE(owners, PAT) per filing [X42], as for PE / EPS;
- EPS = the filed basic EPS of exactly that period (never derived by YTD subtraction: share counts move), restated to
  today's share basis by the EPS factor of every accepted share-count action that went ex after the value was
  visible (Ind AS 33 restates earlier figures only in filings approved after the event);
- OPM = EBITDA / sales, NPM = net profit / sales, GPM = (sales - COGS) / sales only where materials + purchases are
  >= 10% of sales [C6]; equity capital = the paid-up capital stated in the results filing.
A quarter is `FactBook.quarter` (filed 3 months, or YTD_k - YTD_k-1, §6.2); a fiscal year is the filed 12-month value
(the latest 12-month PAT period on or before the row's quarter end, as `annual_ratios`), else the 4 quarters. A
missing period gives NULL, never a partial one. Operating profit, EBIT, OPM and GPM are NULL for lenders and insurers.

History-gated columns (C9; NULL until enough in-scope fiscal years exist, then on by themselves): FY CAGR of sales,
owners' profit, EBITDA (fundamentals.cagr with `min_periods_required = 4 * years + 1` at the FY end, so the FY25
filing is a valid base) and restated EPS; the median of yearly sales growth; mean owners' profit and EBIT.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime
from decimal import Decimal

from financials.fundamentals import (
    FactBook,
    _add_months,
    cagr,
    entity_filter,
    insurer_basis,
    latest_fiscal_year,
    qoq_growth,
    quarters_available_since,
    safe_div,
)
from financials.timeutil import utc_to_ist_date

# Quarter offsets (months back from the latest quarter end) and their column suffixes.
QUARTERS = {
    "latest_quarter": 0, "preceding_quarter": -3, "preceding_year_quarter": -12, "2quarters_back": -6,
    "3quarters_back": -9,
}  # fmt: skip
Q3 = ("latest_quarter", "preceding_quarter", "preceding_year_quarter")
FYS = ("last_year", "preceding_year")
MONEY_LINES = (
    "sales", "operating_profit", "other_income", "depreciation", "ebit", "interest", "pbt", "tax", "pat", "net_profit",
    "exceptional_items",
)  # fmt: skip
DEEP_LINES = ("sales", "operating_profit", "net_profit")  # also 2 and 3 quarters back (Screener's gallery)
GROWTH_YEARS = (3, 5, 7, 10)
MEDIAN_YEARS = (5, 10)
AVERAGE_YEARS = (5, 10)

MONEY_COLUMNS = (
    *(f"{line}_{q}" for line in MONEY_LINES for q in Q3),
    *(f"{line}_{q}" for line in DEEP_LINES for q in ("2quarters_back", "3quarters_back")),
    *(f"{line}_{fy}" for line in MONEY_LINES for fy in FYS),
    "sales_ttm_1y_back",
    *(f"avg_earnings_{n}y" for n in AVERAGE_YEARS), *(f"avg_ebit_{n}y" for n in AVERAGE_YEARS),
)  # fmt: skip
EPS_COLUMNS = (*(f"eps_{q}" for q in Q3), *(f"eps_{fy}" for fy in FYS))
MARGIN_COLUMNS = (
    "opm_latest_quarter_pct", "opm_preceding_quarter_pct", "opm_preceding_year_pct",
    *(f"npm_{p}_pct" for p in (*Q3, *FYS)),
    "gpm_latest_quarter_pct", "gpm_last_year_pct", "gpm_preceding_year_pct",
)  # fmt: skip
GROWTH_COLUMNS = (
    "sales_growth_yoy_quarter_pct", "profit_growth_yoy_quarter_pct", "operating_profit_growth_yoy_quarter_pct",
    *(f"{k}_growth_{n}y_pct" for k in ("sales", "profit", "operating_profit", "eps") for n in GROWTH_YEARS),
    *(f"sales_growth_median_{n}y_pct" for n in MEDIAN_YEARS),
    *(f"opm_{n}y_pct" for n in AVERAGE_YEARS),
)  # fmt: skip
EQUITY_CAPITAL_COLUMNS = tuple(f"equity_capital_{q}" for q in Q3)
DATE_COLUMNS = ("last_result_date", "last_annual_result_date")
ROW_COLUMNS = ("book_value_per_share", "is_trade_to_trade")
# Every new screener_features column of this module, in schema order (`opm_last_year_pct` existed and changes
# meaning: the last fiscal year's OPM; the same-quarter value is `opm_preceding_year_quarter_pct` in features.py).
PL_COLUMNS = (
    *MONEY_COLUMNS, *EPS_COLUMNS, *EQUITY_CAPITAL_COLUMNS, *MARGIN_COLUMNS, *GROWTH_COLUMNS, *DATE_COLUMNS,
    *ROW_COLUMNS,
)  # fmt: skip
OUTPUT_COLUMNS = (*PL_COLUMNS, "opm_last_year_pct")

# Industrial lines that do not apply to lenders and insurers (as features._NOT_FOR_LENDERS).
NOT_FOR_LENDERS = tuple(
    c for c in OUTPUT_COLUMNS
    if c.startswith(("operating_profit", "ebit", "opm_", "gpm_", "avg_ebit"))
)  # fmt: skip
TRADE_TO_TRADE_SERIES = frozenset({"BE", "BZ"})

# Derived per-period tags (prefixed so they never collide with a canonical tag).
REV_OPS, EBITDA, EBIT = "pl:rev_ops", "pl:ebitda", "pl:ebit"


# ── first visibility of results (one batched query per as-of) ─────────────────────────────────────────────────────

_PREFETCH: dict[tuple[int, datetime], dict] = {}
_VIS_TAGS = ("pat", "eps_basic")


def _visibility_rows(con, as_of: datetime, entities=None, where: str = "", params=()) -> list:
    """(entity, scope, tag, start, end, first visible, visible of the value the FactBook ranks first). The ranked
    value is the latest results filing's, else the latest annual report's (`fundamentals._ANNUAL_LAST`). A PDF
    correction (decision B; batch K also per-share EPS) counts from its corrected filing's visibility, as in
    `fundamentals._fact_source`, so a corrected EPS the filing never tagged still gets its result date."""
    only, only_p = entity_filter("entity_id", entities)
    from financials.fundamentals import _CURRENT_FILING, CURRENT_VERSION

    tags = ", ".join(f"'{t}'" for t in _VIS_TAGS)
    return con.execute(
        """SELECT entity_id, scope, canonical_tag, period_start, period_end, min(visible_from_ts),
                  coalesce(max(visible_from_ts) FILTER (WHERE NOT annual), max(visible_from_ts))
           FROM (SELECT *, filing_id IN (SELECT filing_id FROM filing_meta WHERE accounting_profile = 'REG34_ANNUAL')
                           AS annual
                 FROM (SELECT entity_id, scope, canonical_tag, period_start, period_end, visible_from_ts, filing_id
                       FROM fact_observations
                       WHERE canonical_tag IN ("""
        + tags
        + ") AND period_type = 'DURATION' AND visible_from_ts <= ? AND "
        + CURRENT_VERSION
        + """ UNION ALL SELECT c.entity_id, c.scope, c.canonical_tag, c.period_start, c.period_end, m.vis, c.filing_id
                       FROM fact_corrections c JOIN """
        + _CURRENT_FILING
        + " m USING (filing_id) WHERE c.revoked_at IS NULL AND c.canonical_tag IN ("
        + tags
        + ") AND c.period_type = 'DURATION' AND m.vis <= ?) WHERE TRUE"
        + only
        + where
        + ") GROUP BY ALL",
        [as_of, as_of, *only_p, *params],
    ).fetchall()


def _index(rows) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for ent, scope, tag, start, end, first, ranked in rows:
        out.setdefault((ent, scope), {})[(tag, start, end)] = (first, ranked)
    return out


def prefetch(con, as_of: datetime, entities=None) -> None:
    """One pass for every entity of a materialisation day (benchmarks: never a per-entity query on the hot path)."""
    _PREFETCH[(id(con), as_of)] = _index(_visibility_rows(con, as_of, entities))


def clear(con, as_of: datetime) -> None:
    _PREFETCH.pop((id(con), as_of), None)


def _visibility(con, book: FactBook, as_of: datetime | None) -> dict:
    """{(tag, start, end): (first visible, ranked value's visible)}; empty without a database (a bare FactBook)."""
    if con is None:
        return {}
    cached = _PREFETCH.get((id(con), as_of))
    if cached is not None:
        return cached.get((book.entity_id, book.scope), {})
    rows = _visibility_rows(con, as_of, None, " AND entity_id = ? AND scope = ?", [book.entity_id, book.scope])
    return _index(rows).get((book.entity_id, book.scope), {})


# ── period values ─────────────────────────────────────────────────────────────────────────────────────────────────


def _derive(book: FactBook) -> None:
    """Per-period (per filing) sales net of excise, EBITDA and EBIT, so quarters and years come from one rule."""
    if REV_OPS in book.durations:
        return
    gross = book.durations.get("revenue_from_operations", {})
    excise = book.durations[book.coalesced("excise_duty", None)]
    book.durations[REV_OPS] = {p: v - excise[p] for p, v in gross.items() if p in excise}
    d = {t: book.durations.get(t, {}) for t in ("profit_before_exceptional_and_tax", "finance_costs",
                                                "depreciation_amortisation", "other_income")}  # fmt: skip
    pbeit, fin, dep, oth = d.values()
    ebitda = {p: v + fin[p] + dep[p] - oth[p] for p, v in pbeit.items() if p in fin and p in dep and p in oth}
    book.durations[EBITDA] = ebitda
    book.durations[EBIT] = {p: v - dep[p] for p, v in ebitda.items()}


def sales_tag(book: FactBook) -> str:
    """The row's sales line (as features._sales_quarter / _lender_overrides)."""
    basis = insurer_basis(book)
    if basis is not None:
        return "insurance_revenue" if basis == "INDAS117" else (
            "net_premium_earned" if basis == "IRDAI_GENERAL" else "net_premium")  # fmt: skip
    if "interest_expended" in book.durations:
        return "interest_earned"
    return REV_OPS


def _tags(book: FactBook) -> dict[str, str]:
    _derive(book)
    return {
        "sales": sales_tag(book), "operating_profit": EBITDA, "other_income": "other_income",
        "depreciation": "depreciation_amortisation", "ebit": EBIT, "interest": "finance_costs", "pbt": "pbt",
        "tax": "tax_expense", "pat": "pat", "net_profit": book.coalesced("pat_owners", "pat"),
        "exceptional_items": book.coalesced("exceptional_items", None),
    }  # fmt: skip


def fy_value(book: FactBook, tag: str, fy: tuple[date, date]) -> Decimal | None:
    """The filed 12-month value of `fy`, else the sum of its 4 quarters (FactBook.ttm; never a partial year)."""
    v = book.durations.get(tag, {}).get(fy)
    return v if v is not None else book.ttm(tag, fy[1])


def _quarter_start(end: date) -> date:
    return _add_months(date(end.year, end.month, 1), -2)


def _gpm(sales, materials, purchases, inv_change) -> Decimal | None:
    """C6: only when materials + purchases are >= 10% of sales (as building_blocks)."""
    if (
        None in (sales, materials, purchases, inv_change)
        or not sales
        or materials + purchases < Decimal("0.10") * sales
    ):
        return None
    return safe_div(sales - (materials + purchases + inv_change), sales)


def _cogs_parts(get) -> tuple:
    return tuple(
        get(t) for t in ("cost_of_materials_consumed", "purchases_of_stock_in_trade", "changes_in_inventories")
    )


def fiscal_years(book: FactBook, end: date) -> tuple[tuple[date, date] | None, tuple[date, date] | None]:
    """(last FY, preceding FY): latest 12-month PAT period ending on or before `end`, and the one 12 months earlier
    if that is filed too."""
    fy = latest_fiscal_year(book, end)
    if fy is None:
        return None, None
    prev = (_add_months(fy[0], -12), _add_months(fy[1], -12))
    return fy, prev if prev in book.durations.get("pat", {}) else None


def _fy_series(book: FactBook, tag: str, fy: tuple[date, date], count: int) -> list[Decimal | None]:
    """`count` consecutive fiscal-year values ending with `fy` (newest first)."""
    return [fy_value(book, tag, (_add_months(fy[0], -12 * i), _add_months(fy[1], -12 * i))) for i in range(count)]


def _history_ok(fy_end: date, years_back: int) -> bool:
    """C9: the oldest fiscal year a window needs ends on or after the cutoff (4 quarters per year, + the FY itself)."""
    return quarters_available_since(fy_end, 4 * years_back + 1)


def _median_growth(values: list[Decimal | None]) -> Decimal | None:
    """Median of yearly growth rates from consecutive FY values (newest first); NULL if any year or base <= 0."""
    rates = [qoq_growth(values[i], values[i + 1]) for i in range(len(values) - 1)]
    return None if not rates or None in rates else statistics.median(rates)


def _mean(values: list[Decimal | None]) -> Decimal | None:
    return None if not values or None in values else sum(values, Decimal(0)) / len(values)


def period_values(con, book: FactBook, end: date, as_of: datetime | None = None) -> dict:
    """Everything of this family that depends only on the scope book (one per entity); `row_columns` finishes it
    per security (EPS restatement, book value per share, lender nulls). Money stays Decimal rupees."""
    tags = _tags(book)
    cols: dict = {}
    q_end = {k: _add_months(end, m) for k, m in QUARTERS.items()}
    for line, tag in tags.items():
        for k in Q3 + (("2quarters_back", "3quarters_back") if line in DEEP_LINES else ()):
            cols[f"{line}_{k}"] = book.quarter(tag, q_end[k])
    for k in Q3:
        sales, ebitda, owners = (cols[f"{x}_{k}"] for x in ("sales", "operating_profit", "net_profit"))
        if k != "preceding_year_quarter":  # that OPM is features.opm_preceding_year_quarter_pct (same definition)
            cols[f"opm_{k}_pct"] = safe_div(ebitda, sales)
        cols[f"npm_{k}_pct"] = safe_div(owners, sales)
        paid_up = book.durations.get("paid_up_equity_capital", {})
        e = q_end[k]
        stated = [v for (_, pe), v in sorted(paid_up.items()) if pe == e]  # a stock: any context ending `e`
        cols[f"equity_capital_{k}"] = paid_up.get((_quarter_start(e), e), stated[0] if stated else None)
    cols["gpm_latest_quarter_pct"] = _gpm(cols["sales_latest_quarter"],
                                          *_cogs_parts(lambda t: book.quarter(t, end)))  # fmt: skip
    for line, col in (("sales", "sales_growth_yoy_quarter_pct"), ("net_profit", "profit_growth_yoy_quarter_pct"),
                      ("operating_profit", "operating_profit_growth_yoy_quarter_pct")):  # fmt: skip
        cols[col] = qoq_growth(cols[f"{line}_latest_quarter"], cols[f"{line}_preceding_year_quarter"])
    # TTM ending a year before the latest quarter: 4 quarters or the H1 / FY bridge, NULL otherwise (FactBook.ttm).
    cols["sales_ttm_1y_back"] = book.ttm(tags["sales"], _add_months(end, -12))

    fy, prev = fiscal_years(book, end)
    for k, p in (("last_year", fy), ("preceding_year", prev)):
        for line, tag in tags.items():
            cols[f"{line}_{k}"] = fy_value(book, tag, p) if p else None
        sales, ebitda, owners = (cols[f"{x}_{k}"] for x in ("sales", "operating_profit", "net_profit"))
        cols[f"opm_{k}_pct"] = safe_div(ebitda, sales)
        cols[f"npm_{k}_pct"] = safe_div(owners, sales)
        cols[f"gpm_{k}_pct"] = _gpm(sales, *_cogs_parts(lambda t, p=p: fy_value(book, t, p))) if p else None

    # History-gated FY windows [C9]: NULL (never a shorter window) until the oldest FY needed is in scope.
    for n in GROWTH_YEARS:
        for key, line in (("sales", "sales"), ("profit", "net_profit"), ("operating_profit", "operating_profit")):
            cols[f"{key}_growth_{n}y_pct"] = (
                cagr(book, tags[line], fy[1], n, min_periods_required=4 * n + 1) if fy else None
            )
    for n in MEDIAN_YEARS:
        ok = fy is not None and _history_ok(fy[1], n)
        cols[f"sales_growth_median_{n}y_pct"] = (
            _median_growth(_fy_series(book, tags["sales"], fy, n + 1)) if ok else None
        )
    for n in AVERAGE_YEARS:
        ok = fy is not None and _history_ok(fy[1], n - 1)
        cols[f"avg_earnings_{n}y"] = _mean(_fy_series(book, tags["net_profit"], fy, n)) if ok else None
        cols[f"avg_ebit_{n}y"] = _mean(_fy_series(book, EBIT, fy, n)) if ok else None
        if ok:  # mean of the N fiscal years' OPM (Screener "OPM 5Year"), each year's EBITDA / sales
            ebitda, sales = _fy_series(book, EBITDA, fy, n), _fy_series(book, tags["sales"], fy, n)
            cols[f"opm_{n}y_pct"] = _mean([safe_div(e, s) for e, s in zip(ebitda, sales, strict=True)])
        else:
            cols[f"opm_{n}y_pct"] = None

    vis = _visibility(con, book, as_of)
    eps = book.durations.get("eps_basic", {})

    def eps_at(p: tuple[date, date] | None):
        if p is None or p not in eps:
            return None
        ranked = vis.get(("eps_basic", *p), (None, None))[1]
        return eps[p], None if ranked is None else utc_to_ist_date(ranked)

    eps_cols = {f"eps_{k}": eps_at((_quarter_start(q_end[k]), q_end[k])) for k in Q3}
    eps_cols |= {"eps_last_year": eps_at(fy), "eps_preceding_year": eps_at(prev)}
    eps_fy = {}
    if fy is not None:
        for i in range(max(GROWTH_YEARS) + 1):
            p = (_add_months(fy[0], -12 * i), _add_months(fy[1], -12 * i))
            eps_fy[i] = eps_at(p)

    pat_vis = {(s, e): v[0] for (t, s, e), v in vis.items() if t == "pat"}
    latest = max((e for (_, e) in pat_vis if e <= end), default=None)
    first = [v for (_, e), v in pat_vis.items() if e == latest]
    cols["last_result_date"] = utc_to_ist_date(min(first)) if first else None
    cols["last_annual_result_date"] = utc_to_ist_date(pat_vis[fy]) if fy in pat_vis else None
    return {"cols": cols, "eps": eps_cols, "eps_fy": eps_fy, "fy_end": fy[1] if fy else None}


# ── per-security finish ───────────────────────────────────────────────────────────────────────────────────────────


def restated_eps(value: tuple[Decimal, date | None] | None, factors, as_of: date) -> Decimal | None:
    """Filed EPS on today's share basis: multiplied by the EPS factor of every accepted share-count action with
    ex-date after the date the value became visible and on or before `as_of` (Rs 10 before a 1:1 bonus is Rs 5)."""
    if value is None:
        return None
    eps, visible = value
    f = Decimal(1)
    for ex, _, eps_factor in factors:
        if (visible is None or ex > visible) and ex <= as_of:
            f *= eps_factor
    return (eps * f).quantize(Decimal("0.0001"))


def eps_cagr(eps_fy: dict, fy_end: date | None, years: int, factors, as_of: date) -> Decimal | None:
    """FY EPS CAGR on today's share basis; NULL until the base FY is in scope [C9] or when either end is <= 0."""
    if fy_end is None or not _history_ok(fy_end, years):
        return None
    cur, base = (restated_eps(eps_fy.get(i), factors, as_of) for i in (0, years))
    if cur is None or base is None or cur <= 0 or base <= 0:
        return None
    return (cur / base) ** (Decimal(1) / Decimal(years)) - 1


def _out(col: str, v):
    """DOUBLE for ratios, Decimal rupees for money (rounded to paise), dates and per-share values as they are."""
    if v is None or col in DATE_COLUMNS or col in EPS_COLUMNS:
        return v
    if col in MONEY_COLUMNS or col in EQUITY_CAPITAL_COLUMNS:
        return v.quantize(Decimal("0.01"))
    return float(v)


def row_columns(pl: dict | None, row: dict, fund: dict, factors, as_of: date, shares, bars, frozen_from) -> dict:
    """All columns of this module for one security row. EPS columns are NULL while an unexplained price gap freezes
    the security (a missed split would mis-state the restatement, as for the dividend yield)."""
    out: dict = dict.fromkeys(OUTPUT_COLUMNS)
    out["is_trade_to_trade"] = row.get("series") in TRADE_TO_TRADE_SERIES
    equity = fund.get("_equity_owners")
    if equity is not None and shares:
        out["book_value_per_share"] = (equity / shares).quantize(Decimal("0.0001"))
    if not pl:
        return out
    out.update({c: _out(c, v) for c, v in pl["cols"].items()})
    frozen = frozen_from is not None and bool(bars) and bars[-1][0] >= frozen_from
    if not frozen:
        out.update({c: restated_eps(v, factors, as_of) for c, v in pl["eps"].items()})
        for n in GROWTH_YEARS:
            g = eps_cagr(pl["eps_fy"], pl["fy_end"], n, factors, as_of)
            out[f"eps_growth_{n}y_pct"] = None if g is None else float(g)
    if fund.get("_lender") or row.get("valuation_archetype") in ("FINANCIAL_LENDING", "INSURANCE"):
        out.update(dict.fromkeys(NOT_FOR_LENDERS))
    return out
