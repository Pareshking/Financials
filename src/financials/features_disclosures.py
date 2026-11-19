"""Columns from `disclosure_facts` [X116] (features 2026.11.16-18D), for `features.py`. Three groups, each one batched
read per materialisation (never a query per security), point in time (`visible_from_ts <= as_of`), NULL when not filed:

Insider receivables (X117; Reg. 34 annual, Schedule III trade-receivables note). Per (entity, scope) the latest fiscal
year end with these facts, from the latest visible annual filing for that year end (then filing, parser version), the
row's scope first, else the other (consolidated first), like features_rpt:
- insider_receivables = TradeReceivablesDueByDirectors + TradeReceivablesDueByOtherOfficers +
  TradeReceivablesDueByFirmsOrCompaniesInWhichAnyDirectorIsPartnerOrDirector at the year-end instant. The firms /
  companies element is the subtotal of ...ByFirmsInWhichAnyDirectorIsPartner + ...ByPrivateCompaniesInWhichAny
  DirectorIsDirector + ...ByPrivateCompaniesInWhichAnyDirectorIsMember (equal in all 4,915 vault cells that file a
  part; filed alone in 1,291): it is used, and the three parts only when it is absent. TradeReceivablesDueByDirectors
  OtherOfficersOrOthers is directors + officers + `...ByOthers` (third parties; equal in all 4,979 vault cells, ELECON:
  = total receivables) and is never added. Each element is summed over the security / current-noncurrent classes of
  its most detailed dimension set only (414 vault cells file both a per-class and a current-noncurrent x class split;
  the per-class value is always the sum of the split).
- insider_receivables_to_receivables = that sum / (trade_receivables_current + trade_receivables_noncurrent) of the
  SAME filing and instant (fact_observations, current parser version); NULL when that is missing or <= 0.
- has_insider_receivables = insider_receivables > 0; insider_receivables_as_of = the instant used.

Shareholding declarations (X118; Reg. 31): from the latest visible shareholding filing (latest as-of date, then the
latest visible revision, as features._preload), the filing's undimensioned entity-level declaration. Every vaulted
filing (4,795) files the entity-level element, and in all of them it equals the OR of its three category variants
(...ForPromoterAndPromoterGroup / ...ForPublicShareholder / ...ForNonPromoterNonPublic): the entity-level value is
used; only when it is absent, true if any variant is true, false if every variant is filed false. A value that is
not true/false (e.g. "******") is NULL.

Subsidiary contribution (X119; Reg. 34 consolidated annual, Schedule III "additional information" table on
`EntitiesConsolidatedAxis`, one typed or explicit member per row): the latest visible consolidated annual filing per
fiscal year end, the latest year end. Rows by `TypeOfEntityConsolidated` (a closed list in the vault: Parent, Indian /
Foreign Subsidiary, Indian / Foreign Associate, Indian / Foreign Joint Venture, Non Controlling Interests In All
Subsidiaries), except that a row whose name says adjustment / elimination is an ADJUSTMENT row whatever its type
(ETERNAL types its consolidation adjustments "Parent", SRF "Indian Subsidiary") and a row whose name says
non-controlling / minority is NCI.
- parent_profit_share = AmountOfShareInProfitOrLossOfEntityConsolidated of the Parent row(s) / the filing's own
  consolidated PAT (fact_observations `pat`, 12 months to the year end, same filing). That is the filed percentage's
  denominator in CUMMINSIND, ETERNAL and SRF; TCS files its percentages against the pre-elimination sum instead, so the
  filed percentage element is not used. NULL without a Parent row (SPARC files subsidiaries only) or PAT <= 0.
- largest_subsidiary_profit_share / largest_subsidiary_name = the subsidiary row with the largest amount / PAT.
- consolidated_entities_count = distinct names of the subsidiary, associate and joint-venture rows (TCS files the NCI
  share of a subsidiary as a second row with the same name).
Fractions as DOUBLE, like the other `_share` / `_to_` columns. EVENT columns: insider and subsidiary (from annual
filings, whose visibility is in the FundamentalsCache key); the shareholding flags are DAILY (shareholding is not).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from financials.db import version_key
from financials.fundamentals import CURRENT_VERSION, entity_filter, safe_div
from financials.run_memo import by_visibility

INSIDER_COLUMNS = ("insider_receivables_as_of", "insider_receivables", "insider_receivables_to_receivables",
                   "has_insider_receivables")  # fmt: skip
SHP_DECLARATION_COLUMNS = ("has_warrants", "has_convertibles", "has_partly_paid", "has_locked_in", "has_dvr_shares",
                           "has_sbo", "is_psu")  # fmt: skip
SUBSIDIARY_COLUMNS = ("subsidiary_fy_end", "parent_profit_share", "largest_subsidiary_profit_share",
                      "largest_subsidiary_name", "consolidated_entities_count")  # fmt: skip
COLUMNS = (*INSIDER_COLUMNS, *SHP_DECLARATION_COLUMNS, *SUBSIDIARY_COLUMNS)

DIRECTORS, OFFICERS = "TradeReceivablesDueByDirectors", "TradeReceivablesDueByOtherOfficers"
FIRMS = "TradeReceivablesDueByFirmsOrCompaniesInWhichAnyDirectorIsPartnerOrDirector"
FIRMS_PARTS = ("TradeReceivablesDueByFirmsInWhichAnyDirectorIsPartner",
               "TradeReceivablesDueByPrivateCompaniesInWhichAnyDirectorIsDirector",
               "TradeReceivablesDueByPrivateCompaniesInWhichAnyDirectorIsMember")  # fmt: skip
INSIDER_ELEMENTS = (DIRECTORS, OFFICERS, FIRMS, *FIRMS_PARTS)
RECEIVABLE_TAGS = ("trade_receivables_current", "trade_receivables_noncurrent")

SHP_DECLARATIONS = {
    "has_warrants": "WhetherTheListedEntityHasIssuedAnyWarrants",
    "has_convertibles": "WhetherTheListedEntityHasIssuedAnyConvertibleSecurities",
    "has_partly_paid": "WhetherTheListedEntityHasIssuedAnyPartlyPaidUpShares",
    "has_locked_in": "WhetherTheListedEntityHasAnySharesInLockedIn",
    "has_dvr_shares": "WhetherCompanyHasEquitySharesWithDifferentialVotingRights",
    "has_sbo": "WhetherTheListedEntityHasAnySignificantBeneficialOwner",
    "is_psu": "WhetherTheListedEntityIsPublicSectorUndertaking",
}
# The category variants of a declaration as filed (the 2022-09-30 taxonomy spells the public one ...ShareHolder).
SHP_VARIANTS = (
    "ForPromoterAndPromoterGroup",
    "ForPublicShareholder",
    "ForPublicShareHolder",
    "ForNonPromoterNonPublic",
)

ENTITY_AXIS = "EntitiesConsolidatedAxis"
ENTITY_NAME, ENTITY_TYPE = "NameOfEntityConsolidated", "TypeOfEntityConsolidated"
ENTITY_PROFIT = "AmountOfShareInProfitOrLossOfEntityConsolidated"
ADJUSTMENT_NAME = re.compile(r"adjust|eliminat", re.I)
NCI_TEXT = re.compile(r"non[\s-]*controlling|minority", re.I)
ZERO = Decimal(0)


def _latest(only: str, where: str) -> str:
    """The rows (`where`; parameters: as_of_ts, the entity filter, the element list) of the latest visible annual
    filing per (entity, scope, period end) that files them: the features_rpt ranking. Filtered before the ranking,
    so the scan never carries text blocks of other elements."""
    return f"""SELECT entity_id, scope, filing_id, period_end, element, dimensions, value_inr, value_text
               FROM disclosure_facts
               WHERE visible_from_ts <= ? AND source_kind = 'ANNUAL' AND in_window {only}
                 AND element IN (SELECT unnest(?)) AND {where}
               QUALIFY dense_rank() OVER (PARTITION BY entity_id, scope, period_end
                                          ORDER BY visible_from_ts DESC, filing_id DESC,
                                                   {version_key("parser_version")} DESC) = 1"""


def _local(qname: str) -> str:
    return qname.split(":")[-1]


def _axes(dimensions: str | None) -> dict[str, str]:
    return {_local(a): _local(m) for a, m in json.loads(dimensions).items()} if dimensions else {}


def _facts_by_filing(con, keys: set[tuple[str, date]], tags: tuple[str, ...], kind: str) -> dict:
    """{(filing_id, period_end): {tag: value_inr}} from fact_observations (current parser version), one read."""
    if not keys:
        return {}
    import pyarrow as pa

    keys_sorted = sorted(keys)
    con.register("_disc_keys", pa.table({"filing_id": [k[0] for k in keys_sorted],
                                         "period_end": [k[1] for k in keys_sorted]}))  # fmt: skip
    period = "f.period_type = 'INSTANT'" if kind == "INSTANT" else "f.period_type = 'DURATION' AND f.period_months = 12"
    try:
        found = con.execute(
            f"""SELECT f.filing_id, f.period_end, f.canonical_tag, f.value_inr
                FROM fact_observations f JOIN _disc_keys k ON f.filing_id = k.filing_id AND f.period_end = k.period_end
                WHERE f.value_inr IS NOT NULL AND {period} AND f.canonical_tag IN (SELECT unnest(?)) AND """
            + CURRENT_VERSION.replace("fact_observations.", "f."),
            [list(tags)],
        ).fetchall()
    finally:
        con.unregister("_disc_keys")
    out: dict = defaultdict(dict)
    for fid, end, tag, value in found:
        out[(fid, end)][tag] = Decimal(value)
    return out


# ── insider receivables ─────────────────────────────────────────────────────────────────────────────────────────


def element_total(cells: list[tuple[dict[str, str], Decimal]]) -> Decimal:
    """One element's value at one instant: the sum over its most detailed dimension set only (module doc)."""
    widest = max(len(axes) for axes, _ in cells)
    return sum((v for axes, v in cells if len(axes) == widest), ZERO)


