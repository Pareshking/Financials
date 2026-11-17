"""Every XBRL fact no other clean table captures -> disclosure_facts rows (pure: instance -> rows) [X116, X120].

The clean parsers (results / annual / NBFC / bank / insurer facts, segments, the annual related-party and AOC-1
schedules, the Reg. 23(9) section, the Reg. 31 line items and named holders, Reg. 30 event details) each keep a
subset of a filing's elements. This parser keeps the rest, fact by fact, so that every element of a parsed in-scope
filing reaches a clean table, or is left in the vault blob by a named rule of parser `disc-2` (owner decision M,
X120; below). `captured` is the set of element local names the filing's other clean rows hold verbatim; staging
computes it from those rows (staging.captured_elements), never from a hand-written list.

An element is "captured" when a clean table holds its facts per element, as filed: `fact_observations.source_element`,
`segment_observations.element`, `related_party_transactions.source_element`, `shareholding_line_items.element`, and
the element vocabularies of the row tables that keep each element's value in a named column (group_structure,
reg23_related_party_transactions, shareholding_major_holders, the related-party text columns). Values that land
only in normalised filing metadata (scope, rounding, dates, ISIN, audit flags, shareholding flags) are NOT
captured verbatim, so their elements are kept here too, as filed.

Rows (one per fact of an uncaptured element, document order `seq` = parsers.xbrl Fact.seq):
- period: as tagged, after the filing parser's named re-dating rule STALE_CONTEXT_DATES [X87] (segments.Windows);
  `in_window` is true only for a duration / instant the filing's own parser validated (results: the declared quarter
  and YTD, the period-end instant; annual: the in-scope fiscal years and year ends; shareholding: the as-of instant).
  A context with no period (shareholding rule SHP16) is period_type NONE, never in a window.
- scope cutoff (C9): a fact whose period ends before `min_period_end` is not stored (counted in `skipped_pre_cutoff`).
- values: `value_text` exactly as filed (a long text as a pointer, TEXT_POINTER below); numeric facts also typed:
  money (unit INR) as `value_inr` DECIMAL(20,2) rupees (XBRL values are absolute rupees), every other unit (PURE
  fractions or percent points as filed, SHARES, INR_PER_SHARE, foreign currencies, counts) as `value_num`
  DECIMAL(28,8), never float and never rescaled; a value that is not exactly representable keeps only its text.
  Non-numeric "true" / "false" / "yes" / "no" (any case, trimmed) also as `value_bool`.
- dimensions: JSON {axis QName: member QName} exactly as filed, NULL when none.

Named rules of `disc-2` (owner decision M, 2026-11-16; X120). The vault blob keeps every fact, so nothing is lost:
- EXCLUDED_ELEMENT: a fact of a (source_kind, element) pair listed in reference/disclosure_exclusions.csv (subsidiary
  registry data, policy boilerplate, placeholders, masked / personal ids, web links; two independent reviews dropped
  each in every profile) is not stored (`skipped_excluded`). The list is pinned by EXCLUSIONS_SHA256: a changed list
  is a new parser version.
- MASKED_VALUE: a fact whose value_text is only asterisks (NSE masks PAN etc. as `******`) is not stored
  (`skipped_masked`).
- TEXT_POINTER: a value_text longer than TEXT_POINTER_CHARS characters is stored as a pointer: value_text NULL,
  `text_len` (characters), `text_sha256` (of the exact text as filed, UTF-8) and `text_snippet` (the first
  SNIPPET_CHARS characters after removing HTML tags and entities and collapsing whitespace);
  `financials.disclosures.full_text` returns the whole text from the vault blob (filing -> blob, seq) after
  verifying the sha256. Shorter values keep value_text and leave the three columns NULL.
READ_ELEMENTS (every element a reader selects from disclosure_facts) are exempt from all three: the exclusion list may
not name one (checked on load) and their values are stored exactly as under `disc-1`, so no reader's answer changes.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from financials.money import to_inr
from financials.parsers.indas_corp import period_months
from financials.parsers.segments import Windows
from financials.parsers.xbrl import Instance

DISCLOSURE_PARSER_VERSION = "disc-2"
EXCLUSIONS_FILE = Path(__file__).resolve().parents[3] / "reference" / "disclosure_exclusions.csv"
# sha256 of the sorted "source_kind,element" lines of EXCLUSIONS_FILE (the reasons are documentation only)
EXCLUSIONS_SHA256 = "55de2ef387c3137855b412762300fe54bb9358c9005b7f9fdb282b4506c99a3d"
TEXT_POINTER_CHARS = 1000
SNIPPET_CHARS = 300
BOOLEANS = {"true": True, "false": False, "yes": True, "no": False}
_INR_MAX = Decimal(10) ** 18  # DECIMAL(20,2)
_NUM_MAX = Decimal(10) ** 20  # DECIMAL(28,8)
_NUM_QUANTUM = Decimal("0.00000001")
_MASKED = re.compile(r"\*+")
_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")

# Every element a reader selects from disclosure_facts: features_disclosures (X117-X119), filing_checks.
# filed_scrip_code (G79) and related_parties.pending_results_filings (X115). tests/test_disclosures.py derives the set
# from those modules and fails when a reader names an element missing here.
_SHP_DECLARATIONS = (
    "WhetherTheListedEntityHasIssuedAnyWarrants",
    "WhetherTheListedEntityHasIssuedAnyConvertibleSecurities",
    "WhetherTheListedEntityHasIssuedAnyPartlyPaidUpShares",
    "WhetherTheListedEntityHasAnySharesInLockedIn",
    "WhetherCompanyHasEquitySharesWithDifferentialVotingRights",
    "WhetherTheListedEntityHasAnySignificantBeneficialOwner",
    "WhetherTheListedEntityIsPublicSectorUndertaking",
)
_SHP_VARIANTS = ("", "ForPromoterAndPromoterGroup", "ForPublicShareholder", "ForPublicShareHolder",
                 "ForNonPromoterNonPublic")  # fmt: skip
READ_ELEMENTS = frozenset({
    "TradeReceivablesDueByDirectors",
    "TradeReceivablesDueByOtherOfficers",
    "TradeReceivablesDueByFirmsOrCompaniesInWhichAnyDirectorIsPartnerOrDirector",
    "TradeReceivablesDueByFirmsInWhichAnyDirectorIsPartner",
    "TradeReceivablesDueByPrivateCompaniesInWhichAnyDirectorIsDirector",
    "TradeReceivablesDueByPrivateCompaniesInWhichAnyDirectorIsMember",
    "NameOfEntityConsolidated",
    "TypeOfEntityConsolidated",
    "AmountOfShareInProfitOrLossOfEntityConsolidated",
    "ScripCode",
    "NameOfCounterParty",
    *(e + v for e in _SHP_DECLARATIONS for v in _SHP_VARIANTS),
})  # fmt: skip


@dataclass(frozen=True)
class DisclosureFact:
    seq: int  # document order, = parsers.xbrl Fact.seq of the filing's instance
    element_ns: str
    element: str  # local name as filed
    context_id: str
    period_type: str  # DURATION | INSTANT | NONE
    period_start: date | None  # = period_end for INSTANT; NULL for NONE
    period_end: date | None
    period_months: int | None  # DURATION on whole calendar months only
    in_window: bool
    dimensions: str | None  # JSON {axis: member} as filed
    unit_ref: str | None
    unit: str | None  # Instance.unit_kind: INR | PURE | SHARES | INR_PER_SHARE | <CCY> | UNKNOWN
    value_inr: Decimal | None
    value_num: Decimal | None
    value_bool: bool | None
    value_text: str | None  # NULL for a TEXT_POINTER row
    text_len: int | None = None  # TEXT_POINTER rows only (module doc)
    text_sha256: str | None = None
    text_snippet: str | None = None


@dataclass
class DisclosureReport:
    facts: list[DisclosureFact]
    skipped_pre_cutoff: int = 0
    skipped_excluded: int = 0  # EXCLUDED_ELEMENT
    skipped_masked: int = 0  # MASKED_VALUE
    pointers: int = 0  # TEXT_POINTER


def exclusions_sha256(pairs) -> str:
    return hashlib.sha256("\n".join(sorted(f"{k},{e}" for k, e in pairs)).encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def excluded_elements() -> frozenset[tuple[str, str]]:
    """The EXCLUDED_ELEMENT rule: {(source_kind, element)} of reference/disclosure_exclusions.csv, checked against
    EXCLUSIONS_SHA256 and READ_ELEMENTS (a changed or unsafe list raises: it would silently change `disc-2`)."""
    with EXCLUSIONS_FILE.open(encoding="utf-8", newline="") as fh:
        pairs = frozenset((r["source_kind"], r["element"]) for r in csv.DictReader(fh))
    if exclusions_sha256(pairs) != EXCLUSIONS_SHA256:
        raise RuntimeError(f"{EXCLUSIONS_FILE.name} changed (sha256 {exclusions_sha256(pairs)}): a new exclusion "
                           "list is a new DISCLOSURE_PARSER_VERSION; change both together")  # fmt: skip
    unsafe = sorted(e for _, e in pairs if e in READ_ELEMENTS)
    if unsafe:
        raise RuntimeError(f"{EXCLUSIONS_FILE.name} names elements a reader selects: {unsafe}")
    return pairs


def is_masked(text: str) -> bool:
    """The MASKED_VALUE rule: the value is asterisks only."""
    return _MASKED.fullmatch(text) is not None


def text_sha256(text: str) -> str:
    """sha256 of a value exactly as filed (UTF-8), as stored for a TEXT_POINTER row."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snippet(text: str) -> str:
    """The first SNIPPET_CHARS characters of a text block without HTML tags and entities, whitespace collapsed
    (tags written as entities inside the text are removed too)."""
    plain = _TAG.sub(" ", html.unescape(_TAG.sub(" ", text)))
    return _SPACE.sub(" ", plain).strip()[:SNIPPET_CHARS]


