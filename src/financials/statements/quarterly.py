"""Quarterly results rows, Screener-style layout, built from our documented definitions (architecture §12).

Each row is a top-level number plus the sub-rows it is built from, so every figure ties back to XBRL.
Row definitions were checked against user-supplied Screener exports for Q2 FY27 [S1-S7]; the two
places where Screener follows the company's PDF presentation rather than anything in the XBRL are
reported as `divergences`, never silently imitated [S3, S4].

INDAS_CORP works on `ParsedResults` (canonical tags). Bank / NBFC / life / general-insurance rows work
on their own parsers' canonical tags (Batches 4-6); `quarter_facts` remains for inspection scripts.
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
    scope_used: str | None = None  # CONSOLIDATED | STANDALONE, from the filing [C18]

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
            # Labelled manufacturing lines where the filer discloses them [X50]; None = not disclosed
            "Power and fuel": v("power_and_fuel"),
            "Freight": v("freight"),
            "Other expenses (rest, net of excise)": None
            if v("other_expenses") is None
            else v("other_expenses") - excise - z("power_and_fuel") - z("freight"),
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
    rows["EPS"] = eps_row(result, start, end)
    st = QuarterStatement("INDAS_CORP", (start, end), rows, scope_used=result.meta.get("scope"))
    _eps_divergence(st, result)
    assoc = v("share_of_associates_jv")
    if assoc:
        st.divergences.append(
            "ASSOCIATES_PLACEMENT: share of associates/JVs is after PBT here; Screener adds it to Other Income "
            "and PBT when the company's PDF shows it above PBT [S3]"
        )
    if v("regulatory_deferral_movement"):
        st.divergences.append(
            "REGULATORY_DEFERRAL_PLACEMENT: the regulatory deferral movement is after tax here; Screener adds it to "
            "Other Income and PBT (Tata Power) [S16]"
        )
    if v("pat_discontinued"):
        st.divergences.append(
            "DISCONTINUED_PLACEMENT: discontinued operations are after continuing PAT here; Screener adds them to "
            "Other Income and PBT (TMPV demerger gain 82,616 Cr) [S16]"
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


def bank_quarter(result, start: date, end: date) -> QuarterStatement:
    """IGAAP_BANK rows from the bank parser (canonical tags) [S4, X58]. Screener's 'Expenses' = operating expenses
    + provisions; our PBT is after exceptional items, which stay a row of their own (BANK_EXCEPTIONAL)."""

    def v(tag: str) -> Decimal | None:
        return result.value(tag, start, end)

    opex, prov = v("operating_expenses"), v("provisions")
    interest, expended = v("interest_earned"), v("interest_expended")
    gnpa, nnpa = v("gross_npa"), v("net_npa")
    rows = {
        "Revenue": Row("Revenue", interest, {
            "Interest on advances / bills": v("interest_on_advances"),
            "Income on investments": v("income_on_investments"),
            "Interest on RBI / inter-bank balances": v("interest_on_rbi_interbank"),
            "Other interest": v("other_interest"),
        }),
        "Interest": Row("Interest", expended),
        "Expenses": Row("Expenses", None if opex is None or prov is None else opex + prov, {
            "Employee cost": v("employee_benefit_expense"), "Other operating expenses": v("other_operating_expenses"),
            "Provisions and contingencies": prov,
        }),
        "Other Income": Row("Other Income", v("other_income")),
        "Exceptional items": Row("Exceptional items", v("exceptional_items")),
        "Profit before tax": Row("Profit before tax", v("pbt")),
        "Tax": Row("Tax", v("tax_expense")),
        "Net Profit": Row("Net Profit", v("pat_owners") if v("pat_owners") is not None else v("pat"), {
            "Profit for the period": v("pat"), "Extraordinary items": v("extraordinary_items"),
            "Share of associates": v("share_of_associates_jv"),
            "Minority interest": None if v("pat_nci") is None else -v("pat_nci"),
        }),
        "NII": Row("NII", None if None in (interest, expended) else interest - expended),
        "PPOP": Row("PPOP", v("ppop")),
        "GNPA %": Row("GNPA %", v("gnpa_pct"), {"Gross NPA": gnpa}),
        "NNPA %": Row("NNPA %", v("nnpa_pct"), {"Net NPA": nnpa}),
        "PCR": Row("PCR", None if gnpa is None or nnpa is None or not gnpa else (gnpa - nnpa) / gnpa),
        "EPS": eps_row(result, start, end),
    }  # fmt: skip
    st = QuarterStatement("IGAAP_BANK", (start, end), rows, scope_used=result.meta.get("scope"))
    if v("exceptional_items"):
        st.divergences.append(
            "BANK_EXCEPTIONAL: our PBT is after exceptional items; Screener's PBT is Revenue - Interest - Expenses "
            "+ Other Income (before exceptional) while its Net Profit is after them [S4]"
        )
    _eps_divergence(st, result)
    return st


def nbfc_quarter(result, start: date, end: date) -> QuarterStatement:
    """INDAS_NBFC rows from the Division III parser (canonical tags) [S5, X55]. Screener-compatible top rows plus
    lender rows: NII, PPOP and credit cost (impairment on financial instruments)."""

    def v(tag: str) -> Decimal | None:
        return result.value(tag, start, end)

    def z(tag: str) -> Decimal:
        return v(tag) or ZERO

    exp, fin, dep = v("total_expenses"), z("finance_costs"), z("depreciation_amortisation")
    oi = {"Other income (reported)": v("other_income"), "Exceptional items": v("exceptional_items")}
    rev_parts = {
        "Interest earned": v("interest_earned"), "Fees and commission": v("fee_commission_income"),
        "Net gain on fair value changes": v("net_gain_fair_value"), "Dividend": v("dividend_income"),
        "Rental": v("rental_income"), "Gain on derecognition": v("net_gain_derecognition"),
        "Sale of products": v("sale_of_products"), "Sale of services": v("sale_of_services"),
        "Other operating revenue": v("other_operating_revenue"),
    }  # fmt: skip
    opex_parts = {
        "Fees and commission expense": v("fee_commission_expense"),
        "Net loss on fair value changes": v("net_loss_fair_value"),
        "Loss on derecognition": v("net_loss_derecognition"),
        "Impairment on financial instruments": v("impairment_financial_instruments"),
        "Employee cost": v("employee_benefit_expense"),
        "Materials / inventory": _sum({"m": v("cost_of_materials_consumed"), "p": v("purchases_of_stock_in_trade"),
                                       "c": v("changes_in_inventories")}),
        "Other expenses": v("other_expenses"),
    }  # fmt: skip
    interest, rev, other = v("interest_earned"), v("revenue_from_operations"), z("other_income")
    imp = z("impairment_financial_instruments")
    nii = None if interest is None else interest - fin
    opex = None if exp is None else exp - fin - imp
    ppop = None if None in (rev, opex) else rev + other - fin - opex
    pat = v("pat")
    rows = {
        "Revenue": Row("Revenue", rev, rev_parts),
        "Interest": Row("Interest", v("finance_costs")),
        "Expenses": Row("Expenses", None if exp is None else exp - fin - dep, opex_parts),
        "Other Income": Row("Other Income", _sum(oi), oi),
        "Depreciation": Row("Depreciation", v("depreciation_amortisation")),
        "Profit before tax": Row("Profit before tax", v("pbt")),
        "Tax": Row("Tax", v("tax_expense"), {"Current": v("current_tax"), "Deferred": v("deferred_tax")}),
        "Net Profit": Row("Net Profit", v("pat_owners") if v("pat_owners") is not None else pat,
                          {"Profit for the period": pat, "Share of associates / JVs": v("share_of_associates_jv"),
                           "Non-controlling interests": None if v("pat_nci") is None else -v("pat_nci")}),
        "NII": Row("NII", nii, {"Interest earned": interest, "Less: finance costs": -fin}),
        "PPOP": Row("PPOP", ppop, {"Net total income": None if rev is None else rev + other - fin,
                                   "Less: operating expenses": None if opex is None else -opex}),
        "Credit cost": Row("Credit cost", v("impairment_financial_instruments")),
        "EPS": eps_row(result, start, end),
    }  # fmt: skip
    st = QuarterStatement("INDAS_NBFC", (start, end), rows, scope_used=result.meta.get("scope"))
    if v("share_of_associates_jv"):
        st.divergences.append(
            "ASSOCIATES_PLACEMENT: share of associates/JVs is after PBT here; Screener adds it to Other Income "
            "and PBT [S3]"
        )
    _eps_divergence(st, result)
    return st


def eps_row(result, start: date, end: date) -> Row:
    """Effective EPS [X53, C15]: COALESCE(NULLIF(filed, 0), owners' profit / period-end shares). Filed values are
    kept as sub-rows; period-end shares (paid-up / face value) differ from weighted-average shares, so the computed
    value is an approximation used only when the filing has no usable EPS."""

    def v(tag: str) -> Decimal | None:
        return result.value(tag, start, end)

    shares = result.value("shares_from_paid_up", end, end)
    owners = v("pat_owners") if v("pat_owners") is not None else v("pat")
    continuing = None if owners is None else owners - (v("pat_discontinued") or ZERO)
    computed = None if owners is None or not shares else owners / shares
    computed_cont = None if continuing is None or not shares else continuing / shares
    filed, filed_cont = v("eps_basic"), v("eps_basic_continuing")
    effective = filed if filed else computed
    effective_cont = filed_cont if filed_cont else computed_cont
    return Row("EPS", effective, {
        "Filed EPS": filed, "Computed (owners' profit / period-end shares)": computed,
        "Filed continuing EPS": filed_cont, "Continuing EPS (effective)": effective_cont,
    })  # fmt: skip


def _eps_divergence(st: QuarterStatement, result) -> None:
    for w in result.meta.get("warnings", []):
        if w["code"] == "EPS_INCONSISTENT":
            st.divergences.append(f"EPS_INCONSISTENT: filed {w['filed']} vs computed {w['computed']} [X53]")


def life_quarter(result, start: date, end: date) -> QuarterStatement:
    """IRDAI_LIFE rows from the insurer parser [S6, X62]: policyholders' revenue account + shareholders' P&L."""

    def z(tag: str) -> Decimal:
        return result.value(tag, start, end) or ZERO

    v = lambda tag: result.value(tag, start, end)  # noqa: E731
    ph_tax = z("tax_policyholders")
    rev = None if v("total_income") is None else (
        z("total_income") - z("other_income_policyholders") - z("transfer_from_shareholders")
        + z("investment_income_shareholders")
    )  # fmt: skip
    rows = {
        "Revenue": Row("Revenue", rev, {
            "Net premium": v("net_premium"), "Investment income (policyholders)": v("investment_income_policyholders"),
            "Investment income (shareholders)": v("investment_income_shareholders"),
        }),
        "Other Income": Row("Other Income", z("other_income_policyholders") + z("other_income")
                            + z("transfer_from_shareholders")),
        "Expenses": Row("Expenses", None if v("total_expenses") is None else (
            z("total_expenses") - ph_tax + z("funds_for_future_appropriation_flow") + z("shareholders_expenses")), {
            "Benefits paid (net)": v("benefits_paid_net"),
            "Change in actuarial liability": v("change_in_actuarial_liability"),
            "Expenses of management": v("expenses_of_management"),
        }),
        "Profit before tax": Row("Profit before tax", None if v("pbt") is None else z("pbt") + ph_tax,
                                 {"Shareholders' PBT": v("pbt"), "Policyholders' tax": ph_tax}),
        "Tax": Row("Tax", z("tax_expense") + ph_tax),
        "Net Profit": Row("Net Profit", v("pat")),
        "Net surplus (policyholders)": Row("Net surplus (policyholders)", v("net_surplus")),
        "EPS": eps_row(result, start, end),
    }  # fmt: skip
    st = QuarterStatement("IRDAI_LIFE", (start, end), rows, scope_used=result.meta.get("scope"))
    st.divergences.append(
        "LIFE_TRANSFER_GROSSUP: the shareholders->policyholders transfer sits in both Other Income and Expenses "
        "(nets to zero); Screener PBT adds back policyholder-account tax [S6]"
    )
    return st


def general_quarter(result, start: date, end: date) -> QuarterStatement:
    """IRDAI_GENERAL rows from the insurer parser [S7, X63]."""

    def z(tag: str) -> Decimal:
        return result.value(tag, start, end) or ZERO

    v = lambda tag: result.value(tag, start, end)  # noqa: E731
    rev = None if v("operating_income") is None else (
        z("operating_income") - z("other_income_policyholders") + z("investment_income_shareholders")
    )  # fmt: skip
    rows = {
        "Revenue": Row("Revenue", rev, {
            "Net premium earned": v("net_premium_earned"),
            "Investment income (policyholders)": v("investment_income_policyholders"),
            "Investment income (shareholders)": v("investment_income_shareholders"),
        }),
        "Other Income": Row("Other Income", z("other_income_policyholders") + z("other_income")),
        "Expenses": Row("Expenses", None if v("operating_expenses") is None else
                        z("operating_expenses") + z("shareholders_expenses"), {
            "Claims incurred": v("claims_incurred"), "Net commission": v("net_commission"),
            "Operating expenses (insurance)": v("operating_expenses_insurance"),
            "Shareholders' expenses": v("shareholders_expenses"),
        }),
        "Profit before tax": Row("Profit before tax", v("pbt")),
        "Tax": Row("Tax", v("tax_expense")),
        "Net Profit": Row("Net Profit", v("pat")),
        "Underwriting result": Row("Underwriting result", v("underwriting_result")),
        "EPS": eps_row(result, start, end),
    }  # fmt: skip
    return QuarterStatement("IRDAI_GENERAL", (start, end), rows, scope_used=result.meta.get("scope"))


def indas_insurance_quarter(result, start: date, end: date) -> QuarterStatement:
    """INDAS_INSURANCE (Ind AS 117) rows [X64]. Not comparable with IRDAI-format rows: revenue is insurance revenue
    (not premium), expenses are insurance service expenses, and reinsurance is a separate net line."""
    v = lambda tag: result.value(tag, start, end)  # noqa: E731
    rows = {
        "Insurance revenue": Row("Insurance revenue", v("insurance_revenue"),
                                 {"PAA": v("insurance_revenue_paa"), "Non-PAA": v("insurance_revenue_non_paa")}),
        "Insurance service expenses": Row("Insurance service expenses", v("insurance_service_expenses"), {
            "Incurred claims": v("claims_incurred"),
            "Adjustments to incurred-claims liabilities": v("adjustments_to_lic"),
            "Commission": v("commission"), "Employee cost": v("employee_benefit_expense"),
            "Other": v("other_insurance_service_expenses"),
            "Acquisition cash-flow amortisation": v("acquisition_cash_flow_amortisation"),
            "Onerous contracts": v("onerous_contract_losses"),
        }),
        "Net reinsurance result": Row("Net reinsurance result", v("net_reinsurance_result")),
        "Insurance service result": Row("Insurance service result", v("insurance_service_result")),
        "Net finance result": Row("Net finance result", v("net_finance_result"),
                                  {"Investment income": v("investment_income_total_indas")}),
        "Other income / expenses (net)": Row("Other income / expenses (net)", v("other_revenue_expenses_net")),
        "Exceptional items": Row("Exceptional items", v("exceptional_items")),
        "Profit before tax": Row("Profit before tax", v("pbt")),
        "Net Profit": Row("Net Profit", v("pat")),
        "EPS": eps_row(result, start, end),
    }  # fmt: skip
    return QuarterStatement("INDAS_INSURANCE", (start, end), rows, scope_used=result.meta.get("scope"))


def indas_insurance_tie_out(st: QuarterStatement) -> Decimal | None:
    """Revenue - service expenses + net reinsurance + net finance + other + exceptional - PBT (0 = rows reconcile)."""
    r = {k: (row.value or ZERO) for k, row in st.rows.items() if k != "EPS"}
    if st.rows["Insurance revenue"].value is None or st.rows["Profit before tax"].value is None:
        return None
    return (r["Insurance revenue"] - r["Insurance service expenses"] + r["Net reinsurance result"]
            + r["Net finance result"] + r["Other income / expenses (net)"] + r["Exceptional items"]
            - r["Profit before tax"])  # fmt: skip


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
