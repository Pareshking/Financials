"""Quarterly results rows, Screener-style layout, built from our documented definitions (architecture §12).

Each row is a top-level number plus the sub-rows it is built from, so every figure ties back to XBRL.
Row definitions were checked against user-supplied Screener exports for Q2 FY27 [S1-S7]; the two
places where Screener follows the company's PDF presentation rather than anything in the XBRL are
reported as `divergences`, never silently imitated [S3, S4].

INDAS_CORP works on `ParsedResults` (canonical tags). Bank / NBFC / life / general-insurance rows work
on the raw non-dimensional quarter facts until those parsers exist (Mandate 2 batches 4-6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from financials.parsers.xbrl import Instance

ZERO = Decimal(0)
CR = Decimal(10) ** 7


@dataclass
class Row:
    name: str
    value: Decimal | None
    parts: dict[str, Decimal | None] = field(default_factory=dict)


@dataclass
class QuarterStatement:
    profile: str
    period: tuple[date, date]
    rows: dict[str, Row]
    divergences: list[str] = field(default_factory=list)

    def crore(self, name: str) -> Decimal | None:
        v = self.rows[name].value
        return None if v is None else (v / CR).quantize(Decimal("0.01"))


def _sum(parts: dict[str, Decimal | None]) -> Decimal | None:
    vals = [v for v in parts.values() if v is not None]
    return sum(vals, ZERO) if vals else None


# --------------------------------------------------------------------------- INDAS_CORP (canonical tags)


def corp_quarter(result, start: date, end: date) -> QuarterStatement:
    """Rows for an INDAS_CORP filing. `result` is `ParsedResults` from parsers.indas_corp."""

    def v(tag: str) -> Decimal | None:
        return result.value(tag, start, end)

    def z(tag: str) -> Decimal:
        return v(tag) or ZERO

    gross, excise = v("revenue_from_operations"), z("excise_duty")
    rows: dict[str, Row] = {}
    # S1: Sales = revenue from operations net of excise (label rule X40)
    rows["Sales"] = Row("Sales", None if gross is None else gross - excise,
                        {"Revenue from operations": gross, "Less: excise duty": -excise})  # fmt: skip
    total_exp = v("total_expenses")
    dep, fin = z("depreciation_amortisation"), z("finance_costs")
    # S1: Expenses = total expenses - depreciation - finance costs - excise
    rows["Expenses"] = Row(
        "Expenses",
        None if total_exp is None else total_exp - dep - fin - excise,
        {
            "Materials consumed": v("cost_of_materials_consumed"),
            "Purchases of stock-in-trade": v("purchases_of_stock_in_trade"),
            "Change in inventories": v("changes_in_inventories"),
            "Employee cost": v("employee_benefit_expense"),
            "Other expenses (net of excise)": None if v("other_expenses") is None else v("other_expenses") - excise,
        },
    )
    rows["Operating Profit"] = Row(
        "Operating Profit",
        None if rows["Sales"].value is None or rows["Expenses"].value is None
        else rows["Sales"].value - rows["Expenses"].value,
    )  # fmt: skip
    # S2: Other income includes exceptional items (Screener folds them in; we keep them as a sub-row)
    oi = {"Other income (reported)": v("other_income"), "Exceptional items": v("exceptional_items")}
    rows["Other Income"] = Row("Other Income", _sum(oi), oi)
    rows["Depreciation"] = Row("Depreciation", v("depreciation_amortisation"))
    rows["Interest"] = Row("Interest", v("finance_costs"))
    pbt_parts = {
        "Profit before exceptional items": v("profit_before_exceptional_and_tax"),
        "Exceptional items": v("exceptional_items"),
    }
    rows["Profit before tax"] = Row("Profit before tax", v("pbt"), pbt_parts)
    rows["Tax"] = Row("Tax", v("tax_expense"), {"Current": v("current_tax"), "Deferred": v("deferred_tax")})
    pat = v("pat")
    rows["Net Profit"] = Row(
        "Net Profit",
        v("pat_owners") if v("pat_owners") is not None else pat,  # S5: owners' share
        {
            "Profit after tax (continuing)": v("pat_continuing"),
            "Regulatory deferral movement": v("regulatory_deferral_movement"),
            "Discontinued operations": v("pat_discontinued"),
            "Share of associates / JVs": v("share_of_associates_jv"),
            "Profit for the period": pat,
            "Non-controlling interests": None if v("pat_nci") is None else -v("pat_nci"),
        },
    )
    rows["EPS"] = Row("EPS", v("eps_basic"))
    st = QuarterStatement("INDAS_CORP", (start, end), rows)
    assoc = v("share_of_associates_jv")
    if assoc:
        st.divergences.append(
            "ASSOCIATES_PLACEMENT: share of associates/JVs is after PBT here; Screener adds it to Other Income "
            "and PBT when the company's PDF shows it above PBT [S3]"
        )
    return st


# --------------------------------------------------------------------------- financial profiles (raw elements)


def quarter_facts(inst: Instance, end: date) -> dict[str, Decimal]:
    """Non-dimensional numeric facts for the 3-month context ending at `end` (first occurrence wins)."""
    out: dict[str, Decimal] = {}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if c.dimensions or c.instant is not None or not f.is_numeric or c.end != end or f.name in out:
            continue
        if (c.end.year - c.start.year) * 12 + c.end.month - c.start.month + 1 != 3:
            continue
        try:
            out[f.name] = Decimal(f.value_text.strip())
        except ArithmeticError:
            continue
    return out


def _g(facts: dict[str, Decimal], *names: str) -> Decimal:
    return sum((facts.get(n, ZERO) for n in names), ZERO)


def _row(name: str, facts: dict[str, Decimal], plus: tuple[str, ...], minus: tuple[str, ...] = ()) -> Row:
    parts = {n: facts.get(n) for n in plus} | {f"Less: {n}": (-facts[n] if n in facts else None) for n in minus}
    present = any(n in facts for n in plus)
    return Row(name, (_g(facts, *plus) - _g(facts, *minus)) if present else None, parts)


def bank_quarter(facts: dict[str, Decimal]) -> QuarterStatement:
    """IntegratedFinance_Banking [S4]. Screener's 'Expenses' = operating expenses + provisions."""
    rows = {
        "Revenue": _row("Revenue", facts, ("InterestEarned",)),
        "Interest": _row("Interest", facts, ("InterestExpended",)),
        "Expenses": _row("Expenses", facts, ("OperatingExpenses", "ProvisionsOtherThanTaxAndContingencies")),
        "Other Income": _row("Other Income", facts, ("OtherIncome",)),
        "Profit before tax": _row("Profit before tax", facts, ("ProfitLossFromOrdinaryActivitiesBeforeTax",)),
        "Tax": _row("Tax", facts, ("TaxExpense",)),
        "Net Profit": _row(
            "Net Profit", facts, ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",)
        ),
        "Exceptional items": _row("Exceptional items", facts, ("ExceptionalItems",)),
    }
    st = QuarterStatement("IGAAP_BANK", (None, None), rows)
    if facts.get("ExceptionalItems"):
        st.divergences.append(
            "BANK_EXCEPTIONAL: our PBT is after exceptional items; Screener's PBT is Revenue - Interest - Expenses "
            "+ Other Income (before exceptional) while its Net Profit is after them [S4]"
        )
    return st