def _decimal(text: str) -> Decimal | None:
    try:
        v = Decimal(text.strip())
    except InvalidOperation:
        return None
    return v if v.is_finite() else None


def typed_value(text: str, unit: str | None) -> tuple[Decimal | None, Decimal | None, bool | None]:
    """(value_inr, value_num, value_bool) of one fact: see the module doc."""
    if unit is None:
        return None, None, BOOLEANS.get(text.strip().lower())
    v = _decimal(text)
    if v is None:
        return None, None, None
    if unit == "INR":
        inr = to_inr(v)
        return (inr if inr == v and abs(inr) < _INR_MAX else None), None, None
    num = v.quantize(_NUM_QUANTUM) if abs(v) < _NUM_MAX else None
    return None, (num if num is not None and num == v else None), None


def parse_disclosures(
    inst: Instance,
    captured: frozenset[str] | set[str],
    windows: Windows | None,
    *,
    min_period_end: date | None,
    source_kind: str,
) -> DisclosureReport:
    """One DisclosureFact per fact whose element is not in `captured`, after the named rules (module doc)."""
    report = DisclosureReport([])
    durations = windows.durations if windows else frozenset()
    instants = windows.instants if windows else frozenset()
    excluded = {e for k, e in excluded_elements() if k == source_kind}
    for f in inst.facts:
        if f.name in captured:
            continue
        if f.name in excluded:
            report.skipped_excluded += 1
            continue
        read = f.name in READ_ELEMENTS
        if not read and is_masked(f.value_text):
            report.skipped_masked += 1
            continue
        c = inst.contexts[f.context_id]
        start, end = c.start, c.end
        if c.instant is not None:
            kind, start, end = "INSTANT", None, c.instant
        elif end is not None:
            kind = "DURATION"
        else:
            kind, start = "NONE", None
        if windows is not None and kind != "NONE":
            start, end = windows.resolve(start, end)
        if min_period_end is not None and end is not None and end < min_period_end:
            report.skipped_pre_cutoff += 1
            continue
        if kind == "INSTANT":
            start, months, ok = end, None, end in instants
        elif kind == "DURATION":
            months = period_months(start, end) if start is not None else None
            if months is not None and not 1 <= months <= 18:
                months = None
            ok = (start, end) in durations
        else:
            months, ok = None, False
        unit = inst.unit_kind(f.unit_ref)
        inr, num, flag = typed_value(f.value_text, unit)
        text, pointer = f.value_text, {}
        if not read and len(text) > TEXT_POINTER_CHARS:
            pointer = {"text_len": len(text), "text_sha256": text_sha256(text), "text_snippet": snippet(text)}
            text = None
            report.pointers += 1
        report.facts.append(
            DisclosureFact(
                seq=f.seq,
                element_ns=f.ns,
                element=f.name,
                context_id=f.context_id,
                period_type=kind,
                period_start=start,
                period_end=end,
                period_months=months,
                in_window=ok,
                dimensions=json.dumps(dict(c.dimensions)) if c.dimensions else None,
                unit_ref=f.unit_ref,
                unit=unit,
                value_inr=inr,
                value_num=num,
                value_bool=flag,
                value_text=text,
                **pointer,
            )
        )
    return report
