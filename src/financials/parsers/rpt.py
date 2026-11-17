"""Reg. 34 annual XBRL: the Ind AS 24 related-party schedule -> related_party_transactions rows [X113].

Evidence (docs/references.md X113; the eight committed AR_XBRL fixtures, vault scan 2026-11-16): the schedule is one
two-dimensional table of the MCA Ind AS taxonomy. Each row is one context pair per fiscal year:
`CategoriesOfRelatedPartiesAxis` (explicit member: `SubsidiariesMember`, `AssociatesMember`, `ParentMember`,
`JointControlOrSignificantInfluenceMember`, `KeyManagementPersonnelOfEntityOrParentMember`,
`OtherRelatedPartiesMember`, ...) x `RelatedPartyAxis` (typed member `C1`, `C2`, ...: a row position inside the
filing, never an identity across filings). Text on the year's duration context: `NameOfRelatedParty`,
`PermanentAccountNumberOfRelatedParty`, `CINOfRelatedParty`, `CountryOfIncorporationOrResidenceOfRelatedParty`,
`DescriptionOfNatureOfRelatedPartyRelationship`, `DescriptionOfNatureOfTransactionsWithRelatedParty`. Amounts:
one element per transaction kind on the duration context (`PurchasesOfGoodsRelatedPartyTransactions`, ...) and
the year-end balances on the instant context (`AmountsPayable/ReceivableRelatedPartyTransactions`).

Rules:
- `FLOW_ELEMENTS` / `BALANCE_ELEMENTS` map each verified element to a canonical type (TXN_TYPES); every other
  element of the schedule (provisions for doubtful debts, outstanding commitments) is not a transaction and stays
  in disclosure_facts (as filed) and the vault blob. Amounts are stored as filed (zeros included: "filed as nil" is
  not "not filed").
- royalties are the taxonomy's licence transfers: `TransfersUnderLicenseAgreementsToEntity...` (the entity pays,
  `royalty`) and `...FromEntity...` (`royalty_received`); loans are finance transfers (`...FromEntity...` =
  `loans_given`, `...ToEntity...` = `loans_taken`).
- NATURE_RULE (named, X113): the catch-all paid element `OtherRelatedPartyTransactionsExpense` gets a specific type
  (remuneration, royalty, rent, dividend, interest) only when the row's nature-of-transactions text names exactly
  one of them; otherwise it stays `other`. ELIN "Remuneration, Dividend paid" stays `other`; most nature texts are
  "refer below" (vault scan) and stay `other` too.
- a context with only `RelatedPartyAxis` (no category; 661 facts in the vault scan) gets category OTHER.
- category: SUBSIDIARY / ASSOCIATE / JOINT_VENTURE / KMP / PROMOTER_GROUP (parent, entities with joint control or
  significant influence over the filer) / OTHER; the filed member is kept.
- only periods the annual parser validated as in scope (C9): durations in `in_scope_periods`, instants in
  `in_scope_instants`. A row needs a name.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from financials.parsers.xbrl import Instance

RPT_PARSER_VERSION = "rpt-1"
PARTY_AXIS = "RelatedPartyAxis"
CATEGORY_AXIS = "CategoriesOfRelatedPartiesAxis"

TXN_TYPES = ("purchases", "sales", "services_received", "services_rendered", "loans_given", "loans_taken", "royalty",
             "royalty_received", "rent", "rent_received", "remuneration", "dividend", "interest", "guarantees",
             "other")  # fmt: skip
BALANCE_TYPES = ("balance_payable", "balance_receivable")

# element -> canonical type (duration contexts). Every element is seen in a committed fixture or the vault scan.
FLOW_ELEMENTS: dict[str, str] = {
    "PurchasesOfGoodsRelatedPartyTransactions": "purchases",
    "PurchasesOfPropertyAndOtherAssetsRelatedPartyTransactions": "purchases",
    "RevenueFromSaleOfGoodsRelatedPartyTransactions": "sales",
    "SalesOfPropertyAndOtherAssetsRelatedPartyTransactions": "sales",
    "ServicesReceivedRelatedPartyTransactions": "services_received",
    "RevenueFromRenderingOfServicesRelatedPartyTransactions": "services_rendered",
    "TransfersUnderFinanceAgreementsFromEntityRelatedPartyTransactions": "loans_given",
    "TransfersUnderFinanceAgreementsToEntityRelatedPartyTransactions": "loans_taken",
    "LeasesAsLesseeRelatedPartyTransactions": "rent",
    "LeasesAsLessorRelatedPartyTransactions": "rent_received",
    # licence transfers = royalties: to the entity = the entity pays, from the entity = it receives
    "TransfersUnderLicenseAgreementsToEntityRelatedPartyTransactions": "royalty",
    "TransfersUnderLicenseAgreementsFromEntityRelatedPartyTransactions": "royalty_received",
    "ProvisionOfGuaranteesOrCollateralByEntityRelatedPartyTransactions": "guarantees",
    "ProvisionOfGuaranteesOrCollateralToEntityRelatedPartyTransactions": "guarantees",
    "TransfersOfResearchAndDevelopmentFromEntityRelatedPartyTransactions": "other",
    "TransfersOfResearchAndDevelopmentToEntityRelatedPartyTransactions": "other",
    "SettlementOfLiabilitiesByEntityOnBehalfOfRelatedPartyRelatedPartyTransactions": "other",
    "SettlementOfLiabilitiesOnBehalfOfEntityByRelatedPartyRelatedPartyTransactions": "other",
    "ParticipationInDefinedBenefitPlanThatSharesRisksBetweenGroupEntitiesRelatedPartyTransactions": "other",
    "OtherRelatedPartyTransactionsContributionMade": "other",
    "OtherRelatedPartyTransactionsContributionReceived": "other",
    "OtherRelatedPartyTransactionsExpense": "other",
    "OtherRelatedPartyTransactionsIncome": "other",
}
BALANCE_ELEMENTS: dict[str, str] = {
    "AmountsPayableRelatedPartyTransactions": "balance_payable",
    "AmountsReceivableRelatedPartyTransactions": "balance_receivable",
}
NATURE_RULE_ELEMENTS = frozenset({"OtherRelatedPartyTransactionsExpense"})  # paid by the entity only
NATURE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("remuneration", re.compile(r"remunerat|salar|sitting\s+fee|managerial|compensation", re.I)),
    ("royalty", re.compile(r"royalt", re.I)),
    ("rent", re.compile(r"\brent|\blease", re.I)),
    ("dividend", re.compile(r"dividend", re.I)),
    ("interest", re.compile(r"interest", re.I)),
)
TEXT_ELEMENTS = {
    "NameOfRelatedParty": "name",
    "PermanentAccountNumberOfRelatedParty": "pan",
    "CINOfRelatedParty": "cin",
    "CountryOfIncorporationOrResidenceOfRelatedParty": "country",
    "DescriptionOfNatureOfRelatedPartyRelationship": "relationship",
    "DescriptionOfNatureOfTransactionsWithRelatedParty": "nature",
}
CATEGORIES = {
    "SubsidiariesMember": "SUBSIDIARY",
    "AssociatesMember": "ASSOCIATE",
    "JointVenturesWhereEntityIsVenturerMember": "JOINT_VENTURE",
    "KeyManagementPersonnelOfEntityOrParentMember": "KMP",
    "ParentMember": "PROMOTER_GROUP",
    "JointControlOrSignificantInfluenceMember": "PROMOTER_GROUP",
    "OtherRelatedPartiesMember": "OTHER",
}
NO_CATEGORY = "(none)"  # a RelatedPartyAxis-only context (661 facts in the vault scan): category OTHER
CATEGORY_VALUES = ("SUBSIDIARY", "ASSOCIATE", "JOINT_VENTURE", "KMP", "PROMOTER_GROUP", "OTHER")


@dataclass(frozen=True)
class RelatedPartyRow:
    row_member: str  # typed RelatedPartyAxis member as filed (row position inside the filing)
    category_member: str  # CategoriesOfRelatedPartiesAxis member as filed (local name)
    category: str  # CATEGORY_VALUES
    period_type: str  # DURATION (transactions) | INSTANT (balances)
    period_start: date
    period_end: date
    counterparty_name: str
    pan: str | None
    cin: str | None
    country: str | None
    relationship: str | None
    nature: str | None
    txn_type: str  # TXN_TYPES | BALANCE_TYPES
    source_element: str
    amount: Decimal


def _local(x: str) -> str:
    return x.split(":")[-1]


def _clean(text: str | None) -> str | None:
    t = " ".join((text or "").split())
    return t or None


def nature_type(nature: str | None) -> str | None:
    """NATURE_RULE: the one specific type the nature text names, else None (none or several)."""
    hits = {t for t, rx in NATURE_PATTERNS if nature and rx.search(nature)}
    return hits.pop() if len(hits) == 1 else None


def _row_key(inst: Instance, context_id: str) -> tuple[str, str] | None:
    dims = {_local(a): m for a, m in inst.contexts[context_id].dimensions}
    if PARTY_AXIS not in dims or not set(dims) <= {PARTY_AXIS, CATEGORY_AXIS}:
        return None
    return dims[PARTY_AXIS], _local(dims.get(CATEGORY_AXIS, NO_CATEGORY))


def parse_related_parties(
    inst: Instance, durations: set[tuple[date, date]], instants: set[date]
) -> list[RelatedPartyRow]:
    """One row per (party, category, element, in-scope period) of the related-party schedule that has a name."""
    texts: dict[tuple[str, str, date], dict[str, str]] = defaultdict(dict)
    amounts: list[tuple[tuple[str, str], str, str, date, date, Decimal]] = []
    for f in inst.facts:
        key = _row_key(inst, f.context_id)
        if key is None:
            continue
        c = inst.contexts[f.context_id]
        if f.name in TEXT_ELEMENTS:
            end = c.instant or c.end
            texts[(*key, end)].setdefault(TEXT_ELEMENTS[f.name], f.value_text)
            continue
        if f.name in FLOW_ELEMENTS and c.instant is None and (c.start, c.end) in durations:
            kind, start, end = "DURATION", c.start, c.end
        elif f.name in BALANCE_ELEMENTS and c.instant is not None and c.instant in instants:
            kind, start, end = "INSTANT", c.instant, c.instant
        else:
            continue
        try:
            value = Decimal(f.value_text.strip())
        except InvalidOperation:
            continue
        amounts.append((key, f.name, kind, start, end, value))
    out: dict[tuple, RelatedPartyRow] = {}
    for (member, cat), element, kind, start, end, value in amounts:
        t = texts.get((member, cat, end), {})
        name = _clean(t.get("name"))
        if name is None:
            continue
        nature = _clean(t.get("nature"))
        txn = FLOW_ELEMENTS.get(element) or BALANCE_ELEMENTS[element]
        if element in NATURE_RULE_ELEMENTS:
            txn = nature_type(nature) or txn
        row = RelatedPartyRow(
            row_member=member,
            category_member=cat,
            category=CATEGORIES.get(cat, "OTHER"),
            period_type=kind,
            period_start=start,
            period_end=end,
            counterparty_name=name,
            pan=_clean(t.get("pan")),
            cin=_clean(t.get("cin")),
            country=_clean(t.get("country")),
            relationship=_clean(t.get("relationship")),
            nature=nature,
            txn_type=txn,
            source_element=element,
            amount=value,
        )
        out.setdefault((member, cat, element, start, end), row)  # first fact wins on a duplicate (document order)
    return sorted(out.values(), key=lambda r: (r.period_end, r.period_type, _order(r.row_member), r.category_member,
                                               r.source_element))  # fmt: skip


def _order(member: str) -> tuple[int, str]:
    digits = re.sub(r"\D", "", member)
    return (int(digits), member) if digits else (1 << 30, member)
