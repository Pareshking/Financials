#!/usr/bin/env bash
# QA (X180-X182): apply the annual-check calibration to the live DB. Run from the repo root after merging.
# No restage / re-parse: the rules change only the two checks, not any parsed fact. Single writer: nothing else may
# hold data/market.duckdb while this runs.
set -euo pipefail
DATA=${DATA:-data}

# 0. Registry: if docs/tag_registry.yaml conflicted at merge, take main's file and re-add the QA batch:
#    python scripts/inspect_xbrl_exhaustive.py tests/fixtures/annual_checks/*.xml --registry docs/tag_registry.yaml --batch QA

# 1. Re-run G328 (prior-year columns, X110 + X182 class) and G93 (share counts, X114 + X181) for every promoted Reg. 34
#    annual. Queues findings with deterministic ids, closes open ones the re-run no longer produces (FIXED_BY_RULE).
#    Expected on the 2026-11-17 snapshot: prior year open 721 -> ~1,321 filings (OLD 281, NEW 1,040; classes NEW
#    REGROUPED 681 / RESTATED 337 / SCALE 22, OLD 176 / 99 / 6); share counts open 66 -> ~70 (OLD 28 / 14 entities,
#    NEW 42 / 23). The prior-year increase is coverage (OLD annuals were promoted before the check existed), not new
#    defects. Takes ~2 min (one factbook read per annual filing).
python -m financials --data-dir "$DATA" audit-annual

# 2. Review by class. Nothing is auto-accepted: bulk-ACCEPTing class REGROUPED is an owner decision.
python - "$DATA" <<'PY'
import sys

import duckdb

con = duckdb.connect(f"{sys.argv[1]}/market.duckdb", read_only=True)
for row in con.execute(
    """SELECT reason_code, coalesce(json_extract_string(details, '$.class'), '-') AS cls, count(*) AS findings,
              count(DISTINCT entity_id) AS entities
       FROM quarantine_queue WHERE resolved_at IS NULL
         AND reason_code IN ('ANNUAL_PRIOR_YEAR_DIFFERS', 'ANNUAL_SHARE_COUNT_DIFFERS')
       GROUP BY ALL ORDER BY ALL"""
).fetchall():
    print(row)
PY
