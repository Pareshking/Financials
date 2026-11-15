"""Balance-sheet, working-capital, cash-flow and capital-allocation family (ratio catalogue Batches 2 and 3: A6, A7
and the A1 / A2 / B1 / B2 rows built on them), for `features.py`.

One wide column per (line, period), every value from the row's own scope book (one scope per row, never mixed [C18]),
read point in time. Money stays Decimal rupees; ratios are DOUBLE fractions (days in days, turnover in times).

Periods (as the P&L family in features_pl, so "last year" / "preceding year" mean the same fiscal years):
- an unsuffixed balance-sheet line is the latest balance sheet on or before the row's quarter end (`bs_as_of`, H1 or
  FY [X13]); annual notes (gross block, accumulated depreciation, contingent liabilities, advance from customers) are
  Reg. 34 only [X71, X73] and are read at the last fiscal year's end (NULL until that year's annual report is visible);
- "preceding year" = the balance sheet at the end of the fiscal year before the last one (the year of
  `sales_preceding_year`); "N years back" = the last fiscal year's end minus N years;
- cash-flow lines are the filed 12-month values of the last / preceding fiscal year (cash flow is filed H1 / FY only,
  never derived from quarters).
A balance sheet that is filed but omits a line means nil for that line (Schedule III omits nil lines [C23]): debt,
leases, inventory, receivables and payables are then 0, as in the Screener-style statement (statements.balance_sheet,
S10), whose Borrowings (incl. leases), Net Block, CWIP, Investments, Total and Other Assets - Other Liabilities
(working capital, as the built `working_capital`) these columns reuse.

History-gated (C9): N-years-back values, 3/5/7/10-year cash-flow sums, 3-year averages and conversions, incremental
ROIC 3Y / 5Y and 10-year share counts are NULL until the oldest fiscal year (or date) they need is in scope, then on
by themselves; never a shorter window. Lenders and insurers keep the raw capital, cash-flow and share-count lines
and get NULL for the industrial lines and ratios (`NOT_FOR_LENDERS`); `roa` keeps the lenders' own definition.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from financials import features_pl
from financials.db import version_key
from financials.fundamentals import (
    BookAsResult,
    FactBook,
    _add_months,
    average_instant,
    entity_filter,
    insurer_basis,
    invested_capital_at,
    latest_fiscal_year,
    quarters_available_since,
    safe_div,
    screener_convention_ratios,
)
from financials.parsers.indas_corp import period_months
from financials.scope import financials_in_scope
from financials.statements.balance_sheet import balance_sheet

ZERO = Decimal(0)
FYS = ("last_year", "preceding_year")
BACK_YEARS = (3, 5, 7, 10)
BOOK_BACK_YEARS = (3, 5, 10)
CASH_BACK_YEARS = (3, 5, 7)
DEBTOR_BACK_YEARS = (3, 5)
EXPORT_BACK_YEARS = (3, 5)
SUM_YEARS = (3, 5, 7, 10)
INCREMENTAL_ROIC_YEARS = (1, 3, 5)

BS_LINES = (
    "debt", "equity_capital", "reserves", "balance_sheet_total", "net_block", "cwip", "investments", "current_assets",
    "current_liabilities", "lease_liabilities", "inventory", "trade_receivables", "trade_payables", "cash_equivalents",
)  # fmt: skip
ANNUAL_LINES = ("gross_block", "accumulated_depreciation", "contingent_liabilities", "advance_from_customers")
PRECEDING_LINES = ("debt", "net_block", "gross_block", "cwip", "working_capital")
BACK_LINES = ("debt", "net_block", "working_capital")
CF_LINES = ("cfo", "cfi", "cff", "net_cash_flow", "cash_beginning", "cash_end", "fcf")
SUM_LINES = ("fcf", "cfo", "cfi")

MONEY_COLUMNS = (
    *BS_LINES, *ANNUAL_LINES,
    *(f"{x}_preceding_year" for x in PRECEDING_LINES),
    *(f"{x}_{n}y_back" for x in BACK_LINES for n in BACK_YEARS),
    *(f"cash_{n}y_back" for n in CASH_BACK_YEARS),
    *(f"{x}_{k}" for x in CF_LINES for k in FYS),
    *(f"{x}_{n}y" for x in SUM_LINES for n in SUM_YEARS),
)  # fmt: skip
PER_SHARE_COLUMNS = (
    "face_value", "book_value_preceding_year", *(f"book_value_{n}y_back" for n in BOOK_BACK_YEARS), "graham_number",
)  # fmt: skip
COUNT_COLUMNS = ("shares_preceding_year", "shares_10y_back")
RATIO_COLUMNS = (
    "current_ratio", "quick_ratio", "net_debt_to_equity", "long_term_debt_to_equity", "debt_to_equity_preceding_year",
    "financial_leverage", "asset_turnover", "earning_power", "roe_preceding_year", "roce_preceding_year",
    "roa_preceding_year", "exports_pct", *(f"exports_pct_{n}y_back" for n in EXPORT_BACK_YEARS),
    *(f"inventory_turnover_{n}y_back" for n in BACK_YEARS), *(f"debtor_days_{n}y_back" for n in DEBTOR_BACK_YEARS),
    "avg_debtor_days_3y", "avg_working_capital_days_3y",
    *(f"cfo_to_ebitda_{k}" for k in FYS), "fcf_conversion_3y", "cfo_to_ebitda_3y", "net_debt_to_fcf_3y",
    "price_to_fcf", "equity_fcf_yield", "shareholder_yield", "buyback_yield", "dilution_1y", "dilution_5y",
    "reinvestment_rate",
    *(f"incremental_roic_{n}y" for n in INCREMENTAL_ROIC_YEARS), "net_debt_to_ebitda",
)  # fmt: skip
# Every new screener_features column of this module, in schema order. `roa` (lenders until 6C) is also filled for
# industrial books here: TTM owners' profit / average total assets, both over the 12 months to `bs_as_of`.
OUTPUT_COLUMNS = (*MONEY_COLUMNS, *PER_SHARE_COLUMNS, *COUNT_COLUMNS, *RATIO_COLUMNS)

# What stays meaningful for lenders and insurers: capital, total, cash, contingent liabilities, face value, share
# counts and per-share book value, the cash-flow statement lines and payout yields.
LENDER_COLUMNS = frozenset(
    {
        "equity_capital", "reserves", "balance_sheet_total", "cash_equivalents", "contingent_liabilities",
        "face_value", "book_value_preceding_year", *(f"book_value_{n}y_back" for n in BOOK_BACK_YEARS),
        "graham_number", *COUNT_COLUMNS, "dilution_1y", "dilution_5y", "shareholder_yield", "buyback_yield",
        *(f"{x}_{k}" for x in ("cfo", "cfi", "cff", "net_cash_flow", "cash_beginning", "cash_end") for k in FYS),
        *(f"{x}_{n}y" for x in ("cfo", "cfi") for n in SUM_YEARS), *(f"cash_{n}y_back" for n in CASH_BACK_YEARS),
    }
)  # fmt: skip
NOT_FOR_LENDERS = tuple(c for c in OUTPUT_COLUMNS if c not in LENDER_COLUMNS)

BUYBACK_TAG = "li_payments_to_acquire_or_redeem_entitys_shares"  # zero-drop key, 74 INDAS_CORP filings [C24]
ETR_CAP = Decimal("0.5")


# ── Reg. 31 share counts (one batched query per as-of) ────────────────────────────────────────────────────────────

_PREFETCH: dict[tuple[int, datetime], dict] = {}


def _share_rows(con, as_of: datetime, entities=None, where: str = "", params=()) -> list:
    """(entity, SHP as-of date, TOTAL shares) of the latest visible revision of every shareholding pattern."""
    only, only_p = entity_filter("entity_id", entities)
    return con.execute(
        """WITH f AS (
               SELECT entity_id, as_of_date, filing_id, parser_version FROM (
                   SELECT entity_id, as_of_date, filing_id, parser_version, row_number() OVER (
                       PARTITION BY entity_id, as_of_date ORDER BY visible_from_ts DESC, """
        + version_key()
        + """ DESC, filing_id DESC) AS rn
                   FROM shareholding_meta WHERE visible_from_ts <= ?"""
        + only
        + where
        + """) WHERE rn = 1)
           SELECT f.entity_id, f.as_of_date, o.shares
           FROM f JOIN shareholding_observations o USING (filing_id, parser_version)
           WHERE o.category = 'TOTAL' AND o.shares IS NOT NULL""",
        [as_of, *only_p, *params],
    ).fetchall()


def _index(rows) -> dict[str, dict[date, Decimal]]:
    out: dict[str, dict[date, Decimal]] = defaultdict(dict)
    for ent, d, shares in rows:
        out[ent][d] = Decimal(shares)
    return out


def prefetch(con, as_of: datetime, entities=None) -> None:
    """One pass for every entity of a materialisation day (benchmarks: never a per-entity query on the hot path)."""
    _PREFETCH[(id(con), as_of)] = _index(_share_rows(con, as_of, entities))


def clear(con, as_of: datetime) -> None:
    _PREFETCH.pop((id(con), as_of), None)


def _share_history(con, as_of: datetime, entity_id: str) -> dict[date, Decimal]:
    cached = _PREFETCH.get((id(con), as_of))
    if cached is not None:
        return cached.get(entity_id, {})
    return _index(_share_rows(con, as_of, None, " AND entity_id = ?", [entity_id])).get(entity_id, {})


def shares_at(history: dict[date, Decimal], d: date | None, factors, as_of: date) -> Decimal | None:
    """Reg. 31 total of the pattern as of exactly `d`, on today's share basis: divided by the EPS factor of every
    accepted share-count action with ex-date in (d, as_of] (as features.market_cap_shares). Reg. 31 only: paid-up
    capital is stated in rounded crore by some filers (TCS 3,620,000,000 vs 3,618,087,518), which would fake a
    dilution. NULL when that pattern is not visible or `d` is before the data cutoff [C9]."""
    if d is None or not financials_in_scope(d) or d not in history:
        return None
    shares = history[d]
    for ex, _, eps_factor in factors:
        if d < ex <= as_of:
            shares = shares / eps_factor
    return shares


# ── book-level values ─────────────────────────────────────────────────────────────────────────────────────────────


def _shift(p: tuple[date, date], years: int) -> tuple[date, date]:
    return _add_months(p[0], -12 * years), _add_months(p[1], -12 * years)


def _history_ok(fy_end: date, years_back: int) -> bool:
    """C9: the fiscal year `years_back` before the one ending `fy_end` ends on or after the cutoff."""
    return quarters_available_since(fy_end, 4 * years_back + 1)


def _owners_equity(book: FactBook, d: date) -> Decimal | None:
    g = book.instants
    return g.get("equity_attributable_to_owners", {}).get(d) or g.get("total_equity", {}).get(d)


def bs_lines(book: FactBook, d: date | None) -> dict:
    """Screener-style balance-sheet lines on balance-sheet date `d` ({} when no balance sheet is filed for `d`)."""
    if d is None:
        return {}
    st = balance_sheet(BookAsResult(book), d)
    if st is None:
        return {}

    def g(tag: str) -> Decimal | None:
        return book.instants.get(tag, {}).get(d)

    def z(*tags: str) -> Decimal:
        return sum((g(t) or ZERO for t in tags), ZERO)

    r = st.rows
    reserves = g("other_equity")
    return {
        "debt": r["Borrowings"].value,
        "equity_capital": g("equity_share_capital"),
        "reserves": reserves if reserves is not None else g("reserves_and_surplus"),  # banks / insurers
        "balance_sheet_total": r["Total Assets"].value,  # Screener nets DTA against DTL [S10]
        "net_block": r["Net Block"].value,
        "cwip": r["Capital Work in Progress"].value,
        "investments": r["Investments"].value,
        "current_assets": g("current_assets"),
        "current_liabilities": g("current_liabilities"),
        "lease_liabilities": z("lease_liabilities_noncurrent", "lease_liabilities_current"),
        "inventory": z("inventories"),
        "trade_receivables": z("trade_receivables_current", "trade_receivables_noncurrent"),
        "trade_payables": z("trade_payables_current", "trade_payables_noncurrent"),
        "cash_equivalents": g("cash_and_equivalents"),
        "working_capital": r["Other Assets"].value - r["Other Liabilities"].value,
        "long_term_debt": z("borrowings_noncurrent", "lease_liabilities_noncurrent"),
        "total_assets": g("total_assets"),
        "total_equity": g("total_equity"),
        "equity_owners": _owners_equity(book, d),
    }


def noncash_working_capital(book: FactBook, d: date) -> Decimal | None:
    """(current assets - cash - other bank balances - current investments) - (current liabilities - current
    borrowings - current lease liabilities): operating working capital, financing items removed."""
    g = lambda t: book.instants.get(t, {}).get(d)  # noqa: E731
    ca, cl = g("current_assets"), g("current_liabilities")
    if ca is None or cl is None:
        return None
    z = lambda *ts: sum((g(t) or ZERO for t in ts), ZERO)  # noqa: E731
    return (ca - z("cash_and_equivalents", "bank_balances_other", "current_investments")) - (
        cl - z("borrowings_current", "lease_liabilities_current")
    )


def _fy(book: FactBook, tag: str, p: tuple[date, date] | None) -> Decimal | None:
    return None if p is None else book.durations.get(tag, {}).get(p)


def nopat(book: FactBook, p: tuple[date, date] | None) -> Decimal | None:
    """FY EBIT x (1 - ETR), ETR = tax / PBT clamped to [0, 50%] and 0 for a loss (as building_blocks [C5])."""
    if p is None:
        return None
    ebit = features_pl.fy_value(book, features_pl.EBIT, p)
    if ebit is None:
        return None
    pbt, tax = features_pl.fy_value(book, "pbt", p), features_pl.fy_value(book, "tax_expense", p)
    etr = ZERO
    if pbt is not None and tax is not None and pbt > 0 and tax >= 0:
        etr = min(max(tax / pbt, ZERO), ETR_CAP)
    return ebit * (1 - etr)


def cash_flow_year(book: FactBook, p: tuple[date, date] | None) -> dict:
    """One fiscal year's cash-flow lines as filed (12-month context). Net cash flow is after the FX effect on cash
    (Screener [S12]); cash beginning is the prior year-end cash of the cash-flow statement, else cash end - net cash
    flow (the statement's own identity: the year before FY25 is out of scope, C9). FCF = CFO - capex (PPE +
    intangibles; a missing intangibles line is nil)."""
    out = dict.fromkeys(CF_LINES)
    if p is None or period_months(*p) != 12:
        return out
    cfo = _fy(book, "cfo", p)
    out.update(cfo=cfo, cfi=_fy(book, "cfi", p), cff=_fy(book, "cff", p))
    ncf = _fy(book, "net_cash_flow_after_fx", p)
    if ncf is None and _fy(book, "net_cash_flow", p) is not None:
        ncf = _fy(book, "net_cash_flow", p) + (_fy(book, "fx_effect_on_cash", p) or ZERO)
    out["net_cash_flow"] = ncf
    cash = book.instants.get("cash_cf_statement", {})
    end_cash = cash.get(p[1])
    out["cash_end"] = end_cash
    begin = cash.get(p[0] - timedelta(days=1))
    if begin is None and end_cash is not None and ncf is not None:
        begin = end_cash - ncf
    out["cash_beginning"] = begin
    capex = _fy(book, "capex_ppe", p)
    if cfo is not None and capex is not None:
        out["fcf"] = cfo - capex - (_fy(book, "capex_intangibles", p) or ZERO)
    return out


def cf_window(book: FactBook, cf_end: date | None) -> list[tuple[tuple[date, date], int]] | None:
    """The filed periods behind TTM CFO ending `cf_end` (FactBook.ttm_from_ytd): the FY, or YTD + FY_prev - YTD_prev.
    Other cash-flow lines are summed over the same periods, a line a filing omits counting as nil."""
    if cf_end is None:
        return None
    d = book.durations.get("cfo", {})
    for s, e in d:
        if e != cf_end:
            continue
        m = period_months(s, e)
        if m == 12:
            return [((s, e), 1)]
        if m is None or m > 12 or not book.is_ytd_start(s):
            continue
        fy_prev, ytd_prev = (_add_months(s, -12), s - timedelta(days=1)), (_add_months(s, -12), _add_months(e, -12))
        if fy_prev in d and ytd_prev in d:
            return [((s, e), 1), (fy_prev, 1), (ytd_prev, -1)]
    return None


def _window_sum(book: FactBook, tag: str, window) -> Decimal | None:
    if window is None:
        return None
    vals = book.durations.get(tag, {})
    return sum((sign * vals.get(p, ZERO) for p, sign in window), ZERO)


def _days(book: FactBook, fy_end: date) -> dict:
    """Screener-convention days ratios of exactly the fiscal year ending `fy_end` ({} if that FY is not filed)."""
    fy = latest_fiscal_year(book, fy_end)
    if fy is None or fy[1] != fy_end:
        return {}
    return screener_convention_ratios(book, fy_end)


def _total(values: list) -> Decimal | None:
    """Sum of every year's value; NULL if any year is missing (never a shorter window)."""
    return None if not values or None in values else sum(values, ZERO)


