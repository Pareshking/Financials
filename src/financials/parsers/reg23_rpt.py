"""Integrated Filing (Governance): Reg. 23(9) related-party transactions per counterparty -> reg23 rows [X19, X115].

Evidence (docs/references.md X19 / X115; the 27 committed Integrated Filings that carry the section, read straight
from the XML): one row per typed member of `RelatedPartyTransactionAxis` (`RelatedPartyTransactionDomain1`, ...: a
row position inside the filing, never an identity across filings). Text and amounts on the filing's own
reporting-period duration context: `NameOfListedEntityOrSubsidiaryEnteringIntoTheTransaction`, `NameOfCounterParty`,
`PANOfCounterParty` (masked "******" in 7,892 of 7,931 rows), `RelationshipOfTheCounterpartyWithTheListedEntityOr
ItsSubsidiary` (free text, 266 distinct values: kept as filed, never mapped to a category), `TypeOfRelatedParty
Transaction` (a closed list of 14 values, TYPE_MAP), `ValueOfTheRelatedPartyTransactionAsApprovedByTheAuditCommittee`,
`AmountOfRelatedPartyTransactionDuringTheReportingPeriod`; the balances as `AmountOfRelatedPartyTransaction` on two
instants: the day before the context start (opening) and the context end (closing).

Only standalone Q2 (September) and Q4 (March) filings carry the section (June / December for a calendar financial
year; 27 of 27 such fixtures; none of the other 74
parsed Integrated Filings: consolidated, Q1 or Q3). In all 27 the rows add up exactly to the undimensioned total
(`rpt_total_amount`). The context dates are the filing's reporting-period context, not a period of the disclosure:
NETWEB filed the same rows with the same amounts in an Oct-Mar and, re-filed, in a Jan-Mar context (X82).

The amounts cover the Reg. 23(9) half-year ending on the filing's period end (X160, R13 resolved): SEBI's format D
(circular 2024/185, note 4) asks for the six months ended September 30 and March 31 (or the six months of another
financial year), and the filings agree (POLYMED, CASTROLIND fixtures; 116 of 134 companies in the vault): the Q2 and
the Q4 amounts add up to the Reg. 34 Ind AS 24 year, and the Q4 opening balance is the Q2 closing balance, under a
three-month context. `disclosure_start` / `disclosure_months` record that half-year (HALF_YEAR_RULE). A few
filers put financial-year-to-date amounts and the year's opening balance in the Q4 filing instead (X161: EIDPARRY;
8 of 378 companies by balance roll-forward): nothing inside the filing says so, so the rule stays the prescribed
half-year and these rows still feed no ratio or feature column.

Rules:
- a row needs a counterparty name and a numeric amount during the period; the duration context must end on the
  filing's declared period end (a context ending elsewhere is not read: never trust context dates blindly).
- amounts are stored as filed (zeros included); text is whitespace-normalised; a PAN made only of `*` is NULL.
"""

from __future__ import annotations

import json
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from financials.parsers.indas_corp import period_months
from financials.parsers.xbrl import Instance

REG23_PARSER_VERSION = "reg23-2"  # reg23-2: disclosure_start / disclosure_months (X160)
HALF_YEAR_MONTHS = 6
AXIS = "RelatedPartyTransactionAxis"

# TypeOfRelatedPartyTransaction as filed -> canonical type: every value seen in the 27 fixtures. Another value is
# kept as filed with type `unmapped` (never guessed).
TYPE_MAP: dict[str, str] = {
    "Purchase of goods or services": "purchases",
    "Sale of goods or services": "sales",
    "Purchase of fixed assets": "purchase_of_fixed_assets",
    "Sale of fixed assets": "sale_of_fixed_assets",
    "Loan": "loan",
    "Inter-corporate deposit": "inter_corporate_deposit",
    "Advance": "advance",
    "Investment": "investment",
    "Interest paid": "interest_paid",
    "Interest received": "interest_received",
    "Dividend paid": "dividend_paid",
    "Dividend received": "dividend_received",
    "Remuneration": "remuneration",
    "Any other transaction": "other",
}
TEXT = {
    "NameOfListedEntityOrSubsidiaryEnteringIntoTheTransaction": "listed_party_name",
    "NameOfCounterParty": "counterparty_name",
    "PANOfCounterParty": "counterparty_pan",
    "RelationshipOfTheCounterpartyWithTheListedEntityOrItsSubsidiary": "relationship",
    "TypeOfRelatedPartyTransaction": "type_as_filed",
    "DetailsOfOtherRelatedPartyTransaction": "details",
    "RemarksOnApprovalByAuditCommittee": "approval_remarks",
}
# loan / inter-corporate deposit / investment and indebtedness terms: kept together as JSON text, as filed
TERMS = (
    "NatureOfTheLoansOrInterCorporateDepositsOrAdvancesOrInvestments",
    "InterestRateOfLoansOrInterCorporateDepositsOrAdvancesOrInvestments",
    "TenureOfLoansOrInterCorporateDepositsOrAdvancesOrInvestments",
    "TypeOfLoansOrInterCorporateDepositsOrAdvancesOrInvestmentsSecuredOrUnsecured",
    "PurposeForWhichTheFundsWillBeUtilisedByTheUltimateRecipientOfFundsForEndusage",
    "NatureOfFinancialIndebtedness",
    "CostOfFinancialIndebtedness",
    "TenureOfFinancialIndebtedness",
    "DetailsOfOtherIndebtedness",
)
AMOUNTS = {
    "AmountOfRelatedPartyTransactionDuringTheReportingPeriod": "amount",
    "ValueOfTheRelatedPartyTransactionAsApprovedByTheAuditCommittee": "approved_value",
    "ValueOfTheRelatedPartyTransactionRatifiedByTheAuditCommittee": "ratified_value",
}
BALANCE = "AmountOfRelatedPartyTransaction"
# Every element reg23_related_party_transactions keeps in a column of its own (disclosures.captured)
ELEMENTS = frozenset({*TEXT, *TERMS, *AMOUNTS, BALANCE})


