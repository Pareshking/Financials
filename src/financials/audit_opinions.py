"""audit_opinions rows for results / annual filings promoted before parsers/audit_report.py (or its current version)
existed (`backfill-audit-opinions`) [X121-X124].

New filings get their row from the promoter (staging.audit_opinion_rows inside results_tables). This backfill is for
filings already promoted, like `backfill-disclosures`: it reads each vaulted blob (no download; Vault.read_path
checks the blob's sha256), parses the instance and runs exactly the staging function a new filing uses
(staging.audit_opinion_rows), so the report text is always read whole from the vault, never from the 300-character
snippet of a disclosure_facts pointer row. When the filing's disclosure_facts row of the report element is a pointer
(X120), the text read must have its text_sha256 (TextMismatch otherwise, reported and not written).

Two phases (invariant 10): (1) a process pool (`workers`, default os.cpu_count()) parses the pending blobs and writes
one zstd Parquet file per filing under `<stage_root>/audit_opinions_backfill/` (atomic rename; the workers never open
the database); (2) the single writer inserts every staged file in ONE statement, joined with each filing's entity,
scope, period end and visibility from its latest filing_meta version, marks the entities dirty from their earliest
such visibility (the rows feed features_audit) and commits once; the Parquet files are then removed. A file already
staged for a still-pending filing is reused (an interrupted run resumes without re-parsing).

Pending = a promoted filing (latest filing_meta version) with no audit_opinions row at the current
AUDIT_PARSER_VERSION that is a Reg. 34 annual filing or has a disclosure_facts row of a results audit element
(DeclarationOfUnmodifiedOpinion... / OpinionOfAuditors / TypeOfAuditQualification / FrequencyOfAuditQualification): a
results filing without one files no audit field and would have no row. Idempotent (deterministic ids and keys,
INSERT OR IGNORE) and audited in `admin_log`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from financials import dirty
from financials.db import version_key
from financials.ids import stable_id
from financials.parsers import ParseError
from financials.parsers.audit_report import AUDIT_PARSER_VERSION, REPORT_ELEMENT, RESULTS_ELEMENTS
from financials.timeutil import utc_now, utc_to_ist_date
from financials.vault import Vault

STAGE_DIR = "audit_opinions_backfill"


class TextMismatch(RuntimeError):
    pass


def pending_filings(con) -> list[tuple]:
    """(filing_id, accounting_profile, scope, period_end, storage_path, sha256, expected report text_sha256) of
    every pending filing (module doc), by filing id."""
    return con.execute(
        f"""WITH m AS (
                SELECT filing_id, accounting_profile, scope, period_end FROM filing_meta
                QUALIFY row_number() OVER (PARTITION BY filing_id ORDER BY {version_key()} DESC) = 1)
            SELECT m.filing_id, m.accounting_profile, m.scope, m.period_end, b.storage_path, b.sha256,
                   (SELECT max(d.text_sha256) FROM disclosure_facts d
                    WHERE d.filing_id = m.filing_id AND d.element = ? AND d.dimensions IS NULL) AS expected
            FROM m JOIN filings f USING (filing_id) JOIN blobs b ON b.sha256 = f.sha256
            WHERE NOT EXISTS (SELECT 1 FROM audit_opinions a WHERE a.filing_id = m.filing_id
                              AND a.parser_version = ?)
              AND (m.accounting_profile = 'REG34_ANNUAL' OR EXISTS (
                   SELECT 1 FROM disclosure_facts d WHERE d.filing_id = m.filing_id
                   AND d.element IN (SELECT unnest(?))))
            ORDER BY 1""",
        [REPORT_ELEMENT, AUDIT_PARSER_VERSION, list(RESULTS_ELEMENTS)],
    ).fetchall()


def filing_rows(fid: str, profile: str, scope: str, period_end, data: bytes, expected: str | None) -> list[dict]:
    """The staging rows of one vaulted filing, through staging.audit_opinion_rows (the function a new filing uses)."""
    from financials.parsers.xbrl import parse_instance
    from financials.staging import audit_opinion_rows

    rows = audit_opinion_rows(fid, parse_instance(data), profile, scope, period_end)
    if expected is not None and (not rows or rows[0]["text_sha256"] != expected):
        raise TextMismatch(f"{fid}: the report text read from the vault does not match disclosure_facts text_sha256")
    return rows


def _schema():
    import pyarrow as pa

    s, b, i = pa.string(), pa.bool_(), pa.int32()
    return pa.schema([("audit_opinion_id", s), ("filing_id", s), ("parser_version", s), ("scope", s),
                      ("period_end", pa.date32()), ("source_kind", s), ("audit_opinion", s), ("opinion_rule", s),
                      ("going_concern_uncertainty", b), ("emphasis_of_matter", b), ("going_concern_component", b),
                      ("checkbox_qualified", b),
                      ("opinion_conflict", b), ("declaration", s), ("qualification_count", i),
                      ("qualification_repetitive", b), ("text_len", i), ("text_sha256", s)])  # fmt: skip


def _stage_one(job: tuple) -> tuple[str, str | None, int]:
    """Worker: parse one vaulted filing and write its rows to `<out>/<filing_id>.parquet`. (filing_id, error, rows)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    vault_root, out, fid, profile, scope, period_end, path, sha, expected = job
    try:
        rows = filing_rows(fid, profile, scope, period_end, Vault(Path(vault_root)).read_path(path, sha), expected)
    except (ParseError, OSError, RuntimeError, ValueError) as exc:
        return fid, str(exc), 0
    target = Path(out) / f"{fid}.parquet"
    tmp = target.with_suffix(f".tmp{os.getpid()}")
    pq.write_table(pa.Table.from_pylist(rows, schema=_schema()), tmp, compression="zstd")
    os.replace(tmp, target)
    return fid, None, len(rows)