def insider_total(by_element: dict[str, list[tuple[dict[str, str], Decimal]]]) -> Decimal | None:
    """Directors + other officers + firms / companies (the subtotal, else its parts); None when none is filed."""
    if not any(by_element.get(e) for e in INSIDER_ELEMENTS):
        return None
    firms = [FIRMS] if by_element.get(FIRMS) else [e for e in FIRMS_PARTS if by_element.get(e)]
    return sum((element_total(by_element[e]) for e in (DIRECTORS, OFFICERS, *firms) if by_element.get(e)), ZERO)


@by_visibility  # read once per visibility interval of an incremental run (run_memo)
def insider_inputs(con, as_of_ts: datetime, entities=None) -> dict[tuple[str, str], dict]:
    only, only_p = entity_filter("entity_id", entities)
    cells: dict[tuple[str, str, date], dict] = {}
    for ent, scope, fid, end, element, dims, value in con.execute(
        f"""SELECT entity_id, scope, filing_id, period_end, element, dimensions, value_inr
            FROM ({_latest(only, "period_type = 'INSTANT' AND value_inr IS NOT NULL")})""",
        [as_of_ts, *only_p, list(INSIDER_ELEMENTS)],
    ).fetchall():
        c = cells.setdefault((ent, scope, end), {"filing_id": fid, "by_element": defaultdict(list)})
        c["by_element"][element].append((_axes(dims), Decimal(value)))
    latest: dict[tuple[str, str], tuple[date, dict]] = {}
    for (ent, scope, end), c in cells.items():
        if (ent, scope) not in latest or end > latest[(ent, scope)][0]:
            latest[(ent, scope)] = (end, c)
    dens = _facts_by_filing(con, {(c["filing_id"], end) for end, c in latest.values()}, RECEIVABLE_TAGS, "INSTANT")
    out = {}
    for key, (end, c) in latest.items():
        d = dens.get((c["filing_id"], end), {})
        receivables = sum(d.values(), ZERO) if d else None
        out[key] = {"as_of": end, "insider": insider_total(c["by_element"]), "receivables": receivables}
    return out


