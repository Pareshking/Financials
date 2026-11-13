"""Zero-drop line-item mapping (C24): every numeric XBRL line item becomes a canonical fact.

Curated elements keep their curated canonical tag (`revenue_from_operations`, `cfo`, ...). Every other numeric
element is stored under a deterministic key `li_<snake_case(element)>`; every numeric amount on a text-labelled
"Others"/"Details" member is stored as `oth_<amount key>__<slug(label)>`. Each fact carries a
`line_item_category` and the canonical key of its `parent_subtotal`, both derived deterministically here (the
classification rules in registry_audit.py name the category; the parent is the subtotal the line sits under).

Structural duplicates (a second element carrying the identical value of a mapped line, verified on fixtures)
are still stored, and annotated with `duplicate_of` in the registry: nothing is dropped.

What is not a line item: per-record dimensional rows (one related party, one shareholder, one segment member
without a label, one person in a Reg. 30 filing). Those are records; they live verbatim in raw_xbrl_facts and,
where parsed, in dedicated tables (shareholding_*, corporate_events, segments).
"""

from __future__ import annotations

import re

from financials.registry_audit import classify

# Verified structural duplicates: (profile, element) -> canonical key whose value it repeats [C22, X76].
STRUCTURAL_DUPLICATES = {
    ("IRDAI_LIFE", "Assets"): "total_assets",  # = ApplicationOfFunds
    ("IRDAI_GENERAL", "Assets"): "total_assets",
    ("REG34_ANNUAL", "ExceptionalItems"): "exceptional_items",  # = ExceptionalItemsBeforeTax
}

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake(name: str) -> str:
    return _CAMEL.sub("_", name).lower()


def slug(label: str) -> str:
    s = label.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60] or "unlabelled"


def line_item_key(element: str, curated: dict[str, tuple[str, str]] | None = None) -> str:
    if curated and element in curated:
        return curated[element][0]
    return "li_" + snake(element)


# reason code (registry_audit) -> line_item_category
CATEGORY_OF_REASON = {
    "PER_SHARE_DUPLICATE": "PER_SHARE",
    "OCI_SUBLINE": "OCI",
    "DERIVED_SUBTOTAL": "SUBTOTAL",
    "REGULATORY_MEMO": "MEMO",
    "NON_FINANCIAL_COUNT": "COUNT",
    "CASH_FLOW_DETAIL": "CASH_FLOW",
    "BALANCE_SHEET_DETAIL": "BALANCE_SHEET",
    "SEGMENT_DISCLOSURE": "SEGMENT",
    "DISCONTINUED_DETAIL": "DISCONTINUED",
    "INSURANCE_SCHEDULE_DETAIL": "INSURANCE_SCHEDULE",
    "ANNUAL_ASSET_MOVEMENT": "ASSET_MOVEMENT",
    "ANNUAL_TAX_NOTE": "TAX_NOTE",
    "ANNUAL_SHARE_CAPITAL_NOTE": "SHARE_CAPITAL_NOTE",
    "ANNUAL_SHARE_BASED_PAYMENT_NOTE": "SHARE_BASED_PAYMENT_NOTE",
    "ANNUAL_REMUNERATION_NOTE": "REMUNERATION_NOTE",
    "ANNUAL_EXPENSE_DETAIL": "PNL_EXPENSE",
    "ANNUAL_INCOME_DETAIL": "PNL_INCOME",
    "ANNUAL_EQUITY_NOTE": "EQUITY_NOTE",
}

