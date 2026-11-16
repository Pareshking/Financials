"""Storage maintenance of `data/market.duckdb` (architecture §4.1): `compact` and `prune-versions`.

DuckDB never returns the blocks of deleted rows to the operating system: a DELETE marks rows, a checkpoint may
reuse whole free blocks, but the file only grows. Re-materialised feature days, `rebuild-market` and superseded
parser versions therefore leave dead space behind. Both commands run inside the single writer.

- `compact`: CHECKPOINT, copy every table into a sibling file created from schema.sql (tables in schema order, so
  every foreign key finds its parent), verify each table's row count and the views, then swap the files
  (`market.duckdb` -> `market.duckdb.bak`, new -> `market.duckdb`; the .bak is deleted unless `keep_old`). Refuses
  when the free disk is below 1.1 x the live size (blocks in use by the tables, `pragma_storage_info`).
- `prune-versions` (owner decision I, 2026-11-16): delete the rows of superseded parser versions that no reader can
  select, after writing them to zstd Parquet under an archive directory with a manifest (table, version, rows,
  sha256) and an `admin_log` entry. The vault blobs stay the source of truth: every version is reproducible by a
  re-parse. `PRUNE_RULES` documents per table exactly which rows a reader can still select.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

from financials.db import SCHEMA_SQL, VIEWS_MARKER, apply_schema, connect, version_key
from financials.ids import stable_id
from financials.timeutil import utc_now

FREE_DISK_FACTOR = 1.1  # the copy needs the live size, plus room for indexes and the WAL of the copy
AUTO_COMPACT_MIN_DEAD = 0.2  # automatic compaction only when at least 20% of the file is dead space ...
AUTO_COMPACT_MIN_BYTES = 256 * 1024**2  # ... and at least 256 MB


class StorageError(RuntimeError):
    pass


# ── measurement ─────────────────────────────────────────────────────────────


def user_tables(con, catalog: str | None = None) -> list[str]:
    catalog = catalog or con.execute("SELECT current_database()").fetchone()[0]
    return [t for (t,) in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = ? AND schema_name = 'main' AND NOT temporary "
        "ORDER BY 1", [catalog]).fetchall()]  # fmt: skip


def user_views(con, catalog: str | None = None) -> list[str]:
    catalog = catalog or con.execute("SELECT current_database()").fetchone()[0]
    return [v for (v,) in con.execute(
        "SELECT view_name FROM duckdb_views() WHERE database_name = ? AND schema_name = 'main' AND NOT internal "
        "ORDER BY 1", [catalog]).fetchall()]  # fmt: skip


def table_blocks(con, table: str) -> int:
    """Distinct storage blocks the table's persistent segments use (pragma_storage_info), incl. overflow blocks."""
    return con.execute(
        f"""SELECT count(DISTINCT b) FROM (
              SELECT block_id AS b FROM pragma_storage_info('{table}') WHERE persistent AND block_id >= 0
              UNION ALL
              SELECT unnest(additional_block_ids) FROM pragma_storage_info('{table}')
              WHERE persistent AND additional_block_ids IS NOT NULL)"""
    ).fetchone()[0]


def block_size(con) -> int:
    return con.execute(
        "SELECT block_size FROM pragma_database_size() WHERE database_name = current_database()"
    ).fetchone()[0]


def live_bytes(con) -> dict[str, int]:
    """{table: bytes of the blocks its rows occupy}. Run after a CHECKPOINT: rows still in the WAL have no block."""
    size = block_size(con)
    return {t: table_blocks(con, t) * size for t in user_tables(con)}


# ── compact ─────────────────────────────────────────────────────────────────


@dataclass
class CompactResult:
    status: str  # COMPACTED | REFUSED | SKIPPED
    message: str
    before_bytes: int = 0
    after_bytes: int = 0
    live_bytes: int = 0
    rows: dict[str, int] = field(default_factory=dict)


