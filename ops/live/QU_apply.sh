#!/usr/bin/env bash
# QU (X311, rule U1-2026.11.18-R): rights entitlements leave the Rs 500 Cr universe. Run from the repo root after
# merging. No restage, promote or materialize: only universe_membership (and admin_log) change, and no materialised
# table reads universe_membership. Single writer: nothing else may hold data/market.duckdb while this runs.
# Expected on the 2026-11-18 snapshot: rights_entitlements_removed 5 (UPL-RE, LLOYDS-RE1, M&MFIN-RE1, LLOYDSE-RE,
# ADANI-RE), joined 0; members 2,070 -> 2,065, Permitted members 128 -> 123; no other member changes.
set -euo pipefail
DATA=${DATA:-data}

counts() {
  python - "$DATA" "$1" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
n, perm, re_ = con.execute(
    "SELECT count(*), count(*) FILTER (WHERE listing_category = 'Permitted'), "
    "count(*) FILTER (WHERE regexp_matches(symbol, '-RE[0-9]*$')) FROM universe_membership WHERE universe = 'MCAP500'"
).fetchone()
print(f"{sys.argv[2]}: members {n}, Permitted members {perm}, -RE[n] symbols {re_}")
con.close()
PY
}

counts before
# Full range (default --from = MIN_TRADE_DATE): re-applies U1 to every week end (idempotent for existing members);
# the X311 removal runs on every call and logs the removed rows in admin_log (UNIVERSE_REMOVE_RIGHTS_ENTITLEMENT).
# The printed JSON carries rights_entitlements_removed / rights_entitlements_skipped.
python -m financials --data-dir "$DATA" update-universe
counts after
