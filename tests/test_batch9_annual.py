"""Batch 9: Reg. 34(1) annual report XBRL (REG34_ANNUAL) [X69-X76, C23].

Fixtures: TCS FY26 and FY25 consolidated, Eternal FY26 consolidated, ELIN FY25 standalone (all real, unmodified;
tampering in memory only). Screener parity for the same files is in tests/test_screener_parity.py.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials.fundamentals import annual_ratios, load_factbook
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.reg34_annual import (
    CONTINGENT_RULE,
    PROFILE,
    parse_annual_listing,
    parse_reg34_annual,
    symbol_from_file_name,
)
from financials.promoter import pit_fact, promote
from financials.scope import MIN_PERIOD_END_DATE
from financials.staging import stage_results_xbrl

CR = Decimal(10) ** 7
TCS26 = XBRL_DIR / "AR_XBRL_TCS_09082026012216.xml"
TCS25 = XBRL_DIR / "AR_XBRL_TCS_14082025184751.xml"
ETERNAL26 = XBRL_DIR / "AR_XBRL_ETERNAL_23092026175418.xml"
ELIN25 = XBRL_DIR / "AR_XBRL_ELIN_30092025131606.xml"
LISTING = FIXTURES / "annual" / "nse_annual-reports-xbrl_TCS_20261113.json"
MAR26, MAR25 = date(2026, 3, 31), date(2025, 3, 31)
FY26 = (date(2025, 4, 1), MAR26)


@pytest.fixture(scope="module")
def tcs26():
    return parse_reg34_annual(TCS26.read_bytes(), TCS26.name)


def _v(r, tag, start, end=None):
    return r.value(tag, start, end or start)


def test_listing_gives_symbol_type_and_broadcast_time():
    """X69: the listing JSON has standalone + consolidated rows per year with an IST broadcast timestamp."""
    rows = parse_annual_listing(LISTING.read_bytes())
    assert {(e.to_year, e.submission_type) for e in rows} == {
        (2026, "Standalone"), (2026, "Consolidated"), (2025, "Standalone"), (2025, "Consolidated")
    }  # fmt: skip
    cons26 = next(e for e in rows if (e.to_year, e.submission_type) == (2026, "Consolidated"))
    assert cons26.symbol == "TCS" and cons26.xbrl_url.endswith(TCS26.name)
    assert cons26.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None) == datetime(2026, 8, 8, 19, 52, 19)


@pytest.mark.parametrize(
    ("path", "scope", "fy_end", "rounding"),
    [(TCS26, "CONSOLIDATED", MAR26, "Crores"), (TCS25, "CONSOLIDATED", MAR25, "Crores"),
     (ETERNAL26, "CONSOLIDATED", MAR26, "Crores"), (ELIN25, "STANDALONE", MAR25, "Millions")],
    ids=lambda x: getattr(x, "stem", str(x)),
)  # fmt: skip
def test_annual_filings_parse_with_every_identity_holding(path, scope, fy_end, rounding):
    """X69: dispatcher routes the ICAI 2017 taxonomy (no entity namespace) to REG34_ANNUAL; P&L, cash-flow,
    balance-sheet and PPE identities hold for every in-scope year (no issues)."""
    r = parse_integrated_results(path.read_bytes(), path.name)
    assert r.profile == PROFILE and r.ok, r.issues
    assert (r.meta["scope"], r.meta["fy_end"], r.meta["level_of_rounding"]) == (scope, fy_end, rounding)
    assert r.meta["auditor_qualified"] is False
    assert all(f.period_end >= MIN_PERIOD_END_DATE for f in r.facts)
    assert all(f.period_months in (None, 12) for f in r.facts)


def test_cutoff_drops_pre_fy25_comparatives_silently():
    """C9: an FY25 filing's FY24 comparatives and FY24/FY23 balance sheets are ignored, not errors."""
    r = parse_reg34_annual(TCS25.read_bytes())
    assert r.ok and r.meta["in_scope_periods"] == [(date(2024, 4, 1), MAR25)]
    assert r.meta["ignored_pre_cutoff_facts"] > 50
    assert r.value("pat", date(2023, 4, 1), date(2024, 3, 31)) is None


