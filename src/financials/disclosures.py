"""disclosure_facts rows for filings promoted before parsers/disclosures.py existed (`backfill-disclosures`) [X116].

New filings get their rows from the promoter (staging.disclosure_rows). This backfill is the one-off for filings
already promoted, like `backfill-rpt`: it reads each vaulted blob (no download), rebuilds the filing's clean staging
tables in memory with the same staging functions (staging.results_tables / shareholding_tables / reg30_tables: the
captured element set is computed from them exactly as for a new filing) and stages its disclosure rows. Nothing
else is written: no raw_xbrl_facts, no new parser version of any other table.

Two phases (invariant 10): (1) a process pool (`workers`, default os.cpu_count()) parses the pending blobs and writes
one zstd Parquet file per filing under `<stage_root>/disclosures_backfill/` (atomic rename; the workers never open
the database); (2) the single writer then inserts every staged file in ONE statement (read_parquet joined with each
filing's own entity, scope and visibility from its latest filing_meta / shareholding_meta version or its
corporate_events rows), marks the entities dirty in one call and commits once; the Parquet files are then removed.
A file already staged for a still-pending filing is reused (an interrupted run resumes without re-parsing).

Pending = a promoted, in-scope filing with no disclosure_facts row at the current DISCLOSURE_PARSER_VERSION.
Idempotent (deterministic keys, INSERT OR IGNORE) and audited in `admin_log`. Annual and shareholding filings that
gain rows mark their entity dirty from their earliest such visibility (they feed features_disclosures); results and
event rows feed no feature. A filing that re-parses with issues (promoted by an earlier parser version) is reported,
never written.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from financials import dirty
from financials.db import version_key
from financials.ids import stable_id
from financials.parsers import ParseError
from financials.parsers.disclosures import DISCLOSURE_PARSER_VERSION
from financials.parsers.xbrl import parse_instance
from financials.timeutil import utc_now, utc_to_ist_date
from financials.vault import Vault


def pending_filings(con) -> list[tuple]:
    """(kind, filing_id, entity_id, scope, visible_from_ts, source_url, storage_path, sha256) of promoted filings with
    no disclosure_facts row at the current parser version, results / annual first, then shareholding, then events."""
    done = "NOT EXISTS (SELECT 1 FROM disclosure_facts d WHERE d.filing_id = m.filing_id AND d.parser_version = ?)"
    latest = lambda t: (f"{version_key('m.parser_version')} = (SELECT max({version_key('x.parser_version')}) "  # noqa: E731
                        f"FROM {t} x WHERE x.filing_id = m.filing_id)")  # fmt: skip
    return con.execute(
        f"""SELECT 'RESULTS', m.filing_id, m.entity_id, m.scope, m.visible_from_ts, f.source_url, b.storage_path,
                   b.sha256
            FROM filing_meta m JOIN filings f USING (filing_id) JOIN blobs b USING (sha256)
            WHERE {latest("filing_meta")} AND {done}
            UNION ALL
            SELECT 'SHAREHOLDING', m.filing_id, m.entity_id, NULL, m.visible_from_ts, f.source_url, b.storage_path,
                   b.sha256
            FROM shareholding_meta m JOIN filings f USING (filing_id) JOIN blobs b USING (sha256)
            WHERE {latest("shareholding_meta")} AND {done}
            UNION ALL
            SELECT 'EVENT', m.filing_id, min(m.entity_id), NULL, min(m.visible_from_ts), f.source_url, b.storage_path,
                   b.sha256
            FROM corporate_events m JOIN filings f USING (filing_id) JOIN blobs b USING (sha256)
            WHERE {done} GROUP BY m.filing_id, f.source_url, b.storage_path, b.sha256
            ORDER BY 1, 6""",
        [DISCLOSURE_PARSER_VERSION] * 3,
    ).fetchall()


def filing_rows(kind: str, fid: str, data: bytes, url: str) -> tuple[list[dict], str | None]:
    """(stg_disclosures rows, error) of one vaulted filing, through the staging functions a new filing uses."""
    from financials.parsers.shareholding import shp_instance
    from financials.staging import reg30_tables, results_tables, shareholding_tables

    if kind == "SHAREHOLDING":
        inst = shp_instance(data)[0]
        tables = shareholding_tables(fid, inst, data)
    elif kind == "EVENT":
        inst = parse_instance(data)
        tables = reg30_tables(fid, inst, data)[0]
    else:
        inst = parse_instance(data)
        tables = results_tables(fid, inst, data, url)
    if tables.get("stg_issues"):
        return [], f"parse issues {[i['reason_code'] for i in tables['stg_issues']]}"
    return tables.get("stg_disclosures") or [], None


STAGE_DIR = "disclosures_backfill"


def _schema():
    import pyarrow as pa

    s, i, d = pa.string(), pa.int32(), pa.date32()
    return pa.schema([("filing_id", s), ("parser_version", s), ("source_kind", s), ("scope", s), ("seq", i),
                      ("element_ns", s), ("element", s), ("context_id", s), ("period_type", s), ("period_start", d),
                      ("period_end", d), ("period_months", i), ("in_window", pa.bool_()), ("dimensions", s),
                      ("unit_ref", s), ("unit", s), ("value_inr", pa.decimal128(20, 2)),
                      ("value_num", pa.decimal128(28, 8)), ("value_bool", pa.bool_()), ("value_text", s)])  # fmt: skip


def _stage_one(job: tuple) -> tuple[str, str | None, int]:
    """Worker: parse one vaulted filing and write its rows to `<out>/<filing_id>.parquet`. (filing_id, error, rows)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    vault_root, out, kind, fid, url, path, sha = job
    try:
        rows, error = filing_rows(kind, fid, Vault(Path(vault_root)).read_path(path, sha), url)
    except (ParseError, OSError, RuntimeError, ValueError) as exc:
        rows, error = [], str(exc)
    if error:
        return fid, error, 0
    target = Path(out) / f"{fid}.parquet"
    tmp = target.with_suffix(f".tmp{os.getpid()}")
    pq.write_table(pa.Table.from_pylist(rows, schema=_schema()), tmp, compression="zstd")
    os.replace(tmp, target)
    return fid, None, len(rows)


