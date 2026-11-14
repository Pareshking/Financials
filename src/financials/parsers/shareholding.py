"""Reg. 31 shareholding pattern XBRL (`in-bse-shp` taxonomy) and the NSE shareholding master JSON.

Evidence (docs/references.md SHP1-SHP15):
- namespace `http://www.bseindia.com/xbrl/shp/<version>/in-bse-shp` (no `in-capmkt-ent`);
- category totals sit in instant contexts with one `CategoryOfShareholdersAxis` member;
- promoter + public + non-promoter non-public = total, exactly [SHP8];
- percentages are fractions whose denominator excludes shares underlying depository receipts [SHP9];
- encumbrance quantities sit on the promoter member; pledge is one of three encumbrance kinds [SHP10];
- no promoter category at all for companies without promoters (rule NO_PROMOTER_CATEGORY) [SHP11];
- named >1% public holders are rows on the per-category "Details..." axes [SHP12];
- the 2022-09-30 taxonomy (Q4 FY25 and earlier) never declares its entity contexts `OneD` / `OneI`; rule
  SHP16_UNDECLARED_ENTITY_CONTEXTS reads them as period-less entity facts [SHP16];
- pre-listing / allotment patterns date every category context on the declared DateOfListing / DateOfAllotment, not
  on DateOfReport; rule SHP17_EVENT_DATED takes that event date as the as-of date [SHP17];
- percentages are fractions in some filings and percent points in others, per filing even within one taxonomy;
  the filing's own TOTAL percentage (1 or 100) decides, and rule SHP18_PERCENT_SCALE stores fractions [SHP18].
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from financials.parsers import ParseError
from financials.parsers.xbrl import Instance, parse_instance
from financials.timeutil import IST

SHP_NS_FRAGMENT = "/xbrl/shp/"
CATEGORY_AXIS = "CategoryOfShareholdersAxis"
CATEGORIES = {
    "ShareholdingPatternMember": "TOTAL",
    "ShareholdingOfPromoterAndPromoterGroupMember": "PROMOTER",
    "PublicShareholdingMember": "PUBLIC",
    "InstitutionsDomesticMember": "DII",
    "InstitutionsForeignMember": "FII",
    "MutualFundsOrUTIMember": "MUTUAL_FUNDS",
    "NonInstitutionsMember": "NON_INSTITUTIONS",
    "SharesHeldByNonPromoterNonPublicShareholdersMember": "NON_PROMOTER_NON_PUBLIC",
    "CustodianOrDRHolderMember": "DR_CUSTODIAN",
    "EmployeeBenefitsTrustsMember": "EMPLOYEE_TRUSTS",
    "InstitutionsForeignPortfolioInvestorCategoryOneMember": "FPI_CAT1",
    "InstitutionsForeignPortfolioInvestorCatergoryOneMember": "FPI_CAT1",  # 2022-09-30 taxonomy spelling [SHP16]
    "InstitutionsForeignPortfolioInvestorCategoryTwoMember": "FPI_CAT2",
    "ForeignDirectInvestmentMember": "FDI",
    "OverseasDepositoriesMember": "OVERSEAS_DEPOSITORIES",
    "SovereignWealthFundsDomesticMember": "SWF_DOMESTIC",
    "GovernmentsMember": "GOVERNMENTS",
}
PROMOTER_MEMBER = "ShareholdingOfPromoterAndPromoterGroupMember"
# Encumbrance quantities on the promoter member [SHP10]; pledge is one kind of encumbrance.
ENCUMBRANCE = {
    "NumberOfSharesEncumberedUnderPledged": "pledged",
    "NumberOfSharesEncumberedUnderNonDisposalUndertaking": "ndu",
    "NumberOfSharesEncumberedUnderOtherEncumbrances": "other",
    "NumberOfSharesEncumbered": "total",
}
ENCUMBRANCE_FLAGS = {
    "pledged": "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged",
    "ndu": "WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking",
    "other": "WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU",
}
# Public-side "Details..." axes whose rows are named holders with more than 1% [SHP12]. Promoter-side
# detail axes (IndividualsOrHUF, OthersIndianShareholders, ...) and the "Other..." axes, whose rows are
# sub-category totals (WhetherACategoryOrMoreThan1PercentageOfShareholding = "Category"), are excluded.
PUBLIC_HOLDER_AXES = {
    "DetailsOfSharesHeldByMutualFundsOrUTIAxis": "MUTUAL_FUNDS",
    "DetailsOfSharesHeldByInsuranceCompaniesAxis": "INSURANCE",
    "DetailsOfSharesHeldByProvidentFundsOrPensionFundsAxis": "PENSION_FUNDS",
    "DetailsOfSharesHeldByAlternativeInvestmentFundsAxis": "AIF",
    "DetailsOfSharesHeldByInstitutionsForeignPortfolioInvestorOneAxis": "FPI_CAT1",
    "DetailsOfSharesHeldByForeignDirectInvestmentAxis": "FDI",
    "DetailsOfSharesHeldByForeignCompaniesAxis": "FOREIGN_COMPANIES",
    "DetailsOfSharesHeldByOverseasDepositoriesAxis": "OVERSEAS_DEPOSITORIES",
    "DetailsOfSharesHeldByOtherFinancialInstitutionsAxis": "OTHER_FINANCIAL_INSTITUTIONS",
    "DetailsOfSharesHeldByBodiesCorporateAxis": "BODIES_CORPORATE",
    "DetailsOfSharesHeldByResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhAxis": (
        "RESIDENT_INDIVIDUALS_UPTO_2L"
    ),
    "DetailsOfSharesHeldByResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakhAxis": (
        "RESIDENT_INDIVIDUALS_ABOVE_2L"
    ),
}
SUBTOTAL_FLAG = "WhetherACategoryOrMoreThan1PercentageOfShareholding"  # "Category" rows are sub-totals
NO_PROMOTER_RULE = "NO_PROMOTER_CATEGORY"
MEASURES = {
    "NumberOfShares": "shares",
    "NumberOfShareholders": "holders",
    "ShareholdingAsAPercentageOfTotalNumberOfShares": "pct",
    "NumberOfEquitySharesHeldInDematerializedForm": "demat_shares",
    "NumberOfVotingRights": "voting_rights",
}


@dataclass(frozen=True)
class ShpIssue:
    stage: str
    reason_code: str
    details: dict


@dataclass
class ParsedShareholding:
    meta: dict = field(default_factory=dict)
    categories: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    major_holders: list[dict] = field(default_factory=list)
    line_items: list[dict] = field(default_factory=list)  # C24: every numeric fact per category member
    issues: list[ShpIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


SHP16_RULE = "SHP16_UNDECLARED_ENTITY_CONTEXTS"
SHP16_NS = b"http://www.bseindia.com/xbrl/shp/2022-09-30/in-bse-shp"
SHP16_CONTEXTS = frozenset({"OneD", "OneI"})
SHP17_RULE = "SHP17_EVENT_DATED"
EVENT_DATE_TAGS = ("DateOfListing", "DateOfAllotment")
SHP18_RULE = "SHP18_PERCENT_SCALE"
HUNDRED = Decimal(100)


def shp_instance(data: bytes) -> tuple[Instance, bool]:
    """parse_instance with rule SHP16: only a 2022-09-30 SHP instance may leave exactly `OneD` / `OneI` undeclared."""
    try:
        return parse_instance(data), False
    except ParseError:
        if SHP16_NS not in data[:16384]:
            raise
    inst = parse_instance(data, undeclared_entity_contexts=SHP16_CONTEXTS)
    return inst, True


def _bool(text: str | None) -> bool | None:
    return {"true": True, "false": False}.get((text or "").strip().lower())


def _percent_scale(out: ParsedShareholding) -> None:
    """SHP18: TOTAL pct is exactly 1 (fractions) or exactly 100 (percent points; divide every stated percentage by
    100). Any other TOTAL pct, or a missing one while percentages exist, is PCT_SCALE_UNKNOWN."""
    total = out.categories.get("TOTAL", {}).get("pct")
    has_pct = any("pct" in v for v in out.categories.values())
    if total == 1 or (total is None and not has_pct):
        return
    if total != HUNDRED:
        out.issues.append(ShpIssue("PARSE", "PCT_SCALE_UNKNOWN", {"total_pct": str(total)}))
        return
    for vals in out.categories.values():
        if "pct" in vals:
            vals["pct"] = vals["pct"] / HUNDRED
    for h in out.major_holders:
        if h["pct"] is not None:
            h["pct"] = h["pct"] / HUNDRED
    out.meta["rules_applied"].append(SHP18_RULE)


def _category_instants(inst: Instance) -> set:
    found = set()
    for fact in inst.facts:
        ctx = inst.contexts[fact.context_id]
        if len(ctx.dimensions) != 1 or fact.name not in MEASURES:
            continue
        axis, member = (x.split(":")[-1] for x in ctx.dimensions[0])
        if axis.endswith(CATEGORY_AXIS) and member in CATEGORIES:
            found.add(ctx.instant)
    return found


def _event_date(inst: Instance, date_of_report: date):
    """SHP17: every category measure sits on one instant that differs from DateOfReport and equals the filing's own
    declared DateOfListing or DateOfAllotment -> that event date. Anything else returns None (CONTEXT_CONFLICT)."""
    instants = _category_instants(inst)
    if len(instants) != 1:
        return None
    (instant,) = instants
    if instant is None or instant == date_of_report:
        return None
    for tag in EVENT_DATE_TAGS:
        text = inst.first_text(tag)
        if text and date.fromisoformat(text) == instant:
            return instant
    return None


def parse_shareholding(data: bytes) -> ParsedShareholding:
    inst, shp16 = shp_instance(data)
    out = ParsedShareholding()
    ns = next((u for u in inst.namespaces.values() if SHP_NS_FRAGMENT in u and u.endswith("/in-bse-shp")), None)
    if ns is None:
        out.issues.append(ShpIssue("PARSE", "UNKNOWN_TAXONOMY", {"namespaces": sorted(inst.namespaces.values())}))
        return out
    as_of = inst.first_text("DateOfReport")
    isin = inst.first_text("ISIN")
    if not as_of or not isin:
        out.issues.append(ShpIssue("PARSE", "MISSING_META", {"DateOfReport": as_of, "ISIN": isin}))
        return out
    as_of_date = date.fromisoformat(as_of)
    flags = {k: _bool(inst.first_text(tag)) for k, tag in ENCUMBRANCE_FLAGS.items()}
    out.meta = {
        "taxonomy_ns": ns,
        "as_of_date": as_of_date,
        "stated_isin": isin,
        "stated_symbol": inst.first_text("Symbol"),
        "stated_scrip_code": inst.first_text("ScripCode"),
        "has_partly_paid": _bool(inst.first_text("WhetherTheListedEntityHasIssuedAnyPartlyPaidUpShares")),
        "promoter_pledge_flag": flags["pledged"],
        "rules_applied": [SHP16_RULE] if shp16 else [],
    }
    event_date = _event_date(inst, as_of_date)
    if event_date is not None:
        as_of_date = out.meta["as_of_date"] = event_date
        out.meta["stated_date_of_report"] = as_of
        out.meta["rules_applied"].append(SHP17_RULE)
    encumbrance: dict[str, Decimal] = {}
    holders: dict[tuple[str, str], dict[str, str]] = {}
    for fact in inst.facts:
        ctx = inst.contexts[fact.context_id]
        if len(ctx.dimensions) != 1:
            continue
        axis, member = (x.split(":")[-1] for x in ctx.dimensions[0])
        if axis in PUBLIC_HOLDER_AXES:
            holders.setdefault((axis, member), {})[fact.name] = fact.value_text.strip()
            continue
        if not axis.endswith(CATEGORY_AXIS) or not fact.is_numeric:
            continue
        if member == PROMOTER_MEMBER and fact.name in ENCUMBRANCE:
            encumbrance[ENCUMBRANCE[fact.name]] = fact.decimal()
        measure = MEASURES.get(fact.name)
        category = CATEGORIES.get(member)
        if measure is None or category is None:
            continue
        if ctx.instant is not None and ctx.instant != as_of_date:
            out.issues.append(
                ShpIssue(
                    "PERIOD",
                    "CONTEXT_CONFLICT",
                    {"context": ctx.id, "instant": str(ctx.instant), "as_of": str(as_of_date)},
                )
            )
            continue
        out.categories.setdefault(category, {})[measure] = fact.decimal()

    # Zero-drop (C24): every numeric fact on the category axis (any member, any measure) or without dimensions.
    seen_li: set[tuple[str, str]] = set()
    for fact in inst.facts:
        if not fact.is_numeric:
            continue
        ctx = inst.contexts[fact.context_id]
        if ctx.dimensions and (len(ctx.dimensions) != 1 or not ctx.dimensions[0][0].endswith(CATEGORY_AXIS)):
            continue  # per-holder / per-person record rows: major_holders or raw only
        member = ctx.dimensions[0][1].split(":")[-1] if ctx.dimensions else "ENTITY"
        if (member, fact.name) in seen_li:
            continue
        seen_li.add((member, fact.name))
        out.line_items.append({"category_member": member, "element": fact.name, "value": fact.decimal(),
                               "unit": inst.unit_kind(fact.unit_ref)})  # fmt: skip

    for (axis, member), row in sorted(holders.items()):
        name, shares = row.get("NameOfTheShareholder"), row.get("NumberOfShares")
        if not name or shares is None or row.get(SUBTOTAL_FLAG) == "Category":
            continue
        pct = row.get("ShareholdingAsAPercentageOfTotalNumberOfShares")
        out.major_holders.append(
            {
                "holder_category": PUBLIC_HOLDER_AXES[axis],
                "row_member": member,
                "holder_name": name,
                "shares": Decimal(shares),
                "pct": Decimal(pct) if pct else None,
            }
        )

    _percent_scale(out)
    _apply_no_promoter_rule(out, flags)
    for required in ("TOTAL", "PROMOTER", "PUBLIC"):
        if "shares" not in out.categories.get(required, {}):
            out.issues.append(ShpIssue("PARSE", "MISSING_CRITICAL", {"category": required}))
    _encumbrance_meta(out, flags, encumbrance)
    if out.ok:
        total = out.categories["TOTAL"]["shares"]
        npnp = out.categories.get("NON_PROMOTER_NON_PUBLIC", {}).get("shares", Decimal(0))
        parts = out.categories["PROMOTER"]["shares"] + out.categories["PUBLIC"]["shares"] + npnp
        if parts != total:
            out.issues.append(
                ShpIssue(
                    "IDENTITY",
                    "PROMOTER_PLUS_PUBLIC",
                    {"total": str(total), "promoter_plus_public_plus_npnp": str(parts)},
                )
            )
        if total <= 0:
            out.issues.append(ShpIssue("IDENTITY", "NON_POSITIVE_TOTAL", {"total": str(total)}))
    return out


def _apply_no_promoter_rule(out: ParsedShareholding, flags: dict[str, bool | None]) -> None:
    """Rule NO_PROMOTER_CATEGORY [SHP11]: companies without a promoter group (HDFC Bank, ICICI Bank, ITC)
    file no promoter category at all. Promoter holding is then 0, but only when the filing proves it:
    public + non-promoter non-public = total exactly and no encumbrance is declared."""
    if "PROMOTER" in out.categories or "shares" not in out.categories.get("TOTAL", {}):
        return
    public = out.categories.get("PUBLIC", {}).get("shares")
    npnp = out.categories.get("NON_PROMOTER_NON_PUBLIC", {}).get("shares", Decimal(0))
    if public is None or public + npnp != out.categories["TOTAL"]["shares"] or any(flags.values()):
        return
    out.categories["PROMOTER"] = {"shares": Decimal(0), "holders": Decimal(0), "pct": Decimal(0)}
    out.meta["rules_applied"].append(NO_PROMOTER_RULE)


def _encumbrance_meta(out: ParsedShareholding, flags: dict[str, bool | None], enc: dict[str, Decimal]) -> None:
    """Pledged and total encumbered promoter shares. A kind declared absent (flag false) with no quantity is 0;
    a declared kind with no quantity is unknown (NULL), never guessed."""

    def qty(kind: str) -> Decimal | None:
        if kind in enc:
            return enc[kind]
        return Decimal(0) if flags.get(kind) is False else None

    pledged = qty("pledged")
    if "total" in enc:
        encumbered = enc["total"]
    elif all(v is False for v in flags.values()):
        encumbered = Decimal(0)
    else:
        encumbered = None
    out.meta["promoter_pledged_shares"] = pledged
    out.meta["promoter_encumbered_shares"] = encumbered
    if pledged is not None and encumbered is not None and pledged > encumbered:
        out.issues.append(
            ShpIssue("IDENTITY", "PLEDGE_EXCEEDS_ENCUMBRANCE", {"pledged": str(pledged), "encumbered": str(encumbered)})
        )
    promoter = out.categories.get("PROMOTER", {}).get("shares")
    if encumbered is not None and promoter is not None and encumbered > promoter:
        out.issues.append(
            ShpIssue(
                "IDENTITY", "ENCUMBRANCE_EXCEEDS_PROMOTER", {"encumbered": str(encumbered), "promoter": str(promoter)}
            )
        )


@dataclass(frozen=True)
class ShpMasterEntry:
    symbol: str
    isin: str
    as_of_date: date
    broadcast_ts_ist: datetime
    xbrl_url: str
    revised: bool


def parse_shp_master(data: bytes) -> list[ShpMasterEntry]:
    """NSE `corporate-share-holdings-master` JSON: one entry per filing with its broadcast time."""
    try:
        rows = json.loads(data.decode("utf-8"))
        out = []
        for r in rows:
            out.append(
                ShpMasterEntry(
                    symbol=r["symbol"],
                    isin=r["isin"],
                    as_of_date=datetime.strptime(r["date"], "%d-%b-%Y").date(),
                    broadcast_ts_ist=datetime.strptime(r["broadcastDate"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST),
                    xbrl_url=r["xbrl"],
                    revised=(r.get("revisedData") or "N").upper() == "Y",
                )
            )
        return out
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"shareholding master: {exc}") from exc
