"""Per-profile coverage of the clean tables against raw_xbrl_facts (X116), read-only.

    python scripts/disclosure_coverage.py data/market.duckdb [--json]

For every promoted filing (filing_meta: its accounting profile; shareholding_meta without filing_meta: REG31_SHP;
corporate_events: REG30_EVENT) it compares the distinct raw elements of the filing whose context ends on or after
the C9 cutoff (or has no period, SHP16) with the elements the filing's clean rows hold per element: fact_observations
.source_element, segment_observations.element, related_party_transactions.source_element (+ its text vocabulary),
shareholding_line_items.element, disclosure_facts.element, and the element vocabularies of group_structure,
reg23_related_party_transactions and shareholding_major_holders (the same module constants staging.captured_elements
uses). Prints, per profile: filings, distinct elements, uncaptured distinct elements, uncaptured (filing, element)
pairs and filings with no disclosure_facts row. Run it before dropping raw_xbrl_facts (owner decision J): every
`uncaptured` must be 0. Quarantined / out-of-scope filings have no clean rows and are not counted (their facts live
only in raw_xbrl_facts and the vault blob).
"""

from __future__ import annotations

import argparse
import json

import duckdb

from financials.parsers.aoc1 import SCHEDULES, verbatim_elements
from financials.parsers.reg23_rpt import ELEMENTS as REG23
from financials.parsers.rpt import TEXT_ELEMENTS as RPT_TEXT
from financials.parsers.shareholding import HOLDER_ELEMENTS
from financials.scope import MIN_PERIOD_END_DATE

QUERY = """
WITH prof AS (
  SELECT filing_id, any_value(accounting_profile) AS profile FROM filing_meta GROUP BY 1
  UNION ALL SELECT DISTINCT filing_id, 'REG31_SHP' FROM shareholding_meta
            WHERE filing_id NOT IN (SELECT filing_id FROM filing_meta)
  UNION ALL SELECT DISTINCT filing_id, 'REG30_EVENT' FROM corporate_events),
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


def coverage(con) -> list[dict]:
    voc = [("reg23", e) for e in REG23] + [("rpt", e) for e in RPT_TEXT] + [("holders", e) for e in HOLDER_ELEMENTS]
    voc += [("aoc1_" + r, e) for r in SCHEDULES for e in verbatim_elements(r)]
    import pyarrow as pa

    con.register("_voc", pa.table({"kind": [k for k, _ in voc], "element": [e for _, e in voc]}))
    try:
        return [dict(zip(COLUMNS, r, strict=True)) for r in con.execute(QUERY, [MIN_PERIOD_END_DATE]).fetchall()]
    finally:
        con.unregister("_voc")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    con = duckdb.connect(args.db, read_only=True)
    try:
        rows = coverage(con)
    finally:
        con.close()
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        print(" | ".join(COLUMNS))
        for r in rows:
            print(" | ".join(str(r[c]) for c in COLUMNS))
    return 1 if any(r["uncaptured"] for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
