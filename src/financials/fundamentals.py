"""Point-in-time fundamentals: quarter derivation, TTM, scope continuity and building blocks.

docs/architecture.md §6 and §8. Everything is read as known at `as_of` (visible_from_ts <= as_of).
Money stays Decimal; ratios are returned as Decimal and stored as DOUBLE by the feature layer.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from financials.parsers.indas_corp import period_months
from financials.scope import financials_in_scope

Period = tuple[date, date]


def _add_months(d: date, months: int) -> date:
    """Shift a month-end (or month-start) date by whole months, keeping the end/start convention."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    is_end = d.day == calendar.monthrange(d.year, d.month)[1]
    day = calendar.monthrange(y, m)[1] if is_end else min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


@dataclass
class FactBook:
    """All facts of one entity and scope as visible at `as_of`, latest version per period."""

    entity_id: str
    scope: str
    durations: dict[str, dict[Period, Decimal]] = field(default_factory=dict)
    instants: dict[str, dict[date, Decimal]] = field(default_factory=dict)

    # ── flows ──
    def quarter(self, tag: str, end: date) -> Decimal | None:
        """3-month value ending `end`: reported, or YTD_k − YTD_{k−1} within one fiscal year (§6.2)."""
        d = self.durations.get(tag, {})
        q_start = _add_months(date(end.year, end.month, 1), -2)
        if (q_start, end) in d:
            return d[(q_start, end)]
        prev_end = _add_months(end, -3)
        for (s, e), v in d.items():
            if e == end and (s, prev_end) in d and s < q_start:
                return v - d[(s, prev_end)]
        return None

    def ttm(self, tag: str, end: date) -> Decimal | None:
        """Sum of the 4 quarters ending `end`; falls back to the YTD bridge for H1/FY-only flows."""
        qs = [self.quarter(tag, _add_months(end, -3 * i)) for i in range(4)]
        if None not in qs:
            return sum(qs, Decimal(0))
        return self.ttm_from_ytd(tag, end)

    def ttm_from_ytd(self, tag: str, end: date) -> Decimal | None:
        """Semi-annual bridge (§6.5): FY directly, else YTD_curr + FY_prev − YTD_prev."""
        d = self.durations.get(tag, {})
        for (s, e), v in d.items():
            if e != end:
                continue
            m = period_months(s, e)
            if m == 12:
                return v
            if m is None or m > 12:
                continue
            fy_prev = (_add_months(s, -12), _prev_day_month_end(s))
            ytd_prev = (_add_months(s, -12), _add_months(e, -12))
            if fy_prev in d and ytd_prev in d:
                return v + d[fy_prev] - d[ytd_prev]
        return None

    def coalesced(self, tag: str, fallback: str | None) -> str:
        """Per-period COALESCE(tag, fallback) as a derived tag, so TTM never mixes "present" and "absent" filings.

        `fallback=None` means 0: used for lines whose absence in a filing means "none reported" (excise [X40]).
        Coalescing happens per period (i.e. per filing) before any quarter/TTM arithmetic.
        """
        key = f"{tag}|{fallback or 0}"
        if key not in self.durations:
            primary = self.durations.get(tag, {})
            base = self.durations.get(fallback, {}) if fallback else self.durations.get("revenue_from_operations", {})
            out = {p: primary.get(p, base[p] if fallback else Decimal(0)) for p in base}
            out.update(primary)
            self.durations[key] = out
        return key

    def continuing_owners(self) -> str:
        """Derived tag: COALESCE(owners, total) - discontinued, per period (per filing) [C10, X52].

        Discontinued operations (Ind AS 105, incl. demerger scheme gains such as TMPV's 82,616 Cr in Q2 FY26)
        are assumed attributable to owners: the XBRL does not split NCI between continuing and discontinued.
        """
        key = "pat_owners_continuing"
        if key not in self.durations:
            owners = self.durations[self.coalesced("pat_owners", "pat")]
            disc = self.durations.get("pat_discontinued", {})
            self.durations[key] = {p: v - disc.get(p, Decimal(0)) for p, v in owners.items()}
        return key

    def latest_flow_end(self, tag: str) -> date | None:
        ends = [e for (_, e) in self.durations.get(tag, {})]
        return max(ends) if ends else None

    # ── stocks ──
    def latest_instant(self, tag: str, on_or_before: date | None = None) -> tuple[date, Decimal] | None:
        pts = sorted((d, v) for d, v in self.instants.get(tag, {}).items() if on_or_before is None or d <= on_or_before)
        return pts[-1] if pts else None


def _prev_day_month_end(d: date) -> date:
    """Month end immediately before month-start `d`."""
    prev = _add_months(date(d.year, d.month, 1), -1)
    return date(prev.year, prev.month, calendar.monthrange(prev.year, prev.month)[1])


def load_factbook(con, entity_id: str, scope: str, as_of: datetime) -> FactBook:
    rows = con.execute(
        """SELECT canonical_tag, period_type, period_start, period_end, coalesce(value_inr, value_other)
           FROM (SELECT *, row_number() OVER (
                    PARTITION BY canonical_tag, period_start, period_end
                    ORDER BY visible_from_ts DESC, parser_version DESC) AS rn
                 FROM fact_observations
                 WHERE entity_id = ? AND scope = ? AND visible_from_ts <= ?)
           WHERE rn = 1""",
        [entity_id, scope, as_of],
    ).fetchall()
    book = FactBook(entity_id, scope)
    for tag, ptype, start, end, value in rows:
        if ptype == "INSTANT":
            book.instants.setdefault(tag, {})[end] = Decimal(value)
        else:
            book.durations.setdefault(tag, {})[(start, end)] = Decimal(value)
    return book


SCOPES = ("CONSOLIDATED", "STANDALONE")
ANCHOR_TAG = "pat"  # every profile (corporate, NBFC, bank, insurer) files profit for the period


@dataclass(frozen=True)
class ScopePolicy:
    """Per-company default scopes [Mandate 3, C18]: consolidated when the company files consolidated results for its
    latest quarter (resp. financial year) visible at as-of, else standalone; a manual override wins."""

    default_quarterly_scope: str | None
    default_annual_scope: str | None
    source: str  # DERIVED | OVERRIDE | NONE


@dataclass
class ScopeDecision:
    scope: str
    book: FactBook
    reason: str  # DEFAULT | FALLBACK_DEFAULT_INCOMPLETE | OVERRIDE | YTD_BRIDGE | BALANCE_SHEET_ONLY
    policy: ScopePolicy


