"""Every XBRL fact no other clean table captures -> disclosure_facts rows (pure: instance -> rows) [X116].

The clean parsers (results / annual / NBFC / bank / insurer facts, segments, the annual related-party and AOC-1
schedules, the Reg. 23(9) section, the Reg. 31 line items and named holders, Reg. 30 event details) each keep a
subset of a filing's elements. This parser keeps the rest, fact by fact, so that every element of a parsed in-scope
filing reaches a clean table. `captured` is the set of element local names the filing's other clean rows hold
verbatim; staging computes it from those rows (staging.captured_elements), never from a hand-written list.

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
- values: `value_text` exactly as filed (text blocks included, whatever their size); numeric facts also typed:
  money (unit INR) as `value_inr` DECIMAL(20,2) rupees (XBRL values are absolute rupees), every other unit (PURE
  fractions or percent points as filed, SHARES, INR_PER_SHARE, foreign currencies, counts) as `value_num`
  DECIMAL(28,8), never float and never rescaled; a value that is not exactly representable keeps only its text.
  Non-numeric "true" / "false" / "yes" / "no" (any case, trimmed) also as `value_bool`.
- dimensions: JSON {axis QName: member QName} exactly as filed, NULL when none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from financials.money import to_inr
from financials.parsers.indas_corp import period_months
from financials.parsers.segments import Windows
from financials.parsers.xbrl import Instance

DISCLOSURE_PARSER_VERSION = "disc-1"
BOOLEANS = {"true": True, "false": False, "yes": True, "no": False}
_INR_MAX = Decimal(10) ** 18  # DECIMAL(20,2)
_NUM_MAX = Decimal(10) ** 20  # DECIMAL(28,8)
_NUM_QUANTUM = Decimal("0.00000001")


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
    value_text: str


@dataclass
class DisclosureReport:
    facts: list[DisclosureFact]
    skipped_pre_cutoff: int = 0


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
    inst: Instance, captured: frozenset[str] | set[str], windows: Windows | None, *, min_period_end: date | None
) -> DisclosureReport:
    """One DisclosureFact per fact whose element is not in `captured` (see the module doc)."""
    report = DisclosureReport([])
    durations = windows.durations if windows else frozenset()
    instants = windows.instants if windows else frozenset()
    for f in inst.facts:
        if f.name in captured:
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
                value_text=f.value_text,
            )
        )
    return report
