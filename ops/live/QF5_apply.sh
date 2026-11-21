#!/usr/bin/env bash
# Work QF5 (parser 0.10.12; X335-X339). Run from the repo root on the live machine with QF5 merged, while no other
# writer holds data/market.duckdb. No pinned reader file changed (features.py / fundamentals.py untouched).
#
# Expected (snapshot 2026-11-19, features 21I; step 1 simulated by re-parsing the vault blobs with the QF5 parser):
#   X335: the 27 open ATTRIBUTION_WITHHELD periods with a non-zero NCI and no as-filed NCI (OLD 2, NEW 21,
#         Permitted 4) get asfiled_..._non_controlling_interests; with X325 owners = PAT - NCI as filed, flagged
#         ATTRIBUTION_PAT_LESS_NCI. 6 more (NCI filed 0) show PAT, flagged ATTRIBUTION_AS_FILED. The findings stay open.
#   X337 / X338: BLUSPRING (1), DIGITIDE (2), TRANSRAILL (1) annual reports promote; 8 PERIOD findings close
#         (all NEW): open PERIOD 8 -> 0.
#   X336: 11 UNKNOWN_ISIN findings (JKIL 10, ANDHRSUGAR 1; NEW) close as REPROCESSED in step 2.
#   X339: nothing to apply (classification in scripts/open_findings_report.py only).
set -euo pipefail
DATA=${DATA:-data}
F="python -m financials --data-dir $DATA"

count() {
  python - "$DATA" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
print(*con.execute(
    "SELECT count(*) FILTER (WHERE stage = 'PERIOD'), "
    "count(*) FILTER (WHERE reason_code = 'UNKNOWN_ISIN' AND json_extract_string(details, '$.symbol') "
    "IN ('JKIL', 'ANDHRSUGAR')), count(*) FILTER (WHERE reason_code = 'ATTRIBUTION_WITHHELD') "
    "FROM quarantine_queue WHERE resolved_at IS NULL").fetchone())
PY
}
echo "open PERIOD, JKIL/ANDHRSUGAR UNKNOWN_ISIN, ATTRIBUTION_WITHHELD before: $(count)   expected 8 11 (AW unchanged)"
[ "${DRY:-0}" = "1" ] && exit 0

# 1. Parser 0.10.12: re-parse results / annual filings with open findings (the 27 + 6 AW filings, the 4 annual
#    reports, Ruchira's wrong-template files among them), then promote. If a 0.10.12 staging batch exists from an
#    earlier build, delete it first (restage does not overwrite).
$F restage --category RESULTS_XBRL
$F promote
# 2. X336: re-promote the UNKNOWN_ISIN batches (retryable) with the new identity rule.
$F quarantine reprocess
echo "after: $(count)   expected 0 0 (AW unchanged)"

# 3. X325 shows the newly kept as-filed NCI: materialise the touched entities (promotion marks them dirty).
$F materialize --incremental