def _schema_tables() -> list[str]:
    tables_sql = SCHEMA_SQL.partition(VIEWS_MARKER)[0]
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \(", tables_sql)


def _measure(con) -> tuple[int, int]:
    con.execute("CHECKPOINT")
    live = sum(live_bytes(con).values())
    return live, os.path.getsize(con.execute("SELECT path FROM duckdb_databases() WHERE database_name = "
                                             "current_database()").fetchone()[0])  # fmt: skip


def compact(db_path: Path, *, keep_old: bool = False, free_bytes: int | None = None) -> CompactResult:
    """Rewrite `db_path` without dead space (see module docstring). The caller must not hold the database open:
    this opens it for writing, which DuckDB grants to one process only. `free_bytes` overrides the measured free
    disk (tests)."""
    db_path = Path(db_path)
    new_path = db_path.with_name(db_path.name + ".compact")
    bak_path = db_path.with_name(db_path.name + ".bak")
    for leftover in (new_path, Path(str(new_path) + ".wal")):
        leftover.unlink(missing_ok=True)  # an interrupted earlier compaction; market.duckdb itself is intact
    try:
        con = connect(db_path)
    except duckdb.IOException as exc:
        return CompactResult("REFUSED", f"database busy (another process holds {db_path.name}): {exc}")
    copied = False
    try:
        live, before = _measure(con)
        free = shutil.disk_usage(db_path.parent).free if free_bytes is None else free_bytes
        need = int(FREE_DISK_FACTOR * live)
        if free < need:
            return CompactResult(
                "REFUSED",
                f"free disk {free / 1e9:.2f} GB < {FREE_DISK_FACTOR} x live size {live / 1e9:.2f} GB "
                f"({need / 1e9:.2f} GB) next to {db_path}; free space (or prune-versions first, then compact)",
                before,
                0,
                live,
            )
        tables = user_tables(con)
        views = user_views(con)
        order = [t for t in _schema_tables() if t in tables]
        extra = [t for t in tables if t not in order]
        if extra:
            return CompactResult("REFUSED", f"tables not declared in schema.sql: {extra}; add them to schema.sql "
                                 "or drop them first", before, 0, live)  # fmt: skip
        rows = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in order}
        here = con.execute("SELECT current_database()").fetchone()[0]
        cols = {t: _columns(con, here, t) for t in order}
        new = connect(new_path)
        try:
            apply_schema(new)
        finally:
            new.close()
        con.execute(f"ATTACH '{new_path}' AS compact_new")
        try:
            for t in order:
                got = _columns(con, "compact_new", t)
                if set(got) != set(cols[t]):
                    raise StorageError(f"{t}: columns differ from schema.sql ({sorted(set(got) ^ set(cols[t]))})")
                con.execute(f"INSERT INTO compact_new.main.{t} BY NAME SELECT * FROM {here}.main.{t}")
            for t in order:
                n = con.execute(f"SELECT count(*) FROM compact_new.main.{t}").fetchone()[0]
                if n != rows[t]:
                    raise StorageError(f"{t}: {n} rows copied, {rows[t]} in the database")
            missing = set(views) - set(user_views(con, "compact_new"))
            if missing:
                raise StorageError(f"views missing in the copy: {sorted(missing)}")
            con.execute("CHECKPOINT compact_new")
        finally:
            con.execute("DETACH compact_new")
        copied = True
    finally:  # a refusal or an error closes the database unchanged and removes the partial copy
        con.close()
        if not copied:
            new_path.unlink(missing_ok=True)
    if Path(str(db_path) + ".wal").exists():  # never swap away rows that only the WAL holds
        new_path.unlink(missing_ok=True)
        raise StorageError(f"{db_path}.wal still exists after closing the database; nothing swapped")
    os.replace(db_path, bak_path)
    os.replace(new_path, db_path)
    if not keep_old:
        bak_path.unlink()
    after = os.path.getsize(db_path)
    kept = f"; previous file kept as {bak_path.name}" if keep_old else ""
    return CompactResult("COMPACTED", f"{before / 1e9:.2f} GB -> {after / 1e9:.2f} GB{kept}", before, after, live,
                         rows)  # fmt: skip


def _columns(con, catalog: str, table: str) -> list[str]:
    return [c for (c,) in con.execute(
        "SELECT column_name FROM duckdb_columns() WHERE database_name = ? AND schema_name = 'main' AND table_name = ? "
        "ORDER BY column_index", [catalog, table]).fetchall()]  # fmt: skip


