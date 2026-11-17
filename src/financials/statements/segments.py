"""Ind AS 108 segment facts per entity and period, point in time, from `segment_observations` [X49].

The quarterly business-segment rows (`ReportableSegment*Axis`, elements `parsers.segments.SEGMENT_ELEMENTS`) of the
results filings of one entity visible at `as_of`, latest version per (scope, period end), each filing at its current
parser version: one query, no file access. Before decision J this read `raw_xbrl_facts`; the clean table holds the
same facts in the periods the filing's parser validated (pre-cutoff comparatives and opening balances are not
parsed, C9; the vault blob keeps them).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from financials.db import version_key
from financials.parsers.segments import SEGMENT_ELEMENTS


def segment_facts(con, entity_id: str, as_of: datetime, *, scope: str | None = None) -> list[dict]:
    """Rows {scope, filing_period_end, segment, member, element, period_start, period_end, value}; period_start is
    None for an instant. Each filing is read at its current parser version (the latest filing_meta version, X83)."""
    rows = con.execute(
        f"""WITH f AS (
             SELECT filing_id, parser_version, scope, period_end, row_number() OVER (
                      PARTITION BY scope, period_end ORDER BY visible_from_ts DESC, {version_key()} DESC) AS rn
             FROM filing_meta
             WHERE entity_id = ? AND visible_from_ts <= ? AND accounting_profile <> 'REG34_ANNUAL'
               AND (? IS NULL OR scope = ?)
               AND {version_key()} = (SELECT max({version_key("x.parser_version")}) FROM filing_meta x
                                      WHERE x.filing_id = filing_meta.filing_id))
           SELECT f.scope, f.period_end, s.member, s.label, s.element, s.period_type, s.period_start, s.period_end,
                  s.value_inr
           FROM f JOIN segment_observations s USING (filing_id, parser_version)  -- the ranked version only
           WHERE f.rn = 1 AND s.axis_kind = 'BUSINESS' AND regexp_replace(s.axis, '^.*:', '') LIKE 'ReportableSegment%'
             AND s.element IN (SELECT unnest(?))""",
        [entity_id, as_of, scope, scope, list(SEGMENT_ELEMENTS)],
    ).fetchall()
    facts = [(sc, fe, label or m, m, n, None if pt == "INSTANT" else ps, pe, v)
             for sc, fe, m, label, n, pt, ps, pe, v in rows]  # fmt: skip
    return [
        {"scope": sc, "filing_period_end": fe, "segment": seg, "member": m, "element": n,
         "period_start": s, "period_end": e, "value": v}
        for sc, fe, seg, m, n, s, e, v in sorted(facts, key=lambda x: (x[0], x[1], x[4], x[3], str(x[5]), x[6]))
    ]  # fmt: skip


def segment_totals(rows: list[dict], element: str, period: tuple[date | None, date]) -> dict[str, Decimal]:
    """{segment label: value} for one element and period (start None for balance-sheet instants)."""
    return {
        r["segment"]: r["value"]
        for r in rows
        if r["element"] == element and (r["period_start"], r["period_end"]) == period
    }
