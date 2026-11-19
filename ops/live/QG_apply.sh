#!/usr/bin/env bash
# Work QG (X330-X334): IGAAP_CORP, SME-listed members' results on SEBI's non-Ind AS template. Run from the repo root on
# the live machine with the QG code merged (parser 0.10.11), while no other writer holds data/market.duckdb.
#
#   DRY=1 DATA=<dir> ops/live/QG_apply.sh   read-only: prints the counts and the findings this script would touch.
#
# Expected (live DB 2026-11-19, read-only; step 1 simulated by parsing every vaulted blob of the 65 open
# OtherThanBank UNKNOWN_TAXONOMY findings with the worktree parser):
#   members with results financials (universe_membership, any non-REG34 filing_meta): 2049 of 2065
#   open UNKNOWN_TAXONOMY: 85 (OtherThanBank 65 = SME 61 + Main Board 4; AR_XBRL_NI annual 20)
#   step 1 (restage + promote): 59 SME filings of 13 members promote as IGAAP_CORP (their finding closes:
#     "parser 0.10.11: promoted"); 53 resolve by ISIN, 6 by X88 (GICL's pre-split ISIN INE947T01014); 2 GICL Q2 FY26
#     files of 14-15 Nov 2025 (amounts and EPS 1e5x, X333) are quarantined as PARSE / AMOUNTS_SCALED instead; L&T
#     Q4 FY25 S / C and Ruchira Q4 FY25 / Q1 FY26 (TypeOfCompany Main Board) stay UNKNOWN_TAXONOMY, same finding ids
#     -> open UNKNOWN_TAXONOMY 26, AMOUNTS_SCALED 2; members with results financials 2050 (+BAHETI: its only
#        results are IGAAP_CORP); 12 more gain point-in-time history before their first Ind AS filing
#   step 2 ACCEPTs 4 (the 2 GICL files' stale UNKNOWN_TAXONOMY and their AMOUNTS_SCALED findings: both periods are
#     covered by the re-filings of 15 Jan 2026, which promote in step 1) -> open UNKNOWN_TAXONOMY 24, AMOUNTS_SCALED 0
# Step 1 also re-parses every other filing with an open parse / identity / period finding (as QA2 / QC2 did); only
# OtherThanBank filings change with 0.10.11 (no other profile's output changed), so other counts move only through
# other merged work.
set -euo pipefail
DATA=${DATA:-data}
F="python -m financials --data-dir $DATA"

counts() {
  python - "$DATA" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
members = con.execute(
    "SELECT count(DISTINCT entity_id) FILTER (WHERE entity_id IN (SELECT entity_id FROM filing_meta "
    "WHERE accounting_profile <> 'REG34_ANNUAL')), count(DISTINCT entity_id) FROM universe_membership").fetchone()
tax = con.execute(
    "SELECT count(*) FILTER (WHERE reason_code = 'UNKNOWN_TAXONOMY'), "
    "count(*) FILTER (WHERE reason_code = 'UNKNOWN_TAXONOMY' AND json_extract_string(details, '$.entity_namespace') "
    "LIKE '%IntegratedFinance_OtherThanBank%'), count(*) FILTER (WHERE reason_code = 'AMOUNTS_SCALED') "
    "FROM quarantine_queue WHERE resolved_at IS NULL").fetchone()
igaap = con.execute("SELECT count(DISTINCT filing_id), count(DISTINCT entity_id) FROM filing_meta "
                    "WHERE accounting_profile = 'IGAAP_CORP'").fetchone()
print(f"members with results financials {members[0]} of {members[1]}; open UNKNOWN_TAXONOMY {tax[0]} "
      f"(OtherThanBank {tax[1]}), AMOUNTS_SCALED {tax[2]}; IGAAP_CORP filings {igaap[0]} / entities {igaap[1]}")
PY
}
echo "before: $(counts)"
echo "   expected: members 2049 of 2065; UNKNOWN_TAXONOMY 85 (OtherThanBank 65), AMOUNTS_SCALED 0; IGAAP_CORP 0 / 0"