def insider_columns(inputs: dict | None) -> dict:
    out = dict.fromkeys(INSIDER_COLUMNS)
    if inputs is None or inputs["insider"] is None:
        return out
    insider, den = inputs["insider"], inputs["receivables"]
    ratio = safe_div(insider, den) if den is not None and den > 0 else None
    out.update(insider_receivables_as_of=inputs["as_of"], insider_receivables=insider,
               insider_receivables_to_receivables=None if ratio is None else float(ratio),
               has_insider_receivables=insider > 0)  # fmt: skip
    return out


# ── shareholding declarations ───────────────────────────────────────────────────────────────────────────────────


def declaration(values: dict[str, bool | None], element: str) -> bool | None:
    """The entity-level declaration, else the OR of its category variants (module doc)."""
    if element in values:
        return values[element]
    variants = [values[element + v] for v in SHP_VARIANTS if element + v in values]
    if any(v is True for v in variants):
        return True
    return False if variants and all(v is False for v in variants) else None


@by_visibility  # read once per visibility interval of an incremental run (run_memo)
def shp_inputs(con, as_of_ts: datetime, entities=None) -> dict[str, dict[str, bool | None]]:
    only, only_p = entity_filter("entity_id", entities)
    wanted = [e + v for e in SHP_DECLARATIONS.values() for v in ("", *SHP_VARIANTS)]
    out: dict[str, dict[str, bool | None]] = defaultdict(dict)
    for ent, element, flag in con.execute(
        f"""WITH f AS (
                SELECT entity_id, filing_id FROM shareholding_meta WHERE visible_from_ts <= ? {only}
                QUALIFY row_number() OVER (PARTITION BY entity_id ORDER BY as_of_date DESC, visible_from_ts DESC,
                                           {version_key()} DESC, filing_id DESC) = 1)
            SELECT f.entity_id, d.element, d.value_bool FROM f JOIN disclosure_facts d USING (filing_id)
            WHERE d.dimensions IS NULL AND d.element IN (SELECT unnest(?))
            QUALIFY dense_rank() OVER (PARTITION BY d.filing_id ORDER BY {version_key("d.parser_version")} DESC) = 1""",
        [as_of_ts, *only_p, wanted],
    ).fetchall():
        out[ent][element] = flag
    return dict(out)