def test_identity_without_isin_comes_from_file_name_and_cin(tcs26):
    """X70: no ISIN/Symbol in the annual XBRL; the NSE file name carries the symbol, the filing carries the CIN."""
    assert tcs26.meta["stated_isin"] is None
    assert tcs26.meta["stated_symbol"] == "TCS" == symbol_from_file_name(TCS26.name)
    assert tcs26.meta["stated_cin"] == "L22210MH1995PLC084781"


def test_ppe_schedule_classes_sum_to_gross_block(tcs26):
    """X71: top-level classes (summed over owned/leased sub-classes) + other = gross block; gross - accumulated
    depreciation = net PPE (₹ Cr, 31-Mar-2026)."""
    got = {f.canonical_tag: f.value / CR for f in tcs26.facts if f.period_end == MAR26 and f.source_element ==
           "PPE_SCHEDULE"}  # fmt: skip
    assert got == {
        "ppe_gross_block": Decimal("39208"), "ppe_accumulated_depreciation": Decimal("28176"),
        "ppe_gross_land": Decimal("1959"), "ppe_gross_buildings": Decimal("8821"),
        "ppe_gross_plant_equipment": Decimal("1039"), "ppe_gross_office_equipment": Decimal("3385"),
        "ppe_gross_computers": Decimal("15983"), "ppe_gross_furniture": Decimal("2432"),
        "ppe_gross_vehicles": Decimal("59"), "ppe_gross_other": Decimal("5530"),  # leasehold 3124 + other 2406
    }  # fmt: skip
    assert _v(tcs26, "ppe_net", MAR26) / CR == Decimal("11032") == Decimal("39208") - Decimal("28176")
    assert _v(tcs26, "cwip", MAR26) / CR == Decimal("2665")


def test_label_rules_leases_and_right_of_use(tcs26):
    """X37, X72: lease liabilities and ROU assets exist only as labelled 'Others' members."""
    assert _v(tcs26, "lease_liabilities_noncurrent", MAR26) / CR == Decimal("9453")
    assert _v(tcs26, "right_of_use_assets", MAR26) is not None
    assert {"LEASE_LIAB_NONCURRENT", "LEASE_LIAB_CURRENT", "RIGHT_OF_USE_ASSETS"} <= set(tcs26.meta["rules_applied"])


def test_note_disclosures(tcs26):
    """X73, X75: contingent liabilities and audit fees are non-dimensional; geographic revenue is on
    GeographicalAreasAxis where filed; R&D and royalty are absent for TCS (NULL, never 0)."""
    assert _v(tcs26, "contingent_liabilities", MAR26) / CR == Decimal("2330")
    assert _v(tcs26, "audit_fees", *FY26) is not None
    assert _v(tcs26, "rnd_expense", *FY26) is None and _v(tcs26, "royalty_expense", *FY26) is None


def test_contingent_zero_placeholder_rule():
    """X73: both contingent elements zero (Maruti, Info Edge FY26) = not disclosed. Reproduced in memory on TCS."""
    data = TCS26.read_bytes()
    for el in (b"ContingentLiabilities", b"ContingentLiabilitiesAndCommitments"):
        data, n = re.subn(
            rb"(<in-gaap:" + el + rb" [^>]*>|<ind-as:" + el + rb" [^>]*>)[0-9.]+(<)", rb"\g<1>0\g<2>", data
        )
        assert n >= 2
    r = parse_reg34_annual(data, TCS26.name)
    assert r.ok and CONTINGENT_RULE in r.meta["rules_applied"]
    assert _v(r, "contingent_liabilities", MAR26) is None


def test_broken_identity_is_an_issue():
    data = TCS26.read_bytes()
    pattern = rb'(<ind-as:ProfitBeforeTax [^>]*contextRef="FROM_Apr01_2025_TO_Mar31_2026"[^>]*>)[0-9.]+'
    data, n = re.subn(pattern, rb"\g<1>1.00", data, count=1)
    assert n == 1
    r = parse_reg34_annual(data, TCS26.name)
    assert not r.ok and {i.stage for i in r.issues} == {"IDENTITY"}


def _book(r):
    from financials.fundamentals import FactBook

    b = FactBook("e", r.meta["scope"])
    for f in r.facts:
        if f.period_type == "INSTANT":
            b.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
        else:
            b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return b


