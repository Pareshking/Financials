#!/usr/bin/env bash
# QT (owner decisions T and U, 2026-11-18): rule X273 FIXED_ASSET_ONE_DEFINITION and the X274 verification.
# No parser change, no restage, no promote, no quarantine resolution: X273 acts in the FactBook (fundamentals.py)
# at materialisation only; X274 (restated comparatives) changes no code.
# fundamentals.py is pinned in tests/test_incremental_materialize.py: QT did NOT bump FEATURES_VERSION or the pinned
# hash. After the main session bumps both at merge, the full materialize below is required (--incremental refuses).
# Expected on the snapshot of 2026-11-18 (21E state, latest as-of): 2,131 balance-sheet dates of 849 entities decided
# by the rule (OLD 262 / NEW 587); net block changes on 514 dates (OLD 98 / NEW 207 entities).
set -euo pipefail
PY="${PY:-python}"
D="${D:-data}"
TO="${TO:?set TO to the latest trading day, e.g. TO=2026-11-18}"

$PY -m financials --data-dir "$D" materialize --from 2024-10-01 --to "$TO"