def backfill_audit_opinions(
    con, vault: Vault, stage_root: Path, *, limit: int | None = None, workers: int | None = None
) -> dict:
    """audit_opinions rows for every pending filing (`limit` filings at most): parallel parse to staging Parquet, then
    one insert by the single writer (module doc). Call outside a transaction: it commits once."""
    pending = pending_filings(con)[:limit]
    out = Path(stage_root) / STAGE_DIR
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(str(vault.root), str(out), fid, profile, scope, end, path, sha, expected)
            for fid, profile, scope, end, path, sha, expected in pending
            if not (out / f"{fid}.parquet").exists()]  # fmt: skip
    workers = workers or os.cpu_count() or 1
    if workers > 1 and len(jobs) > 1:
        from multiprocessing import get_context

        with get_context("spawn").Pool(workers) as pool:
            results = list(pool.imap_unordered(_stage_one, jobs, chunksize=8))
    else:
        results = [_stage_one(j) for j in jobs]
    errors = sorted(f"{fid}: {err}" for fid, err, _ in results if err)
    files = [str(out / f"{p[0]}.parquet") for p in pending if (out / f"{p[0]}.parquet").exists()]
    inserted, by_opinion = 0, {}
    if files:
        latest = f"""SELECT filing_id, entity_id, visible_from_ts FROM filing_meta
                     QUALIFY row_number() OVER (PARTITION BY filing_id ORDER BY {version_key()} DESC) = 1"""
        src = f"FROM read_parquet(?) p JOIN ({latest}) k USING (filing_id)"
        try:
            con.execute("BEGIN")
            before = con.execute("SELECT count(*) FROM audit_opinions").fetchone()[0]
            con.execute(
                f"""INSERT OR IGNORE INTO audit_opinions BY NAME
                    SELECT p.*, k.entity_id, k.visible_from_ts {src}""",
                [files],
            )
            inserted = con.execute("SELECT count(*) FROM audit_opinions").fetchone()[0] - before
            by_opinion = {f"{k}:{o}": n for k, o, n in con.execute(
                f"SELECT p.source_kind, coalesce(p.audit_opinion, 'NONE'), count(*) {src} GROUP BY ALL ORDER BY ALL",
                [files]).fetchall()}  # fmt: skip
            marks = con.execute(f"SELECT k.entity_id, min(k.visible_from_ts) {src} GROUP BY 1", [files]).fetchall()
            dirty.mark(con, {ent: utc_to_ist_date(ts) for ent, ts in marks}, "AUDIT_OPINION_BACKFILL", STAGE_DIR)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        for f in files:
            Path(f).unlink(missing_ok=True)
    result = {"filings": len(files), "rows": inserted, "rows_by_opinion": by_opinion, "pending": len(pending),
              "parsed": len(jobs), "workers": workers, "errors": errors[:50], "error_count": len(errors)}  # fmt: skip
    con.execute(
        "INSERT INTO admin_log VALUES (?, 'BACKFILL_AUDIT_OPINIONS', ?, ?, NULL, ?)",
        [stable_id("admin", "BACKFILL_AUDIT_OPINIONS", AUDIT_PARSER_VERSION, utc_now().isoformat()),
         json.dumps({"parser_version": AUDIT_PARSER_VERSION, "limit": limit, "workers": workers}),
         json.dumps(result), utc_now()],
    )  # fmt: skip
    return result