if [ "${DRY:-0}" = "1" ]; then
  exit 0
fi

# 1. Parser 0.10.11: re-parse results / annual filings with open findings, then promote. If a 0.10.11 staging batch
#    exists from an earlier build, delete it first (restage does not overwrite).
$F restage --category RESULTS_XBRL
$F promote
echo "after restage + promote: $(counts)"
echo "   expected: members 2050 of 2065; UNKNOWN_TAXONOMY 26 (OtherThanBank 4), AMOUNTS_SCALED 2; IGAAP_CORP 59 / 13"

# 2. GICL Q2 FY26 of 14 Nov (standalone) / 15 Nov 2025 (consolidated): X333 blocks them; the period is the 15 Jan 2026
#    re-filings' (fil_bd8638afaf2dc35cbf2584d6 S, fil_2e8d18644bab3c4b58490f99 C), promoted in step 1. ACCEPT the
#    stale UNKNOWN_TAXONOMY finding and the AMOUNTS_SCALED finding of each (expected ids q_6cd488c58aa6363c6cc3ba1c S,
#    q_103756e2c8367f5686a79c7b C). Skipped when not open, or when the re-filing did not promote.
python - "$DATA" <<'PY'
import sys

from financials.admin import AdminError, resolve_quarantine
from financials.db import connect

PAIRS = {  # scaled filing -> re-filing of the same scope and period
    "fil_8841ae90c7dbb6c43bb71344": "fil_bd8638afaf2dc35cbf2584d6",
    "fil_94a52b47729d23cc63d00319": "fil_2e8d18644bab3c4b58490f99",
}
con = connect(f"{sys.argv[1]}/market.duckdb")
try:
    for bad, good in PAIRS.items():
        if not con.execute("SELECT count(*) FROM filing_meta WHERE filing_id = ? AND accounting_profile = 'IGAAP_CORP'",
                           [good]).fetchone()[0]:
            print("skip", bad, "- re-filing", good, "not promoted")
            continue
        for qid, reason in con.execute(
            "SELECT quarantine_id, reason_code FROM quarantine_queue WHERE filing_id = ? AND resolved_at IS NULL "
            "AND reason_code IN ('UNKNOWN_TAXONOMY', 'AMOUNTS_SCALED') ORDER BY 1", [bad]).fetchall():
            note = (f"X333 AMOUNTS_AND_EPS_SCALED: every amount and the EPS of this GICL Q2 FY26 filing are 1e5x those of "
                    f"its re-filing {good} (15 Jan 2026: EPS 0.61 / 0.63, PAT 181.89 / 171.56 lakh), which is promoted; "
                    f"this filing stays unpromoted, raw blob kept")
            if reason == "UNKNOWN_TAXONOMY":
                note = "parser 0.10.11 reads the template (IGAAP_CORP, X330); " + note
            try:
                resolve_quarantine(con, qid, action="ACCEPT", note=note)
                print("accepted", qid, reason, bad)
            except AdminError as exc:
                print("skip", qid, exc)
finally:
    con.close()
PY
echo "after ACCEPT: $(counts)"
echo "   expected: members 2050 of 2065; UNKNOWN_TAXONOMY 24 (OtherThanBank 4), AMOUNTS_SCALED 0; IGAAP_CORP 59 / 13"

# 3. src/financials/fundamentals.py changed (X334: IGAAP_CORP is its own accounting basis) and it is pinned by
#    tests/test_incremental_materialize.py, so FEATURES_VERSION is bumped at merge and `--incremental` refuses until a
#    full run: run the full materialize the main session schedules. Before that bump, --incremental would rebuild
#    only the 13 entities the promotions marked dirty.
$F materialize --incremental || echo "incremental refused (pending FEATURES_VERSION bump): run the full materialize"
