#!/usr/bin/env bash
# Work QR (X194-X197): NEW-member Screener comparison. Apply to the live database after merge.
#
# Code change: X194 ROCE_SCREENER_POSITIVE_CAPITAL in src/financials/fundamentals.py (screener_convention_ratios).
# No parser change, no restage, no promote, no quarantine resolution: the rule acts at materialisation only.
# fundamentals.py is pinned in tests/test_incremental_materialize.py, so the main session bumps
# features.FEATURES_VERSION and the pinned hash once at merge; --incremental refuses until this full run.
#
# Expected effect on the 2026-11-13 snapshot: roce_screener becomes NULL for 5 NEW rows
# (AQYLON, VISACHROME, DIACABS, GVKPIL, EUROBOND) and changes for no OLD row; nothing else changes.
set -euo pipefail
cd "$(dirname "$0")/../.."

python -m financials --data-dir data materialize --from 2024-10-01 --to 2026-11-13

# Check (read-only): the five rows are NULL now.
python - <<'EOF'
import duckdb
con = duckdb.connect("data/market.duckdb", read_only=True)
rows = con.execute(
    "SELECT symbol, roce_screener FROM screener_features "
    "WHERE symbol IN ('AQYLON','VISACHROME','DIACABS','GVKPIL','EUROBOND') ORDER BY 1"
).fetchall()
print(rows)
assert all(v is None for _, v in rows), rows
EOF