def maybe_compact(db_path: Path, out, *, data_dir_arg: str = "data") -> CompactResult:
    """After a full `materialize --from/--to` or `rebuild-market`: compact when enough of the file is dead space and
    the disk has room; otherwise say why and print the command. Silent when there is little dead space."""
    try:
        con = connect(db_path)
    except duckdb.IOException as exc:
        return CompactResult("SKIPPED", f"database busy: {exc}")
    try:
        live, size = _measure(con)
    finally:
        con.close()
    dead = size - live
    cmd = f"python -m financials --data-dir {data_dir_arg} compact"
    if dead < AUTO_COMPACT_MIN_BYTES or dead < AUTO_COMPACT_MIN_DEAD * size:
        r = CompactResult("SKIPPED", f"file {size / 1e9:.2f} GB, live {live / 1e9:.2f} GB: little dead space", size,
                          size, live)  # fmt: skip
    else:
        r = compact(db_path)
        if r.status == "REFUSED":
            r.message += f"; run `{cmd}` when there is room"
    if r.status != "SKIPPED":  # nothing worth reclaiming: say nothing
        print(f"compact: {r.status} {r.message}", file=out)
    return r


# ── prune superseded parser versions (owner decision I) ─────────────────────

VK = version_key  # dotted versions compare numerically, as every reader ranks them

# The current results-filing version, as every fact / segment reader selects it (fundamentals.CURRENT_VERSION:
# the latest filing_meta version of the filing; a filing without filing_meta has every version current).
_CUR = f"(SELECT filing_id, arg_max(parser_version, {VK()}) AS pv FROM filing_meta GROUP BY filing_id)"

# (filing_id, parser_version) pairs never pruned: a quarantine finding names the version (details.parser_version),
# or the filing has an open quarantine finding (inspect / reprocess read its raw rows, any version).
_PROTECTED = """(SELECT filing_id, json_extract_string(details, '$.parser_version') AS pv FROM quarantine_queue
                 WHERE filing_id IS NOT NULL AND json_extract_string(details, '$.parser_version') IS NOT NULL)"""
_OPEN_Q = "(SELECT DISTINCT filing_id FROM quarantine_queue WHERE filing_id IS NOT NULL AND resolved_at IS NULL)"


def _not_protected(t: str = "t") -> str:
    return (
        f" AND {t}.filing_id NOT IN {_OPEN_Q} AND NOT EXISTS (SELECT 1 FROM {_PROTECTED} p "
        f"WHERE p.filing_id = {t}.filing_id AND p.pv = {t}.parser_version)"
    )


# A newer shareholding version of the same filing that every Reg. 31 reader ranks above this one at every as-of:
# readers take, per (entity, SHP as-of date), the row with the latest visible_from_ts <= as_of, then the highest
# version. A newer version outranks an older one at every as-of only when both are visible from the same instant
# (a re-parse that moved visibility leaves the old version selectable in between, X83).
_SHP_DOMINATED = f"""EXISTS (SELECT 1 FROM shareholding_meta m0 JOIN shareholding_meta m1
      ON m1.filing_id = m0.filing_id AND m1.entity_id = m0.entity_id AND m1.as_of_date = m0.as_of_date
     AND m1.visible_from_ts = m0.visible_from_ts AND {VK("m1.parser_version")} > {VK("m0.parser_version")}
     WHERE m0.filing_id = t.filing_id AND m0.parser_version = t.parser_version)"""


@dataclass(frozen=True)
class PruneRule:
    table: str
    removable: str  # SQL condition on alias t: the row can be deleted
    why: str