def test_annual_ratios_tcs_fy26(tcs26):
    """C23, pinned from the FY26 filing (FY25 comparatives give the prior year)."""
    out = annual_ratios(_book(tcs26), date(2026, 9, 30))
    assert out["annual_fy_end"] == MAR26
    assert out["piotroski_f"] == 5
    assert out["beneish_m"] == pytest.approx(Decimal("-2.3193"), abs=Decimal("0.0001"))
    assert out["capex_to_depreciation"] == pytest.approx(Decimal(4037) / Decimal(5560), abs=Decimal("0.0001"))
    assert out["cwip_to_gross_block"] == pytest.approx(Decimal(2665) / Decimal(39208), abs=Decimal("0.0001"))
    # ROTE = owners' PAT / (owners' equity - goodwill - other intangibles) = 49,210 / (107,240 - 9,108 - 176)
    assert out["rote"] == pytest.approx(Decimal(49210) / Decimal(97956), abs=Decimal("0.0001"))
    cl_nw = Decimal(2330) / Decimal(107240)
    assert out["contingent_liabilities_to_net_worth"] == pytest.approx(cl_nw, abs=Decimal("0.0001"))
    assert out["rnd_and_royalty_intensity"] is None


def test_scores_need_a_post_cutoff_prior_year():
    """FY25 alone: its prior year (FY24) is before the cutoff, so Piotroski and Beneish are NULL [C9]."""
    out = annual_ratios(_book(parse_reg34_annual(TCS25.read_bytes())), date(2025, 9, 30))
    assert out["annual_fy_end"] == MAR25
    assert out["piotroski_f"] is None and out["beneish_m"] is None
    assert out["capex_to_depreciation"] is not None


# ── promotion: identity, point in time, restated comparatives ────────────────────────────────────────

FY26_BROADCAST = datetime(2026, 8, 8, 19, 52, 19)  # 09-AUG-2026 01:22:19 IST [listing]


def _stage(m, data, name, ts):
    return stage_results_xbrl(m.vault, m.stage_root, data=data, source_url="https://nsearchives.nseindia.com/"
                              "corporate/xbrl/" + name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                              broadcast_ts_source="API_FIELD")  # fmt: skip


@pytest.fixture
def tcs_market(market):
    promote(market.con, market.stage_day("20251014"))
    return market


def test_annual_filing_promotes_by_symbol_and_restated_comparative_wins_only_after_its_broadcast(tcs_market):
    m = tcs_market
    r = promote(m.con, _stage(m, TCS26.read_bytes(), TCS26.name, FY26_BROADCAST))
    assert r.status == "PROMOTED", r
    ent = m.con.execute("SELECT entity_id FROM filing_meta WHERE accounting_profile = 'REG34_ANNUAL'").fetchone()[0]
    assert pit_fact(m.con, ent, "CONSOLIDATED", "pat_owners", *FY26, datetime(2026, 8, 1)) is None  # before broadcast
    assert pit_fact(m.con, ent, "CONSOLIDATED", "pat_owners", *FY26, datetime(2026, 8, 9)) / CR == Decimal("49210")
    fy25 = (date(2024, 4, 1), MAR25)
    original = pit_fact(m.con, ent, "CONSOLIDATED", "contingent_liabilities", MAR25, MAR25, datetime(2026, 8, 9))
    assert original / CR == Decimal("2511")
    # A later revision of the same annual report restates the FY25 comparative (in memory: a new blob/filing).
    revised = re.sub(rb'(<ind-as:ContingentLiabilities [^>]*contextRef="AS_OF_Mar31_2025"[^>]*>)25110000000.00(<)',
                     rb"\g<1>26000000000.00\g<2>", TCS26.read_bytes())  # fmt: skip
    assert revised != TCS26.read_bytes()
    r2 = promote(m.con, _stage(m, revised, TCS26.name, datetime(2026, 9, 1)))
    assert r2.status == "PROMOTED", r2
    assert pit_fact(m.con, ent, "CONSOLIDATED", "contingent_liabilities", MAR25, MAR25, datetime(2026, 8, 20)) == (
        original
    )
    assert pit_fact(m.con, ent, "CONSOLIDATED", "contingent_liabilities", MAR25, MAR25, datetime(2026, 9, 2)) / CR == (
        Decimal("2600")
    )
    assert pit_fact(m.con, ent, "CONSOLIDATED", "pat_owners", *fy25, datetime(2026, 9, 2)) / CR == Decimal("48553")
    book = load_factbook(m.con, ent, "CONSOLIDATED", datetime(2026, 9, 2))
    assert annual_ratios(book, date(2026, 9, 30))["piotroski_f"] == 5