def _mean(values: list) -> Decimal | None:
    total = _total(values)
    return None if total is None else total / len(values)


def _exports(book: FactBook, p: tuple[date, date] | None) -> Decimal | None:
    """Revenue from foreign customers / revenue by geography (Reg. 34 GeographicalAreasAxis, Ind AS 108.33 [X75])."""
    foreign, domestic = _fy(book, "revenue_foreign", p), _fy(book, "revenue_domestic", p)
    if foreign is None or domestic is None:
        return None
    return safe_div(foreign, foreign + domestic)


def _face_value(book: FactBook, end: date) -> Decimal | None:
    fv = [(e, s, v) for (s, e), v in book.durations.get("face_value_per_share", {}).items() if e <= end]
    return max(fv)[2] if fv else None


def period_values(book: FactBook, end: date, b: dict) -> dict:
    """Everything of this family that depends only on the scope book; `row_columns` finishes it per security (share
    counts, market-cap ratios, lender NULLs). `b` = fundamentals.building_blocks(book, end)."""
    tags = features_pl._tags(book)  # per-period sales net of excise, EBITDA, EBIT, owners' profit (features_pl)
    lender = insurer_basis(book) is not None or "interest_earned" in book.durations
    c: dict = dict.fromkeys(OUTPUT_COLUMNS)
    for k in ("graham_number", *COUNT_COLUMNS, "book_value_preceding_year",
              *(f"book_value_{n}y_back" for n in BOOK_BACK_YEARS), "price_to_fcf", "equity_fcf_yield",
              "shareholder_yield", "buyback_yield", "dilution_1y", "dilution_5y", "net_debt_to_ebitda"):  # fmt: skip
        c.pop(k)  # per security
    bs = b.get("bs_as_of")
    cur = bs_lines(book, bs)
    c.update({k: cur.get(k) for k in BS_LINES})
    c["face_value"] = _face_value(book, end)
    eq = b.get("total_equity")
    if cur:
        c["current_ratio"] = safe_div(cur["current_assets"], cur["current_liabilities"])
        if cur["current_assets"] is not None:
            c["quick_ratio"] = safe_div(cur["current_assets"] - cur["inventory"], cur["current_liabilities"])
        c["long_term_debt_to_equity"] = safe_div(cur["long_term_debt"], cur["total_equity"])
    c["net_debt_to_equity"] = safe_div(b.get("net_debt"), eq)
    c["earning_power"] = safe_div(b.get("ebit"), b.get("total_assets"))
    roa = None
    if bs is not None:  # 12 months to the balance sheet: TTM flows and (opening + closing) / 2 balances [C16]
        avg_assets = average_instant(book, "total_assets", bs)[0]
        opening = _add_months(bs, -12)
        eq0, eq1 = _owners_equity(book, opening), _owners_equity(book, bs)
        if avg_assets is not None and eq0 is not None and eq1 is not None:
            c["financial_leverage"] = safe_div(avg_assets, (eq0 + eq1) / 2)
        c["asset_turnover"] = safe_div(book.ttm(tags["sales"], bs), avg_assets)
        roa = safe_div(book.ttm(tags["net_profit"], bs), avg_assets)

    fy = latest_fiscal_year(book, end)
    fy_end = fy[1] if fy else None
    prev = _shift(fy, 1) if fy else None
    at = lambda tag, d: book.instants.get(tag, {}).get(d) if d else None  # noqa: E731
    if fy:
        c["gross_block"] = at("ppe_gross_block", fy_end)
        c["accumulated_depreciation"] = at("ppe_accumulated_depreciation", fy_end)
        c["contingent_liabilities"] = at("contingent_liabilities", fy_end)  # without commitments, as the ratio [X73]
        c["advance_from_customers"] = at("advance_from_customers", fy_end)
        c["exports_pct"] = _exports(book, fy)
    equity_at: dict = {}
    if prev:
        pl = bs_lines(book, prev[1])
        for k in PRECEDING_LINES:
            c[f"{k}_preceding_year"] = pl.get(k)
        c["gross_block_preceding_year"] = at("ppe_gross_block", prev[1])
        c["debt_to_equity_preceding_year"] = safe_div(pl.get("debt"), pl.get("total_equity"))
        equity_at["preceding_year"] = (prev[1], _owners_equity(book, prev[1]))
        c["roe_preceding_year"] = safe_div(features_pl.fy_value(book, tags["net_profit"], prev), equity_at[
            "preceding_year"][1])  # fmt: skip
        if pl.get("debt") is not None and pl.get("total_equity") is not None:
            c["roce_preceding_year"] = safe_div(features_pl.fy_value(book, features_pl.EBIT, prev),
                                                pl["debt"] + pl["total_equity"])  # fmt: skip
        c["roa_preceding_year"] = safe_div(features_pl.fy_value(book, tags["net_profit"], prev),
                                           average_instant(book, "total_assets", prev[1])[0])  # fmt: skip

    # N years back from the last fiscal year end: NULL (never an older or newer year) until it is in scope [C9].
    if fy:
        for n in sorted({*BACK_YEARS, *BOOK_BACK_YEARS, *CASH_BACK_YEARS}):
            d = _add_months(fy_end, -12 * n)
            ok = financials_in_scope(d)
            lines = bs_lines(book, d) if ok and n in BACK_YEARS else {}
            for k in BACK_LINES if n in BACK_YEARS else ():
                c[f"{k}_{n}y_back"] = lines.get(k)
            if n in BOOK_BACK_YEARS:
                equity_at[n] = (d, _owners_equity(book, d) if ok else None)
            if n in CASH_BACK_YEARS:
                c[f"cash_{n}y_back"] = at("cash_cf_statement", d) if ok else None
            if n in BACK_YEARS:
                c[f"inventory_turnover_{n}y_back"] = _days(book, d).get("inventory_turnover") if ok else None
            if n in DEBTOR_BACK_YEARS:
                c[f"debtor_days_{n}y_back"] = _days(book, d).get("debtor_days") if ok else None
            if n in EXPORT_BACK_YEARS:
                c[f"exports_pct_{n}y_back"] = _exports(book, _shift(fy, n)) if ok else None
        if _history_ok(fy_end, 2):
            years = [_days(book, _add_months(fy_end, -12 * i)) for i in range(3)]
            c["avg_debtor_days_3y"] = _mean([y.get("debtor_days") for y in years])
            c["avg_working_capital_days_3y"] = _mean([y.get("working_capital_days") for y in years])

    # Cash flow: last / preceding fiscal year, N-year sums and 3-year conversions [G224, G233].
    cf = {k: cash_flow_year(book, p) for k, p in (("last_year", fy), ("preceding_year", prev))}
    for k in FYS:
        for line in CF_LINES:
            c[f"{line}_{k}"] = cf[k][line]
        p = fy if k == "last_year" else prev
        ebitda = features_pl.fy_value(book, features_pl.EBITDA, p) if p else None
        c[f"cfo_to_ebitda_{k}"] = safe_div(cf[k]["cfo"], ebitda)
    sums: dict = {}
    if fy:
        for n in SUM_YEARS:
            if not _history_ok(fy_end, n - 1):
                continue
            years = [cash_flow_year(book, _shift(fy, i)) for i in range(n)]
            for line in SUM_LINES:
                c[f"{line}_{n}y"] = _total([y[line] for y in years])
            if n == 3:
                sums = {
                    "fcf": c["fcf_3y"], "cfo": c["cfo_3y"],
                    "pat": _total([features_pl.fy_value(book, tags["net_profit"], _shift(fy, i)) for i in range(3)]),
                    "ebitda": _total([features_pl.fy_value(book, features_pl.EBITDA, _shift(fy, i)) for i in range(3)]),
                }  # fmt: skip
    if sums:
        c["fcf_conversion_3y"] = safe_div(sums["fcf"], sums["pat"])
        c["cfo_to_ebitda_3y"] = safe_div(sums["cfo"], sums["ebitda"])
        if sums["fcf"] is not None and sums["fcf"] > 0 and b.get("net_debt") is not None:
            c["net_debt_to_fcf_3y"] = b["net_debt"] / (sums["fcf"] / 3)

    # Capital allocation on fiscal years [G215, G216].
    if fy and prev:
        n0 = nopat(book, fy)
        wc1, wc0 = noncash_working_capital(book, fy_end), noncash_working_capital(book, prev[1])
        capex, dep = _fy(book, "capex_ppe", fy), features_pl.fy_value(book, "depreciation_amortisation", fy)
        if None not in (n0, wc1, wc0, capex, dep) and n0 > 0:
            capex += _fy(book, "capex_intangibles", fy) or ZERO
            c["reinvestment_rate"] = (capex - dep + (wc1 - wc0)) / n0
        for n in INCREMENTAL_ROIC_YEARS:
            if not _history_ok(fy_end, n):
                continue
            base = _shift(fy, n)
            n_base, ic1, ic0 = nopat(book, base), invested_capital_at(book, fy_end), invested_capital_at(book, base[1])
            if None not in (n0, n_base, ic1, ic0) and ic1 - ic0 > 0:
                c[f"incremental_roic_{n}y"] = (n0 - n_base) / (ic1 - ic0)

    window = cf_window(book, b.get("cf_as_of"))
    payouts = {k: _window_sum(book, t, window) for k, t in (("dividends", "dividends_paid"), ("buyback", BUYBACK_TAG),
                                                           ("issued", "share_issue_proceeds"))}  # fmt: skip
    return {"cols": c, "lender": lender, "roa": roa, "equity_at": equity_at, "payouts": payouts}


