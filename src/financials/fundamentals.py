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


def choose_scope(con, entity_id: str, as_of: datetime, end: date, *, quarters: int = 4) -> tuple[str, FactBook] | None:
    """CONSOLIDATED when `quarters` consecutive consolidated quarters exist, else STANDALONE (§6.4)."""
    for scope in ("CONSOLIDATED", "STANDALONE"):
        book = load_factbook(con, entity_id, scope, as_of)
        if all(book.quarter("revenue_from_operations", _add_months(end, -3 * i)) is not None for i in range(quarters)):
            return scope, book
    for scope in ("CONSOLIDATED", "STANDALONE"):  # H1/FY-only reporters (TTM via YTD bridge)
        book = load_factbook(con, entity_id, scope, as_of)
        if book.ttm("revenue_from_operations", end) is not None:
            return scope, book
    return None


def safe_div(a: Decimal | None, b: Decimal | None, *, positive_denominator: bool = True) -> Decimal | None:
    if a is None or b is None or b == 0 or (positive_denominator and b < 0):
        return None
    return a / b


def _sum(*vals: Decimal | None) -> Decimal | None:
    return None if any(v is None for v in vals) else sum(vals, Decimal(0))  # type: ignore[arg-type]


def building_blocks(book: FactBook, end: date) -> dict[str, Decimal | date | None]:
    """Canonical blocks (§8) for the TTM window ending `end` and the latest balance sheet <= end."""
    t = lambda tag: book.ttm(tag, end)  # noqa: E731
    rev = t("revenue_from_operations")
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

    debt = _sum(stock("borrowings_noncurrent"), stock("borrowings_current"))
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
        "gross_profit": gross_profit,
        "ebitda": ebitda,
        "ebit": ebit,
        "pat": t("pat"),
        "other_income": oth,
        "pbt": pbt,
        "etr": etr,
        "nopat": nopat,
        "total_debt": debt,
        "cash_liquid": cash,
        "net_debt": net_debt,
        "total_equity": equity,
        "invested_capital": invested,
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


def yoy_growth(book: FactBook, tag: str, end: date) -> Decimal | None:
    """TTM vs TTM a year earlier; needs 8 same-scope quarters (or both YTD bridges) (§6.4)."""
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
