#!/usr/bin/env bash
# QB7 (X247, X265): BSE results XBRL of the Permitted members (rule U1-P) into the live DB. Run from the repo root
# after merging AND pushing (workflow_dispatch reads bse-fetch.yml from the ref, and needs its new `only` input).
# No restage of NSE filings: NSE XML parses exactly as before (no parser version bump). Single writer: nothing else may
# hold data/market.duckdb while steps 3-5 run.
set -euo pipefail
DATA=${DATA:-data}
REPO=${REPO:-Pareshking/Financials}
REF=${REF:-main}

# 1. Runner fetch, two batches (113 codes from `bse-members`, 2026-11-18). Per batch: 2 listing calls per scrip
#    (FlagDur 6, then FlagDur 7 in a second pass) + 1 call per in-scope file (Q4 FY25 .. Q2 FY27 = 7 filings, standalone
#    + consolidated when the company has subsidiaries: 7-14 files). 57 scrips: 114 + ~400-800 = ~520-910 calls at
#    4-6 s pacing + transfer (~0.5 s for a 0.3-0.6 MB file) = ~50-85 min, inside the 120-min job limit.
#    Blocked (401/403/429) stops the job; the ledger is uploaded either way (if: always()).
B1=532067,500488,505036,530745,530499,524634,506597,526173,531381,530245,543766,531847,523850,504731,507944,506285,539018,509438,533095,514183,532485,539607,541096,535693,500147,512068,538715,500068,526783,530643,500123,539533,509525,533477,500672,511628,539730,522195,513536,500168,523862,505710,515147,508486,532467,522073,504092,501298,504786,508807,532468,505890,537750,500245,522101,524520,509732
B2=523323,539997,519421,502958,523475,500264,500267,507836,534091,538668,512267,504882,530129,500307,506532,514330,513119,531859,513511,539469,504132,539195,513532,531637,532503,523710,539921,515043,540737,512393,519397,531771,512453,523606,517166,539300,530845,539956,522229,501421,507753,500414,506687,505978,506808,506685,509960,519152,505232,530521,522122,500365,505872,511702,505163,512020
if [[ "${DISPATCH:-0}" == 1 ]]; then
  gh workflow run bse-fetch.yml -R "$REPO" --ref "$REF" -f scrips="$B1" -f since=2025-04-01 -f only=results
  echo "batch 1 dispatched; dispatch batch 2 after it finishes (BSE pacing is per runner, keep one at a time):"
  echo "  gh workflow run bse-fetch.yml -R $REPO --ref $REF -f scrips=$B2 -f since=2025-04-01 -f only=results"
  exit 0
fi

# 2. Download each run's artifact (1-day retention) into its own empty directory:
#    gh run download <run-id> -R "$REPO" -n bse-fetch -D bse_fetch_b1   (and bse_fetch_b2)
for d in bse_fetch_b1 bse_fetch_b2; do
  [[ -f "$d/ledger.jsonl" ]] || { echo "missing $d/ledger.jsonl"; exit 1; }
  grep -c '"dataset": "results_xbrl"' "$d/ledger.jsonl" || true
done

# 3. Vault + stage (sha256 checked against the ledger; results .html through the NSE results parser), then promote.
python -m financials --data-dir "$DATA" import-bse bse_fetch_b1
python -m financials --data-dir "$DATA" import-bse bse_fetch_b2
python -m financials --data-dir "$DATA" promote

# 4. What landed: BSE results filings by status; identity failures (UNKNOWN_ISIN: a member without NSE identifier
#    rows and no BSE1 scrip code) and scrip-code conflicts are quarantined, never guessed.
python - "$DATA" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
print(con.execute(
    """SELECT count(DISTINCT f.filing_id) AS bse_results_filings, count(DISTINCT m.filing_id) AS promoted,
              count(DISTINCT m.entity_id) AS entities
       FROM filings f LEFT JOIN filing_meta m USING (filing_id)
       WHERE f.exchange = 'BSE' AND f.category = 'RESULTS_XBRL'""").fetchall())
for row in con.execute(
    """SELECT q.stage, q.reason_code, count(*) FROM quarantine_queue q JOIN filings f USING (filing_id)
       WHERE f.exchange = 'BSE' AND f.category = 'RESULTS_XBRL' AND q.resolved_at IS NULL GROUP BY 1, 2 ORDER BY 3 DESC"""
).fetchall():
    print(row)
PY

# 5. Materialize: the new filings mark their entities dirty.
python -m financials --data-dir "$DATA" materialize --incremental
