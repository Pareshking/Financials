"""Work QF5 (parser 0.10.12): X335 the NCI of an X86 withheld period kept as filed, X336 ISIN one character off the
symbol's ISIN, X337 a long first financial period, X338 a pre-cutoff irregular / conflicting comparative ignored.

Fixtures (`xbrl_qf5/`, MANIFEST section QF5): FCL 9M FY26 consolidated (X335), Bluspring Enterprises' first annual
report 2024-02-11..2025-03-31 (X337, X152), Transrail Lighting FY25 annual (X338), J. Kumar Infraprojects Q3 FY26
and Andhra Sugars Q4 FY26 results (X336). Kept out of `xbrl/` so the end-to-end fixture market is unchanged.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

import financials.fundamentals as F
from _fixture_helpers import FIXTURES
from financials.fundamentals import FactBook, load_factbook
from financials.parsers.indas_corp import first_period_months, parse_indas_corp_results
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.promoter import compact_name, company_names_match, promote
from financials.staging import stage_results_xbrl

QF5 = FIXTURES / "xbrl_qf5"
FCL_9M = QF5 / "INTEGRATED_FILING_INDAS_1625647_13022026080434_WEB.xml"
BLUSPRING = QF5 / "AR_XBRL_BLUSPRING_16012026154522.xml"
TRANSRAILL = QF5 / "AR_XBRL_TRANSRAILL_07012026120651.xml"
JKIL_Q3 = QF5 / "INTEGRATED_FILING_INDAS_1619130_05022026045616_WEB.xml"
ANDHRSUGAR_Q4 = QF5 / "INTEGRATED_FILING_INDAS_1677615_30052026054952_WEB.xml"
NCI = F.ASFILED_NCI_TAG
OWNERS = "asfiled_profit_or_loss_attributable_to_owners_of_parent"


# ── X335: owners / NCI of a withheld period as filed ────────────────────────────────────────────────────────────


def _facts(r, start, end):
    return {f.canonical_tag: (f.value, f.source_element) for f in r.facts
            if (str(f.period_start), str(f.period_end)) == (start, end)}  # fmt: skip


def test_x335_fcl_withheld_9m_keeps_its_nci_as_filed():
    """FCL 9M FY26 as filed: owners 771,438,000 + NCI 40,765,000 = 812,203,000, PAT 791,648,000 (X86 withholds the
    split). Q3 reconciles (263,475,000 + 37,682,000 = PAT 301,157,000), so the NCI element is mapped for Q3 and,
    before X335, preserve_withheld skipped the element for the 9M period too."""
    r = parse_indas_corp_results(FCL_9M.read_bytes())
    assert [(i.reason_code, i.details["period"]) for i in r.findings] == [
        ("ATTRIBUTION_WITHHELD", ["2025-04-01", "2025-12-31"])
    ]
    m9 = _facts(r, "2025-04-01", "2025-12-31")
    assert "pat_owners" not in m9 and "pat_nci" not in m9 and m9["attribution_withheld"][0] == 1
    assert m9[NCI] == (Decimal("40765000"), "ProfitOrLossAttributableToNonControllingInterests")
    assert m9[OWNERS] == (Decimal("771438000"), "ProfitOrLossAttributableToOwnersOfParent")
    q3 = _facts(r, "2025-10-01", "2025-12-31")
    assert q3["pat_nci"] == (Decimal("37682000"), "ProfitOrLossAttributableToNonControllingInterests")
    assert NCI not in q3 and OWNERS not in q3  # a reconciling period keeps its canonical values only
    assert [f for f in r.facts if f.canonical_tag == NCI and f.period_months != 9] == []


def test_x335_x325_owners_profit_is_pat_less_nci_flagged():
    r = parse_indas_corp_results(FCL_9M.read_bytes())
    book = FactBook("FCL", "CONSOLIDATED", fy_starts=frozenset({date(2025, 4, 1)}))
    for f in r.facts:
        if f.period_type == "DURATION":
            book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    m9 = (date(2025, 4, 1), date(2025, 12, 31))
    owners = book.coalesced("pat_owners", "pat")
    assert book.stated(owners, m9) is None  # validated: withheld (X86 unchanged)
    book.fill_as_filed = True
    assert book.stated(owners, m9) == Decimal("791648000") - Decimal("40765000") == Decimal("750883000")
    assert book.dq == {F.DQ_ATTRIBUTION_NCI}


# ── X337 / X338: periods of first-year annual reports ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "end", "months"),
    [
        (date(2024, 2, 11), date(2025, 3, 31), 14),  # BLUSPRING
        (date(2024, 2, 10), date(2025, 3, 31), 14),  # DIGITIDE
        (date(2023, 10, 2), date(2025, 3, 31), 18),
        (date(2023, 9, 15), date(2025, 3, 31), None),  # 19 months: beyond invariant 6
        (date(2024, 7, 28), date(2025, 3, 31), None),  # 9 months: a stub (X152), not a long first period
        (date(2024, 4, 1), date(2025, 3, 31), None),  # starts on the 1st: whole-month period_months applies
        (date(2024, 2, 11), date(2025, 3, 30), None),  # not a month end
    ],
)
def test_x337_first_period_months(start, end, months):
    assert first_period_months(start, end) == months


def test_x337_bluspring_first_period_is_stored_as_a_one_off():
    """Bluspring (demerged from Quess, incorporated 11 Feb 2024) declares only 2024-02-11..2025-03-31 and a carve-out
    comparative 2023-04-01..2024-02-10: both irregular, so the whole annual report was held back (3 PERIOD findings)."""
    r = parse_reg34_annual(BLUSPRING.read_bytes(), BLUSPRING.name)
    assert not r.issues and not r.findings
    assert (r.meta["fy_start"], r.meta["fy_end"]) == (date(2024, 2, 11), date(2025, 3, 31))
    assert r.meta["first_periods"] == [(date(2024, 2, 11), date(2025, 3, 31))]
    assert r.meta["stub_periods"] == [(date(2023, 4, 1), date(2024, 2, 10))]  # X152 once the first period is regular
    assert {"FIRST_PERIOD_LONG", "IRREGULAR_COMPARATIVE_STUB"} <= set(r.meta["rules_applied"])
    durations = {(f.period_start, f.period_end, f.period_months) for f in r.facts if f.period_type == "DURATION"}
    assert durations == {(date(2024, 2, 11), date(2025, 3, 31), 14)}
    v = _facts(r, "2024-02-11", "2025-03-31")
    assert v["revenue_from_operations"][0] == Decimal("23223750000")
    assert v["pat"][0] == Decimal("-824780000")
    assert _facts(r, "2025-03-31", "2025-03-31")["total_assets"][0] == Decimal("13081990000")


def test_x338_transrail_typo_in_pre_cutoff_comparative_is_ignored():
    """Transrail FY25 declares 2023-01-04..2024-03-31 for context D_01042023_31032024 (day and month swapped): a
    CONTEXT_CONFLICT on a pre-cutoff comparative held the FY25 annual report back."""
    r = parse_reg34_annual(TRANSRAILL.read_bytes(), TRANSRAILL.name)
    assert not r.issues and not r.findings
    assert r.meta["declared_periods"] == [(date(2024, 4, 1), date(2025, 3, 31))]
    assert {"PRE_CUTOFF_DECLARED_PERIOD_IGNORED", "UNDECLARED_PRE_CUTOFF_CONTEXT"} <= set(r.meta["rules_applied"])
    assert {f.period_months for f in r.facts if f.period_type == "DURATION"} == {12}
    assert _facts(r, "2024-04-01", "2025-03-31")["pat"][0] == Decimal("3343400000")


def test_x338_an_in_scope_conflict_still_quarantines():
    data = TRANSRAILL.read_bytes().replace(  # in memory only; the fixture is untouched
        b'contextRef="D_01042024_31032025">2024-04-01', b'contextRef="D_01042024_31032025">2024-01-04'
    )
    r = parse_reg34_annual(data, TRANSRAILL.name)
    assert [i.reason_code for i in r.issues][:1] == ["CONTEXT_CONFLICT"]


def test_x337_a_19_month_period_stays_irregular_and_so_does_its_comparative():
    """In memory, 2023-09-11..2025-03-31 (19 months, declared and context): beyond 18 months it is irregular, and with
    no regular in-scope period the pre-cutoff comparative is not ignored (X338) either."""
    data = BLUSPRING.read_bytes().replace(b">2024-02-11<", b">2023-09-11<")
    r = parse_reg34_annual(data, BLUSPRING.name)
    assert sorted((i.reason_code, tuple(i.details.get("dates", ()))) for i in r.issues) == [
        ("IRREGULAR_PERIOD", ("2023-04-01", "2024-02-10")),
        ("IRREGULAR_PERIOD", ("2023-09-11", "2025-03-31")),
        ("NO_DECLARED_PERIOD", ()),
    ]


def _stage(market, path, broadcast):
    return stage_results_xbrl(market.vault, market.stage_root, data=path.read_bytes(),
                              source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + path.name,
                              fetched_at=datetime(2026, 11, 19, 6), broadcast_ts=broadcast,
                              broadcast_ts_source="API_FIELD")  # fmt: skip


def test_x337_bluspring_promotes_and_no_ttm_or_annual_reader_uses_the_14_months(market):
    promote(market.con, market.stage_day("20251023"))
    r = promote(market.con, _stage(market, BLUSPRING, datetime(2026, 1, 16, 10, 15)))
    assert r.status == "PROMOTED", r
    con = market.con
    months = con.execute("SELECT DISTINCT period_months FROM fact_observations WHERE filing_id = ? "
                         "AND period_type = 'DURATION'", [r.message]).fetchall()  # fmt: skip
    assert months == [(14,)]
    seg = con.execute("SELECT DISTINCT period_months FROM segment_observations WHERE filing_id = ? "
                      "AND period_type = 'DURATION'", [r.message]).fetchall()  # fmt: skip
    assert seg in ([], [(14,)])
    assert con.execute("SELECT count(*) FROM quarantine_queue WHERE filing_id = ? AND stage = 'PERIOD'",
                       [r.message]).fetchone() == (0,)  # fmt: skip
    (ent,) = con.execute("SELECT DISTINCT entity_id FROM filing_meta WHERE filing_id = ?", [r.message]).fetchone()
    book = load_factbook(con, ent, "STANDALONE", datetime(2026, 11, 19))
    p = (date(2024, 2, 11), date(2025, 3, 31))
    assert book.durations["pat"][p] == Decimal("-824780000")  # stated, as a one-off period
    assert book.ttm("pat", p[1]) is None and book.ttm("revenue_from_operations", p[1]) is None
    assert F.latest_fiscal_year(book, date(2025, 12, 31)) is None  # annual readers take 12-month periods only
    assert book.instants["total_assets"][p[1]] == Decimal("13081990000")


# ── X336: ISIN one character off the symbol's ISIN ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stated", "legal", "ok"),
    [
        ("J.KUMAR INFRAPROJECTS LIMITED", "JKUMAR INFR.LTD.", True),
        ("THE ANDHRA SUGARS LIMITED", "ANDHRA SUGARS LTD", True),
        ("Godrej Agrovet Limited", "GODREJ AGROVET LIMITED", True),  # names_agree (X88)
        ("J.KUMAR INFRAPROJECTS LIMITED", "JK CEMENT LTD", False),
        ("ANDHRA PAPER LIMITED", "ANDHRA SUGARS LTD", False),
        (None, "ANDHRA SUGARS LTD", False),
    ],
)
def test_x336_company_names_match(stated, legal, ok):
    assert company_names_match(stated, legal) is ok


def test_x336_compact_name():
    assert compact_name("J.KUMAR INFRAPROJECTS LIMITED") == "JKUMARINFRAPROJECTS"
    assert compact_name("JKUMAR INFR.LTD.") == "JKUMARINFR"
    assert compact_name("THE ANDHRA SUGARS LIMITED") == compact_name("ANDHRA SUGARS LTD") == "ANDHRASUGARS"


@pytest.mark.parametrize(
    ("path", "symbol", "stated", "actual"),
    [
        (JKIL_Q3, "JKIL", "INE576101022", "INE576I01022"),  # digit 1 for the letter I, inside the issuer code
        (ANDHRSUGAR_Q4, "ANDHRSUGAR", "INE715N01021", "INE715B01021"),  # N for B
    ],
)
def test_x336_isin_one_character_off_promotes_to_the_symbols_entity(market, path, symbol, stated, actual):
    assert stated.encode() in path.read_bytes() and actual.encode() not in path.read_bytes()
    promote(market.con, market.stage_day("20250228"))
    r = promote(market.con, _stage(market, path, datetime(2026, 2, 5, 11)))
    assert r.status == "PROMOTED", r
    ent = market.con.execute("SELECT DISTINCT entity_id FROM filing_meta WHERE filing_id = ?", [r.message]).fetchone()
    want = market.con.execute("SELECT entity_id FROM securities WHERE security_id = ?",
                              [market.security_id(symbol)]).fetchone()  # fmt: skip
    assert ent == want
    (params,) = market.con.execute(
        "SELECT params FROM admin_log WHERE action = 'RULE:ISIN_ONE_CHAR_SYMBOL_NAME_MATCH'"
    ).fetchone()
    assert (json.loads(params)["stated_isin"], json.loads(params)["isin"]) == (stated, actual)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"J.KUMAR INFRAPROJECTS LIMITED", b"J.K. CEMENT LIMITED"),  # the name does not match
        (b"INE576101022", b"INE576101023"),  # two characters off
    ],
)
def test_x336_otherwise_stays_quarantined(market, tmp_path, old, new):
    promote(market.con, market.stage_day("20250228"))
    data = JKIL_Q3.read_bytes()
    assert old in data
    alt = tmp_path / JKIL_Q3.name
    alt.write_bytes(data.replace(old, new))  # a modified copy outside the fixtures
    r = promote(market.con, _stage(market, alt, datetime(2026, 2, 5, 11)))
    assert r.status == "QUARANTINED"
    assert market.con.execute("SELECT reason_code FROM quarantine_queue WHERE filing_id = ?",
                              [r.message]).fetchone() == ("UNKNOWN_ISIN",)  # fmt: skip
