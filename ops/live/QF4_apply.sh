#!/usr/bin/env bash
# Work QF4 (X306-X310): open findings of the expanded universe settled from the filings' own XBRL. Run from the repo
# root on the live machine with the QF4 code merged, while no other writer holds data/market.duckdb.
# Quarantine ids are deterministic, computed on the 2026-11-18 14:40 snapshot (read only) with this code: for every
# ANNUAL_PRIOR_YEAR_DIFFERS finding the id the re-run below produces is tried first, then the snapshot id. A finding
# that is no longer open on the live DB (resolved since, or re-keyed by a later rule) is skipped and counted.
set -euo pipefail
DATA=${DATA:-data}
F="python -m financials --data-dir $DATA"

# 0. Registry: if docs/tag_registry.yaml conflicted at merge, take main's file and re-add the QF4 batch:
#    python scripts/inspect_xbrl_exhaustive.py tests/fixtures/annual_restated/INTEGRATED_FILING_INDAS_1447925_22052025091528_WEB.xml \
#        tests/fixtures/annual_restated/AR_XBRL_VINDHYATEL_01092026190709.xml \
#        tests/fixtures/annual_restated/INTEGRATED_FILING_INDAS_1424269_24042025081042_WEB.xml \
#        tests/fixtures/annual_restated/AR_XBRL_KIRLPNU_19082026192059.xml --registry docs/tag_registry.yaml --batch QF4

# 1. Re-run the prior-year check (X306-X307 sub-classes of CASH_FLOW_RESTATED). On the snapshot: 62 of the 115
#    CASH_FLOW_RESTATED findings get a new sub-class and therefore a new id (old id closed FIXED_BY_RULE):
#    CASH_EQUIVALENTS_RECLASSIFIED 39 (NEW 27 / OLD 12), FX_EFFECT_RECLASSIFIED 23 (NEW 7 / OLD 16). ~12 min.
#    (33 RESTATED findings also re-key on the snapshot because code merged after 14:40 changed their differences.)
$F audit-annual

# 2. ACCEPT 236 findings (ops/live/QF4_resolutions.json: ids to try in order, note with the evidence):
#    - ANNUAL_PRIOR_YEAR_DIFFERS / RESTATED (230 open on the snapshot: OLD 95 / NEW 135):
#        X306 CASH_EQUIVALENTS_RECLASSIFIED 39, X307 FX_EFFECT_RECLASSIFIED 23 (owner decision 2026-11-18 delegated,
#        as X233 RECLASSIFIED: no amount restated);
#        NEW BOTTOM_LINE_RESTATED with the restatement cause quoted from the annual's own XBRL text blocks
#        (amalgamation / scheme / demerger under Ind AS 103 Appendix C, Ind AS 8 prior-period error, change of
#        accounting policy, the company's reported-vs-restated reconciliation): 28 (decision A precedent);
#        NEW BOTTOM_LINE_RESTATED immaterial (every differing bottom line within Rs 10 lakh and 0.1%): 7.
#    - YTD_QUARTER_MISMATCH (546 open NEW): the FY YTD of the Q4 results equals, to the tolerance, the same figure
#        in the audited Reg. 34 annual report (a second filing; the circular case where the YTD comes only from the
#        annual is excluded): 102 (44 of them with the merger cause stated in that annual); YTDs inside FY26 of the
#        entities whose FY26 annual states a scheme / amalgamation effected in the year: 37.
python - "$DATA" <<'PY'
import collections, json, sys
from financials.admin import AdminError, resolve_quarantine
from financials.db import connect

con = connect(f"{sys.argv[1]}/market.duckdb")
done, skipped = collections.Counter(), collections.Counter()
try:
    for r in json.load(open("ops/live/QF4_resolutions.json")):
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

# 3. Nothing is corrected (no decision-B values): no materialize needed for this work.
