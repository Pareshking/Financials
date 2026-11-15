"""Reg. 34 annual XBRL: the AOC-1 subsidiary / associate / joint-venture schedule -> group_structure rows [X112].

Evidence (docs/references.md X112; fixtures AR_XBRL_CUMMINSIND_04092026113534.xml, AR_XBRL_TCS_09082026012216.xml):
the schedule is three typed-axis tables of the MCA Ind AS taxonomy. Each row is one typed member ("1", "2", ...) of
the axis in one year's contexts (`..._1_D2026` duration, `..._1_I2026` instant); the member number is a row
position inside that year only, never an identity across years. Per relation:

- SUBSIDIARY, `SignificantInvestmentsInSubsidiariesAxis`: `NameOfSubsidiary`, `CINOfSubsidiaryCompany`,
  `CountryOfIncorporationOrResidenceOfSubsidiary`, `PercentageOfShareholdingInSubsidiary` (AOC-1, a fraction:
  1 = 100%), else `ProportionOfOwnershipInterestInSubsidiary` (Ind AS 112); `ShareCapitalOfSubsidiary` +
  `ReservesAndSurplusOfSubsidiary` (net worth), `TurnoverOfSubsidiary`, `ProfitAfterTaxOfSubsidiary`.
- ASSOCIATE, `SignificantInvestmentsInAssociatesAxis`: `NameOfAssociateEntity`, `CINOfAssociateEntity`,
  `CountryOfIncorporationOrResidenceOfAssociate`, `ProportionOfOwnershipInterestInAssociate`,
  `NetWorthAttributableToShareholdingAsPerLatestAuditedBalanceSheetAssociate`, `AmountOfInvestmentInAssociate`,
  `ProfitLossForYearAssociateConsideredInConsolidation`.
- JOINT_VENTURE, `JointVenturesAxis`: the same with `...JointVenture` names (`NameOfJointVenture`, `CINOfJointVenture`,
  `CountryOfIncorporationOfJointVenture`, ...).

Rules: a row needs a name; holdings are stored as filed and as a fraction only when 0 <= value <= 1 (one vaulted
filing of 1,492 carries an associate holding above 1: kept as filed, fraction NULL); money is rupees (absolute,
like every XBRL value); only fiscal-year ends the annual parser accepted as in scope (C9) are emitted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from financials.parsers.xbrl import Instance

AOC1_PARSER_VERSION = "aoc1-1"

# relation -> (axis, {field: element})
SCHEDULES: dict[str, tuple[str, dict[str, str]]] = {
    "SUBSIDIARY": (
        "SignificantInvestmentsInSubsidiariesAxis",
        {
            "name": "NameOfSubsidiary",
            "cin": "CINOfSubsidiaryCompany",
            "country": "CountryOfIncorporationOrResidenceOfSubsidiary",
            "holding": "PercentageOfShareholdingInSubsidiary",
            "holding_alt": "ProportionOfOwnershipInterestInSubsidiary",
            "share_capital": "ShareCapitalOfSubsidiary",
            "reserves": "ReservesAndSurplusOfSubsidiary",
            "turnover": "TurnoverOfSubsidiary",
            "pat": "ProfitAfterTaxOfSubsidiary",
        },
    ),
    "ASSOCIATE": (
        "SignificantInvestmentsInAssociatesAxis",
        {
            "name": "NameOfAssociateEntity",
            "cin": "CINOfAssociateEntity",
            "country": "CountryOfIncorporationOrResidenceOfAssociate",
            "holding": "ProportionOfOwnershipInterestInAssociate",
            "net_worth": "NetWorthAttributableToShareholdingAsPerLatestAuditedBalanceSheetAssociate",
            "investment": "AmountOfInvestmentInAssociate",
            "pat": "ProfitLossForYearAssociateConsideredInConsolidation",
        },
    ),
    "JOINT_VENTURE": (
        "JointVenturesAxis",
        {
            "name": "NameOfJointVenture",
            "cin": "CINOfJointVenture",
            "country": "CountryOfIncorporationOfJointVenture",
            "holding": "ProportionOfOwnershipInterestInJointVenture",
            "net_worth": "NetWorthAttributableToShareholdingAsPerLatestAuditedBalanceSheetJointVenture",
            "investment": "AmountOfInvestmentInJointVenture",
            "pat": "ProfitLossForYearJointVentureConsideredInConsolidation",
        },
    ),
}
_AXIS_RELATION = {axis: rel for rel, (axis, _) in SCHEDULES.items()}


@dataclass(frozen=True)
class GroupMember:
    relation: str  # SUBSIDIARY | ASSOCIATE | JOINT_VENTURE
    row_member: str  # typed member as filed (row position inside the year)
    period_end: date  # fiscal year end of the row
    name: str
    cin: str | None
    country: str | None
    holding_as_filed: str | None
    holding_fraction: Decimal | None  # 0..1
    net_worth_inr: Decimal | None  # subsidiary: share capital + reserves; associate / JV: attributable net worth
    turnover_inr: Decimal | None
    pat_inr: Decimal | None  # subsidiary PAT; associate / JV: profit considered in consolidation
    investment_inr: Decimal | None


def _local(x: str) -> str:
    return x.split(":")[-1]


def _num(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_group_structure(inst: Instance, year_ends: set[date]) -> list[GroupMember]:
    """One GroupMember per (relation, typed member, fiscal year end in `year_ends`) that has a name."""
    cells: dict[tuple[str, str, date], dict[str, str]] = defaultdict(dict)
    wanted = {rel: {el: field for field, el in fields.items()} for rel, (_, fields) in SCHEDULES.items()}
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if len(c.dimensions) != 1:
            continue
        axis, member = c.dimensions[0]
        rel = _AXIS_RELATION.get(_local(axis))
        if rel is None or f.name not in wanted[rel]:
            continue
        end = c.instant or c.end
        if end not in year_ends:
            continue
        cells[(rel, member, end)].setdefault(wanted[rel][f.name], f.value_text.strip())
    out = []
    for (rel, member, end), v in sorted(cells.items(), key=lambda kv: (kv[0][2], kv[0][0], _order(kv[0][1]))):
        name = " ".join((v.get("name") or "").split())
        if not name:
            continue
        held = v.get("holding") if v.get("holding") is not None else v.get("holding_alt")
        frac = _num(held)
        if frac is not None and not Decimal(0) <= frac <= Decimal(1):
            frac = None
        if rel == "SUBSIDIARY":
            cap, res = _num(v.get("share_capital")), _num(v.get("reserves"))
            net_worth = None if cap is None or res is None else cap + res
        else:
            net_worth = _num(v.get("net_worth"))
        out.append(
            GroupMember(
                relation=rel,
                row_member=member,
                period_end=end,
                name=name,
                cin=(v.get("cin") or None),
                country=(v.get("country") or None),
                holding_as_filed=held,
                holding_fraction=frac,
                net_worth_inr=net_worth,
                turnover_inr=_num(v.get("turnover")),
                pat_inr=_num(v.get("pat")),
                investment_inr=_num(v.get("investment")),
            )
        )
    return out


def _order(member: str) -> tuple[int, str]:
    return (int(member), "") if member.isdigit() else (1 << 30, member)
