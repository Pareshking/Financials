#!/usr/bin/env bash
# QS (X221-X222): rule SHARES_REG31_OUTLIER in features.market_cap_shares (owner decision S, 2026-11-18).
# Code-only rule: no re-parse, no promotion and no quarantine resolution is needed. HMT's CROSS_CHECK_FAILED
# findings stay open (decision S); nothing here touches them.
#
# The rule changes features.py (pinned in tests/test_incremental_materialize.py). QS does NOT bump
# features.FEATURES_VERSION or the pinned hash; after the main session bumps them at merge, run ONE full
# materialisation (--incremental refuses until then):
#
#   python -m financials --data-dir data materialize --from 2024-10-01 --to <last trading day>
#
# Expected on the snapshot of 2026-11-17: 306 rows of 16 securities change shares_source REG31 -> ISSUE_SIZE
# (OLD 1: DEVYANI 3-8 Oct 2025; NEW 15), every other share count identical.
# From the merge on, promoting a PR-zip mcap file writes a MCAP_DAY dirty marker (every row from its trade date).
set -euo pipefail
echo "QS: no database steps; run a full materialize after the FEATURES_VERSION bump (see comments)."