def scope_policy(con, entity_id: str, as_of: datetime) -> ScopePolicy:
    row = con.execute(
        "SELECT quarterly_scope, annual_scope FROM entity_scope_override WHERE entity_id = ?", [entity_id]
    ).fetchone()
    if row:
        return ScopePolicy(row[0], row[1], "OVERRIDE")
    rows = con.execute(
        """SELECT period_months, scope, period_end FROM fact_observations
           WHERE entity_id = ? AND canonical_tag = ? AND period_type = 'DURATION' AND period_months IN (3, 12)
             AND visible_from_ts <= ? GROUP BY period_months, scope, period_end""",
        [entity_id, ANCHOR_TAG, as_of],
    ).fetchall()
    ends: dict[tuple[int, str], set[date]] = {}
    for months, scope, end in rows:
        ends.setdefault((months, scope), set()).add(end)

    def complete_quarters(scope: str) -> bool:
        """All 4 trailing quarters (ending at the scope's latest quarter) filed in this scope, as 3-month facts
        or as Q4 = FY - 9M (a 12-month fact closing the year)."""
        q = ends.get((3, scope), set())
        if not q:
            return False
        last = max(q)
        need = [_add_months(last, -3 * i) for i in range(4)]
        fy = ends.get((12, scope), set())
        return all(e in q or e in fy for e in need)

    def pick(months: int) -> str | None:
        cons, stand = ends.get((months, "CONSOLIDATED")), ends.get((months, "STANDALONE"))
        if not cons and not stand:
            return None
        if months == 3 and cons and stand and not complete_quarters("CONSOLIDATED") and complete_quarters("STANDALONE"):
            # Cadence mismatch: consolidated only at H1 / FY, standalone every quarter -> quarterly default STANDALONE
            return "STANDALONE"
        return "CONSOLIDATED" if cons and (not stand or max(cons) >= max(stand)) else "STANDALONE"

    quarterly = pick(3)
    annual = pick(12) or quarterly
    return ScopePolicy(quarterly, annual, "DERIVED" if quarterly or annual else "NONE")


def _anchor(book: FactBook) -> str:
    return ANCHOR_TAG if ANCHOR_TAG in book.durations else "revenue_from_operations"


def _has_quarters(book: FactBook, end: date, quarters: int) -> bool:
    tag = _anchor(book)
    return all(book.quarter(tag, _add_months(end, -3 * i)) is not None for i in range(quarters))


def resolve_scope(con, entity_id: str, as_of: datetime, end: date, *, quarters: int = 4) -> ScopeDecision | None:
    """One scope for the whole TTM window, never a mix of standalone and consolidated quarters (§6.4).

    1. The default quarterly scope, if it has all `quarters` quarters.
    2. Otherwise the other scope, only if *it* has all of them (reason FALLBACK_DEFAULT_INCOMPLETE).
    3. Otherwise a TTM via the H1 / FY bridge in the default scope, then the other one (YTD_BRIDGE).
    4. Otherwise the latest balance sheet in the default scope, then the other (BALANCE_SHEET_ONLY): no flow ratios.
    A manual override pins the scope and is never silently replaced: if it lacks data the decision is None.
    """
    policy = scope_policy(con, entity_id, as_of)
    if policy.default_quarterly_scope is None and policy.source != "OVERRIDE":
        order = list(SCOPES)
    else:
        first = policy.default_quarterly_scope or "CONSOLIDATED"
        order = [first] if policy.source == "OVERRIDE" else [first, *[s for s in SCOPES if s != first]]
    books = {s: load_factbook(con, entity_id, s, as_of) for s in order}
    default_reason = "OVERRIDE" if policy.source == "OVERRIDE" else "DEFAULT"
    for i, s in enumerate(order):
        if _has_quarters(books[s], end, quarters):
            return ScopeDecision(s, books[s], default_reason if i == 0 else "FALLBACK_DEFAULT_INCOMPLETE", policy)
    for s in order:
        if books[s].ttm(_anchor(books[s]), end) is not None:
            return ScopeDecision(s, books[s], "YTD_BRIDGE", policy)
    for s in order:
        if books[s].latest_instant("total_assets", end) is not None:
            return ScopeDecision(s, books[s], "BALANCE_SHEET_ONLY", policy)
    return None


def choose_scope(con, entity_id: str, as_of: datetime, end: date, *, quarters: int = 4) -> tuple[str, FactBook] | None:
    """Backward-compatible wrapper: (scope, book) of `resolve_scope`, excluding balance-sheet-only decisions."""
    d = resolve_scope(con, entity_id, as_of, end, quarters=quarters)
    if d is None or d.reason == "BALANCE_SHEET_ONLY":
        return None
    return d.scope, d.book


def safe_div(a: Decimal | None, b: Decimal | None, *, positive_denominator: bool = True) -> Decimal | None:
    if a is None or b is None or b == 0 or (positive_denominator and b < 0):
        return None
    return a / b


def _sum(*vals: Decimal | None) -> Decimal | None:
    return None if any(v is None for v in vals) else sum(vals, Decimal(0))  # type: ignore[arg-type]


def _sum_present(*vals: Decimal | None) -> Decimal | None:
    """Sum of the lines a balance sheet reports; NULL only if it reports none of them."""
    got = [v for v in vals if v is not None]
    return sum(got, Decimal(0)) if got else None


