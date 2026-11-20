"""Rule X352 STAGING_CLEAN: remove the staging directories of promoted filing batches that no reader needs any more.

A filing batch is vaulted (its blob and `filings` row are the record, decision J) and, once promoted, its staging
directory is read again only by:

- `reprocess` and `quarantine resolve --action OVERRIDE` (admin.reprocess / _repromote_filing): batches of filings
  with an open finding;
- `rebuild-market`: market-day batches (it deletes their promotion_log rows and promotes them again);
- `Jobs.mcap_day`: finds a staged PR zip by its directory name;
- discovery (`Jobs.is_done`): a promoted filing's directory, or the X345 ledger PROMOTED_FILINGS.txt in its place.

So only directories of the per-filing jobs (CLEANABLE_JOBS) are removed, and only when promotion_log records the
directory as PROMOTED / ALREADY_PROMOTED / OUT_OF_SCOPE (never QUARANTINED, ABORTED, or a batch still waiting), its
filing is in the X345 ledger (promoted, no open PARSE / IDENTITY / PERIOD finding) and the filing has no open finding
of any kind. Everything else is kept, as are the market, calendar, corporate-action, classification and backfill
directories. A removed batch can be staged again from the vault (`restage`, discovery). Opt-in:
`promote --clean-staging`, or `clean-staging [--dry-run]` (the dry run opens the database read only and deletes
nothing).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from financials import promoted_ledger

CLEANABLE_JOBS = ("results_xbrl", "shareholding", "raw_only", "reg30_event")
CLEANABLE_STATUSES = ("PROMOTED", "ALREADY_PROMOTED", "OUT_OF_SCOPE")
_RUN_ID = re.compile(r"^(fil_[0-9a-f]{24})(?:-[A-Za-z0-9._-]+)?$")  # a filing id, or a re-parse of it (`fid-0.10.6`)


def _size(d: Path) -> int:
    """Disk space of a batch directory (allocated blocks, as `du`: a batch is a few small Parquet files)."""
    total = os.stat(d).st_blocks * 512
    for entry in os.scandir(d):
        if entry.is_file(follow_symlinks=False):
            total += entry.stat(follow_symlinks=False).st_blocks * 512
    return total


def clean_staging(con, stage_root: Path, *, dry_run: bool = False) -> dict:
    """Remove (or with `dry_run` only count) the removable directories; returns counts and bytes by job. Reads the
    database only (one query each for the log and the open findings) and the ledger file."""
    stage_root = Path(stage_root)
    ledger = promoted_ledger.read(stage_root)
    logged = con.execute(
        "SELECT stage_path FROM promotion_log WHERE job IN (SELECT unnest(?)) AND status IN (SELECT unnest(?))",
        [list(CLEANABLE_JOBS), list(CLEANABLE_STATUSES)],
    ).fetchall()
    open_filings = {r[0] for r in con.execute(
        "SELECT DISTINCT filing_id FROM quarantine_queue WHERE resolved_at IS NULL AND filing_id IS NOT NULL"
    ).fetchall()}  # fmt: skip
    out = {"dry_run": dry_run, "removed": 0, "bytes": 0, "kept_open_finding": 0, "kept_not_in_ledger": 0,
           "by_job": {}}  # fmt: skip
    for (rel,) in sorted(logged):
        job, _, run_id = rel.partition("/")
        m = _RUN_ID.match(run_id)
        d = stage_root / rel
        if job not in CLEANABLE_JOBS or m is None or "/" in run_id or not d.is_dir():
            continue
        fid = m.group(1)
        if fid in open_filings:
            out["kept_open_finding"] += 1
            continue
        if fid not in ledger:
            out["kept_not_in_ledger"] += 1
            continue
        size = _size(d)
        if not dry_run:
            shutil.rmtree(d)
        out["removed"] += 1
        out["bytes"] += size
        j = out["by_job"].setdefault(job, {"dirs": 0, "bytes": 0})
        j["dirs"] += 1
        j["bytes"] += size
    return out
