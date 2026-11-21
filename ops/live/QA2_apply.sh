#!/usr/bin/env bash
# Work QA2 (X317-X319): open ATTRIBUTION_WITHHELD findings (NEW cohort, plus OLD 2 and Permitted 5). Run from the repo
# root on the live machine with the QA2 code merged (parser 0.10.10), while no other writer holds data/market.duckdb.
# Quarantine ids are deterministic (snapshot 2026-11-19 ~00:55, features 21I).
#
#   DRY=1 DATA=<dir> ops/live/QA2_apply.sh   read-only: prints the counts and checks every ACCEPT id is open.
#
# Expected (snapshot; step 1 simulated by re-parsing the 150 findings' vault blobs with the worktree parser):
#   open ATTRIBUTION_WITHHELD before: 150   (OLD 2, NEW 143, Permitted 5)
#   step 1 closes 24 (X317 6: DCXINDIA 2, JYOTISTRUC 2, INDOBORAX 1, MOLDTECH FY26 1;
#                     X318 18: PRIMESECU 7, GOLDIAM 3, HILINFRA 3, SPAL 2, STYL 1, SUKHJITS 1, FREDUN 1 Permitted)
#     -> 126 (OLD 2, NEW 120, Permitted 4)
#   step 2 ACCEPTs 22 (16 entities; the period's split is stated consistently by another filing)
#     -> 104 (OLD 2, NEW 98, Permitted 4)
# Step 1 also re-parses every other filing with an open parse / identity / period finding (as QC / QC2 did); only
# ATTRIBUTION_WITHHELD periods can change with 0.10.10, so other counts move only through other merged work.
# Not touched: 8 resolved KAYNES findings X318 would recover (no open finding, so restage skips them; see X318).
set -euo pipefail
DATA=${DATA:-data}
F="python -m financials --data-dir $DATA"

count_open() {
  python - "$DATA" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
print(*con.execute(
    "SELECT count(*), "
    "count(*) FILTER (WHERE entity_id IN (SELECT entity_id FROM universe_membership WHERE reason = 'SEED_EXISTING')), "
    "count(*) FILTER (WHERE entity_id IN (SELECT entity_id FROM universe_membership WHERE reason <> 'SEED_EXISTING' "
    "AND listing_category = 'Listed')), "
    "count(*) FILTER (WHERE entity_id IN (SELECT entity_id FROM universe_membership WHERE listing_category = 'Permitted')) "
    "FROM quarantine_queue WHERE reason_code = 'ATTRIBUTION_WITHHELD' AND resolved_at IS NULL"
).fetchone())
PY
}
echo "open ATTRIBUTION_WITHHELD (all, OLD, NEW, Permitted) before: $(count_open)   expected 150 2 143 5"

if [ "${DRY:-0}" = "1" ]; then
  python - "$DATA" <<'PY'
import json
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
ids = [i for r in json.load(open("ops/live/QA2_resolutions.json")) for i in r["ids"]]
ok = con.execute("SELECT count(*) FROM quarantine_queue WHERE quarantine_id IN (SELECT unnest(?)) "
                 "AND reason_code = 'ATTRIBUTION_WITHHELD' AND resolved_at IS NULL", [ids]).fetchone()[0]
print(f"ACCEPT ids open: {ok} of {len(ids)}   expected 22 of 22")
PY
  exit 0
fi

# 1. Parser 0.10.10 (X317, X318): re-parse results / annual filings with open findings, then promote (closes the
#    recovered periods' findings: "parser 0.10.10: promoted"). If a 0.10.10 staging batch exists from an earlier
#    build, delete it first (restage does not overwrite).
$F restage --category RESULTS_XBRL
$F promote
echo "after restage + promote: $(count_open)   expected 126 2 120 4"

# 2. ACCEPT 22 findings (ops/live/QA2_resolutions.json: ids, note with the evidence). Skipped if no longer open.
python - "$DATA" <<'PY'
import collections
import json
import sys

from financials.admin import AdminError, resolve_quarantine
from financials.db import connect

con = connect(f"{sys.argv[1]}/market.duckdb")
done, skipped = collections.Counter(), collections.Counter()
try:
    for r in json.load(open("ops/live/QA2_resolutions.json")):
        for qid in r["ids"]:
            try:
                resolve_quarantine(con, qid, action="ACCEPT", note=r["note"])
            except AdminError:
                continue
            done[r["bucket"]] += 1
            break
        else:
            skipped[r["bucket"]] += 1
            print("skip", r["ids"])
finally:
    con.close()
print("resolved", dict(done))
print("skipped", dict(skipped))
PY
echo "after ACCEPT: $(count_open)   expected 104 2 98 4"

# 3. X317 / X318 give owners' profit to periods that were withheld (EPS, P/E, ROE inputs of 11 entities). No file
#    pinned by test_incremental_materialize changed; the re-promoted filings mark their entities dirty, so
#    `materialize --incremental` (or the full run the main session schedules) picks them up.
$F materialize --incremental || echo "incremental refused (pending FEATURES_VERSION bump): run the full materialize"