def building_blocks(book: FactBook, end: date) -> dict[str, Decimal | date | None]:
    """Canonical blocks (§8) for the TTM window ending `end` and the latest balance sheet <= end."""
    t = lambda tag: book.ttm(tag, end)  # noqa: E731
    gross_rev = t("revenue_from_operations")
    # Net of excise duty when the filing labels an excise line [X40]; absent label = no excise.
    excise = t(book.coalesced("excise_duty", None))
    rev = None if gross_rev is None or excise is None else gross_rev - excise
    materials, purchases, inv_change = (
        t("cost_of_materials_consumed"),
        t("purchases_of_stock_in_trade"),
        t("changes_in_inventories"),
    )
    gross_profit = None
    if None not in (rev, materials, purchases, inv_change) and rev and materials + purchases >= Decimal("0.10") * rev:
        gross_profit = rev - (materials + purchases + inv_change)
    pbeit, fin, dep, oth = (
        t("profit_before_exceptional_and_tax"),
        t("finance_costs"),
        t("depreciation_amortisation"),
        t("other_income"),
    )
    ebitda = None if None in (pbeit, fin, dep, oth) else pbeit + fin + dep - oth
    ebit = None if ebitda is None or dep is None else ebitda - dep
    pbt, tax = t("pbt"), t("tax_expense")
    etr = Decimal(0)
    if pbt is not None and tax is not None and pbt > 0 and tax >= 0:
        etr = min(max(tax / pbt, Decimal(0)), Decimal("0.5"))
    nopat = None if ebit is None else ebit * (1 - etr)

    bs = book.latest_instant("total_assets", end)
    bs_as_of = bs[0] if bs else None

    def stock(tag: str) -> Decimal | None:
        if bs_as_of is None:
            return None
        return book.instants.get(tag, {}).get(bs_as_of)

    borrowings = _sum(stock("borrowings_noncurrent"), stock("borrowings_current"))
    # Lease liabilities from labelled "Others" lines [X39], added exactly once; absent label = none reported.
    leases = (stock("lease_liabilities_noncurrent") or Decimal(0)) + (stock("lease_liabilities_current") or Decimal(0))
    debt = None if borrowings is None else borrowings + leases
    cash = _sum(stock("cash_and_equivalents"), stock("bank_balances_other"), stock("current_investments"))
    equity = stock("total_equity")
    net_debt = None if debt is None or cash is None else debt - cash
    invested = None if None in (equity, debt, cash) else equity + debt - cash

    cfo_end = book.latest_flow_end("cfo")
    cf_end = cfo_end if cfo_end is not None and cfo_end <= end else None
    cfo = book.ttm_from_ytd("cfo", cf_end) if cf_end else None
    capex = None
    if cf_end:
        ppe = book.ttm_from_ytd("capex_ppe", cf_end)
        intang = book.ttm_from_ytd("capex_intangibles", cf_end) or Decimal(0)
        capex = None if ppe is None else ppe + intang
    fcf = None if cfo is None or capex is None else cfo - capex
    fcff = None
    if fcf is not None:
        ip = book.ttm_from_ytd("interest_paid_operating", cf_end) or Decimal(0)
        ir = book.ttm_from_ytd("interest_received_operating", cf_end) or Decimal(0)
        fcff = fcf + ip * (1 - etr) - ir * (1 - etr)

    return {
        "rev_ops": rev,
        "gross_revenue": gross_rev,
        "excise_duty": excise,
        "lease_liabilities": leases if bs_as_of is not None else None,
        "gross_profit": gross_profit,
        "ebitda": ebitda,
        "ebit": ebit,
        "pat": t("pat"),
        # Profit for PE / ROE: owners' share when the filing attributes profit (consolidated) [X42]
        # COALESCE(owners, total) per filing before the 4-quarter roll-up, so a mixed window stays non-NULL
        "pat_owners": t(book.coalesced("pat_owners", "pat")),
        # PE earnings: owners' profit from continuing operations (excludes Ind AS 105 / demerger gains) [C10]
        "pat_owners_continuing": t(book.continuing_owners()),
        # Core earnings: continuing owners' profit less exceptional items net of tax (at the TTM effective rate,
        # since the filing does not tag the tax on exceptional items) [C14]
        "core_continuing_profit": _core(t(book.continuing_owners()), t(book.coalesced("exceptional_items", None)), etr),
        "other_income": oth,
        "pbt": pbt,
        "etr": etr,
        "nopat": nopat,
        "total_debt": debt,
        "cash_liquid": cash,
        "net_debt": net_debt,
        "total_equity": equity,
        "equity_owners": stock("equity_attributable_to_owners") or equity,
        "minority_interest": stock("non_controlling_interest") or (Decimal(0) if equity is not None else None),
        # Investments = non-current + current + equity-method (associates/JVs) [X44]. invested_capital is
        # financing-side (equity + debt - cash), so associate stakes are already inside it; adding them again
        # would double count. Operating IC removes them to match NOPAT, which excludes associates' profit.
        "investments": _sum_present(
            stock("noncurrent_investments"), stock("current_investments"), stock("equity_method_investments")
        ),
        "equity_method_investments": stock("equity_method_investments"),
        "invested_capital": invested,
        # ROIC denominator: (opening + closing) / 2 over 12 months [C16]; NULL without the opening balance sheet
        "avg_invested_capital": _avg_invested(book, bs_as_of, invested),
        "operating_invested_capital": None
        if invested is None
        else invested - (stock("equity_method_investments") or Decimal(0)),
        "total_assets": stock("total_assets"),
        "current_assets": stock("current_assets"),
        "current_liabilities": stock("current_liabilities"),
        "total_liabilities": stock("total_liabilities"),
        "other_equity": stock("other_equity"),
        "cfo": cfo,
        "capex": capex,
        "fcf": fcf,
        "fcff": fcff,
        "bs_as_of": bs_as_of,
        "cf_as_of": cf_end if cfo is not None else None,
    }


def invested_capital_at(book: FactBook, d: date) -> Decimal | None:
    """equity + borrowings + labelled leases - liquid cash, on balance-sheet date `d` (same definition as §8)."""
    g = lambda tag: book.instants.get(tag, {}).get(d)  # noqa: E731
    borrowings = _sum(g("borrowings_noncurrent"), g("borrowings_current"))
    cash = _sum(g("cash_and_equivalents"), g("bank_balances_other"), g("current_investments"))
    equity = g("total_equity")
    if None in (borrowings, cash, equity):
        return None
    leases = (g("lease_liabilities_noncurrent") or Decimal(0)) + (g("lease_liabilities_current") or Decimal(0))
    return equity + borrowings + leases - cash


def _avg_invested(book: FactBook, closing_date: date | None, closing: Decimal | None) -> Decimal | None:
    if closing_date is None or closing is None:
        return None
    opening = invested_capital_at(book, _add_months(closing_date, -12))
    return None if opening is None else (opening + closing) / 2


CASH_CONVERSION_COLUMNS = (
    "sloan_accrual", "cfo_to_ebitda", "fcf_to_pat", "working_capital_intensity", "receivables_sales_divergence",
    "net_debt_to_fcf", "cost_of_debt", "dol", "gross_ebitda_spread",
)  # fmt: skip
DOL_MIN_REVENUE_CHANGE = Decimal("0.05")


def debt_at(book: FactBook, d: date) -> Decimal | None:
    g = lambda tag: book.instants.get(tag, {}).get(d)  # noqa: E731
    borrowings = _sum(g("borrowings_noncurrent"), g("borrowings_current"))
    if borrowings is None:
        return None
    return (
        borrowings + (g("lease_liabilities_noncurrent") or Decimal(0)) + (g("lease_liabilities_current") or Decimal(0))
    )


