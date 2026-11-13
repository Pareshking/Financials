"""Factor maths and verification, using real ex-date prices from the bhavcopy fixtures."""

from datetime import date
from decimal import Decimal

import pytest

from financials.corp_actions import (
    CorpAction,
    adjust_closes,
    audit_day,
    cumulative_factor,
    theoretical_factors,
    verify_action,
)

D = Decimal


def act(t, num=None, den=None, **kw):
    return CorpAction(
        action_id="a",
        security_id="s",
        action_type=t,
        ex_date=date(2025, 9, 22),
        ratio_num=None if num is None else D(num),
        ratio_den=None if den is None else D(den),
        **kw,
    )


@pytest.mark.parametrize(
    ("action", "price", "eps"),
    [
        (act("SPLIT", 2, 10), D("0.2"), D("0.2")),
        (act("BONUS", 1, 1), D("0.5"), D("0.5")),
        (act("BONUS", 1, 2), D(2) / D(3), D(2) / D(3)),
        (act("CONSOLIDATION", 10, 1), D(10), D(10)),
        (act("DIVIDEND", cash_per_share=D("50")), D(1), D(1)),  # never adjusts prices [C2]
        (act("MERGER"), D(1), D(1)),
        (act("DEMERGER"), None, D(1)),
    ],
)
def test_theoretical_factors(action, price, eps):
    assert theoretical_factors(action, D("100")) == (price, eps)


def test_rights_factor_is_terp_over_cum_close():
    a = act("RIGHTS", 1, 4, issue_price=D("50"))  # 1 new per 4 held at 50; cum close 100
    price, eps = theoretical_factors(a, D("100"))
    assert price == eps == D("0.9")  # (4*100 + 1*50) / (5*100)


@pytest.mark.parametrize("bad", [act("SPLIT", 10, 2), act("CONSOLIDATION", 2, 10), act("BONUS", 0, 1)])
def test_inconsistent_ratios_are_rejected(bad):
    v = verify_action(bad, D("100"), D("100"))
    assert v.status == "QUARANTINED"


@pytest.mark.parametrize(
    ("action", "open_ex", "close_prev"),
    [
        (act("SPLIT", 2, 10), D("148.20"), D("709.40")),  # ADANIPOWER 22-Sep-2025
        (act("BONUS", 1, 1), D("1534.00"), D("3038.00")),  # PIDILITIND 23-Sep-2025
        (act("SPLIT", 1, 10), D("1042.00"), D("9922.00")),  # TATAINVEST 14-Oct-2025
    ],
)
def test_real_ex_dates_verify(action, open_ex, close_prev):
    v = verify_action(action, open_ex, close_prev)
    assert v.status == "VERIFIED", v


def test_wrong_ratio_against_real_gap_is_quarantined():
    v = verify_action(act("BONUS", 1, 2), D("1534.00"), D("3038.00"))  # PIDILITIND was 1:1
    assert v.status == "QUARANTINED"


def test_demerger_factor_is_observed_gap():
    v = verify_action(act("DEMERGER"), D("400.00"), D("660.75"))  # TATAMOTORS 14-Oct-2025
    assert v.status == "VERIFIED"
    assert v.price_factor == D("400.00") / D("660.75")
    assert v.eps_factor == 1


def test_small_factor_is_unobservable():
    v = verify_action(act("RIGHTS", 1, 20, issue_price=D("90")), D("80"), D("100"))
    assert v.status == "UNOBSERVABLE"


def test_gap_auditor():
    s, d = "s", date(2025, 9, 23)
    assert audit_day(s, d, D("105"), D("100"), [], False) == []
    (f,) = audit_day(s, d, D("1534"), D("3038"), [], False)
    assert f.reason_code == "UNEXPLAINED_GAP"
    ok = [act("BONUS", 1, 1, status="VERIFIED", price_factor=D("0.5"))]
    assert audit_day(s, d, D("1534"), D("3038"), ok, False) == []
    pending = [act("BONUS", 1, 1)]
    assert [f.reason_code for f in audit_day(s, d, D("1534"), D("3038"), pending, False)] == ["UNEXPLAINED_GAP"]
    assert [f.reason_code for f in audit_day(s, d, D("100"), D("100"), [], True)] == ["ISIN_CHANGE_WITHOUT_ACTION"]


def test_adjustment_applies_only_before_ex_date_and_respects_freeze():
    split = CorpAction(
        "a",
        "s",
        "SPLIT",
        date(2025, 9, 22),
        D(2),
        D(10),
        status="VERIFIED",
        price_factor=D("0.2"),
        eps_factor=D("0.2"),
    )
    bars = [(date(2025, 9, 19), D("709.40")), (date(2025, 9, 22), D("170.25")), (date(2025, 9, 23), D("160"))]
    assert adjust_closes(bars, [split]) == [
        (date(2025, 9, 19), D("141.880")),
        (date(2025, 9, 22), D("170.25")),
        (date(2025, 9, 23), D("160")),
    ]
    assert [d for d, _ in adjust_closes(bars, [split], frozen_from=date(2025, 9, 23))] == [
        date(2025, 9, 19),
        date(2025, 9, 22),
    ]
    assert cumulative_factor([split], date(2025, 9, 19), kind="eps") == D("0.2")
    pending = CorpAction("b", "s", "SPLIT", date(2025, 9, 22), D(2), D(10))
    assert cumulative_factor([pending], date(2025, 9, 19)) == 1


def test_same_day_split_and_bonus_verify_on_combined_factor():
    """NAZARA 26-Sep-2025: FV 4 -> 2 split and 1:1 bonus, combined factor 0.25."""
    from financials.corp_actions import verify_group

    split, bonus = act("SPLIT", 2, 4), act("BONUS", 1, 1)
    assert verify_action(split, D("291.00"), D("1116.00")).status == "QUARANTINED"  # alone: 0.5 vs 0.26
    results = verify_group([split, bonus], D("291.00"), D("1116.00"))
    assert [r.status for r in results] == ["VERIFIED", "VERIFIED"]
    assert [r.price_factor for r in results] == [D("0.5"), D("0.5")]


def test_unknown_member_quarantines_group():
    from financials.corp_actions import verify_group

    results = verify_group([act("BONUS", 1, 1), act("UNKNOWN")], D("1534"), D("3038"))
    assert {r.status for r in results} == {"QUARANTINED"}


def test_dividend_does_not_explain_a_large_gap():
    div = act("DIVIDEND", cash_per_share=D("160"), status="UNOBSERVABLE", price_factor=D(1))
    (f,) = audit_day("s", date(2025, 9, 22), D("80"), D("100"), [div], False)
    assert f.reason_code == "UNEXPLAINED_GAP"
