"""DuckDB access. Only the promoter opens the market database for writing."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

SCHEMA_SQL = files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")


def connect(path: str | Path = ":memory:", *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def apply_schema(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Create missing tables, then add columns that schema.sql declares but an existing database lacks.

    Idempotent: a second run changes nothing. Only nullable, constraint-free columns are added automatically;
    a new NOT NULL / PRIMARY KEY / UNIQUE / REFERENCES column needs a deliberate migration and raises.
    Returns the statements executed by the upgrade (empty for a fresh or current database).
    """
    con.execute(SCHEMA_SQL)
    return upgrade_columns(con)


_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", re.S)
_NOT_COLUMN = ("PRIMARY KEY", "UNIQUE", "FOREIGN KEY", "CHECK", "CONSTRAINT")
_CONSTRAINED = re.compile(r"\b(NOT NULL|PRIMARY KEY|UNIQUE|REFERENCES)\b", re.I)


class SchemaMigrationError(RuntimeError):
    pass


def declared_columns(schema_sql: str | None = None) -> dict[str, list[tuple[str, str]]]:
    """{table: [(column, definition)]} in declaration order, parsed from schema.sql (read at call time)."""
    schema_sql = SCHEMA_SQL if schema_sql is None else schema_sql
    out: dict[str, list[tuple[str, str]]] = {}
    for table, body in _TABLE_RE.findall(schema_sql):
        cols = []
        for raw in body.splitlines():
            line = raw.split("--", 1)[0].strip().rstrip(",").strip()
            if not line or line.upper().startswith(_NOT_COLUMN):
                continue
            name, _, definition = line.partition(" ")
            cols.append((name, definition.strip()))
        out[table] = cols
    return out


def upgrade_columns(con: duckdb.DuckDBPyConnection) -> list[str]:
    executed = []
    for table, cols in declared_columns().items():
        existing = set(table_columns(con, table))
        for name, definition in cols:
            if name in existing:
                continue
            if _CONSTRAINED.search(definition):
                raise SchemaMigrationError(f"{table}.{name}: '{definition}' needs a deliberate migration")
            stmt = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}"
            con.execute(stmt)
            executed.append(stmt)
    return executed


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
    on_conflict: str | None = None,
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
        con.execute(f"{verb} {table} BY NAME SELECT * FROM {name}" + (f" {on_conflict}" if on_conflict else ""))
    finally:
        con.unregister(name)
    return len(rows)


def fetch_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    cur = con.execute(sql, list(params))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