# Curated canonical tags: category and parent by pattern (first match wins).
_CURATED = (
    (r"^(eps_|face_value)", "PER_SHARE", "pat"),
    (r"^(oci_|total_comprehensive)", "OCI", "total_comprehensive_income"),
    (r"^cf_adj_|^share_based_payments_addback$", "CASH_FLOW", "cf_adjustments_total"),
    (r"^cf_wc_", "CASH_FLOW", "cash_generated_from_operations"),
    (r"^(capex_|ppe_disposals|interest_received_investing|dividends_received_investing|investments_(purchased|sold))",
     "CASH_FLOW", "cfi"),
    (r"^(borrowings_(proceeds|repayments)|interest_paid_financing|dividends_paid|lease_payments|share_issue_proceeds)",
     "CASH_FLOW", "cff"),
    (r"^(cfo|cfi|cff|net_cash_flow|fx_effect|cash_generated|income_taxes_paid|interest_(paid|received)_operating"
     r"|dividends_received_operating|cf_adjustments_total|cash_cf_statement)", "CASH_FLOW", "net_cash_flow"),
    (r"^(cost_of_materials|purchases_of_stock|changes_in_inventories|employee_benefit|finance_costs"
     r"|depreciation_amortisation|other_expenses|excise_duty|power_and_fuel|freight|advertising|rnd_expense"
     r"|royalty_expense|audit_fees)", "PNL_EXPENSE", "total_expenses"),
    (r"^(revenue_from_operations|other_income)", "PNL_INCOME", "total_income"),
    (r"^(total_income|total_expenses|profit_before|pbt|tax_expense|current_tax|deferred_tax$|pat|exceptional"
     r"|share_of_associates|discontinued|regulatory_deferral)", "PNL", "pat"),
    (r"^(total_assets|current_assets|noncurrent_assets)$", "BALANCE_SHEET", "total_assets"),
    (r"^(total_equity|equity_|other_equity|non_controlling)", "BALANCE_SHEET", "total_equity"),
    (r"(liabilit|borrowings|payables|advance_from_customers|contingent)", "BALANCE_SHEET", "total_liabilities"),
    (r".*", "BALANCE_SHEET", "total_assets"),
)  # fmt: skip
_CURATED_RX = tuple((re.compile(rx), c, p) for rx, c, p in _CURATED)


def _parent_for(category: str, element: str) -> str | None:
    e = element
    if category == "CASH_FLOW":
        if "Investing" in e or e.startswith(
            ("Purchase", "ProceedsFromSales", "CashAdvances", "CashReceiptsFromRepayment")
        ):
            return "cfi"
        if "Financing" in e or e.startswith(
            ("ProceedsFromIssuing", "ProceedsFromBorrowings", "Repayments", "PaymentsOf")
        ):
            return "cff"
        if e.startswith(("Adjustments", "OtherAdjustments")):
            return "cf_adjustments_total"
        return "cfo"
    if category == "BALANCE_SHEET":
        current = "Current" in e and "Noncurrent" not in e
        if "Liabilit" in e or "Payable" in e or "Provision" in e or "Borrowing" in e:
            return "current_liabilities" if current else "total_liabilities"
        return "current_assets" if current else "total_assets"
    return {
        "PER_SHARE": "pat",
        "OCI": "oci_net",
        "SEGMENT": "revenue_from_operations",
        "DISCONTINUED": "pat_discontinued",
        "PNL_EXPENSE": "depreciation_amortisation" if re.search(r"^(Depreciation|Amortisation|Depletion)Expense", e)
        else "changes_in_inventories" if e.startswith("ChangesInInventories") or e == "ChangesInOtherInventories"
        else "employee_benefit_expense" if re.search(r"Salar|Contribution|Gratuity|Pension|Leave|Staff|"
                                                               r"EmployeeMedical|EmployeeShare|Retirement", e)
        else "finance_costs" if re.search(r"Interest|Borrowing", e) else "other_expenses",
        "PNL_INCOME": "revenue_from_operations" if re.search(r"^(Revenue|Domestic|Export|OtherOperatingRevenues)", e)
        else "other_income",
        "TAX_NOTE": "tax_expense",
        "ASSET_MOVEMENT": "ppe_net",
        "SHARE_CAPITAL_NOTE": "equity_share_capital",
        "EQUITY_NOTE": "other_equity",
        "SHARE_BASED_PAYMENT_NOTE": "share_based_payments_addback",
        "REMUNERATION_NOTE": "employee_benefit_expense",
        "INSURANCE_SCHEDULE": "pat",
    }.get(category)  # fmt: skip


def describe_key(key: str) -> dict:
    """Category / parent for a curated canonical tag (also label-rule and derived facts)."""
    cat, parent = next((c, p) for rx, c, p in _CURATED_RX if rx.search(key))
    return {"canonical_key": key, "line_item_category": cat, "parent_subtotal": None if parent == key else parent}


def describe(profile: str, element: str, curated: dict[str, tuple[str, str]] | None = None) -> dict:
    """Canonical key, category, parent subtotal and duplicate annotation for one element of one profile."""
    key = line_item_key(element, curated)
    if curated and element in curated:
        d = describe_key(key)
        cat, parent = d["line_item_category"], d["parent_subtotal"]
    else:
        reason = classify(element, profile)
        cat = CATEGORY_OF_REASON.get(reason, "UNCLASSIFIED") if reason else "UNCLASSIFIED"
        parent = _parent_for(cat, element)
    return {"canonical_key": key, "line_item_category": cat, "parent_subtotal": parent,
            "duplicate_of": STRUCTURAL_DUPLICATES.get((profile, element))}  # fmt: skip
