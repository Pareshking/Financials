#!/usr/bin/env bash
# RULES25 (X363-X365), live application by the single writer. Never between 18:45-19:15 or 23:30-23:55 IST
# (scheduled runs write then). No parser, schema or features change: nothing to restage or re-materialise.
set -euo pipefail
DATA="${DATA:-data}"

# 1. X363 CASH_EQUIVALENTS_BOUNDARY + X364 RESTATEMENT_RECONCILED_IN_FILING: re-run the annual checks (the CLI now
#    passes the vault, which X364 reads). Expected from the 2026-11-25 read-only replay: 7 open CASH_FLOW_RESTATED
#    findings (WELENT S q_b6e520864b7685d1122bb38a, WELENT C q_9f1ea31dd484dbe740464274, SYSTMTXC S
#    q_8a4102f98735b30c424939fd, SYSTMTXC C q_93b72303c81377712cfc25e4, SHRIRAMPPS C q_7f4ca90a451544fe5af919b7,
#    JSL C q_0d2375cf092a391b6926da2e, SENORES S q_9e11484032862bc2a1720f90) are re-keyed to the sub-class (new ids,
#    closed FIXED_BY_RULE under the old ones) and the new findings are resolved ACCEPTED by PRIOR_YEAR_ACCEPTED_CLASS;
#    "accepted_reconciled" 0 (the 7 findings X364 settles are already ACCEPTED by hand).
python -m financials --data-dir "$DATA" audit-annual

# 2. Check: no open finding is left with the new sub-class, and the 7 old ids are closed.
python - "$DATA" <<'PY'
import sys
import duckdb
con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
old = ["q_b6e520864b7685d1122bb38a", "q_9f1ea31dd484dbe740464274", "q_8a4102f98735b30c424939fd",
       "q_93b72303c81377712cfc25e4", "q_7f4ca90a451544fe5af919b7", "q_0d2375cf092a391b6926da2e",
       "q_9e11484032862bc2a1720f90"]
print(con.execute("SELECT resolution, count(*) FROM quarantine_queue WHERE quarantine_id IN (SELECT unnest(?)) "
                  "GROUP BY 1", [old]).fetchall())
print(con.execute("SELECT resolution, count(*) FROM quarantine_queue WHERE reason_code = 'ANNUAL_PRIOR_YEAR_DIFFERS' "
                  "AND json_extract_string(details, '$.subclass') = 'CASH_EQUIVALENTS_BOUNDARY' GROUP BY 1").fetchall())
PY

# 3. X365 (optional, owner's choice; network, local machine; 5-30 MB per PDF, ~2,000 files per fiscal year for the
#    whole universe): list and vault annual report PDFs raw only, then promote. Example for a few symbols:
#   python -m financials --data-dir "$DATA" fetch-annual-reports --symbols WELENT SYSTMTXC --min-to-year 2026
#   python -m financials --data-dir "$DATA" promote
