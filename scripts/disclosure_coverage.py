"""Per-profile coverage of the clean tables against raw_xbrl_facts (X116), read-only.

    python scripts/disclosure_coverage.py data/market.duckdb [--json]

For every promoted filing (filing_meta: its accounting profile; shareholding_meta without filing_meta: REG31_SHP;
corporate_events: REG30_EVENT) it compares the distinct raw elements of the filing whose context ends on or after
the C9 cutoff (or has no period, SHP16) with the elements the filing's clean rows hold per element: fact_observations
.source_element, segment_observations.element, related_party_transactions.source_element (+ its text vocabulary),
shareholding_line_items.element, disclosure_facts.element, and the element vocabularies of group_structure,
reg23_related_party_transactions and shareholding_major_holders (the same module constants staging.captured_elements
uses). Prints, per profile: filings, distinct elements, uncaptured distinct elements, uncaptured (filing, element)
pairs and filings with no disclosure_facts row. It is the gate of `drop-raw-xbrl` (owner decision J,
financials.raw_xbrl.coverage): every `uncaptured` must be 0. Quarantined / out-of-scope filings have no clean rows
and are not counted (their facts live only in the vault blob after the drop). On a database without the table (after
the drop) it says so: the same property is then pinned per profile by tests/test_disclosures.py, which parses the
fixture blobs directly.
"""

from __future__ import annotations

import argparse
import json

import duckdb

from financials.raw_xbrl import COLUMNS, coverage


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
    if rows is None:
        print("raw_xbrl_facts is not in this database (dropped, owner decision J): nothing to measure")
        return 0
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        print(" | ".join(COLUMNS))
        for r in rows:
            print(" | ".join(str(r[c]) for c in COLUMNS))
    return 1 if any(r["uncaptured"] for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
