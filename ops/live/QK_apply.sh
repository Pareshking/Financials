#!/usr/bin/env bash
# Work QK (X312): audit-annual records the owner-accepted ANNUAL_PRIOR_YEAR_DIFFERS classes as ACCEPTED when it writes
# them (rule PRIOR_YEAR_ACCEPTED_CLASS) and carries a case-by-case acceptance forward only when the re-keyed finding
# has the same statement totals (rule PRIOR_YEAR_ACCEPTANCE_CARRIED). Run from the repo root on the live machine with
# the QK code merged, while no other writer holds data/market.duckdb. Nothing is corrected; no materialize needed.
#
# Dry check on the 2026-11-18 20:38 snapshot (read-only replay, this code): the re-run reproduces every open id
# (0 new), and resolves 228 open findings ACCEPTED by class (REGROUPED with every total compared 186, RESTATED
# RECLASSIFIED 35, DISCONTINUED_REPRESENTED 7), 0 carried. Open ANNUAL_PRIOR_YEAR_DIFFERS OLD 175 -> 76,
# NEW 218 -> 89. Left open: RESTATED BOTTOM_LINE_RESTATED OLD 48 / NEW 32, CASH_FLOW_RESTATED OLD 19 / NEW 34,
# SCALE OLD 9 / NEW 21, REGROUPED NEW 2 (one company S + C compared only the balance-sheet totals, as in QP3).
set -euo pipefail
DATA=${DATA:-data}
F="python -m financials --data-dir $DATA"

counts() {
  python - "$DATA" <<'PY'
import sys
import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
rows = con.execute("""
  WITH coh AS (SELECT entity_id, any_value(CASE WHEN reason = 'SEED_EXISTING' THEN 'OLD' ELSE 'NEW' END) AS cohort
               FROM universe_membership GROUP BY 1)
  SELECT coalesce(coh.cohort, '?'), json_extract_string(q.details, '$.class') ||
         coalesce('/' || json_extract_string(q.details, '$.subclass'), ''), count(*)
  FROM quarantine_queue q LEFT JOIN coh USING (entity_id)
  WHERE q.reason_code = 'ANNUAL_PRIOR_YEAR_DIFFERS' AND q.resolved_at IS NULL GROUP BY ALL ORDER BY ALL""").fetchall()
tot = {}
for cohort, cls, n in rows:
    tot[cohort] = tot.get(cohort, 0) + n
    print(f"  {cohort:4} {cls:40} {n}")
print("  open ANNUAL_PRIOR_YEAR_DIFFERS:", tot)
con.close()
PY
}

echo "before:"; counts
# Re-run the prior-year check; X312 resolves in the same transaction. The JSON adds accepted_by_class /
# accepted_carried. ~12 min. A second run changes nothing.
$F audit-annual
echo "after:"; counts
