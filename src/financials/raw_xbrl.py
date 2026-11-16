"""Owner decision J (2026-11-16): the gate for, and the one-shot removal of, the `raw_xbrl_facts` table.

`raw_xbrl_facts` held every XBRL fact verbatim, once per parser version. Every element of every parsed filing now
reaches a clean table (`disclosure_facts` holds whatever no other clean table captures, X116) and the vault blob is
the source of truth: anything that needs a filing's raw facts parses the blob (`parsers.xbrl.parse_instance`).

- `coverage(con)`: per accounting profile / file type, the raw elements of the promoted filings (contexts on or
  after the C9 cutoff, or with no period) that no clean row of the filing holds. Read-only; needs the table, so it
  runs on a database that still has it (`scripts/disclosure_coverage.py` prints it). After the drop the same
  property is pinned per profile by a fixture test that parses the blobs (tests/test_disclosures.py).
- `drop_raw_xbrl(con)`: refuses unless `coverage` reports 0 uncaptured elements for every profile; then drops the
  table in one transaction with an `admin_log` entry (rows, the values that live only in the vault from then on,
  reason, decision J). Idempotent: a database without the table is left alone.

What then lives only in the vault, by design: facts of pre-cutoff contexts (C9: comparatives before
MIN_PERIOD_END_DATE are never parsed into canonical tables) and every fact of quarantined / out-of-scope filings
(invariant 9: quarantine keeps the raw data, which is the vault blob).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from financials.db import version_key
from financials.ids import stable_id
from financials.scope import MIN_PERIOD_END_DATE
from financials.timeutil import utc_now

TABLE = "raw_xbrl_facts"
DECISION = "owner decision J (2026-11-16)"

_PROFILES = """
  SELECT filing_id, any_value(accounting_profile) AS profile FROM filing_meta GROUP BY 1
  UNION ALL SELECT DISTINCT filing_id, 'REG31_SHP' FROM shareholding_meta
            WHERE filing_id NOT IN (SELECT filing_id FROM filing_meta)
  UNION ALL SELECT DISTINCT filing_id, 'REG30_EVENT' FROM corporate_events"""

QUERY = f"""
WITH prof AS ({_PROFILES}),
raw AS (
  SELECT DISTINCT r.filing_id, r.element_name AS element FROM raw_xbrl_facts r JOIN prof p USING (filing_id)
  WHERE p.profile = 'REG30_EVENT' OR coalesce(r.ctx_instant, r.ctx_end) IS NULL
     OR coalesce(r.ctx_instant, r.ctx_end) >= ?),
cap AS (
  SELECT DISTINCT filing_id, source_element AS element FROM fact_observations
  UNION SELECT DISTINCT filing_id, element FROM segment_observations
  UNION SELECT DISTINCT filing_id, source_element FROM related_party_transactions
  UNION SELECT DISTINCT filing_id, element FROM shareholding_line_items
  UNION SELECT DISTINCT filing_id, element FROM disclosure_facts
  UNION SELECT f.filing_id, v.element FROM (SELECT DISTINCT filing_id FROM related_party_transactions) f
        JOIN _voc v ON v.kind = 'rpt'
  UNION SELECT f.filing_id, v.element FROM (SELECT DISTINCT filing_id FROM reg23_related_party_transactions) f
        JOIN _voc v ON v.kind = 'reg23'
  UNION SELECT f.filing_id, v.element FROM (SELECT DISTINCT filing_id FROM shareholding_major_holders) f
        JOIN _voc v ON v.kind = 'holders'
  UNION SELECT f.filing_id, v.element FROM (SELECT DISTINCT filing_id, relation FROM group_structure) f
        JOIN _voc v ON v.kind = 'aoc1_' || f.relation)
SELECT p.profile, count(DISTINCT r.filing_id) AS filings, count(DISTINCT r.element) AS elements,
       count(DISTINCT r.element) FILTER (WHERE c.element IS NULL) AS uncaptured,
       count(*) FILTER (WHERE c.element IS NULL) AS uncaptured_pairs,
       count(DISTINCT r.filing_id) FILTER (WHERE r.filing_id NOT IN (SELECT filing_id FROM disclosure_facts))
           AS filings_without_disclosures