def backfill_disclosures(
    con, vault: Vault, stage_root: Path, *, limit: int | None = None, workers: int | None = None
) -> dict:
    """Disclosure rows for every pending filing (`limit` filings at most): parallel parse to staging Parquet, then
    one insert by the single writer (module doc). Call outside a transaction: it commits once."""
    pending = pending_filings(con)[:limit]
    out = Path(stage_root) / STAGE_DIR
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(str(vault.root), str(out), kind, fid, url, path, sha)
            for kind, fid, _, _, _, url, path, sha in pending if not (out / f"{fid}.parquet").exists()]  # fmt: skip
    errors: list[str] = []
    workers = workers or os.cpu_count() or 1
    if workers > 1 and len(jobs) > 1:
        from multiprocessing import get_context

        with get_context("spawn").Pool(workers) as pool:
            results = list(pool.imap_unordered(_stage_one, jobs, chunksize=4))
    else:
        results = [_stage_one(j) for j in jobs]
    errors += [f"{fid}: {err}" for fid, err, _ in results if err]
    import pyarrow as pa

    keys = [(fid, ent, scope if kind == "RESULTS" else None, visible) for kind, fid, ent, scope, visible, *_ in pending
            if (out / f"{fid}.parquet").exists()]  # fmt: skip
    rows_total, kinds = 0, {}
    if keys:
        files = [str(out / f"{k[0]}.parquet") for k in keys]
        con.register("_disc_keys", pa.table({"filing_id": [k[0] for k in keys], "entity_id": [k[1] for k in keys],
                                             "scope": pa.array([k[2] for k in keys], pa.string()),
                                             "visible_from_ts": [k[3] for k in keys]}))  # fmt: skip
        try:
            con.execute("BEGIN")
            src = "FROM read_parquet(?) p JOIN _disc_keys k USING (filing_id)"
            kinds = dict(con.execute(f"SELECT p.source_kind, count(*) {src} GROUP BY 1", [files]).fetchall())
            # scope as promoted (an identity override can only change the entity, never the scope)
            con.execute(
                f"""INSERT OR IGNORE INTO disclosure_facts BY NAME
                    SELECT p.* EXCLUDE (scope), k.scope, k.entity_id, k.visible_from_ts {src}""",
                [files],
            )
            marks = con.execute(
                f"""SELECT k.entity_id, min(k.visible_from_ts) {src}
                    WHERE p.source_kind IN ('ANNUAL', 'SHAREHOLDING') GROUP BY 1""",
                [files],
            ).fetchall()
            dirty.mark(con, {ent: utc_to_ist_date(ts) for ent, ts in marks}, "DISCLOSURE_BACKFILL", STAGE_DIR)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        finally:
            con.unregister("_disc_keys")
        rows_total = sum(kinds.values())
        for f in files:
            Path(f).unlink(missing_ok=True)
    result = {"filings": len(keys), "rows": rows_total, "rows_by_kind": kinds, "pending": len(pending),
              "parsed": len(jobs), "workers": workers, "errors": errors[:50], "error_count": len(errors)}  # fmt: skip
    con.execute(
        "INSERT INTO admin_log VALUES (?, 'BACKFILL_DISCLOSURES', ?, ?, NULL, ?)",
        [stable_id("admin", "BACKFILL_DISCLOSURES", DISCLOSURE_PARSER_VERSION, utc_now().isoformat()),
         json.dumps({"parser_version": DISCLOSURE_PARSER_VERSION, "limit": limit, "workers": workers}),
         json.dumps(result), utc_now()],
    )  # fmt: skip
    return result
