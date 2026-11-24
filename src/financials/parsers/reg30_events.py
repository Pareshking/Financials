"""Reg. 30 structured event XBRL (SEBI `in-capmkt` event taxonomies) and the NSE announcements RSS [E1-E7].

Three event families are parsed (namespace path segment -> family):
- `Regulation_30_Para_B_Of_Part_A_Of_Schedule_III`: orders/contracts, litigation, other Para B items [E3, E4];
- `Changes_In_Management`: appointments / cessations of directors, KMP, SMP, auditors, one record per person on
  `ChangeInManagementAxis` [E5];
- `Alteration_Of_Capital_And_Fund_Raising`: allotments of securities (ESOP, debt, ...) [E6];
- `Announcement_For_Fraud_Or_Default`: fraud / default / arrest disclosures; no ISIN (symbol only) and the amount is
  free text, never parsed into a number [E7];
- `Action_Initiation_Or_Action_Taken_Or_Order_Passed` (`AIATOP_*.xml`, Para B sub-para 20): one record per action
  taken (`REGULATORY_ACTION`) or initiated (`REGULATORY_ACTION_INITIATED`); the fine is `AmountOfFineOrPenalty`
  (X360, E12);
- `Regulation_30_Restructuring` (`REG30_Restructuring_*.xml`): one acquisition, incorporation or sale / disposal per
  filing; the amount is the cash consideration (X360, E13).
Other families (analyst meets, board outcomes, agreements) are vaulted raw only [E2].

Pure: bytes -> event rows. Amounts are absolute rupees (unit INR).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from financials.parsers import ParseError, canonical_archive_url
from financials.parsers.xbrl import parse_instance

FAMILIES = {
    "Regulation_30_Para_B_Of_Part_A_Of_Schedule_III": "PARA_B",
    "Changes_In_Management": "CHANGE_IN_MANAGEMENT",
    "Alteration_Of_Capital_And_Fund_Raising": "FUND_RAISING",
    "Announcement_For_Fraud_Or_Default": "FRAUD_OR_DEFAULT",
    "Action_Initiation_Or_Action_Taken_Or_Order_Passed": "REGULATORY_ACTION",
    "Regulation_30_Restructuring": "RESTRUCTURING",
}
NOT_APPLICABLE = {"NOT APPLICABLE", "NA", "N.A.", "NIL", "-"}


@dataclass(frozen=True)
class EventIssue:
    stage: str
    reason_code: str
    details: dict


@dataclass
class ParsedEvents:
    family: str | None = None
    meta: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    issues: list[EventIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _local(x: str) -> str:
    return x.split(":")[-1]


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return None if not v or v.upper() in NOT_APPLICABLE else v


def _date(v: str | None) -> date | None:
    try:
        return date.fromisoformat((v or "").strip())
    except ValueError:
        return None


def parse_reg30_event(data: bytes) -> ParsedEvents:
    inst = parse_instance(data)
    out = ParsedEvents()
    ent_ns = next((u for u in inst.namespaces.values() if u.endswith("/in-capmkt-ent")), None)
    family = next((f for seg, f in FAMILIES.items() if ent_ns and f"/{seg}/" in ent_ns), None)
    out.family = family
    main: dict[str, str] = {}
    records: dict[str, dict[str, tuple[str, str | None]]] = {}  # typed member -> {element: (value, unit)}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if not c.dimensions:
            main.setdefault(f.name, f.value_text.strip())
        else:
            key = "|".join(_local(m) for _, m in c.dimensions)
            records.setdefault(key, {})[f.name] = (f.value_text.strip(), f.unit_ref)
    out.meta = {
        "entity_namespace": ent_ns,
        "stated_symbol": main.get("NSESymbol"),
        "stated_isin": main.get("ISIN"),
        "company_name": main.get("NameOfTheCompany"),
        "report_date": _date(main.get("DateOfReport")),
        "occurred_on": _date(main.get("DateOfOccurrenceOfEvent") or main.get("DateOfOccurrenceOfEventOrInformation")),
    }
    if family is None:
        return out  # vaulted raw only [E2]
    identity_ok = out.meta["stated_isin"] or (family == "FRAUD_OR_DEFAULT" and out.meta["stated_symbol"])
    if not identity_ok or out.meta["report_date"] is None:
        out.issues.append(EventIssue("PARSE", "MISSING_META", {k: str(v) for k, v in out.meta.items()}))
        return out
    handlers = {"PARA_B": _para_b, "CHANGE_IN_MANAGEMENT": _cim, "FUND_RAISING": _fund_raising,
                "FRAUD_OR_DEFAULT": _fraud, "REGULATORY_ACTION": _regulatory_action,
                "RESTRUCTURING": _restructuring}  # fmt: skip
    handlers[family](main, records, out)
    # Zero-drop (C24): every numeric element of the filing is kept on its event rows' details.
    numeric = {}
    for f in inst.facts:
        if f.is_numeric:
            key = "|".join(_local(m) for _, m in inst.contexts[f.context_id].dimensions) or "MAIN"
            numeric.setdefault(key, {})[f.name] = f.value_text.strip()
    for e in out.events:
        e.setdefault("details", {})["numeric"] = {**numeric.get("MAIN", {}), **numeric.get(e["record_key"], {})}
    return out


def _val(rec: dict, name: str) -> str | None:
    return (rec.get(name) or (None,))[0]


def _money(v: tuple[str, str | None] | None) -> Decimal | None:
    if v is None or v[1] is None:
        return None
    try:
        return Decimal(v[0])
    except ArithmeticError:
        return None


def _para_b(main: dict, records: dict, out: ParsedEvents) -> None:
    kind = main.get("TypeOfEventAsPerRegulation30ParaBOfPartAOfScheduleIII") or ""
    for key, rec in sorted(records.items()):
        sub = (rec.get("SubTypeOfEventAsPerRegulation30ParaBOfPartAOfScheduleIII") or (None,))[0] or main.get(
            "SubTypeOfEventAsPerRegulation30ParaBOfPartAOfScheduleIII"
        )
        if "AmountOfTheOrdersOrContracts" in rec or "NameOfTheEntityAwardingTheOrdersOrContracts" in rec:
            event_type = "ORDER_WIN" if (sub or "").startswith("Bagging/Receiving") else "ORDER_OTHER"
            out.events.append(
                {
                    "record_key": key,
                    "event_type": event_type,
                    "event_subtype": sub,
                    "occurred_on": _date((rec.get("DateOfBaggingOrReceivingOfOrdersOrContracts") or ("",))[0])
                    or out.meta["occurred_on"],
                    "counterparty": _clean((rec.get("NameOfTheEntityAwardingTheOrdersOrContracts") or ("",))[0]),
                    "amount_inr": _money(rec.get("AmountOfTheOrdersOrContracts")),
                    "details": {
                        "domestic_or_international": (
                            rec.get("WhetherOrdersOrContractsIsAwardedByDomesticOrInternationalEntity") or (None,)
                        )[0],
                        "related_party": (
                            rec.get("WhetherTheOrderOrContractWouldFallWithinRelatedPartyTransactions") or (None,)
                        )[0],
                        "nature": (rec.get("NatureOfOrdersOrContracts") or (None,))[0],
                    },
                }
            )
    if not out.events:
        litigation = kind.startswith("Pendency of any litigation")
        # Litigation fields sit partly in typed sub-type contexts [E4]: read main first, then every record.
        flat = dict(main)
        for rec in records.values():
            for k, (v, _) in rec.items():
                flat.setdefault(k, v)
        main = flat
        out.events.append(
            {
                "record_key": "MAIN",
                "event_type": "LITIGATION" if litigation else "PARA_B_OTHER",
                "event_subtype": kind or None,
                "occurred_on": out.meta["occurred_on"],
                "counterparty": _clean(
                    main.get("DetailsOfOtherLitigationAgainstParty") or main.get("LitigationAgainstParty")
                ),
                "amount_inr": None,
                "details": {
                    "stage": main.get("StageOfDisclosureOfLitigationOrDispute"),
                    "sub_type": main.get("SubTypeOfEventAsPerRegulation30ParaBOfPartAOfScheduleIII"),
                },
            }
        )


def _cim(main: dict, records: dict, out: ParsedEvents) -> None:
    for key, rec in sorted(records.items()):

        def g(name, rec=rec):
            return _val(rec, name)

        category = g("CategoryForChange")
        if category is None:
            continue
        out.events.append(
            {
                "record_key": key,
                "event_type": "AUDITOR_CHANGE" if category == "Auditors" else "MANAGEMENT_CHANGE",
                "event_subtype": g("TypeOfChange"),
                "occurred_on": _date(g("EffectiveDateOfReasonOfChange")) or out.meta["occurred_on"],
                "counterparty": None,
                "amount_inr": None,
                "person_name": g("NameOfDesignatedPerson"),
                "person_category": category,
                "designation": g("DesignationOfDesignatedPerson"),
                "change_type": g("TypeOfChange"),
                "cessation_category": g("CategoryOfCessation"),
                "details": {"remarks": g("RemarksForChangeInManagement")},
            }
        )


def _fund_raising(main: dict, records: dict, out: ParsedEvents) -> None:
    pre, post = (
        main.get("NumberOfSharesPaidUpPreAllotmentOfSecurities"),
        main.get("NumberOfSharesPaidUpPostAllotmentOfSecurities"),
    )
    out.events.append(
        {
            "record_key": "MAIN",
            "event_type": "ALLOTMENT",
            "event_subtype": main.get("TypeOfIssuanceForAllotmentOfSecurities"),
            "occurred_on": _date(main.get("DateOfBoardOrCommitteeForAllotmentOfSecurities")) or out.meta["occurred_on"],
            "counterparty": None,
            "amount_inr": None,  # no consideration element in the taxonomy [E6]
            "details": {
                "security": main.get("TypeOfSecuritiesAllottedForAllotmentOfSecurities"),
                "shares_pre": pre,
                "shares_post": post,
            },
        }
    )


def _fraud(main: dict, records: dict, out: ParsedEvents) -> None:
    out.events.append(
        {
            "record_key": "MAIN",
            "event_type": "FRAUD_OR_DEFAULT",
            "event_subtype": main.get("TypeOfDisclosureInRelationToEventOfFraudOrDefaults"),
            "occurred_on": _date(main.get("DateOfWhenTheFraudOrDefaultOrArrestWasUnearthingOrOccurred"))
            or out.meta["report_date"],
            "counterparty": None,
            "amount_inr": None,  # free text in the filing ("Rs 794.36 Lakhs ...") [E7]
            "person_category": main.get("CategoryOfEntityForWhichDisclosureIsFiledForFraudOrDefaults"),
            "details": {
                "stage": main.get("TypeOfEventOfFraudOrDefaults"),
                "amount_text": main.get("EstimatedAmountInvolvedInFraudOrDefaultOrArrestWasUnearthingOrOccurred"),
            },
        }
    )


def _regulatory_action(main: dict, records: dict, out: ParsedEvents) -> None:
    """X360 (E12): one event per `ActionsTaken<n>` / `ActionsInitiated<n>` record; the persons-against sub-records
    (`..._PersonsAgainstWhom...<n>`) and signatories are details, not events."""
    for key, rec in sorted(records.items()):
        if "|" in key:
            continue
        for word, event_type in (("Taken", "REGULATORY_ACTION"), ("Initiated", "REGULATORY_ACTION_INITIATED")):
            kind = _val(rec, f"TypeOfActions{word}OrOrdersPassed")
            if kind is None and f"Actions{word}OrOrdersPassedBy" not in rec:
                continue
            against = sorted(
                {v for k2, r2 in records.items() if k2.startswith(key + "|")
                 for v in [_val(r2, f"NameOfPersonAgainstWhomActions{word}OrOrdersPassed")] if v}
            )  # fmt: skip
            out.events.append(
                {
                    "record_key": key,
                    "event_type": event_type,
                    "event_subtype": _clean(kind),
                    "occurred_on": _date(
                        _val(rec, f"DateOfReceiptOfCommunicationReceivedForActions{word}OrOrdersPassed")
                    )
                    or out.meta["occurred_on"],
                    "counterparty": _clean(_val(rec, f"NameOfAuthorityFromWhomActions{word}OrOrdersPassed")),
                    "amount_inr": _money(rec.get("AmountOfFineOrPenalty")),
                    "details": {
                        "by": _val(rec, f"Actions{word}OrOrdersPassedBy"),
                        "against": _val(rec, f"Actions{word}OrOrdersPassedAgainst"),
                        "persons_against": against,
                        "nature": _val(rec, f"NatureAndDetailsOfTheActions{word}OrOrdersPassed"),
                        "period": _val(
                            rec, f"PeriodForWhichCommunicationWouldBeApplicableForActions{word}OrOrdersPassed"
                        ),
                        "announcement": main.get("TypeOfAnnouncement"),
                    },
                }
            )
            break


RESTRUCTURING_TYPES = {  # filed type -> (event type, cash consideration element, counterparty element)
    "Acquisition (including agreement to acquire)": (
        "ACQUISITION", "AmountOfCashConsiderationForAcquisitionEvent", "NameOfTheTargetEntity"),
    "Acquisition of \u201cto be incorporated companies\u201d": (
        "INCORPORATION", "AmountOfCashConsiderationForIncorporation", "NameOfTheIncorporatedEntity"),
    "Sale or disposal of unit(s)/division(s)/subsidiary": (
        "SALE_OR_DISPOSAL", None, "NameOfUnitOrDivisionOrSubsidiaryOfTheListedEntity"),
}  # fmt: skip


def _restructuring(main: dict, records: dict, out: ParsedEvents) -> None:
    """X360 (E13): one event per filing, all facts in non-dimensional contexts; `Update` filings restate an earlier
    announcement (kept as their own event, flagged in details). Unknown event types become RESTRUCTURING_OTHER."""
    raw = {k: v for k, v in main.items()}
    for rec in records.values():  # the unit / division name sits in a typed context (sale or disposal)
        for k, (v, _) in rec.items():
            raw.setdefault(k, v)
    kind = main.get("TypeOfEventOfAnnouncementPertainingToRegulation30Restructuring")
    event_type, amount_el, name_el = RESTRUCTURING_TYPES.get(kind or "", ("RESTRUCTURING_OTHER", None, None))
    if kind is None and main.get("TypeOfAnnouncementPertainingToRegulation30Restructuring") == "Update":
        event_type = "RESTRUCTURING_UPDATE"  # an update names no event type: never counted as a new acquisition
    amount = None
    if amount_el and raw.get(amount_el) is not None:
        try:
            amount = Decimal(raw[amount_el])
        except ArithmeticError:
            amount = None
    out.events.append(
        {
            "record_key": "MAIN",
            "event_type": event_type,
            "event_subtype": kind,
            "occurred_on": out.meta["occurred_on"],
            "counterparty": _clean(raw.get(name_el)) if name_el else None,
            "amount_inr": amount,
            "details": {
                "announcement": main.get("TypeOfAnnouncementPertainingToRegulation30Restructuring"),
                "consideration": main.get("NatureOfConsiderationForAcquisitionEvent"),
                "control_acquired": main.get("PercentageOfControlAcquired"),
                "related_party": main.get("WhetherTheAcquisitionWouldFallWithinRelatedPartyTransactions"),
                "industry": main.get("IndustryToWhichTheEntityBeingAcquiredBelongs"),
                "share_exchange_ratio": main.get("ShareExchangeRatioForAcquisitionEvent"),
            },
        }
    )


@dataclass(frozen=True)
class AnnouncementItem:
    company: str
    subject: str
    xbrl_url: str | None
    pub_ts_ist: datetime | None


def parse_announcements_rss(data: bytes) -> list[AnnouncementItem]:
    """`content/RSS/Online_announcements.xml` [A3, A4, E1]: title = company, link = attachment (XBRL for structured
    events), pubDate = IST broadcast time."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"announcements RSS: {exc}") from exc
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        items.append(
            AnnouncementItem(
                company=" ".join((it.findtext("title") or "").split()),
                subject=" ".join((it.findtext("description") or "").split()),
                xbrl_url=canonical_archive_url(link) if "/corporate/xbrl/" in link else None,
                pub_ts_ist=_pub(pub),
            )
        )
    return items


def _pub(text: str) -> datetime | None:
    """Most items carry seconds; some only minutes ('13-NOV-2026 13:10') [E1]: minute precision is kept as is."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
