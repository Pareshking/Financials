#!/usr/bin/env bash
# QB8 (X280-X283): parser 0.10.8 reads the BSE results inline XBRL that batch 1 of the BSE results fetch quarantined:
# booleans displayed 'true' / 'false' (X280), unclosed <BR> in text blocks (X281), <thead> closed by </tbody> (X282),
# reporting period displayed but not tagged (X283). NSE XML parses exactly as before.
# Run from the repo root after merging; single writer: nothing else may hold data/market.duckdb.
set -euo pipefail
PY="${PY:-python}"
D="${D:-data}"

count() {
  "$PY" - "$D" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
for row in con.execute(
    """SELECT f.exchange, q.stage, q.reason_code, count(*) FROM quarantine_queue q JOIN filings f USING (filing_id)
       WHERE f.category = 'RESULTS_XBRL' AND q.resolved_at IS NULL AND q.stage IN ('PARSE', 'IDENTITY', 'PERIOD')
       GROUP BY ALL ORDER BY 1, 4 DESC"""
).fetchall():
    print(row)
PY
}

echo "open results parse / identity / period findings before:"; count

# 1. Re-parse every results filing with an open PARSE / IDENTITY / PERIOD finding (restage RESULTS_XBRL selects
#    exactly those, NSE and BSE alike; the NSE ones re-parse unchanged and stay quarantined) at 0.10.8, then promote.
#    A filing that now promotes closes its earlier findings (FIXED_BY_RULE, "parser 0.10.8: promoted").
#    Expected (batch-1 ledger, 686 files re-parsed offline): every BSE INVALID_XBRL (280) and NO_DECLARED_PERIOD (10)
#    filing now parses with no parse / period issue, so all 290 close at parse level; the promotion's own gates
#    (identity, share cross-check, attribution) may raise new, separate findings on some of them.
#    ATTRIBUTION_WITHHELD (1) is untouched. If a 0.10.8 staging batch exists from an earlier build, delete it first.
"$PY" -m financials --data-dir "$D" restage --category RESULTS_XBRL
"$PY" -m financials --data-dir "$D" promote

echo "open results parse / identity / period findings after:"; count

# 2. Market-side findings frozen behind these filings (none expected): reprocess, then materialize the new entities.
"$PY" -m financials --data-dir "$D" quarantine reprocess
"$PY" -m financials --data-dir "$D" materialize --incremental