# ── per-security finish ───────────────────────────────────────────────────────────────────────────────────────────

Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")


def _out(col: str, v):
    """Decimal rupees (paise) for money, Decimal per-share values (4 dp), int counts, DOUBLE for ratios."""
    if v is None:
        return None
    if col in MONEY_COLUMNS:
        return v.quantize(Q2)
    if col in PER_SHARE_COLUMNS:
        return v.quantize(Q4)
    if col in COUNT_COLUMNS:
        return int(v)
    return float(v)


def graham_number(eps: Decimal | None, bvps: Decimal | None) -> Decimal | None:
    """sqrt(22.5 x EPS x book value per share) (Graham: PE 15 x PB 1.5); NULL unless both are > 0."""
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return (Decimal("22.5") * eps * bvps).sqrt()


def row_columns(con, as_of_ts: datetime, bsv: dict | None, row: dict, factors, as_of: date) -> dict:
    """All columns of this module for one security row (after features_pl.row_columns: needs `eps_ttm`,
    `book_value_per_share`, `market_cap`, `shares`, `shp_as_of`)."""
    v: dict = dict.fromkeys(OUTPUT_COLUMNS)
    v["roa"] = row.get("roa")
    v["graham_number"] = graham_number(row.get("eps_ttm"), row.get("book_value_per_share"))
    history = _share_history(con, as_of_ts, row["entity_id"]) if con is not None else {}
    shp = row.get("shp_as_of")
    now = shares_at(history, shp, factors, as_of)
    year_ago = shares_at(history, _add_months(shp, -12), factors, as_of) if shp else None
    v["shares_preceding_year"] = year_ago
    v["shares_10y_back"] = shares_at(history, _add_months(shp, -120), factors, as_of) if shp else None
    if now is not None and year_ago:
        v["dilution_1y"] = now / year_ago - 1  # Reg. 31 both ends, today's share basis
    five_ago = shares_at(history, _add_months(shp, -60), factors, as_of) if shp else None
    if now is not None and five_ago:
        v["dilution_5y"] = now / five_ago - 1  # G219; NULL until the pattern 5 years back is in scope (~Apr 2030)
    mcap, fcf = row.get("market_cap"), row.get("fcf_ttm")
    if mcap is not None and mcap > 0 and fcf is not None:
        v["equity_fcf_yield"] = fcf / mcap  # G170: levered FCF (CFO - capex) / market cap; signed
        v["price_to_fcf"] = mcap / fcf if fcf > 0 else None
    net_debt, ebitda = row.get("net_debt"), row.get("ebitda_ttm")
    v["net_debt_to_ebitda"] = safe_div(net_debt, ebitda)
    if bsv:
        v.update(bsv["cols"])
        for key, (d, equity) in bsv["equity_at"].items():
            col = "book_value_preceding_year" if key == "preceding_year" else f"book_value_{key}y_back"
            v[col] = safe_div(equity, shares_at(history, d, factors, as_of))
        pay = bsv["payouts"]
        if mcap is not None and mcap > 0 and None not in pay.values():
            v["shareholder_yield"] = (pay["dividends"] + pay["buyback"] - pay["issued"]) / mcap  # G218 / G316
            v["buyback_yield"] = pay["buyback"] / mcap
    out = {c: _out(c, x) for c, x in v.items() if c != "roa"}
    lender = (bsv or {}).get("lender") or row.get("valuation_archetype") in ("FINANCIAL_LENDING", "INSURANCE")
    if lender:
        out.update(dict.fromkeys(NOT_FOR_LENDERS))
        out["roa"] = row.get("roa")  # lenders' own definition (fundamentals.nbfc_blocks / bank_blocks)
    else:
        roa = (bsv or {}).get("roa")
        out["roa"] = row.get("roa") if roa is None else float(roa)
    return out


