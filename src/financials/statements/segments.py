"""Ind AS 108 segment facts per entity and period, point in time, from the raw facts already in the database [X49].

Segment rows are per-member dimensional records, so they are not zero-drop line items (C24); they stay verbatim in
`raw_xbrl_facts`. This helper reads them back the way `parsers.segments` reads a file (same elements, label from
`DescriptionOfReportableSegment`), for the filings of one entity visible at `as_of`, latest version per
(scope, period end): one query, no file access.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from financials.db import version_key
from financials.parsers.segments import SEGMENT_ELEMENTS


def segment_facts(con, entity_id: str, as_of: datetime, *, scope: str | None = None) -> list[dict]:
    """Rows {scope, period_end_of_filing, segment, member, element, period_start, period_end, value}."""
    rows = con.execute(
        """WITH f AS (
             SELECT filing_id, scope, period_end, row_number() OVER (
                      PARTITION BY scope, period_end ORDER BY visible_from_ts DESC, """
        + version_key()
        + """ DESC) AS rn
             FROM filing_meta
             WHERE entity_id = ? AND visible_from_ts <= ? AND accounting_profile <> 'REG34_ANNUAL'
               AND (? IS NULL OR scope = ?))
           SELECT f.scope, f.period_end, r.element_name, r.ctx_start, r.ctx_end, r.ctx_instant, r.dimensions,
                  r.value_text
           FROM f JOIN raw_xbrl_facts r USING (filing_id)
           WHERE f.rn = 1 AND r.dimensions IS NOT NULL
             AND r.element_name IN (SELECT unnest(?))""",
        [entity_id, as_of, scope, scope, [*SEGMENT_ELEMENTS, "DescriptionOfReportableSegment"]],
    ).fetchall()
    labels: dict[tuple, str] = {}
    facts = []
    for sc, filed_end, name, start, end, instant, dims, text in rows:
        axis, member = next(iter(json.loads(dims).items()))
        if not axis.split(":")[-1].startswith("ReportableSegment"):
            continue
        if name == "DescriptionOfReportableSegment":
            labels.setdefault((sc, filed_end, member), text.strip())
            continue
        facts.append((sc, filed_end, member, name, None if instant else start, instant or end, Decimal(text.strip())))
    return [
        {"scope": sc, "filing_period_end": fe, "segment": labels.get((sc, fe, m), m), "member": m, "element": n,
         "period_start": s, "period_end": e, "value": v}
        for sc, fe, m, n, s, e, v in sorted(facts, key=lambda x: (x[0], x[1], x[3], x[2], str(x[4]), x[5]))
    ]  # fmt: skip


def segment_totals(rows: list[dict], element: str, period: tuple[date | None, date]) -> dict[str, Decimal]:
    """{segment label: value} for one element and period (start None for balance-sheet instants)."""
    return {
        r["segment"]: r["value"]
        for r in rows
        if r["element"] == element and (r["period_start"], r["period_end"]) == period
    }
