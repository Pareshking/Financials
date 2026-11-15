"""AOC-1 group structure for annual filings promoted before the schedule was parsed (batch H) [X108].

New Reg. 34 annual filings get their `group_structure` rows from the promoter (staging.group_structure_rows). This
backfill is the one-off for filings already in `filing_meta`: it reads each vaulted blob (no download), re-parses it
with the current annual parser to get the in-scope fiscal-year ends, and inserts the AOC-1 rows with the filing's
own entity, scope and visibility (the latest parser version of its `filing_meta`). Idempotent (deterministic keys,
INSERT OR IGNORE) and audited in `admin_log`, like admin.py; run it with the single-writer connection.
"""

from __future__ import annotations

import json

from financials.db import insert_rows, version_key
from financials.ids import stable_id
from financials.parsers import ParseError
from financials.parsers.aoc1 import AOC1_PARSER_VERSION
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.parsers.xbrl import parse_instance
from financials.staging import group_structure_rows
from financials.timeutil import utc_now
from financials.vault import Vault


def pending_filings(con) -> list[tuple]:
    """(filing_id, entity_id, scope, visible_from_ts, source_url, storage_path, sha256) of REG34_ANNUAL filings with
    no group_structure rows at the current AOC-1 parser version (latest filing_meta version per filing)."""
    return con.execute(
        f"""SELECT m.filing_id, m.entity_id, m.scope, m.visible_from_ts, f.source_url, b.storage_path, b.sha256
            FROM filing_meta m JOIN filings f USING (filing_id) JOIN blobs b USING (sha256)
            WHERE m.accounting_profile = 'REG34_ANNUAL'
              AND {version_key("m.parser_version")} = (SELECT max({version_key("x.parser_version")})
                                                       FROM filing_meta x WHERE x.filing_id = m.filing_id)
              AND NOT EXISTS (SELECT 1 FROM group_structure g WHERE g.filing_id = m.filing_id
                              AND g.parser_version = ?)
            ORDER BY f.source_url""",
        [AOC1_PARSER_VERSION],
    ).fetchall()


def backfill_group_structure(con, vault: Vault, *, limit: int | None = None) -> dict:
    done, rows_total, errors = 0, 0, []
    for fid, ent, scope, visible, url, path, sha in pending_filings(con)[:limit]:
        try:
            data = vault.read_path(path, sha)
            parsed = parse_reg34_annual(data, url.rsplit("/", 1)[-1])
            if parsed.issues:
                errors.append(f"{fid}: parse issues {[i.reason_code for i in parsed.issues]}")
                continue
            rows = group_structure_rows(fid, parse_instance(data), parsed)
        except (ParseError, OSError, RuntimeError) as exc:
            errors.append(f"{fid}: {exc}")
            continue
        insert_rows(con, "group_structure", [{**r, "entity_id": ent, "scope": scope, "visible_from_ts": visible}
                                             for r in rows], or_ignore=True)  # fmt: skip
        done, rows_total = done + 1, rows_total + len(rows)
    result = {"filings": done, "rows": rows_total, "errors": errors[:50], "error_count": len(errors)}
    con.execute(
        "INSERT INTO admin_log VALUES (?, 'BACKFILL_GROUP_STRUCTURE', ?, ?, NULL, ?)",
        [stable_id("admin", "BACKFILL_GROUP_STRUCTURE", AOC1_PARSER_VERSION, utc_now().isoformat()),
         json.dumps({"parser_version": AOC1_PARSER_VERSION, "limit": limit}), json.dumps(result), utc_now()],
    )  # fmt: skip
    return result