# ── DSL aliases (Screener's names; money in INR crore, fractions in %) ────────────────────────────────────────────


def dsl_aliases() -> dict[str, tuple[str, str]]:
    crore = lambda col, note: (f"({col} / 10000000)", f"INR crore, {note}")  # noqa: E731
    pct = lambda col, note: (f"({col} * 100)", f"%, {note}")  # noqa: E731
    out: dict[str, tuple[str, str]] = {}
    names = {
        "debt": ["debt"], "equity_capital": ["equity capital"], "reserves": ["reserves"],
        "balance_sheet_total": ["balance sheet total", "total assets"], "net_block": ["net block"],
        "cwip": ["capital work in progress", "cwip"], "investments": ["investments"],
        "current_assets": ["current assets"], "current_liabilities": ["current liabilities"],
        "lease_liabilities": ["lease liabilities"], "inventory": ["inventory"],
        "trade_receivables": ["trade receivables"], "trade_payables": ["trade payables"],
        "cash_equivalents": ["cash equivalents"], "gross_block": ["gross block"],
        "accumulated_depreciation": ["accumulated depreciation"], "contingent_liabilities": ["contingent liabilities"],
        "advance_from_customers": ["advance from customers"], "working_capital": ["working capital"],
    }  # fmt: skip
    for col in (*BS_LINES, *ANNUAL_LINES):
        for n in names[col]:
            out[n] = crore(col, "latest balance sheet" if col in BS_LINES else "Reg. 34, last FY end")
    for line in PRECEDING_LINES:
        for n in names[line]:
            out[f"{n} preceding year"] = crore(f"{line}_preceding_year", "end of the FY before the last FY")
    for line in BACK_LINES:
        for y in BACK_YEARS:
            for n in names[line]:
                for yy in (f"{y}years", f"{y} years"):
                    out[f"{n} {yy} back"] = crore(f"{line}_{y}y_back", f"last FY end - {y} years (NULL until in scope)")
    for y in CASH_BACK_YEARS:
        for yy in (f"{y}years", f"{y} years"):
            out[f"cash {yy} back"] = crore(f"cash_{y}y_back", f"FY-end cash {y} years back (NULL until in scope)")
    cf = {"cfo": ["cash from operations", "operating cash flow"], "cfi": ["cash from investing", "investing cash flow"],
          "cff": ["cash from financing", "financing cash flow"], "net_cash_flow": ["net cash flow"],
          "cash_beginning": ["cash beginning of"], "cash_end": ["cash end of"],
          "fcf": ["free cash flow"]}  # fmt: skip
    for line, ns in cf.items():
        for k, kn in (("last_year", "last year"), ("preceding_year", "preceding year")):
            for n in ns:
                out[f"{n} {kn}"] = crore(f"{line}_{k}", f"filed FY cash flow, {kn}")
    for line in SUM_LINES:
        for y in SUM_YEARS:
            for n in cf[line]:
                for yy in (f"{y}years", f"{y} years"):
                    out[f"{n} {yy}"] = crore(f"{line}_{y}y", f"sum over {y} FYs (NULL until in scope)")
    out["face value"] = ("face_value", "INR per share")
    out["book value preceding year"] = ("book_value_preceding_year", "INR per share, today's share basis")
    for y in BOOK_BACK_YEARS:
        for yy in (f"{y}years", f"{y} years"):
            out[f"book value {yy} back"] = (f"book_value_{y}y_back", "INR per share (NULL until in scope)")
    out["graham number"] = ("graham_number", "INR per share, sqrt(22.5 x EPS x book value per share)")
    out["number of equity shares preceding year"] = ("shares_preceding_year", "count, Reg. 31, today's share basis")
    for yy in ("10years", "10 years"):
        out[f"number of equity shares {yy} back"] = ("shares_10y_back", "count (NULL until in scope)")
    plain = {
        "current ratio": ("current_ratio", "x"), "quick ratio": ("quick_ratio", "x"),
        "net debt to equity": ("net_debt_to_equity", "x"),
        "long term debt to equity": ("long_term_debt_to_equity", "x (non-current borrowings + leases)"),
        "debt to equity preceding year": ("debt_to_equity_preceding_year", "x"),
        "financial leverage": ("financial_leverage", "x, avg total assets / avg owners' equity"),
        "asset turnover": ("asset_turnover", "x, TTM sales / avg total assets"),
        "asset turnover ratio": ("asset_turnover", "x, TTM sales / avg total assets"),
        "price to free cash flow": ("price_to_fcf", "x (NULL when FCF <= 0)"),
        "price to fcf": ("price_to_fcf", "x (NULL when FCF <= 0)"),
        "net debt to ebitda": ("net_debt_to_ebitda", "x"),
        "net debt to fcf 3years": ("net_debt_to_fcf_3y", "years (mean 3-FY FCF; NULL until in scope)"),
        "inventory turnover ratio": ("inventory_turnover", "x (sales / closing inventory)"),
        "average debtor days 3years": ("avg_debtor_days_3y", "days (NULL until in scope)"),
        "average working capital days 3years": ("avg_working_capital_days_3y", "days (NULL until in scope)"),
    }  # fmt: skip
    out.update(plain)
    for y in BACK_YEARS:
        for yy in (f"{y}years", f"{y} years"):
            for n in ("inventory turnover", "inventory turnover ratio"):
                out[f"{n} {yy} back"] = (f"inventory_turnover_{y}y_back", "x (NULL until in scope)")
    for y in DEBTOR_BACK_YEARS:
        for yy in (f"{y}years", f"{y} years"):
            out[f"debtor days {yy} back"] = (f"debtor_days_{y}y_back", "days (NULL until in scope)")
    pcts = {
        "earning power": ("earning_power", "TTM EBIT / total assets"),
        "return on assets": ("roa", "TTM owners' profit / avg total assets"),
        "roe preceding year": ("roe_preceding_year", "FY-1"), "roce preceding year": ("roce_preceding_year", "FY-1"),
        "roa preceding year": ("roa_preceding_year", "FY-1, average assets"),
        "return on assets preceding year": ("roa_preceding_year", "FY-1, average assets"),
        "exports percentage": ("exports_pct", "of revenue by geography, Reg. 34"),
        "cfo to ebitda last year": ("cfo_to_ebitda_last_year", "FY"),
        "cfo to ebitda preceding year": ("cfo_to_ebitda_preceding_year", "FY"),
        "fcf conversion 3years": ("fcf_conversion_3y", "3-FY FCF / owners' profit (NULL until in scope)"),
        "cfo to ebitda 3years": ("cfo_to_ebitda_3y", "3 FYs (NULL until in scope)"),
        "equity fcf yield": ("equity_fcf_yield", "TTM FCF / market cap"),
        "fcf yield equity": ("equity_fcf_yield", "TTM FCF / market cap"),
        "shareholder yield": ("shareholder_yield", "TTM dividends + buybacks - issues / market cap"),
        "buyback yield": ("buyback_yield", "TTM buyback cash / market cap"),
        "dilution 1year": ("dilution_1y", "Reg. 31 share count change, 1 year"),
        "equity dilution 1year": ("dilution_1y", "Reg. 31 share count change, 1 year"),
        "dilution 5years": ("dilution_5y", "Reg. 31 share count change, 5 years (NULL until in scope)"),
        "equity dilution 5years": ("dilution_5y", "Reg. 31 share count change, 5 years (NULL until in scope)"),
        "reinvestment rate": ("reinvestment_rate", "of FY NOPAT"),
    }  # fmt: skip
    for n, (col, note) in pcts.items():
        out[n] = pct(col, note)
    for y in EXPORT_BACK_YEARS:
        for yy in (f"{y}years", f"{y} years"):
            out[f"exports percentage {yy} back"] = pct(f"exports_pct_{y}y_back", "NULL until in scope")
    for y in INCREMENTAL_ROIC_YEARS:
        for yy in (f"{y}year", f"{y}years", f"{y} years"):
            out[f"incremental roic {yy}"] = pct(f"incremental_roic_{y}y", "change in NOPAT / change in IC")
    return out