FROM raw r JOIN prof p USING (filing_id) LEFT JOIN cap c USING (filing_id, element)
GROUP BY 1 ORDER BY 2 DESC"""
COLUMNS = ("profile", "filings", "elements", "uncaptured", "uncaptured_pairs", "filings_without_disclosures")

# Values (rows of the latest raw version per filing) that no clean table holds by design: pre-cutoff contexts of
# promoted filings (C9) and every fact of filings with no clean rows (quarantined, out of scope, unparsed families).
VAULT_ONLY_QUERY = f"""
WITH prof AS ({_PROFILES}),
latest AS (SELECT filing_id, arg_max(parser_version, {version_key()}) AS pv FROM raw_xbrl_facts GROUP BY 1)
SELECT count(*) AS rows,
       count(DISTINCT r.filing_id) AS filings,
       count(*) FILTER (WHERE r.parser_version = l.pv AND p.profile IS NOT NULL AND p.profile <> 'REG30_EVENT'
                        AND coalesce(r.ctx_instant, r.ctx_end) < ?) AS pre_cutoff_values,
       count(*) FILTER (WHERE r.parser_version = l.pv AND p.profile IS NULL) AS unpromoted_values,
       count(DISTINCT r.filing_id) FILTER (WHERE p.profile IS NULL) AS unpromoted_filings
FROM raw_xbrl_facts r JOIN latest l USING (filing_id)
LEFT JOIN (SELECT DISTINCT filing_id, profile FROM prof) p USING (filing_id)"""


def table_exists(con) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = ? AND schema_name = 'main' "
        "AND database_name = current_database()", [TABLE]).fetchone()[0])  # fmt: skip


def coverage(con) -> list[dict] | None:
    """[{profile, filings, elements, uncaptured, uncaptured_pairs, filings_without_disclosures}] measured against
    raw_xbrl_facts, or None when the table is already gone (decision J). Read-only."""
    if not table_exists(con):
        return None
    import pyarrow as pa

    from financials.parsers.aoc1 import SCHEDULES, verbatim_elements
    from financials.parsers.reg23_rpt import ELEMENTS as REG23
    from financials.parsers.rpt import TEXT_ELEMENTS as RPT_TEXT
    from financials.parsers.shareholding import HOLDER_ELEMENTS

    voc = [("reg23", e) for e in REG23] + [("rpt", e) for e in RPT_TEXT] + [("holders", e) for e in HOLDER_ELEMENTS]
    voc += [("aoc1_" + r, e) for r in SCHEDULES for e in verbatim_elements(r)]
    con.register("_voc", pa.table({"kind": [k for k, _ in voc], "element": [e for _, e in voc]}))
    try:
        return [dict(zip(COLUMNS, r, strict=True)) for r in con.execute(QUERY, [MIN_PERIOD_END_DATE]).fetchall()]
    finally:
        con.unregister("_voc")


@dataclass
class DropResult:
    status: str  # DROPPED | ALREADY_DROPPED | REFUSED
    message: str
    coverage: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def drop_raw_xbrl(con, *, note: str = "", now: datetime | None = None) -> DropResult:
    """Drop raw_xbrl_facts (decision J) once the coverage gate holds. Caller is the single writer."""
    cov = coverage(con)
    if cov is None:
        return DropResult("ALREADY_DROPPED", f"{TABLE} is not in the database; nothing to do")
    bad = [r for r in cov if r["uncaptured"]]
    if bad:
        return DropResult("REFUSED", "uncaptured elements: " + ", ".join(
            f"{r['profile']} {r['uncaptured']} element(s) / {r['uncaptured_pairs']} filing-element pair(s)"
            for r in bad) + "; capture them in a clean table (or run backfill-disclosures / backfill-rpt) first",
            cov)  # fmt: skip
    counts = dict(zip(("rows", "filings", "pre_cutoff_values", "unpromoted_values", "unpromoted_filings"),
                      con.execute(VAULT_ONLY_QUERY, [MIN_PERIOD_END_DATE]).fetchone(), strict=True))  # fmt: skip
    now = now or utc_now()
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DROP TABLE {TABLE}")
        con.execute(
            "INSERT INTO admin_log VALUES (?, 'DROP_RAW_XBRL', ?, ?, ?, ?)",
            [stable_id("adm", "drop_raw_xbrl", now), json.dumps({"table": TABLE, "decision": "J"}),
             json.dumps({**counts, "coverage": cov}, default=str),
             note or f"{DECISION}: every element reaches a clean table (disclosure_facts, X116); the vault blobs stay "
             "the source of truth. Pre-cutoff contexts (C9) and quarantined / out-of-scope filings' facts live only "
             "in the vault from now on", now],
        )  # fmt: skip
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return DropResult("DROPPED", f"{counts['rows']} rows of {counts['filings']} filings dropped; vault only from now "
                      f"on: {counts['pre_cutoff_values']} pre-cutoff values, {counts['unpromoted_values']} values of "
                      f"{counts['unpromoted_filings']} filings without clean rows", cov, counts)  # fmt: skip
