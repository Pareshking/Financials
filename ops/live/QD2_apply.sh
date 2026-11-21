#!/usr/bin/env bash
# QD2 (X293, X294): field-level PDF audit of a stratified random sample of 60 NEW companies (2026-11-18). Ids are from
# the snapshot of 2026-11-18 14:40; a correction or resolve of something already closed fails harmlessly (set +e).
set -u
PY="${PY:-python}"
D="${D:-data}"

set +e
# 1. PDF corrections (owner decision B, X107), read twice from the filing's own signed results PDF:
#    - NPST Q2 FY27 H1 cash flow, standalone and consolidated (XBRL CFO / CFI / CFF / cash generated classified
#      differently from the printed statement; same net change);
#    - MIDHANI Q2 FY27 paid-up equity capital, standalone and consolidated (XBRL 18,374 lakh for the printed 18,734.00);
#      closes the 30-Sep-2026 share cross-check q_848209141a5a4f34d0c95423 as CORRECTED.
$PY ops/live/QD2_corrections.py "$D/market.duckdb"
set -e

# 2. X293 changes fundamentals.py (pinned in tests/test_incremental_materialize.py): after the main session bumps
#    FEATURES_VERSION and the pin, the full materialize the version bump requires (expected on the 14:40 snapshot:
#    owners' TTM of 26 consolidated entities changes, OLD 4 / NEW 22, 9 by more than 1%; eps_ttm, pe, roe,
#    eps_continuing_ttm, npm_pct follow).
# $PY -m financials --data-dir "$D" materialize --from 2024-10-01 --to <latest trading day>
$PY -m financials --data-dir "$D" materialize --incremental
