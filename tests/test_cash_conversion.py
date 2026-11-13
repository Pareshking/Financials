"""Corporate cash-conversion and operating-leverage ratios [C19] on synthetic books (pure arithmetic)."""

from datetime import date
from decimal import Decimal

import pytest

from financials.fundamentals import FactBook, building_blocks, cash_conversion_blocks

D = Decimal
END = date(2026, 9, 30)
OPEN = date(2025, 9, 30)


def _quarters(end: date, n: int) -> list[tuple[date, date]]:
    out, e = [], end
    for _ in range(n):
        s = date(e.year, e.month - 2, 1)
        out.append((s, e))
        e = date(s.year, s.month - 1, 30 if s.month - 1 in (6, 9) else 31) if s.month > 1 else date(s.year - 1, 12, 31)
    return out


def _book(quarters: int = 4, growth: bool = False) -> FactBook:
    b = FactBook("e", "CONSOLIDATED")
    qs = _quarters(END, quarters)
    for i, p in enumerate(qs):
        scale = D(1) if not growth or i < 4 else D("0.8")  # the year before is 20% smaller
        for tag, v in {"revenue_from_operations": 1000, "cost_of_materials_consumed": 400,
                       "purchases_of_stock_in_trade": 0, "changes_in_inventories": 0, "pat": 60, "pbt": 80,
                       "tax_expense": 20, "profit_before_exceptional_and_tax": 80, "finance_costs": 10,
                       "depreciation_amortisation": 20, "other_income": 5}.items():  # fmt: skip
            b.durations.setdefault(tag, {})[p] = D(v) * scale
    h1, fy_prev, h1_prev = (date(2026, 4, 1), END), (date(2025, 4, 1), date(2026, 3, 31)), (date(2025, 4, 1), OPEN)
    for tag, (a, c, e) in {"cfo": (120, 250, 110), "cfi": (-50, -90, -40), "capex_ppe": (40, 80, 30)}.items():
        b.durations.setdefault(tag, {}).update({h1: D(a), fy_prev: D(c), h1_prev: D(e)})
    for d, scale in ((END, D(1)), (OPEN, D("0.9"))):
        for tag, v in {"total_assets": 2000, "total_equity": 1000, "borrowings_noncurrent": 300,
                       "borrowings_current": 100, "cash_and_equivalents": 50, "bank_balances_other": 0,
                       "current_investments": 50, "trade_receivables_current": 300, "inventories": 200,
                       "trade_payables_current": 150}.items():  # fmt: skip
            b.instants.setdefault(tag, {})[d] = D(v) * scale
    return b


def test_cash_conversion_ratios():
    book = _book()
    b = building_blocks(book, END)
    c = cash_conversion_blocks(book, END, b)
    assert b["cfo"] == D(260) and b["fcf"] == D(170)  # TTM via H1 / FY bridge: 120 + 250 - 110; capex 90
    cfi = D(-50) + D(-90) - D(-40)
    assert c["sloan_accrual"] == (D(240) - D(260) - cfi) / ((D(2000) + D(1800)) / 2)
    assert c["cfo_to_ebitda"] == D(260) / b["ebitda"]
    assert c["fcf_to_pat"] == D(170) / D(240)
    assert c["working_capital_intensity"] == (D(300) + D(200) - D(150)) / D(4000)
    assert c["net_debt_to_fcf"] == b["net_debt"] / D(170)
    assert c["cost_of_debt"] == D(40) / ((D(400) + D(360)) / 2)
    assert c["gross_ebitda_spread"] == (b["gross_profit"] - b["ebitda"]) / D(4000)


def test_yoy_ratios_stay_null_before_eight_in_scope_quarters():
    c = cash_conversion_blocks(_book(), END, building_blocks(_book(), END))
    assert c["dol"] is None and c["receivables_sales_divergence"] is None


def test_dol_and_receivables_divergence_with_history(monkeypatch):
    monkeypatch.setattr("financials.fundamentals.quarters_available_since", lambda end, n: True)
    book = _book(quarters=8, growth=True)
    b = building_blocks(book, END)
    c = cash_conversion_blocks(book, END, b)
    prev = building_blocks(book, date(2025, 9, 30))
    drev = b["rev_ops"] / prev["rev_ops"] - 1
    assert drev == D("0.25")
    assert c["dol"] == (b["ebit"] / prev["ebit"] - 1) / drev
    assert c["receivables_sales_divergence"] == (D(300) / D(270) - 1) - drev


def test_dol_guard_when_revenue_barely_moves(monkeypatch):
    monkeypatch.setattr("financials.fundamentals.quarters_available_since", lambda end, n: True)
    book = _book(quarters=8)  # flat revenue: |change| < 5%
    assert cash_conversion_blocks(book, END, building_blocks(book, END))["dol"] is None


@pytest.mark.parametrize("tag", ["cost_of_materials_consumed"])
def test_gross_spread_needs_material_cogs(tag):
    book = _book()
    for p in book.durations[tag]:
        book.durations[tag][p] = D(10)  # 1% of revenue: below the 10% materiality guard (C6)
    assert cash_conversion_blocks(book, END, building_blocks(book, END))["gross_ebitda_spread"] is None