PRUNE_RULES: tuple[PruneRule, ...] = (
    PruneRule(
        "fact_observations",
        f"""t.parser_version <> (SELECT c.pv FROM {_CUR} c WHERE c.filing_id = t.filing_id)
            AND NOT (t.canonical_tag = 'pat' AND t.period_type = 'DURATION' AND t.period_months IN (3, 12)
                     AND NOT EXISTS (SELECT 1 FROM fact_observations k
                         WHERE k.filing_id = t.filing_id
                           AND k.parser_version = (SELECT c.pv FROM {_CUR} c WHERE c.filing_id = t.filing_id)
                           AND k.canonical_tag = 'pat' AND k.period_type = 'DURATION' AND k.entity_id = t.entity_id
                           AND k.scope = t.scope AND k.period_months = t.period_months AND k.period_end = t.period_end
                           AND k.visible_from_ts <= t.visible_from_ts))""",
        "every value reader filters CURRENT_VERSION (latest filing_meta version; filings without filing_meta keep "
        "all). The scope decision's anchor periods (fundamentals.ANCHOR_TAG 'pat', 3 / 12 months) group every "
        "version: an old anchor row stays unless the current version of the filing has the same period visible "
        "no later",
    ),
    PruneRule(
        "segment_observations",
        f"t.parser_version <> (SELECT c.pv FROM {_CUR} c WHERE c.filing_id = t.filing_id)",
        "every reader filters SEGMENT_CURRENT_VERSION (latest filing_meta version)",
    ),
    PruneRule(
        "raw_xbrl_facts",
        f"""t.parser_version <> coalesce((SELECT c.pv FROM {_CUR} c WHERE c.filing_id = t.filing_id), '')
            AND {VK("t.parser_version")} < (SELECT max({VK("r.parser_version")}) FROM raw_xbrl_facts r
                                             WHERE r.filing_id = t.filing_id)""",
        "readers take the current filing_meta version (statements.segments) or any one version of the filing "
        "(ScripCode, quarantine checks of unparsed filings); the latest raw version and the filing_meta version "
        "stay",
    ),
    PruneRule(
        "shareholding_observations",
        f"""{_SHP_DOMINATED} AND EXISTS (SELECT 1 FROM shareholding_observations k WHERE k.filing_id = t.filing_id
              AND {VK("k.parser_version")} > {VK("t.parser_version")} AND k.entity_id = t.entity_id
              AND k.as_of_date = t.as_of_date AND k.category = t.category AND k.visible_from_ts = t.visible_from_ts)""",
        "readers join the ranked shareholding_meta row (latest visible, then highest version); the promoter's "
        "share cross-check reads observations by (visible_from_ts, version): an old row goes only when a newer "
        "version of the filing, visible from the same instant, has the same category",
    ),
    PruneRule(
        "shareholding_line_items",
        _SHP_DOMINATED,
        "read only through the ranked shareholding_meta row",
    ),
    PruneRule(
        "shareholding_major_holders",
        _SHP_DOMINATED,
        "read only through the ranked shareholding_meta row",
    ),
    PruneRule(
        "related_party_transactions",
        f"""EXISTS (SELECT 1 FROM related_party_transactions k WHERE k.filing_id = t.filing_id
              AND {VK("k.parser_version")} > {VK("t.parser_version")} AND k.entity_id = t.entity_id
              AND k.scope = t.scope AND k.period_end = t.period_end AND k.period_type = t.period_type
              AND k.visible_from_ts = t.visible_from_ts)""",
        "features_rpt ranks rows per (entity, scope, period_end) by visible_from_ts, filing, version: an old row "
        "goes only when a newer version of the filing covers the same period, visible from the same instant",
    ),
    PruneRule(
        "group_structure",
        f"""{VK("t.parser_version")} < (SELECT max({VK("g.parser_version")}) FROM group_structure g
                                         WHERE g.filing_id = t.filing_id)""",
        "no feature reader; the AOC-1 backfill checks the current AOC-1 version only: the latest version per filing "
        "stays",
    ),
)

# Kept whole, and why (docs/architecture.md §4.1): filing_meta and shareholding_meta are read across every
# version (rounding level, fiscal-year starts, accounting basis, the visibility timestamps of the fundamentals
# cache, the shareholding ranking itself) and are small; corporate_events has one row per event (event_id), and
# fact_corrections names a filing, not a version (readers join the current filing_meta version).
KEPT_WHOLE = ("filing_meta", "shareholding_meta", "corporate_events", "fact_corrections")


def _removable_sql(rule: PruneRule) -> str:
    return f"FROM {rule.table} t WHERE ({rule.removable}){_not_protected()}"