def _owners_or_total(facts: dict[str, Decimal]) -> str:
    owners = "ProfitOrLossAttributableToOwnersOfParent"
    return owners if owners in facts else "ProfitLossForPeriod"


def nbfc_quarter(facts: dict[str, Decimal]) -> QuarterStatement:
    """IntegratedFinance_NBFC [S5]: same shape as INDAS_CORP, revenue = RevenueFromOperations."""
    rows = {
        "Revenue": _row("Revenue", facts, ("RevenueFromOperations",)),
        "Interest": _row("Interest", facts, ("FinanceCosts",)),
        "Expenses": _row(
            "Expenses", facts, ("Expenses",), ("FinanceCosts", "DepreciationDepletionAndAmortisationExpense")
        ),
        "Other Income": _row("Other Income", facts, ("OtherIncome", "ExceptionalItemsBeforeTax")),
        "Depreciation": _row("Depreciation", facts, ("DepreciationDepletionAndAmortisationExpense",)),
        "Profit before tax": _row("Profit before tax", facts, ("ProfitBeforeTax",)),
        "Tax": _row("Tax", facts, ("TaxExpense",)),
        "Net Profit": _row("Net Profit", facts, (_owners_or_total(facts),)),
    }
    st = QuarterStatement("INDAS_NBFC", (None, None), rows)
    if facts.get("ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod"):
        st.divergences.append("ASSOCIATES_PLACEMENT [S3]")
    return st


