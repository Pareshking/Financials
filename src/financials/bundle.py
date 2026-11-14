"""Compact export / import of the market database as zstd Parquet shards (local or private object storage).

Not for git: the repository is public and the data is NSE-derived (CLAUDE.md "No redistribution"; `data/` and
Parquet are gitignored). `export-bundle` writes `<out>/<table>/part-NNN.parquet` plus `manifest.json` (row count and
an order-independent checksum per table); every shard stays under `max_file_mb` (re-split when a shard is larger) and
the whole bundle under `max_total_mb`, else the export fails. `import-bundle` loads a bundle into a new database in
schema order (foreign keys) and verifies counts and checksums.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from financials.db import apply_schema, connect, declared_columns

RAW_TABLES = ("raw_xbrl_facts",)  # fact_observations keeps every numeric fact (C24); raw only with --include-raw


class BundleError(RuntimeError):
    pass


def tables(include_raw: bool = False) -> list[str]:
    return [t for t in declared_columns() if include_raw or t not in RAW_TABLES]


def table_checksum(con, table: str) -> tuple[int, str]:
    n, h = con.execute(f"SELECT count(*), coalesce(bit_xor(hash(t)), 0) FROM {table} t").fetchone()
    return int(n), str(h)


def export_bundle(con, out: Path, *, include_raw: bool = False, max_file_mb: float = 50,
                  max_total_mb: float = 250, level: int = 9) -> dict:  # fmt: skip
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    manifest: dict = {"format": 1, "compression": f"zstd-{level}", "tables": {}}
    limit = max_file_mb * 1024 * 1024
    for t in tables(include_raw):
        rows, checksum = table_checksum(con, t)
        d = out / t
        d.mkdir()
        shards = 1
        while True:
            for p in d.glob("*.parquet"):
                p.unlink()
            per = max(1, math.ceil(rows / shards))
            for i in range(shards):
                path = (d / f"part-{i:03d}.parquet").as_posix()
                con.execute(
                    f"COPY (SELECT * FROM {t} ORDER BY ALL LIMIT {per} OFFSET {i * per}) TO '{path}' "
                    f"(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL {level})"
                )
            sizes = [p.stat().st_size for p in sorted(d.glob("*.parquet"))]
            if max(sizes) < limit or per == 1:
                break
            shards = math.ceil(shards * max(sizes) / (limit * 0.8))
        manifest["tables"][t] = {"rows": rows, "checksum": checksum, "files": len(sizes), "bytes": sum(sizes),
                                 "max_file_bytes": max(sizes)}  # fmt: skip
    total = sum(v["bytes"] for v in manifest["tables"].values())
    manifest["total_bytes"] = total
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    if total > max_total_mb * 1024 * 1024:
        raise BundleError(f"bundle is {total / 2**20:.1f} MB > {max_total_mb} MB budget (see {out}/manifest.json)")
    return manifest


def import_bundle(src: Path, db_path: Path) -> dict:
    src, db_path = Path(src), Path(db_path)
    if db_path.exists():
        raise BundleError(f"{db_path} exists: import-bundle only creates a new database")
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    con = connect(db_path)
    try:
        apply_schema(con)
        con.execute("BEGIN TRANSACTION")
        for t in declared_columns():  # schema order respects foreign keys
            if t not in manifest["tables"] or not manifest["tables"][t]["rows"]:
                continue
            con.execute(f"INSERT INTO {t} BY NAME SELECT * FROM read_parquet('{(src / t).as_posix()}/*.parquet')")
        con.execute("COMMIT")
        bad = {t: (v["rows"], v["checksum"], table_checksum(con, t)) for t, v in manifest["tables"].items()
               if table_checksum(con, t) != (v["rows"], v["checksum"])}  # fmt: skip
    finally:
        con.close()
    if bad:
        raise BundleError(f"round trip mismatch: {bad}")
    return {t: v["rows"] for t, v in manifest["tables"].items()}