def shp_columns(values: dict[str, bool | None] | None) -> dict:
    if values is None:
        return dict.fromkeys(SHP_DECLARATION_COLUMNS)
    return {col: declaration(values, element) for col, element in SHP_DECLARATIONS.items()}


# ── subsidiary contribution ─────────────────────────────────────────────────────────────────────────────────────


def entity_role(name: str | None, kind: str | None) -> str:
    """PARENT | SUBSIDIARY | ASSOCIATE | JOINT_VENTURE | NCI | ADJUSTMENT | OTHER of one Schedule III row."""
    name, kind = (name or "").strip(), " ".join((kind or "").split()).lower()
    if ADJUSTMENT_NAME.search(name):
        return "ADJUSTMENT"
    if NCI_TEXT.search(kind) or NCI_TEXT.search(name):
        return "NCI"
    if kind == "parent":
        return "PARENT"
    for suffix, role in (("subsidiary", "SUBSIDIARY"), ("associate", "ASSOCIATE"), ("joint venture", "JOINT_VENTURE")):
        if kind.endswith(suffix):
            return role
    return "OTHER"


@by_visibility  # read once per visibility interval of an incremental run (run_memo)
def subsidiary_inputs(con, as_of_ts: datetime, entities=None) -> dict[str, dict]:
    only, only_p = entity_filter("entity_id", entities)
    years: dict[tuple[str, date], dict] = {}
    for ent, fid, end, element, dims, value_inr, text in con.execute(
        f"""SELECT entity_id, filing_id, period_end, element, dimensions, value_inr, value_text
            FROM ({_latest(only, "scope = 'CONSOLIDATED' AND dimensions IS NOT NULL")})""",
        [as_of_ts, *only_p, [ENTITY_NAME, ENTITY_TYPE, ENTITY_PROFIT]],
    ).fetchall():
        axes = _axes(dims)
        if set(axes) != {ENTITY_AXIS}:
            continue
        y = years.setdefault((ent, end), {"filing_id": fid, "rows": defaultdict(dict)})
        y["rows"][axes[ENTITY_AXIS]][element] = Decimal(value_inr) if element == ENTITY_PROFIT else text
    latest: dict[str, tuple[date, dict]] = {}
    for (ent, end), y in years.items():
        if any(ENTITY_PROFIT in r for r in y["rows"].values()) and (ent not in latest or end > latest[ent][0]):
            latest[ent] = (end, y)
    pats = _facts_by_filing(con, {(y["filing_id"], end) for end, y in latest.values()}, ("pat",), "DURATION")
    return {
        ent: {"fy_end": end, "rows": list(y["rows"].values()), "pat": pats.get((y["filing_id"], end), {}).get("pat")}
        for ent, (end, y) in latest.items()
    }


