"""Related-party schedule for annual filings promoted before batch J (`backfill-rpt`) [X113].

New Reg. 34 annual filings get their `related_party_transactions` rows from the promoter
(staging.related_party_rows). This backfill is the one-off for filings already in `filing_meta`, exactly like
`group_structure.backfill_group_structure`: it reads each vaulted blob (no download), re-parses it with the current
annual parser for the in-scope periods, and inserts the rows with the filing's own entity, scope and visibility (the
latest parser version of its `filing_meta`). Idempotent (deterministic keys, INSERT OR IGNORE; a filing already
holding rows at the current RPT parser version is skipped) and audited in `admin_log`; run it with the
single-writer connection. Each filing that gains rows marks its entity dirty from its visibility (`materialize
--incremental`). A filing whose schedule is empty gets no rows and is re-read on the next run (cheap).
"""

from __future__ import annotations

import json

from financials import dirty
from financials.db import insert_rows, version_key
from financials.ids import stable_id
from financials.parsers import ParseError
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.parsers.rpt import RPT_PARSER_VERSION
from financials.parsers.xbrl import parse_instance
from financials.staging import related_party_rows
from financials.timeutil import utc_now
from financials.vault import Vault


def pending_filings(con) -> list[tuple]:
    """(filing_id, entity_id, scope, visible_from_ts, source_url, storage_path, sha256) of REG34_ANNUAL filings with
    no related_party_transactions rows at the current RPT parser version (latest filing_meta version per filing)."""
    return con.execute(
        f"""SELECT m.filing_id, m.entity_id, m.scope, m.visible_from_ts, f.source_url, b.storage_path, b.sha256
            FROM filing_meta m JOIN filings f USING (filing_id) JOIN blobs b USING (sha256)
            WHERE m.accounting_profile = 'REG34_ANNUAL'
              AND {version_key("m.parser_version")} = (SELECT max({version_key("x.parser_version")})
                                                       FROM filing_meta x WHERE x.filing_id = m.filing_id)
              AND NOT EXISTS (SELECT 1 FROM related_party_transactions r WHERE r.filing_id = m.filing_id
                              AND r.parser_version = ?)
            ORDER BY f.source_url""",
        [RPT_PARSER_VERSION],
    ).fetchall()


def backfill_rpt(con, vault: Vault, *, limit: int | None = None) -> dict:
    done, rows_total, errors = 0, 0, []
    for fid, ent, scope, visible, url, path, sha in pending_filings(con)[:limit]:
        try:
            data = vault.read_path(path, sha)
            parsed = parse_reg34_annual(data, url.rsplit("/", 1)[-1])
            if parsed.issues:
                errors.append(f"{fid}: parse issues {[i.reason_code for i in parsed.issues]}")
                continue
            rows = related_party_rows(fid, parse_instance(data), parsed)
        except (ParseError, OSError, RuntimeError) as exc:
            errors.append(f"{fid}: {exc}")
            continue
        insert_rows(con, "related_party_transactions", [{**r, "entity_id": ent, "scope": scope,
                                                         "visible_from_ts": visible} for r in rows],
                    or_ignore=True)  # fmt: skip
        if rows:  # rows visible since the filing's broadcast: re-materialise from there (`--incremental`)
            dirty.mark_visible(con, ent, visible, "RPT_BACKFILL", fid)
        done, rows_total = done + 1, rows_total + len(rows)
    result = {"filings": done, "rows": rows_total, "errors": errors[:50], "error_count": len(errors)}
    con.execute(
        "INSERT INTO admin_log VALUES (?, 'BACKFILL_RPT', ?, ?, NULL, ?)",
        [stable_id("admin", "BACKFILL_RPT", RPT_PARSER_VERSION, utc_now().isoformat()),
         json.dumps({"parser_version": RPT_PARSER_VERSION, "limit": limit}), json.dumps(result), utc_now()],
    )  # fmt: skip
    return result
