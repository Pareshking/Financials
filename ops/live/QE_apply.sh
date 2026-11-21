#!/usr/bin/env bash
# QE (X300 OPERATING_LINES_BRIDGE, decision 2026-11-18 item 5): the TTM other income, D&A, finance costs, PBT before
# exceptional items, PBT and labelled excise of a restated window bridge through the YTD like revenue and PAT (X106).
# Code-only change in src/financials/fundamentals.py: no restage, no promote, no quarantine resolution.
set -euo pipefail
PY="${PY:-python}"
D="${D:-data}"

# fundamentals.py is pinned in tests/test_incremental_materialize.py. QE does NOT bump FEATURES_VERSION or the pin:
# the main session bumps both once at merge. After that bump `materialize --incremental` refuses until a full run,
# so the version bump requires a full materialize over the whole history (expected on the 14:40 snapshot, see
# docs/references.md X300: TTM operating lines change for restated rows only; EBITDA / OPM / EBIT (ROCE) /
# interest coverage / other_income_to_pbt follow; no value becomes NULL except by X226 on a line's own YTD).
LATEST="${LATEST:?set LATEST to the latest trading day, e.g. LATEST=2026-11-18}"
$PY -m financials --data-dir "$D" materialize --from 2024-10-01 --to "$LATEST"