def cash_conversion_blocks(book: FactBook, end: date, b: dict) -> dict:
    """Corporate cash-conversion and operating-leverage ratios (architecture §10.1b) [C19]. Industrial books only
    (callers NULL them for lenders / insurers). Averages are (opening + closing) / 2 over 12 months; YoY ratios need
    8 in-scope quarters (C9) and stay NULL until then."""
    out = dict.fromkeys(CASH_CONVERSION_COLUMNS)
    t = lambda tag: book.ttm(tag, end)  # noqa: E731
    rev, ebitda, cfo, fcf = b["rev_ops"], b["ebitda"], b["cfo"], b["fcf"]
    cf_end = b["cf_as_of"]
    # Cash flow is filed only at H1 / FY: align P&L numerators to the same 12-month window ending at cf_end, so a
    # Q1 / Q3 as-of never divides a Sep-ending CFO by a Dec-ending EBITDA [C19].
    cfw = building_blocks(book, cf_end) if cf_end else None
    if cfw is not None:
        cfi = book.ttm_from_ytd("cfi", cf_end)
        taxes = book.ttm_from_ytd("income_taxes_paid", cf_end) or Decimal(0)
        avg_assets, _, _ = average_instant(book, "total_assets", cf_end)
        if None not in (cfw["pat"], cfo, cfi, avg_assets) and avg_assets:
            out["sloan_accrual"] = (cfw["pat"] - cfo - cfi) / avg_assets
        if cfw["ebitda"] is not None and cfw["ebitda"] > 0 and cfo is not None:
            out["cfo_to_ebitda"] = (cfo + taxes) / cfw["ebitda"]  # pre-tax CFO vs EBITDA (both before tax)
        if cfw["pat"] is not None and cfw["pat"] > 0:
            out["fcf_to_pat"] = safe_div(fcf, cfw["pat"])
    bs = b["bs_as_of"]
    stock = lambda tag, d=bs: book.instants.get(tag, {}).get(d) if d else None  # noqa: E731
    recv, inv, pay = stock("trade_receivables_current"), stock("inventories"), stock("trade_payables_current")
    if None not in (recv, inv, pay) and rev:
        out["working_capital_intensity"] = (recv + inv - pay) / rev
    if fcf is not None and fcf > 0 and b["net_debt"] is not None:
        out["net_debt_to_fcf"] = b["net_debt"] / fcf
    closing, opening = b["total_debt"], (debt_at(book, _add_months(bs, -12)) if bs else None)
    fin = t("finance_costs")
    if None not in (closing, opening, fin) and closing + opening > 0:
        out["cost_of_debt"] = fin / ((closing + opening) / 2)
    if b["gross_profit"] is not None and rev and ebitda is not None:  # gross profit already needs COGS >= 10% (C6)
        out["gross_ebitda_spread"] = (b["gross_profit"] - ebitda) / rev
    if quarters_available_since(end, 8):
        prev = building_blocks(book, _add_months(end, -12))
        rev0, ebit0, ebit = prev["rev_ops"], prev["ebit"], b["ebit"]
        if None not in (rev, rev0, ebit, ebit0) and rev0 > 0 and ebit0 > 0:  # EBIT_{t-4} > 0 guard
            drev = rev / rev0 - 1
            if abs(drev) >= DOL_MIN_REVENUE_CHANGE:  # guard: DOL explodes when revenue barely moves
                out["dol"] = (ebit / ebit0 - 1) / drev
        recv0 = book.instants.get("trade_receivables_current", {}).get(_add_months(bs, -12)) if bs else None
        if None not in (recv, recv0, rev, rev0) and recv0 > 0 and rev0 > 0:
            out["receivables_sales_divergence"] = (recv / recv0 - 1) - (rev / rev0 - 1)
    return out


REVERSE_DCF_WACC = 0.12
REVERSE_DCF_TERMINAL_G = 0.04
REVERSE_DCF_YEARS = 5


def reverse_dcf_implied_growth(
    ev: float | None,
    fcff: float | None,
    *,
    wacc: float = REVERSE_DCF_WACC,
    terminal_g: float = REVERSE_DCF_TERMINAL_G,
    years: int = REVERSE_DCF_YEARS,
) -> float | None:
    """Growth g of FCFF over `years` that makes the DCF value equal EV [C20]:
    EV = sum_{t=1..n} F(1+g)^t / (1+w)^t + F(1+g)^n (1+tg) / ((w - tg)(1+w)^n).
    NULL when FCFF <= 0 or EV <= 0, or when no g in [-95%, +300%] reproduces EV. Ratios, so floats are fine."""
    if ev is None or fcff is None or ev <= 0 or fcff <= 0 or wacc <= terminal_g:
        return None

    def value(g: float) -> float:
        pv = sum(fcff * (1 + g) ** t / (1 + wacc) ** t for t in range(1, years + 1))
        return pv + fcff * (1 + g) ** years * (1 + terminal_g) / ((wacc - terminal_g) * (1 + wacc) ** years)

    lo, hi = -0.95, 3.0
    if not value(lo) <= ev <= value(hi):
        return None
    for _ in range(200):  # value(g) is increasing in g for F > 0: bisection
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if value(mid) < ev else (lo, mid)
    return round((lo + hi) / 2, 6)


def percentile_rank(current: float | None, history: list[float], *, min_periods_required: int = 4) -> float | None:
    """Share of the security's own prior quarter-end values <= current [C20]; positive values only (a negative PE
    or EV/EBITDA has no valuation meaning); NULL with fewer than `min_periods_required` prior quarters."""
    if current is None or current <= 0:
        return None
    hist = [h for h in history if h is not None and h > 0]
    if len(hist) < min_periods_required:
        return None
    return sum(h <= current for h in hist) / len(hist)


NEWGEN_INPUT_KEYS = (
    "liquid_cash", "ex_cash_earnings", "billings_ttm", "billings_growth_pct", "esop_ttm", "esop_adj_ebitda",
    "rule_of_40", "neg_working_capital_float_pct", "net_burn_multiple", "cash_runway_months", "esop_adj_fcf",
)  # fmt: skip


def contract_liabilities_at(book: FactBook, d: date | None) -> Decimal | None:
    if d is None:
        return None
    c = book.instants.get("contract_liabilities_current", {}).get(d)
    n = book.instants.get("contract_liabilities_noncurrent", {}).get(d)
    return None if c is None and n is None else (c or Decimal(0)) + (n or Decimal(0))