def life_quarter(facts: dict[str, Decimal]) -> QuarterStatement:
    """IntegratedFinance_LI [S6]: policyholders' revenue account + shareholders' P&L, tax from both."""
    rows = {
        "Revenue": _row(
            "Revenue",
            facts,
            ("Income", "InvestmentIncome"),
            ("PolicyholdersAccountOtherIncome", "TransferOfFundsFromShareholdersAccount"),
        ),
        "Other Income": _row(
            "Other Income",
            facts,
            (
                "PolicyholdersAccountOtherIncome",
                "ShareholdersAccountOtherIncome",
                "TransferOfFundsFromShareholdersAccount",
            ),
        ),
        "Expenses": _row(
            "Expenses",
            facts,
            ("Expenses", "FundsForFutureAppropriation", "ShareholdersAccountExpenses"),
            ("ProvisionForTax",),
        ),
        "Profit before tax": _row("Profit before tax", facts, ("ProfitLossBeforeTax", "ProvisionForTax")),
        "Tax": _row("Tax", facts, ("ProvisionsForTaxes", "ProvisionForTax")),
        "Net Profit": _row("Net Profit", facts, ("ProfitLossAfterTaxAndExtraordinaryItems",)),
    }
    st = QuarterStatement("IRDAI_LIFE", (None, None), rows)
    st.divergences.append(
        "LIFE_TRANSFER_GROSSUP: the shareholders->policyholders transfer sits in both Other Income and Expenses "
        "(nets to zero); Screener PBT adds back policyholder-account tax [S6]"
    )
    return st


def general_quarter(facts: dict[str, Decimal]) -> QuarterStatement:
    """IntegratedFinance_GI [S7]: operating income (ex other income) + shareholders' investment income."""
    rows = {
        "Revenue": _row(
            "Revenue", facts, ("OperatingIncome", "ShareholdersAccountIncomeFromInvestments"), ("OtherIncome",)
        ),
        "Other Income": _row("Other Income", facts, ("OtherIncome", "ShareholdersAccountOtherIncome")),
        "Expenses": _row("Expenses", facts, ("OperatingExpenses", "NonOperatingExpense")),
        "Profit before tax": _row("Profit before tax", facts, ("ProfitOrLossBeforeTax",)),
        "Tax": _row("Tax", facts, ("ProvisionForTax",)),
        "Net Profit": _row("Net Profit", facts, ("ProfitLossAfterTax",)),
    }
    return QuarterStatement("IRDAI_GENERAL", (None, None), rows)


def tie_out(st: QuarterStatement) -> Decimal | None:
    """Revenue/Sales - Expenses - Interest - Depreciation + Other Income - PBT (0 means the rows reconcile)."""
    r = st.rows
    top = r.get("Sales") or r.get("Revenue")
    if top is None or top.value is None or r["Profit before tax"].value is None:
        return None
    total = top.value - (r["Expenses"].value or ZERO) + (r["Other Income"].value or ZERO)
    for k in ("Interest", "Depreciation"):
        if k in r and r[k].value is not None:
            total -= r[k].value
    if "Exceptional items" in r and r["Exceptional items"].value is not None:  # banks keep it as its own row
        total += r["Exceptional items"].value
    return total - r["Profit before tax"].value
