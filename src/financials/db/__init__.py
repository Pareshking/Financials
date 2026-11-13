"""DuckDB access. Only the promoter opens the market database for writing."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

SCHEMA_SQL = files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")


def connect(path: str | Path = ":memory:", *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_SQL)


def table_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    if not rows:
        raise KeyError(f"unknown table {table}")
    return [r[0] for r in rows]


def insert_rows(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    or_ignore: bool = False,
) -> int:
    """Bulk-insert dict rows (all with the same keys) through Arrow; columns matched by name.

    Decimal values stay exact: Arrow decimal128 -> DuckDB DECIMAL. Callers quantize money first.
    """
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    if any(list(r.keys()) != cols for r in rows):
        raise KeyError(f"{table}: rows have differing keys")
    unknown = set(cols) - set(table_columns(con, table))
    if unknown:
        raise KeyError(f"{table}: unknown columns {sorted(unknown)}")
    src = pa.Table.from_pylist([dict(r) for r in rows])
    name = f"_src_{table}"
    con.register(name, src)
    try:
        verb = "INSERT OR IGNORE INTO" if or_ignore else "INSERT INTO"
        con.execute(f"{verb} {table} BY NAME SELECT * FROM {name}")
    finally:
        con.unregister(name)
    return len(rows)


def fetch_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    cur = con.execute(sql, list(params))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