def newgen_inputs(book: FactBook, end: date, b: dict) -> dict:
    """Ingredients for the new-gen tech ratios (architecture §10.8) [C21]; EV / market-cap ratios finish in features.

    Liquid cash = cash + other bank balances + current investments: non-current investments are excluded because
    holding stakes dominate them (Info Edge 50,773 Cr of listed Zomato / PB Fintech shares, X68). ESOP cost exists only
    as the H1 / FY cash-flow add-back (X68), so ESOP-based ratios use the cash-flow window. Contract liabilities exist
    only where labelled (5/10 of Batch 7); billings ratios are NULL otherwise."""
    out = dict.fromkeys(NEWGEN_INPUT_KEYS)
    bs = b["bs_as_of"]
    g = lambda tag: book.instants.get(tag, {}).get(bs) if bs else None  # noqa: E731
    cash = [g("cash_and_equivalents"), g("bank_balances_other"), g("current_investments")]
    out["liquid_cash"] = None if all(v is None for v in cash) else sum((v or Decimal(0)) for v in cash)
    cont, oi = b["pat_owners_continuing"], b["other_income"]
    if cont is not None and oi is not None:
        out["ex_cash_earnings"] = cont - oi * (1 - b["etr"])
    rev, fcf = b["rev_ops"], b["fcf"]
    cl, cl0 = contract_liabilities_at(book, bs), contract_liabilities_at(book, _add_months(bs, -12) if bs else None)
    if None not in (rev, cl, cl0):
        out["billings_ttm"] = rev + (cl - cl0)
    cf_end = b["cf_as_of"]
    esop = book.ttm_from_ytd("share_based_payments_addback", cf_end) if cf_end else None
    out["esop_ttm"] = esop
    if esop is not None:
        cfw = building_blocks(book, cf_end)
        if cfw["ebitda"] is not None:
            out["esop_adj_ebitda"] = cfw["ebitda"] + esop
        if fcf is not None:
            out["esop_adj_fcf"] = fcf - esop
    pay, recv, inv = g("trade_payables_current"), g("trade_receivables_current"), g("inventories")
    if None not in (pay, recv) and rev:
        out["neg_working_capital_float_pct"] = ((pay + (cl or Decimal(0))) - (recv + (inv or Decimal(0)))) / rev
    if fcf is not None and fcf < 0 and out["liquid_cash"] is not None:
        out["cash_runway_months"] = out["liquid_cash"] / (-fcf / 12)
    if quarters_available_since(end, 8):
        prev = building_blocks(book, _add_months(end, -12))
        rev0 = prev["rev_ops"]
        if rev is not None and rev0 and rev0 > 0 and b["ebitda"] is not None:
            out["rule_of_40"] = (rev / rev0 - 1) + b["ebitda"] / rev
            if fcf is not None and fcf < 0 and rev > rev0:
                out["net_burn_multiple"] = -fcf / (rev - rev0)
            cl_2y = contract_liabilities_at(book, _add_months(bs, -24) if bs else None)
            if None not in (cl0, cl_2y, out["billings_ttm"]):
                billings0 = rev0 + (cl0 - cl_2y)
                if billings0 > 0:
                    out["billings_growth_pct"] = out["billings_ttm"] / billings0 - 1
    return out


def _core(continuing: Decimal | None, exceptional: Decimal | None, etr: Decimal) -> Decimal | None:
    if continuing is None or exceptional is None:
        return None
    return continuing - exceptional * (1 - etr)


def average_instant(book: FactBook, tag: str, end: date) -> tuple[Decimal | None, date | None, date | None]:
    """(opening + closing) / 2 over the 12 months to `end`: needs both balance sheets, else NULL.
    Returns (average, opening date, closing date) for provenance."""
    closing = book.instants.get(tag, {}).get(end)
    opening_date = _add_months(end, -12)
    opening = book.instants.get(tag, {}).get(opening_date)
    if closing is None or opening is None:
        return None, None, end if closing is not None else None
    return (opening + closing) / 2, opening_date, end


def nbfc_blocks(book: FactBook, end: date) -> dict:
    """Lending ratios for INDAS_NBFC books (architecture §10.5) [X55, C13]. All flows TTM; averages need the
    balance sheet 12 months earlier. GNPA / NNPA / PCR are NULL: the NBFC taxonomy has no such elements [X54]."""
    from financials.parsers.indas_nbfc import INTEREST_TO_REVENUE_MIN, LOANS_TO_ASSETS_MIN

    empty = dict.fromkeys(NBFC_COLUMNS)
    if "interest_earned" not in book.durations:
        return empty
    t = lambda tag: book.ttm(tag, end)  # noqa: E731
    interest, fin, rev = t("interest_earned"), t("finance_costs"), t("revenue_from_operations")
    other, exp, imp = (
        t("other_income"),
        t("total_expenses"),
        t(book.coalesced("impairment_financial_instruments", None)),
    )
    nii = None if None in (interest, fin) else interest - fin
    opex = None if None in (exp, fin, imp) else exp - fin - imp
    income_net = None if None in (rev, other, fin) else rev + other - fin  # net total income
    ppop = None if None in (income_net, opex) else income_net - opex
    bs = book.latest_instant("total_assets", end)
    bs_date = bs[0] if bs else None
    loans = book.instants.get("loans", {}).get(bs_date) if bs_date else None
    if loans is not None and bs and bs[1]:
        lending = loans / bs[1] >= LOANS_TO_ASSETS_MIN
    elif interest is not None and rev:
        lending = interest / rev >= INTEREST_TO_REVENUE_MIN
    else:
        lending = None
    avg_loans, loans_from, loans_to = average_instant(book, "loans", end)
    avg_assets, _, _ = average_instant(book, "total_assets", end)
    owners = t(book.coalesced("pat_owners", "pat"))
    out = {
        "is_lending_nbfc": lending,
        "nii_ttm": nii,
        "ppop_ttm": ppop,
        "cost_to_income": safe_div(opex, income_net),
        "credit_cost": safe_div(imp, avg_loans),
        "nim_asset_proxy": safe_div(nii, avg_assets),
        "roa": safe_div(owners, avg_assets),
        "loans": loans,
        "loans_as_of": loans_to,
        "loans_avg_from": loans_from,
        "gnpa_pct": None,
        "nnpa_pct": None,
        "pcr": None,
    }
    if lending is False:  # investment holding company: lending ratios do not apply [C13]
        for k in ("nii_ttm", "ppop_ttm", "cost_to_income", "credit_cost", "nim_asset_proxy"):
            out[k] = None
    return out