@dataclass(frozen=True)
class Reg23Row:
    row_member: str  # typed RelatedPartyTransactionAxis member as filed
    period_start: date  # the duration context as tagged (the filing's reporting-period context; see module doc)
    period_end: date
    period_months: int | None
    disclosure_start: date  # HALF_YEAR_RULE: first day of the six months ending on period_end (X160)
    disclosure_months: int  # HALF_YEAR_MONTHS
    listed_party_name: str | None  # the listed entity or the subsidiary entering into the transaction
    counterparty_name: str
    counterparty_pan: str | None
    relationship: str | None
    type_as_filed: str | None
    txn_type: str  # TYPE_MAP values | unmapped
    details: str | None
    approval_remarks: str | None
    terms: str | None  # JSON object of TERMS as filed, or None
    amount: Decimal
    approved_value: Decimal | None
    ratified_value: Decimal | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None


def _local(x: str) -> str:
    return x.split(":")[-1]


def _clean(text: str | None) -> str | None:
    t = " ".join((text or "").split())
    return t or None


def _num(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip())
    except InvalidOperation:
        return None


def half_year_start(period_end: date) -> date:
    """HALF_YEAR_RULE (X160): the first day of the six months that end on `period_end` (SEBI format D note 4)."""
    nxt = period_end + timedelta(days=1)
    months = nxt.year * 12 + nxt.month - 1 - HALF_YEAR_MONTHS
    year, month = divmod(months, 12)
    month += 1
    return date(year, month, min(nxt.day, monthrange(year, month)[1]))


def parse_reg23_rpt(inst: Instance, period_end: date | None) -> list[Reg23Row]:
    """One row per typed member of the Reg. 23(9) section whose duration context ends on `period_end`."""
    if period_end is None:
        return []
    dur: dict[str, dict] = defaultdict(dict)
    bal: dict[str, dict[date, Decimal]] = defaultdict(dict)
    span: dict[str, tuple[date, date]] = {}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        dims = {_local(a): m for a, m in c.dimensions}
        if set(dims) != {AXIS}:
            continue
        member = dims[AXIS]
        if c.instant is not None:
            if f.name == BALANCE and (v := _num(f.value_text)) is not None:
                bal[member].setdefault(c.instant, v)
            continue
        if c.end != period_end:
            continue
        span.setdefault(member, (c.start, c.end))
        d = dur[member]
        if f.name in TEXT:
            d.setdefault(TEXT[f.name], f.value_text)
        elif f.name in TERMS:
            d.setdefault("terms", {}).setdefault(f.name, _clean(f.value_text))
        elif f.name in AMOUNTS and (v := _num(f.value_text)) is not None:
            d.setdefault(AMOUNTS[f.name], v)
    out = []
    for member, d in dur.items():
        name, amount = _clean(d.get("counterparty_name")), d.get("amount")
        if name is None or amount is None:
            continue
        start, end = span[member]
        pan = _clean(d.get("counterparty_pan"))
        kind = _clean(d.get("type_as_filed"))
        terms = {k: v for k, v in (d.get("terms") or {}).items() if v}
        out.append(
            Reg23Row(
                row_member=member,
                period_start=start,
                period_end=end,
                period_months=period_months(start, end),
                disclosure_start=half_year_start(end),
                disclosure_months=HALF_YEAR_MONTHS,
                listed_party_name=_clean(d.get("listed_party_name")),
                counterparty_name=name,
                counterparty_pan=None if pan is None or set(pan) <= {"*"} else pan,
                relationship=_clean(d.get("relationship")),
                type_as_filed=kind,
                txn_type=TYPE_MAP.get(kind or "", "unmapped"),
                details=_clean(d.get("details")),
                approval_remarks=_clean(d.get("approval_remarks")),
                terms=json.dumps(terms, sort_keys=True) if terms else None,
                amount=amount,
                approved_value=d.get("approved_value"),
                ratified_value=d.get("ratified_value"),
                opening_balance=bal[member].get(start - timedelta(days=1)),
                closing_balance=bal[member].get(end),
            )
        )
    return sorted(out, key=lambda r: _order(r.row_member))


def _order(member: str) -> tuple[int, str]:
    digits = "".join(ch for ch in member if ch.isdigit())
    return (int(digits), member) if digits else (1 << 30, member)
