"""X355 RIGHTS_PRICE_UNSTATED: a rights record with no issue price (PRAXIS `Rights 5:9`, ex 18-Nov-2026)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import FIXTURES
from financials.corp_actions import CorpAction, theoretical_factors, verify_action
from financials.parsers.nse_corp_actions import parse_nse_corp_actions_json, parse_purpose
from financials.promoter import _actions, promote, record_corp_action

SRC = FIXTURES / "corp_actions" / "nse_corporateActions_equities_16-11-2026_15-12-2026.json"
D = Decimal


def _rights(floor, price=None):
    return CorpAction("ca_x", "sec_x", "RIGHTS", date(2026, 11, 18), D(5), D(9), issue_price=price,
                      issue_price_floor=floor)  # fmt: skip


def test_the_real_record_parses_with_face_value_as_the_price_floor():
    rows = {r.symbol: r for r in parse_nse_corp_actions_json(SRC.read_bytes())}
    p = rows["PRAXIS"]
    assert (p.subject, p.face_value, p.ex_date, p.parse_status) == ("Rights 5:9", D(5), date(2026, 11, 18), "PARSED")
    (c,) = p.components
    assert (c.action_type, c.ratio_num, c.ratio_den, c.issue_price, c.issue_price_floor) == ("RIGHTS", 5, 9, None, 5)
    (s,) = rows["SMLMAH"].components  # a priced rights record is unchanged: issue price = face value + premium
    assert (s.issue_price, s.issue_price_floor) == (D(3506), None)
    assert all(r.parse_status != "UNPARSED" for r in rows.values())
    assert parse_purpose("Rights 5:9", None)[:2] == ("UNPARSED", "rights without issue price or face value")


def test_no_bonus_element_when_face_value_is_at_or_above_the_cum_rights_close():
    # PRAXIS: face value 5, close 17-Nov-2026 4.93, open 18-Nov-2026 4.93 (no gap: consistent with factor 1)
    assert theoretical_factors(_rights(D(5)), D("4.93")) == (1, 1)
    assert theoretical_factors(_rights(D(5)), D(5)) == (1, 1)
    v = verify_action(_rights(D(5)), D("4.93"), D("4.93"))
    assert v.status == "UNOBSERVABLE" and v.price_factor == 1 and v.eps_factor == 1


def test_an_unknown_price_with_face_value_below_the_close_stays_quarantined():
    with pytest.raises(ValueError, match="face value 5 is below the cum-rights close 6"):
        theoretical_factors(_rights(D(5)), D(6))
    assert verify_action(_rights(D(5)), D("5.9"), D(6)).status == "QUARANTINED"
    assert verify_action(_rights(None), D("5.9"), D(6)).status == "QUARANTINED"


def test_a_stated_price_still_wins_over_the_floor():
    f, _ = theoretical_factors(_rights(D(5), price=D(2)), D(4))
    assert f == (9 * D(4) + 5 * D(2)) / (14 * D(4))


def test_the_floor_is_kept_in_the_ledger(market):
    m = market
    promote(m.con, m.stage_day("20250922"))
    sec = m.con.execute("SELECT security_id FROM securities LIMIT 1").fetchone()[0]
    fil = m.con.execute("SELECT filing_id FROM filings LIMIT 1").fetchone()[0]
    a = CorpAction("ca_x355", sec, "RIGHTS", date(2026, 11, 18), D(5), D(9), issue_price_floor=D(5))
    record_corp_action(m.con, a, source_filing_id=fil)
    (back,) = _actions(m.con, "action_id = ?", ["ca_x355"])
    assert back.issue_price_floor == 5 and back.issue_price is None