def bank_blocks(book: FactBook, end: date, regulatory: FactBook | None = None) -> dict:
    """Bank ratios (architecture §10.5) [X58-X61]. `regulatory` is the STANDALONE book: GNPA / NNPA / CET1 / AT1 /
    filed RoA are standalone disclosures (consolidated filings carry 0 placeholders, dropped by X60)."""
    empty = dict.fromkeys(NBFC_COLUMNS + BANK_COLUMNS)
    if "interest_expended" not in book.durations:
        return empty
    t = lambda tag: book.ttm(tag, end)  # noqa: E731
    interest, expended, other = t("interest_earned"), t("interest_expended"), t("other_income")
    opex, ppop, prov = t("operating_expenses"), t("ppop"), t("provisions")
    nii = None if None in (interest, expended) else interest - expended
    avg_adv, adv_from, adv_to = average_instant(book, "advances", end)
    avg_assets, _, _ = average_instant(book, "total_assets", end)
    bs = book.latest_instant("total_assets", end)
    bs_date = bs[0] if bs else None
    adv = book.instants.get("advances", {}).get(bs_date) if bs_date else None
    dep = book.instants.get("deposits", {}).get(bs_date) if bs_date else None
    reg = regulatory or book
    latest = lambda tag: _latest_period_value(reg, tag, end)  # noqa: E731
    gnpa, nnpa = latest("gross_npa"), latest("net_npa")
    out = dict(empty)
    out.update({
        "nii_ttm": nii, "ppop_ttm": ppop,
        "cost_to_income": safe_div(opex, None if None in (nii, other) else nii + other),
        "credit_cost": safe_div(prov, avg_adv), "nim_asset_proxy": safe_div(nii, avg_assets),
        "roa": safe_div(t(book.coalesced("pat_owners", "pat")), avg_assets),
        "loans": adv, "loans_as_of": adv_to if adv_to else bs_date, "loans_avg_from": adv_from,
        "gnpa_pct": latest("gnpa_pct"), "nnpa_pct": latest("nnpa_pct"),
        "pcr": None if gnpa is None or nnpa is None or not gnpa else (gnpa - nnpa) / gnpa,
        "credit_to_deposit": safe_div(adv, dep), "cet1_pct": latest("cet1_ratio"), "at1_pct": latest("at1_ratio"),
        "roa_filed": latest("roa_filed"), "govt_holding_pct": latest("govt_holding_pct"),
        "_bank_revenue": interest,
    })  # fmt: skip
    return out


def _latest_period_value(book: FactBook, tag: str, end: date) -> Decimal | None:
    """Value for the most recent period ending on/before `end` (quarter context preferred over YTD)."""
    d = book.durations.get(tag, {})
    cands = sorted(((e, -(e - s).days, v) for (s, e), v in d.items() if e <= end), reverse=True)
    return cands[0][2] if cands else None


INSURER_COLUMNS = (
    "insurer_basis", "net_premium_earned_ttm", "insurance_revenue_ttm", "claims_ratio", "expense_ratio",
    "combined_ratio", "solvency_ratio", "investment_income_ttm", "persistency_13m", "persistency_61m",
)  # fmt: skip


def insurer_basis(book: FactBook) -> str | None:
    if "insurance_revenue" in book.durations:
        return "INDAS117"
    if "net_premium_earned" in book.durations:
        return "IRDAI_GENERAL"
    if "net_surplus" in book.durations:
        return "IRDAI_LIFE"
    return None


def insurer_blocks(book: FactBook, end: date) -> dict:
    """Insurer ratios (architecture §10.6) [X62-X66]. TTM flows; regulatory ratios as filed for the latest period.
    IRDAI general: claims = incurred / NPE, expense = (net commission + opex) / NPW, combined = sum (matches the
    filed CombinedRatio exactly, X66). Ind AS 117: claims = incurred claims / insurance revenue (gross of
    reinsurance), combined = (service expenses - net reinsurance result) / insurance revenue: a different basis,
    flagged by `insurer_basis`, never compared with IRDAI ratios. Life insurers have no claims / combined ratio."""
    out = dict.fromkeys(INSURER_COLUMNS)
    basis = insurer_basis(book)
    if basis is None:
        return out
    t = lambda tag: book.ttm(tag, end)  # noqa: E731
    latest = lambda tag: _latest_period_value(book, tag, end)  # noqa: E731
    out["insurer_basis"] = basis
    if basis == "IRDAI_GENERAL":
        npe, npw, claims = t("net_premium_earned"), t("net_premium_written"), t("claims_incurred")
        comm, opex = t("net_commission"), t("operating_expenses_insurance")
        cr = safe_div(claims, npe)
        er = safe_div(None if None in (comm, opex) else comm + opex, npw)
        out.update(net_premium_earned_ttm=npe, claims_ratio=cr, expense_ratio=er,
                   combined_ratio=None if None in (cr, er) else cr + er)  # fmt: skip
        inv = (t("investment_income_policyholders"), t("investment_income_shareholders"))
    elif basis == "IRDAI_LIFE":
        out["net_premium_earned_ttm"] = t("net_premium")
        out["expense_ratio"] = safe_div(t("expenses_of_management"), t("gross_premium"))
        out["persistency_13m"], out["persistency_61m"] = latest("persistency_13m"), latest("persistency_61m")
        inv = (t("investment_income_policyholders"), t("investment_income_shareholders"))
    else:
        rev, claims = t("insurance_revenue"), t("claims_incurred")
        ise, re = t("insurance_service_expenses"), t("net_reinsurance_result")
        out.update(insurance_revenue_ttm=rev, claims_ratio=safe_div(claims, rev),
                   combined_ratio=safe_div(None if None in (ise, re) else ise - re, rev))  # fmt: skip
        inv = (t("investment_income_total_indas"),)
    out["investment_income_ttm"] = None if None in inv else sum(inv, Decimal(0))
    out["solvency_ratio"] = latest("solvency_ratio_times")
    return out


BANK_COLUMNS = ("credit_to_deposit", "cet1_pct", "at1_pct", "roa_filed", "govt_holding_pct")

NBFC_COLUMNS = (
    "is_lending_nbfc", "nii_ttm", "ppop_ttm", "cost_to_income", "credit_cost", "nim_asset_proxy", "roa", "loans",
    "loans_as_of", "loans_avg_from", "gnpa_pct", "nnpa_pct", "pcr",
)  # fmt: skip


def quarters_available_since(end: date, quarters: int) -> bool:
    """True if the oldest quarter a window needs ends on/after the v1 cutoff [C9]."""
    oldest_quarter_end = _add_months(end, -3 * (quarters - 1))
    return financials_in_scope(oldest_quarter_end)


def cagr(book: FactBook, tag: str, end: date, years: int, *, min_periods_required: int | None = None) -> Decimal | None:
    """TTM-on-TTM compound growth over `years`. NULL (never a partial-window number) unless the full
    history exists: 4 * (years + 1) quarters by default, all ending on/after the v1 cutoff."""
    required = min_periods_required or 4 * (years + 1)
    if years < 1 or not quarters_available_since(end, required):
        return None
    cur, prev = book.ttm(tag, end), book.ttm(tag, _add_months(end, -12 * years))
    if cur is None or prev is None or cur <= 0 or prev <= 0:
        return None
    return (cur / prev) ** (Decimal(1) / Decimal(years)) - 1


