"""A1.12 Price to Quarterly Earnings (S24): Screener's definition, from its own change-log page (fixture)."""

from __future__ import annotations

import html
import re

import duckdb

from _fixture_helpers import FIXTURES
from financials.dsl import ALIASES, compile_screen

PAGE = FIXTURES / "screener_docs" / "Quarterly-PE.html"


def test_screener_states_the_formula():
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", PAGE.read_text(encoding="utf-8"))))
    assert "Current price/(EPS latest quarter *4)" in text


def test_alias_is_price_over_four_quarters_eps_and_null_unless_eps_is_positive():
    expr = ALIASES["price to quarterly earning"][0]
    assert ALIASES["quarterly pe"][0] == ALIASES["price to quarterly earnings"][0] == expr
    con = duckdb.connect()
    con.execute("CREATE TABLE t (close DECIMAL(18,4), eps_latest_quarter DECIMAL(18,4))")
    con.execute("INSERT INTO t VALUES (100, 2.5), (100, 0), (100, -1), (NULL, 2), (50, NULL)")
    assert [r[0] for r in con.execute(f"SELECT {expr} FROM t").fetchall()] == [10, None, None, None, None]
    cs = compile_screen("Price to Quarterly Earning < 20")
    assert con.execute(f"SELECT count(*) FROM t WHERE {cs.where_sql}", cs.params).fetchone()[0] == 1