def test_annual_filing_whose_symbol_predates_identity_history_is_quarantined(tcs_market):
    """X70: the symbol must resolve on the broadcast date; TCS FY25 was filed 14-Aug-2025, before this test
    market's first bhavcopy (identity history), so it quarantines instead of guessing."""
    m = tcs_market
    r = promote(m.con, _stage(m, TCS25.read_bytes(), TCS25.name, datetime(2025, 8, 14, 13, 17, 52)))
    assert r.status == "QUARANTINED"
    reason = m.con.execute("SELECT reason_code FROM quarantine_queue WHERE stage = 'IDENTITY'").fetchone()[0]
    assert reason == "UNKNOWN_SYMBOL"


@pytest.mark.parametrize("path", [TCS26, ETERNAL26, ELIN25], ids=lambda p: p.stem)
def test_fixed_asset_schedule_sub_rows_tie_out(path):
    """Mandate 4: Land/Building/P&M/Equipments/Computers/Furniture/Vehicles/Other sum to Gross Block, and
    Gross Block - Accumulated Depreciation = Net PPE, for every committed annual filing's year end."""
    from financials.statements.annual import fixed_asset_schedule, schedule_tie_out

    r = parse_reg34_annual(path.read_bytes(), path.name)
    st = fixed_asset_schedule(r, r.meta["fy_end"])
    assert st is not None
    class_gap, net_gap = schedule_tie_out(st)
    assert class_gap == 0
    tol = Decimal("0.5") * {"Crores": 10**7, "Millions": 10**6}[r.meta["level_of_rounding"]] * 3
    assert net_gap is not None and abs(net_gap) <= tol


def test_annual_balance_sheet_and_cash_flow_sub_rows_tie_out(tcs26):
    """Mandate 4: every statement's parts sum to its row (the 'other' line is the remainder), with the annual
    sub-rows populated: short-term loans, trade payables, investments purchased/sold."""
    from financials.statements.balance_sheet import balance_sheet
    from financials.statements.cashflow import cashflow

    bs, cf = balance_sheet(tcs26, MAR26), cashflow(tcs26, *FY26)
    for st in (bs, cf):
        for name, row in st.rows.items():
            if row.parts and row.value is not None and None not in row.parts.values():
                if name in ("Total Liabilities", "Total Assets"):
                    continue
                assert sum(row.parts.values(), Decimal(0)) == row.value, name
    assert bs.rows["Other Assets"].parts["Short term loans"] / CR == _v(tcs26, "loans_current", MAR26) / CR
    inv = cf.rows["Cash from Investing Activity"].parts
    assert inv["Investments purchased"] < 0 and inv["Investments sold"] > 0


def test_annual_ratios_reach_screener_features(tcs_market):
    """End to end: TCS Q2 FY27 Integrated Filing + FY26 annual XBRL promoted; compute_rows fills the annual
    columns for TCS from the annual facts, in the row's (consolidated) scope."""
    from financials.features import compute_rows

    m = tcs_market
    promote(m.con, m.stage_day("20261112"))
    q2 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
    assert promote(m.con, _stage(m, q2.read_bytes(), q2.name, datetime(2026, 10, 8, 12, 0))).status == "PROMOTED"
    assert promote(m.con, _stage(m, TCS26.read_bytes(), TCS26.name, FY26_BROADCAST)).status == "PROMOTED"
    (row,) = [r for r in compute_rows(m.con, date(2026, 11, 12)) if r["symbol"] == "TCS"]
    assert row["scope_used"] == "CONSOLIDATED" and row["annual_fy_end"] == MAR26
    assert row["piotroski_f"] == 5
    assert row["beneish_m"] == pytest.approx(-2.3193, abs=1e-4)
    assert row["cwip_to_gross_block"] == pytest.approx(2665 / 39208, abs=1e-4)
    assert row["rote"] == pytest.approx(49210 / 97956, abs=1e-4)
    assert row["rnd_and_royalty_intensity"] is None
