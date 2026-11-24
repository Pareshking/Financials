"""X356 RIGHTS_AT_OR_ABOVE_MARKET: a rights issue priced at or above the cum-rights close has no bonus element."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from _fixture_helpers import FIXTURES
from financials.corp_actions import CorpAction, theoretical_factors, verify_action
from financials.parsers.nse_corp_actions import parse_nse_corp_actions_json
from financials.promoter import _requeue_rights_above_market

CA = FIXTURES / "corp_actions"
D = Decimal


def _component(name: str, symbol: str):
    (r,) = [r for r in parse_nse_corp_actions_json((CA / name).read_bytes()) if r.symbol == symbol]
    (c,) = r.components
    return r, c


def _action(c, ex):
    return CorpAction("ca_x", "sec_x", "RIGHTS", ex, c.ratio_num, c.ratio_den, issue_price=c.issue_price)


def test_real_rights_above_the_close_take_factor_one():
    # GATECHDVR 51:82 at Rs 1 (face value 1, premium 0); close 25-Apr-2025 0.88, open 28-Apr-2025 0.83
    r, c = _component("nse_corporateActions_equities_30-03-2025_28-04-2025.json", "GATECHDVR")
    assert (r.subject, c.issue_price) == ("Rights 51:82 @ Premium Rs 0/-", D(1))
    a = _action(c, r.ex_date)
    assert theoretical_factors(a, D("0.88")) == (1, 1)  # the formula alone gave 1.0523 (prices raised 5%)
    v = verify_action(a, D("0.83"), D("0.88"))
    assert (v.status, v.price_factor) == ("UNOBSERVABLE", 1)
    # 5PAISA 1:2 at Rs 300 (face value 10 + premium 290); close 16-Mar-2026 292.55
    r, c = _component("nse_corporateActions_equities_23-02-2026_24-03-2026.json", "5PAISA")
    assert c.issue_price == D(300)
    assert theoretical_factors(_action(c, r.ex_date), D("292.55")) == (1, 1)  # was 1.0085


def test_rights_below_the_close_are_unchanged():
    a = CorpAction("ca_y", "sec_y", "RIGHTS", date(2026, 1, 1), D(1), D(4), issue_price=D(50))
    f, e = theoretical_factors(a, D(100))
    assert f == e == (4 * D(100) + D(50)) / (5 * D(100))


def test_old_decisions_above_one_are_requeued_and_manual_ones_stand(market):
    con = market.con
    con.execute("CREATE TEMP TABLE corp_actions AS SELECT * FROM main.corp_actions WHERE false")
    rows = [("a1", "RIGHTS", "UNOBSERVABLE", 1.05), ("a2", "RIGHTS", "REJECTED", 1.12),
            ("a3", "RIGHTS", "VERIFIED", 0.9), ("a4", "BONUS", "VERIFIED", 0.5)]  # fmt: skip
    for aid, t, st, f in rows:
        con.execute("INSERT INTO corp_actions (action_id, security_id, action_type, ex_date, status, price_factor, "
                    "source_filing_id) VALUES (?, 's', ?, DATE '2025-04-28', ?, ?, 'f')", [aid, t, st, f])  # fmt: skip
    _requeue_rights_above_market(con)
    got = dict(con.execute("SELECT action_id, status FROM corp_actions").fetchall())
    assert got == {"a1": "PENDING", "a2": "REJECTED", "a3": "VERIFIED", "a4": "VERIFIED"}
    _requeue_rights_above_market(con)  # idempotent
    assert dict(con.execute("SELECT action_id, status FROM corp_actions").fetchall()) == got
