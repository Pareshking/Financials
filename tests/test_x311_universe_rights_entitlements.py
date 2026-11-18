"""Rule X311: rights entitlements never join the Rs 500 Cr universe (U1-R); members admitted before it are removed."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import FIXTURES
from financials import universe
from financials.parsers.pr_mcap import parse_pr_mcap
from financials.promoter import promote
from financials.staging import stage_mcap_day

PR061224 = FIXTURES / "pr_zip" / "PR061224.zip"
URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR061224.zip"
FRI = date(2024, 12, 6)


def test_pr_zip_lists_the_upl_entitlement_above_the_threshold():
    rows = {(r.symbol, r.series): r for r in parse_pr_mcap(PR061224.read_bytes())}
    re_, eq = rows[("UPL-RE", "BE")], rows[("UPL", "EQ")]
    assert (re_.category, re_.issue_size, re_.close, re_.market_cap_inr) == (
        "Permitted", 93680642, Decimal("190.25"), Decimal("17822742140.50"))  # fmt: skip
    assert re_.market_cap_inr >= universe.THRESHOLD_INR  # Rs 1,782 Cr: rule U1-P admitted it
    assert (eq.category, eq.market_cap_inr) == ("Listed", Decimal("422329389208.65"))


@pytest.fixture
def re_market(tmp_path, monkeypatch):
    m = Market(tmp_path)
    for stage in (m.stage_day("20241206"),
                  stage_mcap_day(m.vault, m.stage_root, data=PR061224.read_bytes(), source_url=URL,
                                 fetched_at=FETCHED_AT)):  # fmt: skip
        assert promote(m.con, stage).status == "PROMOTED"
    # no holiday master covers 2024 in the fixtures; 6 Dec 2024 is a Friday (the week end), which is not under test
    monkeypatch.setattr(universe, "week_end_trading_days", lambda con, start, end: ([FRI], []))
    yield m
    m.con.close()


def _run(con, now):
    con.execute("BEGIN")
    r = universe.update_universe(con, date(2024, 12, 1), date(2024, 12, 8), now=now)
    con.execute("COMMIT")
    return r


def _members(con):
    return dict(con.execute("SELECT symbol, listing_category FROM universe_membership").fetchall())


def test_entitlement_does_not_join_and_the_parent_does(re_market):
    con = re_market.con
    isins = dict(con.execute("SELECT symbol, isin FROM security_identifier_history "
                             "WHERE symbol IN ('UPL', 'UPL-RE')").fetchall())  # fmt: skip
    assert isins == {"UPL": "INE628A01036", "UPL-RE": "INE628A20010"}  # X140 markers: type 20 beside type 01
    r = _run(con, datetime(2024, 12, 7))
    got = _members(con)
    assert "UPL-RE" not in got and got["UPL"] == "Listed"
    assert (r["rights_entitlements_skipped"], r["rights_entitlements_removed"]) == (1, 0)
    assert r["rule_version"] == "U1-2026.11.18-R"
    assert not [s for s in got if re.search(r"-RE[0-9]*$", s)]


def test_member_admitted_before_the_rule_is_removed_and_logged(re_market, monkeypatch):
    con = re_market.con
    with monkeypatch.context() as mp:  # rule U1-P: no entitlement test at all
        mp.setattr(universe, "rights_entitlement_sql", lambda h: "false")
        mp.setattr(universe, "RULE_VERSION", "U1-2026.11.17-P")
        old = _run(con, datetime(2024, 12, 7))
    before = _members(con)
    assert before["UPL-RE"] == "Permitted" and "UPL" in before
    row = con.execute("SELECT security_id, joined_date, market_cap_inr, rule_version FROM universe_membership "
                      "WHERE symbol = 'UPL-RE'").fetchone()  # fmt: skip
    assert row[1:] == (FRI, Decimal("17822742140.50"), "U1-2026.11.17-P")

    new = _run(con, datetime(2024, 12, 8))
    after = _members(con)
    assert new["rights_entitlements_removed"] == 1 and new["joined"] == 0
    assert set(after) == set(before) - {"UPL-RE"} and new["members"] == old["members"] - 1
    note, params, result = con.execute(
        "SELECT note, params, result FROM admin_log WHERE action = 'UNIVERSE_REMOVE_RIGHTS_ENTITLEMENT'"
    ).fetchone()
    assert "X311" in note and json.loads(params)["rule_version"] == "U1-2026.11.18-R"
    (logged,) = json.loads(result)["removed"]
    assert (logged["security_id"], logged["symbol"], logged["market_cap_inr"], logged["rule_version"]) == (
        row[0], "UPL-RE", "17822742140.50", "U1-2026.11.17-P")  # fmt: skip

    again = _run(con, datetime(2024, 12, 9))  # idempotent: nothing left to remove, the entitlement stays out
    assert (again["rights_entitlements_removed"], again["joined"], again["members"]) == (0, 0, new["members"])
    assert con.execute("SELECT count(*) FROM admin_log WHERE action = 'UNIVERSE_REMOVE_RIGHTS_ENTITLEMENT'"
                       ).fetchone()[0] == 1  # fmt: skip
