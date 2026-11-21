"""Promoted-filings ledger (rule X345, PROMOTED_LEDGER): the fetch side's memory of what is already promoted.

`Jobs.is_done` used to treat a vaulted file as done only while its staging directory exists. Staging directories are
disposable (disk clean-ups remove them), so a discovery sweep re-parsed every vaulted filing whose directory was
gone: the 2026-11-19 sweep re-staged 1,086 already-promoted results of 76 symbols in two hours and found nothing new
(about 5,200 of 29,945 NSE results filings had lost their staging directory). After each promote run the single
writer writes the ids of the filings it holds (one per line, sorted, atomic replace) to
`<stage_root>/PROMOTED_FILINGS.txt`; `is_done` also accepts a filing listed there. A filing with an open PARSE,
IDENTITY or PERIOD finding is left out, so a parser fix is still picked up by the next discovery. Runners (empty
data dir, no ledger) behave as before.
"""

from __future__ import annotations

import os
from pathlib import Path

FILE = "PROMOTED_FILINGS.txt"
RETRY_STAGES = ("PARSE", "IDENTITY", "PERIOD")


def write(con, stage_root: Path) -> int:
    """Write the ledger from the database (read only, one query). Returns the number of ids written."""
    ids = [r[0] for r in con.execute(
        "SELECT filing_id FROM filings EXCEPT SELECT filing_id FROM quarantine_queue "
        "WHERE resolved_at IS NULL AND filing_id IS NOT NULL AND stage IN (SELECT unnest(?)) ORDER BY 1",
        [list(RETRY_STAGES)],
    ).fetchall()]  # fmt: skip
    stage_root = Path(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)
    tmp = stage_root / (FILE + ".tmp")
    tmp.write_text("".join(f"{i}\n" for i in ids), encoding="utf-8")
    os.replace(tmp, stage_root / FILE)
    return len(ids)


def read(stage_root: Path) -> frozenset[str]:
    p = Path(stage_root) / FILE
    if not p.exists():
        return frozenset()
    return frozenset(line for line in p.read_text(encoding="utf-8").splitlines() if line)