def subsidiary_columns(inputs: dict | None) -> dict:
    out = dict.fromkeys(SUBSIDIARY_COLUMNS)
    if inputs is None:
        return out
    pat = inputs["pat"]
    share = lambda v: None if pat is None or pat <= 0 or v is None else float(safe_div(v, pat))  # noqa: E731
    parent, subs, names = [], [], set()
    for r in inputs["rows"]:
        role = entity_role(r.get(ENTITY_NAME), r.get(ENTITY_TYPE))
        amount = r.get(ENTITY_PROFIT)
        if role == "PARENT" and amount is not None:
            parent.append(amount)
        elif role in ("SUBSIDIARY", "ASSOCIATE", "JOINT_VENTURE"):
            if r.get(ENTITY_NAME):
                names.add(" ".join(r[ENTITY_NAME].split()).lower())
            if role == "SUBSIDIARY" and amount is not None:
                subs.append((amount, " ".join((r.get(ENTITY_NAME) or "").split()) or None))
    top = max(subs, key=lambda s: (s[0], s[1] or ""), default=None)
    out.update(subsidiary_fy_end=inputs["fy_end"], parent_profit_share=share(sum(parent, ZERO)) if parent else None,
               largest_subsidiary_profit_share=share(top[0]) if top else None,
               largest_subsidiary_name=top[1] if top else None, consolidated_entities_count=len(names))  # fmt: skip
    return out


def add_columns(con, rows: list[dict], as_of_ts: datetime, entities=None) -> None:
    """The features.compute_rows hook (after batch J): three batched reads, then each row's columns, in place."""
    insider = insider_inputs(con, as_of_ts, entities)
    shp = shp_inputs(con, as_of_ts, entities)
    subs = subsidiary_inputs(con, as_of_ts, entities)
    for row in rows:
        ent, scope = row["entity_id"], row.get("scope_used")
        order = [scope] if scope else []
        order += [s for s in ("CONSOLIDATED", "STANDALONE") if s not in order]
        row.update(insider_columns(next((insider[(ent, s)] for s in order if (ent, s) in insider), None)))
        row.update(shp_columns(shp.get(ent)))
        row.update(subsidiary_columns(subs.get(ent)))


def dsl_aliases() -> dict[str, tuple[str, str]]:
    """Screener-style names for the numeric columns of this module (fractions shown x100). The booleans and dates are
    screened by their column names (`has_warrants = true`, `screen --columns`)."""
    return {
        "insider receivables": ("(insider_receivables / 10000000)", "INR crore, trade receivables due by directors / "
                                "officers / their firms and companies, last FY end"),
        "insider receivables pct": ("(insider_receivables_to_receivables * 100)",
                                    "%, insider receivables / trade receivables, same filing"),
        "parent profit share": ("(parent_profit_share * 100)", "%, parent's share of consolidated PAT, last FY"),
        "largest subsidiary profit share": ("(largest_subsidiary_profit_share * 100)",
                                            "%, largest subsidiary's share of consolidated PAT, last FY"),
        "consolidated entities": ("consolidated_entities_count",
                                  "count, subsidiaries + associates + JVs in the Schedule III table"),
    }  # fmt: skip