def yoy_growth(book: FactBook, tag: str, end: date) -> Decimal | None:
    """TTM vs TTM a year earlier; needs 8 same-scope quarters (§6.4)."""
    if not quarters_available_since(end, 8):
        return None
    cur, prev = book.ttm(tag, end), book.ttm(tag, _add_months(end, -12))
    if cur is None or prev is None or prev <= 0:
        return None
    return cur / prev - 1


def altman_z_double_prime(blocks: dict) -> Decimal | None:
    """Z'' = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4 (§10.2).

    X2 uses OtherEquity as a retained-earnings proxy (quarterly XBRL has no retained-earnings tag).
    """
    ta, ca, cl, tl = (
        blocks["total_assets"],
        blocks["current_assets"],
        blocks["current_liabilities"],
        blocks["total_liabilities"],
    )
    re_, ebit, eq = blocks["other_equity"], blocks["ebit"], blocks["total_equity"]
    if None in (ta, ca, cl, tl, re_, ebit, eq) or not ta or not tl:
        return None
    x1, x2, x3, x4 = (ca - cl) / ta, re_ / ta, ebit / ta, eq / tl
    return Decimal("3.25") + Decimal("6.56") * x1 + Decimal("3.26") * x2 + Decimal("6.72") * x3 + Decimal("1.05") * x4


# ── Annual (Reg. 34 / FY) ratios [C23] ───────────────────────────────────────────────────────────────
ANNUAL_COLUMNS = (
    "piotroski_f", "beneish_m", "capex_to_depreciation", "cwip_to_gross_block", "rote",
    "rnd_and_royalty_intensity", "contingent_liabilities_to_net_worth", "annual_fy_end",
)  # fmt: skip
BENEISH = {"const": Decimal("-4.84"), "DSRI": Decimal("0.920"), "GMI": Decimal("0.528"), "AQI": Decimal("0.404"),
           "SGI": Decimal("0.892"), "DEPI": Decimal("0.115"), "SGAI": Decimal("-0.172"), "TATA": Decimal("4.679"),
           "LVGI": Decimal("-0.327")}  # fmt: skip
_COGS = ("cost_of_materials_consumed", "purchases_of_stock_in_trade", "changes_in_inventories")


def latest_fiscal_year(book: FactBook, on_or_before: date) -> tuple[date, date] | None:
    """Latest 12-month PAT period ending on or before `on_or_before`."""
    fys = [p for p in book.durations.get("pat", {}) if period_months(*p) == 12 and p[1] <= on_or_before]
    return max(fys, key=lambda p: p[1]) if fys else None


def _fy(book: FactBook, tag: str, p: tuple[date, date]) -> Decimal | None:
    return book.durations.get(tag, {}).get(p)


def _at(book: FactBook, tag: str, d: date) -> Decimal | None:
    return book.instants.get(tag, {}).get(d)


def _year(book: FactBook, p: tuple[date, date]) -> dict[str, Decimal | None]:
    """One fiscal year's inputs: flows for period `p`, balances at its end."""
    end = p[1]
    rev = _fy(book, "revenue_from_operations", p)
    cogs_parts = [_fy(book, t, p) for t in _COGS]
    cogs = sum((c or Decimal(0) for c in cogs_parts), Decimal(0))  # Schedule III omits nil lines [C23]
    capex_ppe, capex_int = _fy(book, "capex_ppe", p), _fy(book, "capex_intangibles", p)
    return {
        "rev": rev, "pat": _fy(book, "pat", p), "cfo": _fy(book, "cfo", p),
        "gross_margin": None if not rev else (rev - cogs) / rev,
        "dep": _fy(book, "depreciation_amortisation", p), "sga": _fy(book, "other_expenses", p),
        "capex": None if capex_ppe is None else capex_ppe + (capex_int or Decimal(0)),
        "rnd": _fy(book, "rnd_expense", p), "royalty": _fy(book, "royalty_expense", p),
        "ta": _at(book, "total_assets", end), "ca": _at(book, "current_assets", end),
        "cl": _at(book, "current_liabilities", end), "ppe": _at(book, "ppe_net", end),
        "ltd": _at(book, "borrowings_noncurrent", end), "rec": _at(book, "trade_receivables_current", end),
        "share_capital": _at(book, "equity_share_capital", end),
        "equity_owners": _at(book, "equity_attributable_to_owners", end) or _at(book, "total_equity", end),
        "pat_owners": _fy(book, "pat_owners", p) or _fy(book, "pat", p),
        "goodwill": _at(book, "goodwill", end), "intangibles": _at(book, "other_intangibles", end),
        "cwip": _at(book, "cwip", end), "gross_block": _at(book, "ppe_gross_block", end),
        "contingent": _at(book, "contingent_liabilities", end),
    }  # fmt: skip


def piotroski_f(t: dict, p: dict) -> int | None:
    """Piotroski (2000) F-score, 0..9. Assets are year-end, not beginning-of-year: the original needs the balance
    sheet two years back, which is before the data cutoff for FY26 [C9, C23]. Every one of the nine signals needs
    its inputs; one missing input makes the score NULL, never a partial score. LTD = non-current borrowings."""
    need = ("pat", "cfo", "ta", "ltd", "ca", "cl", "share_capital", "gross_margin", "rev")
    if any(t[k] is None for k in need) or any(p[k] is None for k in need) or not t["ta"] or not p["ta"]:
        return None
    if not t["cl"] or not p["cl"]:
        return None
    roa_t, roa_p = t["pat"] / t["ta"], p["pat"] / p["ta"]
    signals = (
        roa_t > 0,
        t["cfo"] > 0,
        roa_t > roa_p,
        t["cfo"] > t["pat"],
        t["ltd"] / t["ta"] < p["ltd"] / p["ta"],
        t["ca"] / t["cl"] > p["ca"] / p["cl"],
        t["share_capital"] <= p["share_capital"],
        t["gross_margin"] > p["gross_margin"],
        t["rev"] / t["ta"] > p["rev"] / p["ta"],
    )
    return sum(int(s) for s in signals)


def beneish_m(t: dict, p: dict) -> Decimal | None:
    """Beneish (1999) 8-variable M-score. SG&A proxy = Ind AS `OtherExpenses` (no SG&A line exists) [C23].
    NULL when any ratio's inputs are missing or a denominator is zero."""
    try:
        idx = {
            "DSRI": (t["rec"] / t["rev"]) / (p["rec"] / p["rev"]),
            "GMI": p["gross_margin"] / t["gross_margin"],
            "AQI": (1 - (t["ca"] + t["ppe"]) / t["ta"]) / (1 - (p["ca"] + p["ppe"]) / p["ta"]),
            "SGI": t["rev"] / p["rev"],
            "DEPI": (p["dep"] / (p["dep"] + p["ppe"])) / (t["dep"] / (t["dep"] + t["ppe"])),
            "SGAI": (t["sga"] / t["rev"]) / (p["sga"] / p["rev"]),
            "TATA": (t["pat"] - t["cfo"]) / t["ta"],
            "LVGI": ((t["cl"] + t["ltd"]) / t["ta"]) / ((p["cl"] + p["ltd"]) / p["ta"]),
        }
    except (TypeError, ZeroDivisionError, ArithmeticError):
        return None
    return BENEISH["const"] + sum(BENEISH[k] * v for k, v in idx.items())


