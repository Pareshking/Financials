"""Screener DSL: grammar, safety, custom ratios, and screens on the real-data feature table."""

from datetime import date
from decimal import Decimal

import pytest

from financials.db import apply_schema, connect
from financials.dsl import ALIASES, DslError, compile_screen, run_screen, save_custom_ratio, tokenize
from financials.features import materialize


def test_multi_word_aliases_and_numbers():
    toks = tokenize("Market Cap > 500 AND In Nifty 500 = 1")
    assert [(t.kind, t.text) for t in toks[:-1]] == [
        ("NAME", "Market Cap"), (("OP", ">")), ("NUM", "500"), ("KW", "and"),
        ("NAME", "In Nifty 500"), ("OP", "="), ("NUM", "1"),
    ]  # fmt: skip


def test_compiles_to_parameterised_sql_with_precedence():
    cs = compile_screen("roe > 15 OR pe < 10 AND NOT debt to equity > 1")
    assert cs.where_sql == "(((roe * 100) > ?) OR ((pe < ?) AND (NOT (debt_to_equity > ?))))"
    assert cs.params == [Decimal(15), Decimal(10), Decimal(1)]
    assert cs.metrics == ["debt to equity", "pe", "roe"]


def test_arithmetic_parentheses_and_safe_division():
    cs = compile_screen("(net profit - 2) / (sales + 1) * 100 >= -5")
    assert cs.where_sql == ("(((((pat_ttm / 10000000) - ?) / NULLIF(((sales_ttm / 10000000) + ?), 0)) * ?) >= (-?))")
    assert cs.params == [Decimal(2), Decimal(1), Decimal(100), Decimal(5)]
    assert compile_screen("(roe > 1 OR roe < 0) AND pe > 0").where_sql.startswith("((((roe")


@pytest.mark.parametrize(
    "query",
    [
        "pe > 10; DROP TABLE ohlcv",
        "pe > 10 -- comment",
        "close > 1 OR 1=1",  # 'close' is not an alias
        "pe >",
        "pe 10",
        "roe > 'x'",
        "unknownmetric > 1",
        "pe > 10 AND",
        "(pe > 10",
        "pe",
    ],
)
def test_rejects_invalid_or_hostile_input(query):
    with pytest.raises(DslError):
        compile_screen(query)


def test_every_alias_compiles_against_feature_table():
    con = connect()
    apply_schema(con)
    for alias in ALIASES:
        cs = compile_screen(f"{alias} > 0")
        con.execute(f"SELECT count(*) FROM screener_features WHERE {cs.where_sql}", cs.params)


def test_custom_ratios_expand_and_cycles_are_rejected():
    con = connect()
    apply_schema(con)
    save_custom_ratio(con, "Net cash to mcap", "(0 - net debt) / market cap * 100")
    save_custom_ratio(con, "Cash rich", "net cash to mcap * 2")
    cs = compile_screen("cash rich > 10", {"net cash to mcap": "(0 - net debt) / market cap * 100",
                                           "cash rich": "net cash to mcap * 2"})  # fmt: skip
    assert "net_debt" in cs.where_sql and "market_cap" in cs.where_sql
    with pytest.raises(DslError, match="cycle"):
        save_custom_ratio(con, "net cash to mcap", "cash rich + 1")
    with pytest.raises(DslError, match="built-in"):
        save_custom_ratio(con, "ROE", "pe * 2")
    with pytest.raises(DslError):
        save_custom_ratio(con, "bad", "pe > 2")  # must be arithmetic


@pytest.fixture(scope="module")
def screened(full_market):
    assert materialize(full_market.con, date(2025, 10, 14)).status == "PROMOTED"
    assert materialize(full_market.con, date(2026, 11, 12)).status == "PROMOTED"
    return full_market


def test_screen_on_real_features(screened):
    rows = run_screen(screened.con, "Market Cap > 100 AND Promoter holding > 30")
    assert [r["symbol"] for r in rows] == ["ELIN"]  # only issuer with Reg. 31 data
    r = rows[0]
    assert r["promoter holding"] == pytest.approx(32.97)
    assert r["market cap"] == pytest.approx(83.83 * 49709220 / 1e7)


def test_missing_data_never_passes(screened):
    assert run_screen(screened.con, "pe > 0") == []  # no TTM windows exist yet
    assert run_screen(screened.con, "NOT pe > 0") == []


def test_point_in_time_screen(screened):
    q = "Price to book value > 0"
    assert run_screen(screened.con, q, as_of=date(2025, 10, 14)) == []  # ELIN results not yet public
    assert [r["symbol"] for r in run_screen(screened.con, q, as_of=date(2026, 11, 12))] == ["ELIN"]


def test_index_membership_filter(screened):
    rows = run_screen(screened.con, "In Nifty 500 = 1", limit=1000)
    assert 450 < len(rows) <= 500
    assert "TMPV" in {r["symbol"] for r in rows}
