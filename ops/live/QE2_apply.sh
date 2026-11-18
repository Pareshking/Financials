#!/usr/bin/env bash
# QE2 (X301 GUARDED_BRIDGE_ONE_BASIS, decision 2026-11-18 item 6): X106 bridges a guarded tag (revenue, total income,
# PAT, PBT incl. JV, owners' PAT) only when the prior year's FY and YTD are on one basis; otherwise the 4-quarter sum
# when those quarters are on one basis, else NULL. Builds on QE (X300): apply after QE_apply.sh (one full run covers both).
# Code-only change in src/financials/fundamentals.py: no restage, no promote, no quarantine resolution.
set -euo pipefail
PY="${PY:-python}"
D="${D:-data}"

# fundamentals.py is pinned in tests/test_incremental_materialize.py. QE2 does NOT bump FEATURES_VERSION or the pin:
# the main session bumps both once at merge, then a full materialize over the whole history (docs/references.md X301:
# ~1,231 guarded TTM values become NULL in 236 entities, sales_ttm in 317 / pat_ttm in 240 book-quarters; G4 daily
# null-rate rise measured at most 0.7 %, limit 1.5 %).
LATEST="${LATEST:?set LATEST to the latest trading day, e.g. LATEST=2026-11-18}"
$PY -m financials --data-dir "$D" materialize --from 2024-10-01 --to "$LATEST"
