#!/usr/bin/env bash
# QB9 (X313): BSE NBFC results XBRL (plain XML `IFNBFCDuplicateUploadDocument/..._IFNBFC.xml`, NSE's NBFC Integrated
# Filing taxonomy) now take the NSE results path. The r14 ledger's 170 IFNBFC files were vaulted and promoted raw only
# (BSE_RESULTS_XBRL); re-importing the same ledger parses them: the filing ids are the same (exchange, URL, sha256), the
# raw-only filings rows stay as they are (append-only), the results batches are new staging paths (results_xbrl/<id>)
# with the ledger's broadcast time (Fld_CreateDate / file name), and promote parses them because they have no
# filing_meta yet. Everything else in the ledger is already promoted (skipped as such). No parser version bump, no file
# pinned in tests/test_incremental_materialize.py changed: materialize --incremental is enough.
# Run from the repo root after merging; single writer: nothing else may hold data/market.duckdb.
set -euo pipefail
PY="${PY:-python}"
D="${D:-data}"
LEDGER="${LEDGER:?set LEDGER to the r14 bse-fetch ledger directory (blobs/ + ledger.jsonl)}"

count() {
  "$PY" - "$D" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
total, have = con.execute(
    """SELECT count(DISTINCT entity_id),
              count(DISTINCT entity_id) FILTER (WHERE entity_id IN (SELECT entity_id FROM filing_meta))
       FROM universe_membership WHERE listing_category = 'Permitted'"""
).fetchone()
print(f"Permitted members with financials: {have} of {total}")
print("still without:", [r[0] for r in con.execute(
    """SELECT symbol FROM universe_membership WHERE listing_category = 'Permitted'
       AND entity_id NOT IN (SELECT entity_id FROM filing_meta) ORDER BY 1""").fetchall()])
for row in con.execute(
    """SELECT f.category, regexp_extract(f.source_url, 'XBRLFILES/([^/]+)/', 1) AS folder, count(*) AS filings,
              count(*) FILTER (WHERE f.filing_id IN (SELECT filing_id FROM filing_meta)) AS parsed,
              count(*) FILTER (WHERE f.filing_id IN (SELECT filing_id FROM quarantine_queue WHERE resolved_at IS NULL))
                AS with_open_findings
       FROM filings f WHERE f.exchange = 'BSE' AND f.category IN ('RESULTS_XBRL', 'BSE_RESULTS_XBRL')
       GROUP BY ALL ORDER BY 1, 2"""
).fetchall():
    print(row)
PY
}

echo "before:"; count

# 1. Re-stage the ledger (sha256 checked; idempotent ids), then promote. Expected on the snapshot of 2026-11-18 20:38
#    (dry run): 170 IFNBFC files parse INDAS_NBFC with no issue, all 12 NBFC members get financials.
"$PY" -m financials --data-dir "$D" import-bse "$LEDGER"
"$PY" -m financials --data-dir "$D" promote

echo "after:"; count

# 2. Open findings the promotion raised on these filings (filing checks, identity), for review.
"$PY" - "$D" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
for row in con.execute(
    """SELECT q.stage, q.reason_code, count(*) FROM quarantine_queue q JOIN filings f USING (filing_id)
       WHERE f.exchange = 'BSE' AND f.source_url LIKE '%IFNBFC.xml' AND q.resolved_at IS NULL GROUP BY 1, 2
       ORDER BY 3 DESC"""
).fetchall():
    print(row)
PY

# 3. The new filings mark their entities dirty.
"$PY" -m financials --data-dir "$D" materialize --incremental