def annual_ratios(book: FactBook, on_or_before: date) -> dict:
    """Annual-statement ratios for the latest fiscal year visible in `book` [C23]."""
    out: dict = dict.fromkeys(ANNUAL_COLUMNS)
    fy = latest_fiscal_year(book, on_or_before)
    if fy is None:
        return out
    t = _year(book, fy)
    prior = (_add_months(fy[0], -12), _add_months(fy[1], -12))
    p = _year(book, prior) if latest_fiscal_year(book, prior[1]) == prior else None
    tangible = None
    if t["equity_owners"] is not None and t["ta"] is not None:
        # Schedule III omits nil lines: no goodwill/intangibles line on a filed balance sheet means none [C23]
        tangible = t["equity_owners"] - (t["goodwill"] or 0) - (t["intangibles"] or 0)
    rnd_royalty = None if t["rnd"] is None and t["royalty"] is None else (t["rnd"] or 0) + (t["royalty"] or 0)
    out.update(
        annual_fy_end=fy[1],
        piotroski_f=piotroski_f(t, p) if p else None,
        beneish_m=beneish_m(t, p) if p else None,
        capex_to_depreciation=safe_div(t["capex"], t["dep"]),
        cwip_to_gross_block=safe_div(t["cwip"], t["gross_block"]),
        rote=safe_div(t["pat_owners"], tangible) if tangible is not None and tangible > 0 else None,
        rnd_and_royalty_intensity=safe_div(rnd_royalty, t["rev"]),
        contingent_liabilities_to_net_worth=safe_div(t["contingent"], t["equity_owners"])
        if t["equity_owners"] and t["equity_owners"] > 0
        else None,
    )
    return out


# ── Screener export conventions [S22] ────────────────────────────────────────────────────────────────
SCREENER_CONVENTION_COLUMNS = (
    "roce_screener", "debtor_days", "inventory_turnover", "working_capital",
    "inventory_days", "days_payable", "cash_conversion_cycle", "working_capital_days",
)  # fmt: skip


class _BookAsResult:
    """Lets the parity-tested statement builders (statements/*) read a FactBook: same rows, same definitions."""

    def __init__(self, book: FactBook) -> None:
        self.book = book
        self.meta = {"scope": book.scope}

    def value(self, tag: str, start: date, end: date) -> Decimal | None:
        if start == end:
            return self.book.instants.get(tag, {}).get(end)
        return self.book.durations.get(tag, {}).get((start, end))


def screener_convention_ratios(book: FactBook, on_or_before: date) -> dict:
    """Screener's export formulas (template v2.1) on our Screener-style rows, latest fiscal year [S22]:
    ROCE = (PBT + Interest) x 2 / (opening + closing (Equity Capital + Reserves + Borrowings));
    Debtor Days = closing Debtors / (Sales / 365); Inventory Turnover = Sales / closing Inventory;
    Working Capital = Other Assets - Other Liabilities (rupees). Kept beside our own ratios, not instead of them:
    `roce` excludes other income and uses closing capital.

    Days ratios on the same Sales denominator as the export's Debtor Days [S23, our definitions; the website's
    are UNVERIFIED]: Inventory Days = closing Inventory / (Sales / 365); Days Payable = closing trade payables /
    (Sales / 365); Cash Conversion Cycle = Debtor + Inventory - Payable days (differs from the website for TCS:
    72 vs 93, the website leaves inventory and payable days blank); Working Capital Days = (current assets - cash &
    bank - current investments - current liabilities) / (Sales / 365), observed to match the website on TCS.
    Schedule III omits nil lines, so a filed balance sheet without an inventory or payables line means 0 days
    [C23]."""
    from financials.statements.balance_sheet import balance_sheet
    from financials.statements.quarterly import corp_quarter

    out: dict = dict.fromkeys(SCREENER_CONVENTION_COLUMNS)
    fy = latest_fiscal_year(book, on_or_before)
    if fy is None:
        return out
    res = _BookAsResult(book)
    pl, bs = corp_quarter(res, *fy), balance_sheet(res, fy[1])
    if bs is None:
        return out
    sales = pl.rows["Sales"].value
    oa = bs.rows["Other Assets"]
    if oa.value is not None and bs.rows["Other Liabilities"].value is not None:
        out["working_capital"] = oa.value - bs.rows["Other Liabilities"].value
    if sales and sales > 0:
        recv, stock = oa.parts.get("Receivables"), oa.parts.get("Inventory")
        out["debtor_days"] = recv / (sales / 365) if recv is not None else None
        out["inventory_turnover"] = sales / stock if stock else None
        per_day = sales / 365
        payables = bs.rows["Other Liabilities"].parts.get("Trade payables")
        out["inventory_days"] = stock / per_day if stock is not None else None
        out["days_payable"] = payables / per_day if payables is not None else None
        parts = (out["debtor_days"], out["inventory_days"], out["days_payable"])
        if None not in parts:
            out["cash_conversion_cycle"] = parts[0] + parts[1] - parts[2]
        ca, cl = (
            book.instants.get("current_assets", {}).get(fy[1]),
            book.instants.get("current_liabilities", {}).get(fy[1]),
        )
        if ca is not None and cl is not None:
            # (current assets - cash & bank - current investments - current liabilities): fits Screener's website
            # Working Capital Days for TCS FY25 (34.1 vs 34) and FY26 (38.4 vs 38) [S23]
            liquid = oa.parts.get("Cash & Bank", Decimal(0)) + bs.rows["Investments"].parts.get(
                "Current investments", Decimal(0)
            )
            out["working_capital_days"] = (ca - liquid - cl) / per_day

    def capital(b):
        vals = [b.rows[k].value for k in ("Equity Capital", "Reserves", "Borrowings")]
        return None if None in vals else sum(vals, Decimal(0))

    prev = balance_sheet(res, _add_months(fy[1], -12))
    pbt, interest = pl.rows["Profit before tax"].value, pl.rows["Interest"].value
    if prev is not None and None not in (pbt, interest):
        c0, c1 = capital(prev), capital(bs)
        if c0 is not None and c1 is not None and c0 + c1 > 0:
            out["roce_screener"] = (pbt + interest) * 2 / (c0 + c1)
    return out
