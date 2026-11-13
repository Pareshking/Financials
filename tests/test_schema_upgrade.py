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
    """schema.sql as it was before Batch 4: screener_features without the lender / EPS / bank columns. New columns
    are always appended before the PRIMARY KEY line, so an old database lacks only trailing columns and the
    positional copy from screener_features_history keeps working after an upgrade."""
    new = ("eps_ttm", "eps_continuing_ttm", "roe_continuing", "core_profit_ttm", "is_lending_nbfc", "nii_ttm",
           "ppop_ttm", "cost_to_income", "credit_cost", "nim_asset_proxy", "roa", "loans", "loans_as_of",
           "loans_avg_from", "gnpa_pct", "nnpa_pct", "pcr", "credit_to_deposit", "cet1_pct", "at1_pct", "roa_filed",
           "govt_holding_pct")  # fmt: skip
    return "\n".join(line for line in SCHEMA_SQL.splitlines() if not re.match(rf"\s+({'|'.join(new)})\s", line))


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
