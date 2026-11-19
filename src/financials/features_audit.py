"""Audit-opinion columns from `audit_opinions` [X121-X124] (features 2026.11.17-20A), for `features.py`: one batched
read per materialisation (never a query per security), point in time (`visible_from_ts <= as_of`), NULL when not
filed. Runs before features_gems, whose `forensic_clean` reads them.

Annual (Reg. 34, the auditor's report text; parsers/audit_report.py): per entity and scope the latest fiscal year end
with a row, from its latest visible filing (then filing id, parser version); the scopes of the entity's latest fiscal
year end are combined (a qualified consolidated report is a red flag whichever scope the row uses):
- audit_opinion = the most severe opinion of those scopes (DISCLAIMER > ADVERSE > QUALIFIED > UNMODIFIED; NULL when
  no scope's text states one, e.g. a report filed as "As per attachment"); audit_opinion_fy_end = that year end.
- audit_opinion_conflict = any scope's text opinion disagrees with its Reg. 34 checkbox (opinion_conflict; true when
  any is, false when every known one is false).
- going_concern_uncertainty = any scope's report has a Material Uncertainty Related to Going Concern section about
  the reporting entity / group (a section about a component only, GOING_CONCERN_COMPONENT, does not count).
- emphasis_of_matter = any scope's report has an Emphasis of Matter section (informational: never fails a gate).
Quarterly (Integrated Filing audit fields): per entity and scope the latest visible results filing that states an
opinion (a declaration of unmodified opinion or a statement on impact of audit qualification; "Not applicable"
quarters state none), the latest quarter end across scopes: audit_opinion_quarterly (most severe of those scopes) and
audit_opinion_quarter_end.
All EVENT columns: they change only when a results / annual filing becomes visible (its filing_meta visibility is in
the FundamentalsCache key).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from financials.db import version_key
from financials.fundamentals import entity_filter
from financials.parsers.audit_report import MODIFIED, worst
from financials.run_memo import by_visibility

COLUMNS = ("audit_opinion", "audit_opinion_fy_end", "audit_opinion_conflict", "going_concern_uncertainty",
           "emphasis_of_matter", "audit_opinion_quarterly", "audit_opinion_quarter_end")  # fmt: skip


@by_visibility  # read once per visibility interval of an incremental run (run_memo)
def inputs(con, as_of_ts: datetime, entities=None) -> dict[str, dict[str, list[tuple]]]:
    """{entity: {'ANNUAL' | 'RESULTS': [(period_end, opinion, conflict, going concern, emphasis)] of the scopes of the
    latest period end}}: one read (module doc)."""
    only, only_p = entity_filter("entity_id", entities)
    found = con.execute(
        f"""WITH v AS (
                SELECT entity_id, source_kind, scope, period_end, audit_opinion, opinion_conflict,
                       going_concern_uncertainty, emphasis_of_matter
                FROM audit_opinions
                WHERE visible_from_ts <= ? {only} AND (source_kind = 'ANNUAL' OR audit_opinion IS NOT NULL)
                QUALIFY row_number() OVER (PARTITION BY entity_id, source_kind, scope
                                           ORDER BY period_end DESC, visible_from_ts DESC, filing_id DESC,
                                                    {version_key()} DESC) = 1)
            SELECT * FROM v QUALIFY rank() OVER (PARTITION BY entity_id, source_kind ORDER BY period_end DESC) = 1
            ORDER BY entity_id, source_kind, scope""",
        [as_of_ts, *only_p],
    ).fetchall()
    out: dict[str, dict[str, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    for ent, kind, _scope, end, opinion, conflict, going, emphasis in found:
        out[ent][kind].append((end, opinion, conflict, going, emphasis))
    return out


def _any(values) -> bool | None:
    known = [v for v in values if v is not None]
    return any(known) if known else None


def columns(inp: dict[str, list[tuple]] | None) -> dict:
    out = dict.fromkeys(COLUMNS)
    if not inp:
        return out
    annual = inp.get("ANNUAL") or []
    if annual:
        out.update(audit_opinion=worst(r[1] for r in annual), audit_opinion_fy_end=annual[0][0],
                   audit_opinion_conflict=_any(r[2] for r in annual),
                   going_concern_uncertainty=_any(r[3] for r in annual),
                   emphasis_of_matter=_any(r[4] for r in annual))  # fmt: skip
    results = inp.get("RESULTS") or []
    if results:
        out.update(audit_opinion_quarterly=worst(r[1] for r in results), audit_opinion_quarter_end=results[0][0])
    return out


def modified_opinion(row: dict) -> bool | None:
    """TRUE when the latest annual or quarterly opinion is QUALIFIED / ADVERSE / DISCLAIMER; FALSE when what is filed
    is unmodified; NULL when neither is filed (features_extra.rf_audit_qualified, features_gems.forensic_clean)."""
    opinions = [row.get("audit_opinion"), row.get("audit_opinion_quarterly")]
    if any(o in MODIFIED for o in opinions):
        return True
    return None if all(o is None for o in opinions) else False


def add_columns(con, rows: list[dict], as_of_ts: datetime, entities=None) -> None:
    """The features.compute_rows hook (before features_gems): one batched read, then each row's columns, in place."""
    found = inputs(con, as_of_ts, entities)
    for row in rows:
        row.update(columns(found.get(row["entity_id"])))


def dsl_aliases() -> dict[str, tuple[str, str]]:
    """Screener-style 1/0 flags; the opinions are screened by their column names (`audit_opinion = 'QUALIFIED'`)."""
    return {
        "audit opinion modified": ("CAST(audit_opinion IN ('QUALIFIED', 'ADVERSE', 'DISCLAIMER') AS INTEGER)",
                                   "1/0, latest annual auditor's report qualified / adverse / disclaimer (text)"),
        "quarterly audit opinion modified": (
            "CAST(audit_opinion_quarterly IN ('QUALIFIED', 'ADVERSE', 'DISCLAIMER') AS INTEGER)",
            "1/0, latest results audit opinion qualified / adverse / disclaimer"),
        "audit opinion conflict": ("CAST(audit_opinion_conflict AS INTEGER)",
                                   "1/0, report text and Reg. 34 checkbox disagree"),
        "going concern uncertainty": ("CAST(going_concern_uncertainty AS INTEGER)",
                                      "1/0, material uncertainty related to going concern (latest annual report)"),
        "emphasis of matter": ("CAST(emphasis_of_matter AS INTEGER)", "1/0, emphasis of matter (latest annual report)"),
    }  # fmt: skip
