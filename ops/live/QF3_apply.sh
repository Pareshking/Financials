#!/usr/bin/env bash
# QF3 (X226 YTD_MISFILED_NO_BRIDGE, X227 roe_screener, X228 NBFC debt / equity): apply to the live DB after merging.
# Run from the repo root. Single writer: nothing else may hold data/market.duckdb while this runs.
# No restage, re-parse or quarantine resolution: the three changes are in the feature layer (features.py,
# fundamentals.py, schema.sql). FEATURES_VERSION was NOT bumped by QF3; bump it (and the pin in
# tests/test_incremental_materialize.py) at merge, then run the FULL materialize below (--incremental refuses
# after a version bump).
set -euo pipefail
DATA=${DATA:-data}

# 0. Registry: if docs/tag_registry.yaml conflicted at merge, take main's file and re-add the QF3 batch:
#    python scripts/inspect_xbrl_exhaustive.py tests/fixtures/ytd_misfiled/*.xml --registry docs/tag_registry.yaml --batch QF3

# 1. Schema: features_events.roe_screener and screener_features.roe_screener are added by the column upgrade
#    (ALTER TABLE ... ADD COLUMN IF NOT EXISTS, appended last; the history view is recreated with it).
python -m financials --data-dir "$DATA" init-db

# 2. Full materialize over the whole history (after the FEATURES_VERSION bump). Expected effects (snapshot
#    2026-11-13 / 2026-11-17):
#    - X227 roe_screener non-NULL on the current rows of 549 / 592 OLD and 1,105 / 1,319 NEW securities;
#    - X228 debt_to_equity non-NULL for 84 lending-NBFC rows (41 OLD, 43 NEW), banks / insurers stay NULL;
#    - X226 pat_ttm NULL for NAZARA (rows from 16-Nov-2026) and AARTIPHARM, sales_ttm NULL for BALAJEE (all NEW;
#      no Nifty 500 seed value changes).
python -m financials --data-dir "$DATA" materialize --from 2024-10-01 --to "$(date -u +%F)"

# 3. Check (read-only).
python - "$DATA" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
print(con.execute(
    "SELECT count(*) FILTER (roe_screener IS NOT NULL), count(*) FILTER (is_lending_nbfc AND debt_to_equity IS NOT NULL), "
    "count(*) FILTER (is_lending_nbfc) FROM screener_features").fetchone())
print(con.execute(
    "SELECT symbol, fundamentals_end, pat_ttm, sales_ttm FROM screener_features "
    "WHERE symbol IN ('NAZARA', 'AARTIPHARM', 'BALAJEE') ORDER BY symbol").fetchall())
PY
