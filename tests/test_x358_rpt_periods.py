"""X358 RPT_BALANCE_ROLL: which period a filing's Reg. 23(9) amounts cover, from the balances of earlier filings.

Real, unmodified files (tests/fixtures/rpt_half_year/): POLYMED files half-years (format D, X160); EIDPARRY files the
financial year to date in Q4 (X161). Each Q4 FY26 filing's opening balances are compared with the closing balances of
the same company's Q2 FY26 (six months earlier) and Q4 FY25 (twelve months earlier) filings.
"""

from __future__ import annotations

from datetime import date

import pytest

from _fixture_helpers import FIXTURES
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.reg23_rpt import parse_reg23_rpt
from financials.parsers.xbrl import parse_instance
from financials.rpt_periods import (
    HALF_YEAR,
    NO_HISTORY,
    TWELVE_MONTHS,
    UNDETERMINED,
    _months_back,
    balance_maps,
    classify,
)

DIR = FIXTURES / "rpt_half_year"


def _maps(name: str):
    data = (DIR / name).read_bytes()
    meta = parse_integrated_results(data, name).meta
    rows = parse_reg23_rpt(parse_instance(data), meta["period_end"])
    return balance_maps((r.counterparty_name, r.txn_type, r.opening_balance, r.closing_balance) for r in rows)


def _q4(q4: str, q2: str, q4_prev: str):
    return classify(_maps(q4)[0], _maps(q2)[1], _maps(q4_prev)[1])


def test_polymed_q4_rolls_from_the_half_year():
    b = _q4("INTEGRATED_FILING_INDAS_1672831_25052026105506_WEB.xml",
            "INTEGRATED_FILING_INDAS_1569348_08112025095047_WEB.xml",
            "INTEGRATED_FILING_INDAS_1432801_07052025030105_WEB.xml")  # fmt: skip
    assert b.basis == HALF_YEAR and b.pairs >= 3 and b.from_year == 0 and b.from_half == b.pairs


def test_eid_parry_q4_rolls_from_the_previous_year_end():
    b = _q4("INTEGRATED_FILING_INDAS_1673448_26052026074140_WEB.xml",
            "INTEGRATED_FILING_INDAS_1571468_11112025064700_WEB.xml",
            "INTEGRATED_FILING_INDAS_1453034_27052025055732_WEB.xml")  # fmt: skip
    assert b.basis == TWELVE_MONTHS and b.from_half == 0 and b.from_year >= b.pairs / 2


def test_a_twelve_month_roll_at_mid_year_fits_no_format_and_too_few_pairs_decide_nothing():
    k = [("A", "sale"), ("B", "sale"), ("C", "sale")]
    half, year = {x: 10_000_000 for x in k}, {x: 20_000_000 for x in k}
    assert classify(dict(year), half, year).basis == TWELVE_MONTHS
    assert classify(dict(year), half, year, year_end=False).basis == UNDETERMINED
    assert classify({k[0]: 20_000_000}, half, year).basis == UNDETERMINED  # one telling pair
    assert classify(dict(year), half, half).basis == UNDETERMINED  # equal earlier closings tell nothing
    assert classify(dict(year), None, year).basis == NO_HISTORY


@pytest.mark.parametrize(("end", "back", "want"), [(date(2026, 3, 31), 6, date(2025, 9, 30)),
                         (date(2026, 9, 30), 12, date(2025, 9, 30)), (date(2025, 12, 31), 6, date(2025, 6, 30)),
                         (date(2026, 2, 28), 12, date(2025, 2, 28))])  # fmt: skip
def test_month_ends(end, back, want):
    assert _months_back(end, back) == want


def test_the_table_is_written_from_promoted_rows(market):
    from financials.rpt_periods import write_periods

    assert write_periods(market.con) == {"filings": 0}


def test_the_view_reads_the_current_versions():
    from financials.parsers.reg23_rpt import REG23_PARSER_VERSION
    from financials.rpt_periods import RPT_PERIOD_RULE_VERSION
    from financials.sources import ROOT

    ddl = (ROOT / "src" / "financials" / "db" / "schema.sql").read_text(encoding="utf-8")
    view = ddl[ddl.index("CREATE OR REPLACE VIEW rpt_half_year") :].split(";", 1)[0]
    assert f"'{REG23_PARSER_VERSION}'" in view and f"'{RPT_PERIOD_RULE_VERSION}'" in view
