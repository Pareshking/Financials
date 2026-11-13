"""init-db upgrades an existing database in place: idempotent ADD COLUMN for new nullable columns."""

import re

import pytest

from financials.db import (
    SCHEMA_SQL,
    SchemaMigrationError,
    apply_schema,
    connect,
    declared_columns,
    table_columns,
    upgrade_columns,
)


def _old_schema() -> str:
    """schema.sql as it was before Batch 4: every screener_features(_history) column after in_nifty500 removed, and
    no supplemental_kpis table. New columns are always appended before the PRIMARY KEY line, so an old database lacks
    only trailing columns and the positional copy from screener_features_history keeps working after an upgrade."""
    out, skipping = [], False
    for line in SCHEMA_SQL.split("CREATE TABLE IF NOT EXISTS supplemental_kpis")[0].splitlines():
        if re.match(r"\s+in_nifty500\s", line):
            out.append(line)
            skipping = True
            continue
        if skipping and line.strip().startswith("PRIMARY KEY"):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


def test_existing_database_gains_new_columns_and_keeps_rows(tmp_path):
    path = tmp_path / "market.duckdb"
    con = connect(path)
    con.execute(_old_schema())
    assert "eps_ttm" not in table_columns(con, "screener_features")
    con.execute("INSERT INTO entity_master (entity_id, legal_name) VALUES ('e1', 'Kept')")
    executed = apply_schema(con)
    assert any("screener_features ADD COLUMN IF NOT EXISTS eps_ttm DECIMAL(18,4)" in s for s in executed)
    assert table_columns(con, "screener_features") == table_columns(con, "screener_features_history")
    assert [c for c, _ in declared_columns()["screener_features"]] == table_columns(con, "screener_features")
    assert con.execute("SELECT legal_name FROM entity_master").fetchall() == [("Kept",)]
    assert "kpi" in table_columns(con, "supplemental_kpis")  # new table created by the same init-db run
    assert apply_schema(con) == []  # idempotent
    con.close()


def test_fresh_database_needs_no_upgrade():
    con = connect()
    assert apply_schema(con) == []


def test_constrained_new_column_is_refused(monkeypatch):
    con = connect()
    apply_schema(con)
    con.execute("ALTER TABLE screener_features DROP COLUMN pcr")
    monkeypatch.setattr(
        "financials.db.SCHEMA_SQL", SCHEMA_SQL.replace("pcr                 DOUBLE,", "pcr DOUBLE NOT NULL,", 2)
    )
    with pytest.raises(SchemaMigrationError):
        upgrade_columns(con)
