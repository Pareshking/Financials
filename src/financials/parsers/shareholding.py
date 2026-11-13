"""Reg. 31 shareholding pattern XBRL (`in-bse-shp` taxonomy) and the NSE shareholding master JSON.

Evidence (docs/references.md SHP1-SHP6), from ELIN's 2026-09-30 filing:
- namespace `http://www.bseindia.com/xbrl/shp/<version>/in-bse-shp` (no `in-capmkt-ent`);
- category totals sit in instant contexts with one `CategoryOfShareholdersAxis` member;
- promoter + public = total, exactly (16,388,405 + 33,320,815 = 49,709,220);
- percentages are fractions; pledged-share quantity tag is not present when nothing is pledged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from financials.parsers import ParseError
from financials.parsers.xbrl import parse_instance
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
}
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
    issues: list[ShpIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _bool(text: str | None) -> bool | None:
    return {"true": True, "false": False}.get((text or "").strip().lower())


def parse_shareholding(data: bytes) -> ParsedShareholding:
    inst = parse_instance(data)
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
    pledge_flag = _bool(inst.first_text("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged"))
    out.meta = {
        "taxonomy_ns": ns,
        "as_of_date": as_of_date,
        "stated_isin": isin,
        "stated_symbol": inst.first_text("Symbol"),
        "stated_scrip_code": inst.first_text("ScripCode"),
        "has_partly_paid": _bool(inst.first_text("WhetherTheListedEntityHasIssuedAnyPartlyPaidUpShares")),
        "promoter_pledge_flag": pledge_flag,
        # Quantity tag UNVERIFIED [SHP5]: only the "nothing pledged" case is known.
        "promoter_pledged_shares": Decimal(0) if pledge_flag is False else None,
    }
    for fact in inst.facts:
        measure = MEASURES.get(fact.name)
        if measure is None or not fact.is_numeric:
            continue
        ctx = inst.contexts[fact.context_id]
        if len(ctx.dimensions) != 1 or not ctx.dimensions[0][0].endswith(CATEGORY_AXIS):
            continue
        member = ctx.dimensions[0][1].split(":")[-1]
        category = CATEGORIES.get(member)
        if category is None:
            continue
        if ctx.instant is not None and ctx.instant != as_of_date:
            out.issues.append(
                ShpIssue("PERIOD", "CONTEXT_CONFLICT", {"context": ctx.id, "instant": str(ctx.instant), "as_of": as_of})
            )
            continue
        out.categories.setdefault(category, {})[measure] = fact.decimal()

    for required in ("TOTAL", "PROMOTER", "PUBLIC"):
        if "shares" not in out.categories.get(required, {}):
            out.issues.append(ShpIssue("PARSE", "MISSING_CRITICAL", {"category": required}))
    if out.ok:
        total = out.categories["TOTAL"]["shares"]
        parts = out.categories["PROMOTER"]["shares"] + out.categories["PUBLIC"]["shares"]
        # Non-promoter non-public holdings (employee trusts) are not in the fixture: any gap is an issue.
        if parts != total:
            out.issues.append(
                ShpIssue("IDENTITY", "PROMOTER_PLUS_PUBLIC", {"total": str(total), "promoter_plus_public": str(parts)})
            )
        if total <= 0:
            out.issues.append(ShpIssue("IDENTITY", "NON_POSITIVE_TOTAL", {"total": str(total)}))
    return out


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
