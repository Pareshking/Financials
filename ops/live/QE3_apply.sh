#!/usr/bin/env bash
# QE (2026-11-19, owner: "Fix the BCG duplicate entity"): X320 (reopen by ISIN), X321 (duplicate entity repair),
# X322 (explicit re-fetch of an archive file served empty / short), X323 (mcap series switch ahead of the bhavcopy).
# Named QE3_apply.sh because ops/live/QE_apply.sh (X300) and QE2_apply.sh already exist and were applied.
# No file pinned in tests/test_incremental_materialize.py changed: --incremental is enough (no version bump).
# Run from the repository root on the owner's machine (single writer; nothing else may hold data/market.duckdb).
set -euo pipefail
PY="${PY:-python}"
D="${D:-data}"
DB="$D/market.duckdb"
BCG_ISIN="INE425B01027"

counts() {  # read-only
  $PY - "$DB" <<'EOF'
import sys, duckdb
c = duckdb.connect(sys.argv[1], read_only=True)
q = lambda s: c.execute(s).fetchone()[0]
print("  securities per ISIN > 1     :", q("SELECT count(*) FROM (SELECT isin FROM security_identifier_history "
      "GROUP BY 1 HAVING count(DISTINCT security_id) > 1)"))
print("  BCG securities / entities   :", q("SELECT count(DISTINCT h.security_id) || ' / ' || count(DISTINCT s.entity_id) "
      "FROM security_identifier_history h JOIN securities s USING (security_id) WHERE h.isin = 'INE425B01027'"))
print("  open AMBIGUOUS_ISIN (BCG)   :", q("SELECT count(*) FROM quarantine_queue WHERE reason_code = 'AMBIGUOUS_ISIN' "
      "AND resolved_at IS NULL AND json_extract_string(details, '$.isin') = 'INE425B01027'"))
print("  BCG filing_meta rows        :", q("SELECT count(*) FROM filing_meta WHERE entity_id IN (SELECT s.entity_id "
      "FROM securities s JOIN security_identifier_history h USING (security_id) WHERE h.isin = 'INE425B01027')"))
print("  open UNRESOLVED_SYMBOL      :", q("SELECT count(*) FROM quarantine_queue WHERE reason_code = 'UNRESOLVED_SYMBOL' "
      "AND resolved_at IS NULL"))
print("  open INVALID_XBRL SOFTTECH/STANLEY:", q("SELECT count(*) FROM quarantine_queue q JOIN filings f USING (filing_id) "
      "WHERE q.reason_code = 'INVALID_XBRL' AND q.resolved_at IS NULL AND (f.source_url LIKE '%1753180_04112026%' "
      "OR f.source_url LIKE '%1757000_12112026%')"))
EOF
}

echo "before:"; counts
# expected before (snapshot 2026-11-19): 1; 2 / 2; 24; 0; 8; 2

# 1. X321: merge the duplicate BCG security / entity into the original (audited: admin_log MERGE_DUPLICATE_ENTITY).
$PY -m financials --data-dir "$D" merge-duplicate-entity --list
$PY -m financials --data-dir "$D" merge-duplicate-entity --isin "$BCG_ISIN" \
  --note "QE X321: BCG BZ (23580) until 30 Dec 2024, back in BE (8841) on 14 Jul 2025 after a suspension; the pre-X320 resolver created sec_6dae438d83ce90d52c27cbb3 / ent_6dae438d83ce90d52c27cbb3, merged into sec_a1c70ad98503ed173df75fb0"
# It prints the gap finding of 14 Jul 2025 (open 21.80 vs close 10.25 on 30 Dec 2024, a suspension of 6.5 months):
# left open for the owner (quarantine inspect <id>; ACCEPT with evidence of the suspension, or CORP_ACTION).

# 2. The 24 AMBIGUOUS_ISIN findings now resolve to one entity: re-promote their staged batches (all 24 are staged).
$PY -m financials --data-dir "$D" quarantine reprocess

# 3. X323: re-run rule U1 over the weeks holding the 8 findings (week ends 31 Oct 2025 and 30 Oct 2026).
# Idempotent for everything else (sticky; no join date moves: the 7 securities joined before those weeks).
$PY -m financials --data-dir "$D" update-universe --from 2025-10-27 --to 2026-11-15

# 4. Derived rows: both BCG entities were marked dirty from 2024-10-01 by the merge; the reprocessed filings mark theirs.
$PY -m financials --data-dir "$D" materialize --incremental

echo "after:"; counts
# expected after: 0; 1 / 1; 0 (unless reprocess lists batch_not_staged); > 0 (the 22 results filings promote; some may raise
# findings of their own); 1 (ELCIDIN, X323 cannot settle it); 2 (until step 5 re-fetches a complete file)

# 5. X322 (optional, owner's live path): SOFTTECH is served as 0 bytes (checked 2026-11-19), STANLEY was vaulted at
# 163,840 bytes. One polite request each (1 s apart) shows the size the archive serves now. Re-fetch only a file
# whose served size differs from the vaulted one; the old blob stays, the new bytes are a new filing.
UA="Mozilla/5.0 (X11; Linux x86_64) financials-research/0.1 (personal, non-commercial)"
X=https://nsearchives.nseindia.com/corporate/xbrl
check() {  # url vaulted_bytes broadcast_utc
  local n; n=$(curl -sS -m 60 -A "$UA" -o /dev/null -w '%{size_download}' "$1")
  echo "$1: served $n bytes, vaulted $2"
  if [ "$n" != "$2" ] && [ "$n" -gt 0 ]; then
    $PY -m financials --data-dir "$D" fetch-results "$1" --refetch --broadcast-utc "$3"
    $PY -m financials --data-dir "$D" promote
    echo "  re-fetched: once the new filing is promoted, REJECT the old INVALID_XBRL finding of $1"
    echo "  (quarantine list --reason INVALID_XBRL; resolve --id Q --action REJECT --note 'X322: superseded by the re-fetched file')"
  fi
}
check "$X/INTEGRATED_FILING_INDAS_1753180_04112026084409_WEB.xml" 0 2026-11-04T15:14:10   # SOFTTECH q_3b04500ea91820f46356c349
sleep 1
check "$X/INTEGRATED_FILING_INDAS_1757000_12112026085222_WEB.xml" 163840 2026-11-12T15:22:23  # STANLEY q_2f607352fdeb94b68d1eb1b6
