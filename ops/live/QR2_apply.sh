#!/usr/bin/env bash
# Work QR2 (X260): rule ROUNDING_ONLY ("Ignore rounding errors if any", owner 2026-11-18). Apply after merge.
#
# Code: money.rounding_only_tolerance / within_rounding_only (shared bound: half a unit per rounded figure, the
# coarser unit when the figures' filings are not known one by one); FactBook.ytd_breaks counts PBT + JV share as two
# figures in a period whose JV share is filed non-zero (pbt_incl_jv); audit-ytd closes a stale rounding-only finding
# FIXED_BY_RULE naming X260; filing_checks' prior-year tolerance now comes from the shared function (same value,
# same finding ids). No parser change, no restage, no promote, no quarantine resolve --id: on the 2026-11-18
# snapshot NO open finding is within the bound (466 YTD_QUARTER_MISMATCH, 262 ANNUAL_PRIOR_YEAR_DIFFERS,
# 110 CROSS_CHECK_FAILED, 60 ANNUAL_SHARE_COUNT_DIFFERS), so the re-audits below are expected to close 0 and raise 0.
# fundamentals.py and money.py are pinned in tests/test_incremental_materialize.py: the main session bumps
# features.FEATURES_VERSION and the pinned hash once at merge (ytd_breaks feeds the YTD_IDENTITY restatement flag;
# on the snapshot its output is unchanged).
set -euo pipefail
cd "$(dirname "$0")/../.."

before=$(python - <<'EOF'
import duckdb
con = duckdb.connect("data/market.duckdb", read_only=True)
print(con.execute("SELECT count(*) FROM quarantine_queue WHERE resolved_at IS NULL AND reason_code IN "
                  "('YTD_QUARTER_MISMATCH', 'ANNUAL_PRIOR_YEAR_DIFFERS', 'ANNUAL_SHARE_COUNT_DIFFERS', "
                  "'CROSS_CHECK_FAILED')").fetchone()[0])
EOF
)

python -m financials --data-dir data audit-ytd        # YTD identity with X260; also re-checks share cross-checks
python -m financials --data-dir data audit-annual     # prior-year + annual share counts on every annual [X180]

python - "$before" <<'EOF'
import sys
import duckdb
con = duckdb.connect("data/market.duckdb", read_only=True)
print("open numeric findings before:", sys.argv[1])
print(con.execute("SELECT reason_code, count(*) FROM quarantine_queue WHERE resolved_at IS NULL AND reason_code IN "
                  "('YTD_QUARTER_MISMATCH', 'ANNUAL_PRIOR_YEAR_DIFFERS', 'ANNUAL_SHARE_COUNT_DIFFERS', "
                  "'CROSS_CHECK_FAILED') GROUP BY 1 ORDER BY 1").fetchall())
print("closed by X260:", con.execute("SELECT count(*) FROM quarantine_queue "
                                     "WHERE resolution_note LIKE 'ROUNDING_ONLY [X260]%'").fetchone()[0])
EOF
