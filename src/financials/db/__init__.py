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
VIEWS_MARKER = "-- views (after column upgrade)\n"  # schema.sql: views run after upgrade_columns


def connect(path: str | Path = ":memory:", *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def version_key(column: str = "parser_version") -> str:
    """SQL sort key for a dotted parser version: '0.10.0' sorts after '0.9.0' (a string sort would not)."""
    return "(" + " || '.' || ".join(f"lpad(split_part({column}, '.', {i}), 9, '0')" for i in (1, 2, 3)) + ")"


def apply_schema(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Create missing tables, then add columns that schema.sql declares but an existing database lacks.

    Idempotent: a second run changes nothing. Only nullable, constraint-free columns are added automatically;
    a new NOT NULL / PRIMARY KEY / UNIQUE / REFERENCES column needs a deliberate migration and raises.
    Returns the statements executed by the upgrade (empty for a fresh or current database). Views (below
    VIEWS_MARKER in schema.sql) are created last, so they may name columns the upgrade just added. A database whose
    screener_features_history is still the wide table raises SchemaMigrationError: `migrate-sparse-history`
    (features_store.migrate_legacy) converts it explicitly.
    """
    if con.execute(_LEGACY_HISTORY).fetchone()[0]:
        raise SchemaMigrationError(
            "screener_features_history is still the wide table: run `python -m financials --data-dir data "
            "migrate-sparse-history` (event-sparse storage, architecture §4.1), then `compact`"
        )
    tables, _, views = SCHEMA_SQL.partition(VIEWS_MARKER)
    con.execute(tables)
    executed = upgrade_columns(con)
    if views.strip():
        con.execute(views)
    return executed


_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", re.S)
_NOT_COLUMN = ("PRIMARY KEY", "UNIQUE", "FOREIGN KEY", "CHECK", "CONSTRAINT")
_CONSTRAINED = re.compile(r"\b(NOT NULL|PRIMARY KEY|UNIQUE|REFERENCES)\b", re.I)


class SchemaMigrationError(RuntimeError):
    pass


# A database from before event-sparse storage (features_store.migrate_legacy converts it): the history is a table.
_LEGACY_HISTORY = (
    "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'screener_features_history' AND schema_name = 'main' "
    "AND database_name = current_database()"
)


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


# Deliberate migrations that relax a NOT NULL column of an existing database to the nullable declaration of schema.sql
# (DuckDB: catalog-only, no rewrite): disclosure_facts.value_text is NULL for the pointer rows of parser disc-2
# (owner decision M, X120).
RELAXED_NOT_NULL = (("disclosure_facts", "value_text"),)


def upgrade_columns(con: duckdb.DuckDBPyConnection) -> list[str]:
    executed = []
    declared = declared_columns()
    for table, column in RELAXED_NOT_NULL:
        definition = dict(declared[table])[column]
        nullable = con.execute(
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = ? AND column_name = ? "
            "AND table_schema = 'main' AND table_catalog = current_database()",
            [table, column],
        ).fetchone()
        if nullable == ("NO",) and not _CONSTRAINED.search(definition):
            stmt = f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"
            con.execute(stmt)
            executed.append(stmt)
    for table, cols in declared.items():
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
