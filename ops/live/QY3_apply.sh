#!/usr/bin/env bash
# Work QY3 (X314-X316): open YTD_QUARTER_MISMATCH findings of the Permitted members. Run from the repo root on the
# live machine with the QY3 code merged (and FEATURES_VERSION bumped by the main session: fundamentals.py changed),
# while no other writer holds data/market.duckdb. Quarantine ids are deterministic (snapshot 2026-11-19, after X312
# and X313 were applied).
#
# Expected on the snapshot (dry run of step 1 read only, worktree code):
#   open YTD_QUARTER_MISMATCH before: 399 (Permitted 72 / 14 entities)
#   step 1 closes 44, raises 0:
#     NBFC_NET_LINE_SIDE [X314] 32 (Permitted 12: ASHIKA H1 FY27 C+S 4, SHARDUL FY26 C+S 4, ZSARACOM FY26 C+S 4;
#                                   NEW 20: PNBGILTS 4, SUMMITSEC 6, INDOTHAI 4, PRIMESECU 4, DHUNINV 2)
#     YTD_COPIES_PRIOR_YEAR [X315] 12 ('consistency holds on re-audit'; ANDREWYU C 4 Permitted, SEJALLTD S 4, WEL S 4)
#   step 2 ACCEPTs 4 (ARYAMAN C 3, BNAGROCHEM C 1)
#   open after: 351 (Permitted 52 / 10 entities)
set -euo pipefail
DATA=${DATA:-data}
F="python -m financials --data-dir $DATA"

count_open() {
  python - "$DATA" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
print(*con.execute(
    "SELECT count(*), count(*) FILTER (WHERE entity_id IN (SELECT entity_id FROM universe_membership "
    "WHERE listing_category = 'Permitted')) FROM quarantine_queue "
    "WHERE reason_code = 'YTD_QUARTER_MISMATCH' AND resolved_at IS NULL"
).fetchone())
PY
}
echo "open YTD_QUARTER_MISMATCH (all, Permitted) before: $(count_open)   expected 399 72"

# 0. Registry: if docs/tag_registry.yaml conflicted at merge, take main's file and re-add the QY3 batch:
#    python scripts/inspect_xbrl_exhaustive.py tests/fixtures/nbfc_net_line/*.xml \
#        tests/fixtures/ytd_copy/Integrated_Finance_Ind_As_526173_*.html --registry docs/tag_registry.yaml --batch QY3

# 1. Re-run the YTD audit with X314 / X315 (~10 min).
$F audit-ytd
echo "after audit-ytd: $(count_open)   expected 355 56"

# 2. ACCEPT 4 findings (ops/live/QY3_resolutions.json: ids, note with the evidence). Skipped if no longer open.
python - "$DATA" <<'PY'
import collections
import json
import sys

from financials.admin import AdminError, resolve_quarantine
from financials.db import connect

con = connect(f"{sys.argv[1]}/market.duckdb")
done, skipped = collections.Counter(), collections.Counter()
try:
    for r in json.load(open("ops/live/QY3_resolutions.json")):
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
echo "after ACCEPT: $(count_open)   expected 351 52"

# 3. X314 / X315 change TTM for the affected entity-scopes (NBFC revenue sums the quarters; the copied 9M YTDs are
#    withheld): after the FEATURES_VERSION bump, run the full materialize the main session schedules
#    (--incremental refuses until then).