def prune_plan(con) -> list[dict]:
    """[{table, parser_version, rows, total_rows}] of the rows `prune_versions` would remove. Read-only."""
    out = []
    for rule in PRUNE_RULES:
        total = dict(con.execute(f"SELECT parser_version, count(*) FROM {rule.table} GROUP BY 1").fetchall())
        gone = dict(con.execute(f"SELECT t.parser_version, count(*) {_removable_sql(rule)} GROUP BY 1").fetchall())
        for v in sorted(total, key=_version_sort):
            out.append({"table": rule.table, "parser_version": v, "rows": gone.get(v, 0), "total_rows": total[v]})
    return out


def _version_sort(v: str) -> tuple:
    return tuple(p.zfill(9) for p in [*v.split("."), "", "", ""][:3])


@dataclass
class PruneResult:
    status: str  # DRY_RUN | PRUNED | NOTHING
    plan: list[dict]
    manifest: Path | None = None
    removed: int = 0


def _safe(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", v)


def prune_versions(con, archive: Path, *, dry_run: bool = False, note: str = "", now: datetime | None = None
                   ) -> PruneResult:  # fmt: skip
    """Archive, then delete, the rows of superseded parser versions no reader can select (PRUNE_RULES). The
    archive (zstd Parquet per table / version, manifest.json with rows and sha256) is written and read back before
    anything is deleted; a failed write raises and deletes nothing. The deletes, their counts checked against the
    archive, and the admin_log entry are one transaction. Caller is the single writer."""
    plan = prune_plan(con)
    todo = [p for p in plan if p["rows"]]
    if dry_run:
        return PruneResult("DRY_RUN", plan)
    if not todo:
        return PruneResult("NOTHING", plan)
    now = now or utc_now()
    run = archive / f"prune-{now:%Y%m%dT%H%M%S}"
    if run.exists():
        raise StorageError(f"{run} exists; refusing to overwrite an archive")
    entries = []
    try:
        for p in todo:
            rule = next(r for r in PRUNE_RULES if r.table == p["table"])
            path = run / p["table"] / f"parser_version={_safe(p['parser_version'])}" / "rows.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            con.execute(
                f"COPY (SELECT t.* {_removable_sql(rule)} AND t.parser_version = ?) TO '{path}' "
                "(FORMAT parquet, COMPRESSION zstd)",
                [p["parser_version"]],
            )
            n = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
            if n != p["rows"]:
                raise StorageError(f"{path}: {n} rows written, {p['rows']} planned")
            entries.append({"table": p["table"], "parser_version": p["parser_version"], "rows": n,
                            "path": path.relative_to(run).as_posix(), "sha256": _sha256(path)})  # fmt: skip
        manifest = run / "manifest.json"
        manifest.write_text(json.dumps({"created_at": now.isoformat(), "note": note, "files": entries,
                                        "rules": {r.table: r.why for r in PRUNE_RULES}}, indent=1),
                            encoding="utf-8")  # fmt: skip
    except BaseException as exc:
        raise StorageError(f"archive write failed under {run}: {exc}; nothing deleted") from exc
    removed = 0
    con.execute("BEGIN TRANSACTION")
    try:
        for rule in PRUNE_RULES:
            want = sum(e["rows"] for e in entries if e["table"] == rule.table)
            if not want:
                continue
            versions = [e["parser_version"] for e in entries if e["table"] == rule.table]
            got = len(con.execute(
                f"DELETE FROM {rule.table} WHERE rowid IN (SELECT t.rowid {_removable_sql(rule)} "
                "AND t.parser_version IN (SELECT unnest(?))) RETURNING 1", [versions]).fetchall())  # fmt: skip
            if got != want:
                raise StorageError(f"{rule.table}: {got} rows to delete, {want} archived; nothing deleted")
            removed += got
        result = {
            "archive": str(run),
            "manifest_sha256": _sha256(manifest),
            "removed": removed,
            "files": [{k: e[k] for k in ("table", "parser_version", "rows", "sha256")} for e in entries],
        }
        con.execute(
            "INSERT INTO admin_log VALUES (?, 'PRUNE_VERSIONS', ?, ?, ?, ?)",
            [stable_id("adm", "prune_versions", now), json.dumps({"archive": str(archive)}), json.dumps(result),
             note or "superseded parser versions (owner decision I)", now],
        )  # fmt: skip
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
    return PruneResult("PRUNED", plan, manifest, removed)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
