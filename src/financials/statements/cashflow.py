"""Cash-flow rows, Screener-style layout, from our own definitions (architecture §14b, evidence X45).

Cash flow is reported only year-to-date in Integrated Filings: H1 in the Q2 filing, FY in the Q4 filing.
Q1 / Q3 filings carry none, so every row is NULL for those quarters (never derived).
Signs: positive = cash in, as filed. Screener's Excel export carries only the four totals, so the
sub-rows below are our definitions and are checked by summation, not against golden values.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from financials.statements.quarterly import QuarterStatement, Row

ZERO = Decimal(0)

WC_GROUPS: dict[str, tuple[str, ...]] = {
    "Receivables": ("cf_wc_trade_receivables_current", "cf_wc_trade_receivables_noncurrent"),
    "Inventory": ("cf_wc_inventories",),
    "Payables": ("cf_wc_trade_payables_current", "cf_wc_trade_payables_noncurrent"),
    "Loans & Advances": (
        "cf_wc_other_current_assets",
        "cf_wc_other_noncurrent_assets",
        "cf_wc_other_financial_assets_current",
        "cf_wc_other_financial_assets_noncurrent",
        "cf_wc_other_bank_balances",
    ),
    "Other WC items": (
        "cf_wc_other_current_liabilities",
        "cf_wc_other_noncurrent_liabilities",
        "cf_wc_provisions_current",
        "cf_wc_provisions_noncurrent",
        "cf_wc_other_financial_liabilities_current",
        "cf_wc_other_financial_liabilities_noncurrent",
    ),
}


def cashflow(result, start: date, end: date) -> QuarterStatement | None:
    """Rows for the YTD cash flow of an INDAS_CORP filing; None when the filing has no cash flow."""

    def v(tag: str) -> Decimal | None:
        return result.value(tag, start, end)

    def z(tag: str) -> Decimal:
        return v(tag) or ZERO

    cfo, cfi, cff = v("cfo"), v("cfi"), v("cff")
    if cfo is None:
        return None
    rows: dict[str, Row] = {}
    wc_parts = {name: sum((z(t) for t in tags), ZERO) for name, tags in WC_GROUPS.items()}
    wc_total = sum(wc_parts.values(), ZERO)
    cgo = v("cash_generated_from_operations")
    taxes = -z("income_taxes_paid")
    pfo = None if cgo is None else cgo - wc_total
    other_op = None if cgo is None else cfo - cgo - taxes
    op_parts = {"Profit from operations": pfo, **wc_parts, "Direct taxes": taxes, "Other operating items": other_op}
    rows["Cash from Operating Activity"] = Row("Cash from Operating Activity", cfo, op_parts)
    rows["Working capital changes"] = Row("Working capital changes", wc_total, wc_parts)

    inv_named = {
        "Fixed assets purchased": -(z("capex_ppe") + z("capex_intangibles")),
        "Fixed assets sold": z("ppe_disposals"),
        "Investments purchased": -z("investments_purchased"),  # Reg. 34 annual only [X74]
        "Investments sold": z("investments_sold"),
        "Interest received": z("interest_received_investing"),
        "Dividends received": z("dividends_received_investing"),
    }
    inv_named["Other investing items"] = None if cfi is None else cfi - sum(inv_named.values(), ZERO)
    rows["Cash from Investing Activity"] = Row("Cash from Investing Activity", cfi, inv_named)

    fin_named = {
        "Proceeds from borrowings": z("borrowings_proceeds"),
        "Repayment of borrowings": -z("borrowings_repayments"),
        "Interest paid": -z("interest_paid_financing"),
        "Dividends paid": -z("dividends_paid"),
        "Lease payments": -z("lease_payments"),
        "Proceeds from shares": z("share_issue_proceeds"),
    }
    fin_named["Other financing items"] = None if cff is None else cff - sum(fin_named.values(), ZERO)
    rows["Cash from Financing Activity"] = Row("Cash from Financing Activity", cff, fin_named)
    # Net Cash Flow after the FX effect on cash, as Screener shows it [S12]; CFI stays as filed (Screener folds
    # the FX effect into CFI, which we report as the FX_IN_INVESTING divergence instead of imitating it).
    fx = z("fx_effect_on_cash")
    after_fx = v("net_cash_flow_after_fx")
    if after_fx is None and v("net_cash_flow") is not None:
        after_fx = v("net_cash_flow") + fx
    rows["Net Cash Flow"] = Row(
        "Net Cash Flow", after_fx, {"Operating": cfo, "Investing": cfi, "Financing": cff, "FX effect on cash": fx}
    )
    st = QuarterStatement("INDAS_CORP", (start, end), rows, scope_used=result.meta.get("scope"))
    if fx:
        st.divergences.append("FX_IN_INVESTING: Screener's CFI includes the FX effect on cash [S12]")
    return st
