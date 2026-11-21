#!/usr/bin/env bash
# SP1 (pipeline speed, X347-X353): nothing to restage or resolve. Optional, owner's choice (X352 is opt-in):
# count, then remove the staging directories of promoted filing batches no reader needs. Never between 18:45-19:15
# or 23:30-23:55 IST (scheduled runs write then).
set -euo pipefail
DATA="${DATA:-data}"
python -m financials --data-dir "$DATA" clean-staging --dry-run   # read-only: 2026-11-20 ~46,500 dirs, ~2.0 GB
if [ "${CLEAN:-no}" = "yes" ]; then
  python -m financials --data-dir "$DATA" clean-staging
fi
# Weekly BSE run (X353), e.g. 4 runners, files of the last 8 days only:
#   gh workflow run bse-fetch.yml -f scrips="$(python -m financials --data-dir "$DATA" bse-members | ...)" \
#     -f since="$(date -d '8 days ago' +%F)" -f window=true -f shards=4
#   then: python -m financials --data-dir "$DATA" import-bse bse-fetch-0/ bse-fetch-1/ bse-fetch-2/ bse-fetch-3/
#         python -m financials --data-dir "$DATA" promote
