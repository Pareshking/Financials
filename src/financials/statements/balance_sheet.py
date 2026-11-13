"""Balance-sheet rows, Screener-style layout, from our documented definitions (architecture §14b, S10-S11).

Integrated Filings carry a balance sheet only at H1 (30 Sep) and FY (31 Mar) ends; other quarters are NULL.
Screener exports only the March balance sheet; its rows were checked against Q4 FY26 filings [S10].
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from financials.statements.quarterly import QuarterStatement, Row

ZERO = Decimal(0)


def balance_sheet(result, end: date) -> QuarterStatement | None:
    def v(tag: str) -> Decimal | None:
        return result.value(tag, end, end)

    def z(tag: str) -> Decimal:
        return v(tag) or ZERO

    assets = v("total_assets")
    if assets is None:
        return None
    rows: dict[str, Row] = {}
    dta, dtl = z("deferred_tax_assets"), z("deferred_tax_liabilities")
    netting = min(dta, dtl) if dta > 0 and dtl > 0 else ZERO  # Screener nets DTA against DTL [S10]
    total = assets - netting
    rows["Equity Capital"] = Row("Equity Capital", v("equity_share_capital"))
    rows["Reserves"] = Row("Reserves", v("other_equity"))  # owners' other equity; NCI sits in Other Liabilities
    borrow = {
        "Borrowings (non-current)": z("borrowings_noncurrent"),
        "Borrowings (current)": z("borrowings_current"),
        "Lease liabilities (non-current)": z("lease_liabilities_noncurrent"),
        "Lease liabilities (current)": z("lease_liabilities_current"),
    }
    rows["Borrowings"] = Row("Borrowings", sum(borrow.values(), ZERO), borrow)
    eq = z("equity_share_capital") + z("other_equity")
    other_liab = total - eq - rows["Borrowings"].value
    nci, tp = z("non_controlling_interest"), z("trade_payables_current")
    rows["Other Liabilities"] = Row(
        "Other Liabilities",
        other_liab,
        {"Non-controlling interest": nci, "Trade payables": tp, "Other liability items": other_liab - nci - tp},
    )
    rows["Total Liabilities"] = Row("Total Liabilities", total, {"Deferred tax netted": -netting})
    nb = {
        "Property, plant & equipment": z("ppe_net"),
        "Investment property": z("investment_property"),
        "Goodwill": z("goodwill"),
        "Other intangibles": z("other_intangibles"),
        "Right-of-use assets": z("right_of_use_assets"),
    }
    rows["Net Block"] = Row("Net Block", sum(nb.values(), ZERO), nb)
    cwip = {"Capital work in progress": z("cwip"), "Intangibles under development": z("intangibles_under_development")}
    rows["Capital Work in Progress"] = Row("Capital Work in Progress", sum(cwip.values(), ZERO), cwip)
    inv = {
        "Non-current investments": z("noncurrent_investments"),
        "Current investments": z("current_investments"),
        "Associates / JVs (equity method)": z("equity_method_investments"),
    }
    rows["Investments"] = Row("Investments", sum(inv.values(), ZERO), inv)
    oa = total - rows["Net Block"].value - rows["Capital Work in Progress"].value - rows["Investments"].value
    recv, stock = z("trade_receivables_current"), z("inventories")
    cash = z("cash_and_equivalents") + z("bank_balances_other")
    rows["Other Assets"] = Row(
        "Other Assets",
        oa,
        {"Receivables": recv, "Inventory": stock, "Cash & Bank": cash, "Other asset items": oa - recv - stock - cash},
    )
    rows["Total Assets"] = Row("Total Assets", total, {"Deferred tax netted": -netting})
    return QuarterStatement("INDAS_CORP", (end, end), rows)
