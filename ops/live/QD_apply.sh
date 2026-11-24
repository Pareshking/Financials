#!/usr/bin/env bash
# QD (X250): field-level PDF audit of 10 NEW companies (2026-11-18). Ids are from the snapshot of 2026-11-18 08:15
# (features 2026.11.18-21E); a resolve of an id already closed fails harmlessly (set +e).
set -u
PY="${PY:-python}"
D="${D:-data}"

set +e
# 1. PDF corrections (owner decision B): HGS Q2 FY27 other intangible assets (XBRL includes right-of-use assets).
$PY ops/live/QD_corrections.py "$D/market.duckdb"

# 2. SANDESH 31-Mar-2026 share cross-check: the consolidated Q4 FY26 XBRL paid-up capital is a digit transposition.
$PY -m financials --data-dir "$D" quarantine resolve --id q_ef352640a80a9b6cff4af04d --action ACCEPT --note 'QD: SANDESH 2026-03-31: consolidated fil_6d9eba980eaba910f395b57a paid-up 76,594,000 / face value 10 = 7,659,400 vs Reg. 31 7,569,421: XBRL digit transposition (765.94 for 756.94 lakh); the standalone Q4 filing and the Q2 FY27 results PDF (https://nsearchives.nseindia.com/corporate/SANDESH_1_03112026184054_Outcome.pdf p10, FY26 column, paid-up 756.94) agree with Reg. 31, which stays the share count'
set -e

# 3. X250 changes features_more.py (pinned): after the main session bumps FEATURES_VERSION and the pin, the segment
#    columns need the full materialize the version bump requires (expected: 148 of 909 entities with segment columns
#    change segment_count / largest_segment_revenue_share; OLD 69, NEW 79).
# $PY -m financials --data-dir "$D" materialize --from 2024-10-01 --to <latest trading day>
$PY -m financials --data-dir "$D" materialize --incremental
