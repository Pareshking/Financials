#!/usr/bin/env bash
# Work QV (X325, rule SHOW_AND_FLAG, owner decision V 2026-11-19): show every stated number, flag the suspect.
# Run from the repo root on the live machine with the QV code merged and FEATURES_VERSION bumped, while no other
# writer holds the DB. No quarantine resolution and no correction: the rule changes only the feature reader.
set -euo pipefail

# --- 1. Schema: features_daily / screener_features gain dq_suspect + dq_flags (view screener_features_history too),
#        and the table features_dq_findings is created. Any write-mode open applies it (db.apply_schema).
python -m financials --data-dir data init-db

# --- 2. Full materialisation (FEATURES_VERSION changed: --incremental refuses until a full run). Run from the first
#        materialised day to the last, so settle_full_run also stores the open-findings state (features_dq_findings)
#        that later incremental runs diff against.
FIRST=2024-10-01
LAST=$(python - <<'EOF'
import duckdb
print(duckdb.connect("data/market.duckdb", read_only=True).execute("SELECT max(as_of_date) FROM features_daily").fetchone()[0])
EOF
)
python -m financials --data-dir data materialize --from "$FIRST" --to "$LAST"

# --- 3. Check: flags per cohort on the latest day (read-only).
python -m financials --data-dir data screen "Data Suspect = 1" --columns "Data Open Finding" --limit 5000 | head -40
