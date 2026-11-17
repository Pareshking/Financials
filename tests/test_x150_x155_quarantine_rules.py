"""Named rules X150-X155 (parser 0.10.5), each from the open filing-side quarantine of 2026-11-17.

X150 ACTUAL_ROUNDING_IS_RUPEES: Reg. 34 `LevelOfRoundingUsedInFinancialStatements = Actual` (23 annual filings).
X151 UNDECLARED_PRE_CUTOFF_CONTEXT: IncomeTaxesPaidRefund tagged for the year before the comparative (14 findings).
X152 IRREGULAR_COMPARATIVE_STUB: the comparative is the company's first period from incorporation (5 filings).
X153 EP_EXPENDITURE_FACE_LINE: E&P expenditure is a separate face-of-P&L line (11 EXPENSE_COMPONENTS findings).
X154 SHP_EXCHANGE_SPECIFIC_TAXONOMY: BSE Ltd's Reg. 31 on SEBI's exchange-specific taxonomy (5 filings).
X155 INS_OTHER_ADJUSTMENTS: Niva Bupa's `OtherAdjustments` inside insurance service expenses (2 findings).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.parsers.indas_corp import _check_identities
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.reg34_annual import _undeclared_pre_cutoff, parse_reg34_annual
from financials.parsers.shareholding import parse_shareholding

CHOICE = XBRL_DIR / "AR_XBRL_CHOICEIN_28102025170241.xml"
ALOK = XBRL_DIR / "AR_XBRL_ALOKINDS_14082026191942.xml"
ENRIN = XBRL_DIR / "AR_XBRL_ENRIN_13032026115920.xml"
ABLBL = XBRL_DIR / "AR_XBRL_ABLBL_01122025184209.xml"
PREMIER = XBRL_DIR / "AR_XBRL_PREMIERENE_28012026112034.xml"
BSE_MAR26 = XBRL_DIR / "SHP_1652898_17042026122104_WEB.xml"
BSE_JUN25 = XBRL_DIR / "SHP_13769_15072025060551_WEB.xml"
NIVA = XBRL_DIR / "IF_INS_COM_IND_AS_19757_WebXMLFile_20261104_181240292.xml"
FY25 = (date(2024, 4, 1), date(2025, 3, 31))


def _annual(path, data: bytes | None = None):
    return parse_reg34_annual(data if data is not None else path.read_bytes(), path.name)


def _value(r, tag, start, end):
    return next((f.value for f in r.facts if f.canonical_tag == tag and (f.period_start, f.period_end) == (start, end)),
                None)  # fmt: skip


# ── X150 ─────────────────────────────────────────────────────────────────────


def test_x150_actual_rounding_is_rupees():
    """Choice International FY25 standalone declares `Actual` (MCA enumeration: Actual, Thousands, Lakhs, Millions,
    Crores, Billions); its amounts are whole rupees and every identity ties to the rupee."""
    raw = CHOICE.read_bytes()
    assert b">Actual<" in raw
    r = _annual(CHOICE)
    assert not r.issues
    assert r.meta["level_of_rounding"] == "Rupees"
    assert "ACTUAL_ROUNDING_IS_RUPEES" in r.meta["rules_applied"]
    assert _value(r, "revenue_from_operations", *FY25) == Decimal("244583569")
    assert _value(r, "pat", *FY25) == Decimal("83399574")


def test_x150_other_unknown_rounding_still_quarantines():
    data = CHOICE.read_bytes().replace(b">Actual<", b">Hundreds<")
    r = _annual(CHOICE, data)
    assert [i.reason_code for i in r.issues] == ["UNKNOWN_ROUNDING"]


# ── X151 ─────────────────────────────────────────────────────────────────────


def test_x151_undeclared_pre_cutoff_context_is_ignored():
    """Alok Industries FY26 consolidated tags IncomeTaxesPaidRefund in D2024 (2023-04-01..2024-03-31), a year no
    DateOfStart/EndOfReportingPeriod declares (FY25, FY26 are declared); it was CONTEXT_CONFLICT, now ignored."""
    raw = ALOK.read_bytes()
    assert b'id="D2024"' in raw
    r = _annual(ALOK)
    assert not r.issues
    assert "UNDECLARED_PRE_CUTOFF_CONTEXT" in r.meta["rules_applied"]
    assert r.meta["declared_periods"] == [FY25, (date(2025, 4, 1), date(2026, 3, 31))]
    taxes = {(f.period_start, f.period_end): f.value for f in r.facts if f.canonical_tag == "income_taxes_paid_total"}
    assert taxes == {FY25: Decimal("270900000"), (date(2025, 4, 1), date(2026, 3, 31)): Decimal("177300000")}


def test_x151_only_pre_cutoff_contexts_before_every_declared_period():
    declared = {FY25, (date(2025, 4, 1), date(2026, 3, 31))}
    assert _undeclared_pre_cutoff((date(2023, 4, 1), date(2024, 3, 31)), declared)
    assert not _undeclared_pre_cutoff((date(2025, 4, 1), date(2025, 9, 30)), declared)  # in scope: conflict
    assert not _undeclared_pre_cutoff((date(2024, 4, 1), date(2024, 12, 31)), declared)  # overlaps FY25
    assert not _undeclared_pre_cutoff((date(2023, 4, 1), date(2024, 3, 31)), set())


# ── X152 ─────────────────────────────────────────────────────────────────────


def test_x152_comparative_stub_is_dropped_current_year_kept():
    """Siemens Energy India FY25 (Oct-Sep): the comparative is 2024-02-07..2024-09-30 (incorporation to the first
    year end); the current year 2024-10-01..2025-09-30 is kept."""
    r = _annual(ENRIN)
    assert not r.issues
    assert "IRREGULAR_COMPARATIVE_STUB" in r.meta["rules_applied"]
    fy = (date(2024, 10, 1), date(2025, 9, 30))
    assert r.meta["declared_periods"] == [fy]
    assert r.meta["stub_periods"] == [(date(2024, 2, 7), date(2024, 9, 30))]
    assert _value(r, "revenue_from_operations", *fy) == Decimal("78267000000.00")
    assert _value(r, "pat", *fy) == Decimal("11001000000.00")
    assert not [f for f in r.facts if f.period_start == date(2024, 2, 7)]


def test_x152_an_only_period_stub_still_quarantines():
    """Aditya Birla Lifestyle Brands FY25: the only declared period is 2024-04-09..2025-03-31 (first period after
    incorporation); nothing regular remains, so the filing stays quarantined."""
    r = _annual(ABLBL)
    assert [i.reason_code for i in r.issues] == ["IRREGULAR_PERIOD", "NO_DECLARED_PERIOD"]


# ── X153 ─────────────────────────────────────────────────────────────────────


def test_x153_ep_expenditure_closes_the_expense_identity():
    """Premier Energies FY25 standalone: the seven components are 62.264 Cr short of Expenses, exactly the filed
    ExpenditureOnProductionTransportationAndOtherExpenditurePertainingToExplorationAndProductionActivities."""
    r = _annual(PREMIER)
    assert not r.issues
    assert {"rule": "EP_EXPENDITURE_FACE_LINE", "period": ["2024-04-01", "2025-03-31"],
            "ep_expenditure": "622640000"} in r.meta["rules_applied"]  # fmt: skip
    assert _value(r, "ep_expenditure", *FY25) == Decimal("622640000")
    assert _value(r, "total_expenses", *FY25) == Decimal("9384040000")  # as filed, nothing added


def test_x153_a_different_gap_still_fails():
    r = _annual(PREMIER)
    r.facts = [replace(f, value=f.value + 10_000_000) if f.canonical_tag == "ep_expenditure" else f for f in r.facts]
    r.issues, r.meta["rules_applied"] = [], []
    r.meta["quarter_period"] = r.meta["ytd_period"] = FY25
    _check_identities(r)
    assert [i.reason_code for i in r.issues] == ["EXPENSE_COMPONENTS"]


# ── X154 ─────────────────────────────────────────────────────────────────────


def test_x154_exchange_specific_shp_taxonomy():
    """BSE Ltd 2026-03-31 on `SHP_Exchange_Specific/2025-10-31/in-capmkt`: no promoter, 100% public."""
    r = parse_shareholding(BSE_MAR26.read_bytes())
    assert r.ok
    assert "SHP_EXCHANGE_SPECIFIC_TAXONOMY" in r.meta["rules_applied"]
    assert r.meta["stated_isin"] == "INE118H01025" and r.meta["as_of_date"] == date(2026, 3, 31)
    assert r.categories["TOTAL"]["shares"] == r.categories["PUBLIC"]["shares"] == Decimal("407884077")
    assert r.categories["FII"]["pct"] == Decimal("0.1942")


def test_x154_trading_members_as_non_promoter_non_public():
    """BSE Ltd 2025-06-30 files trading members and their associates (83,559,827 shares) as non-promoter
    non-public; promoter + public + NPNP = total exactly (SHP8); percent points scaled to fractions (SHP18)."""
    r = parse_shareholding(BSE_JUN25.read_bytes())
    assert r.ok
    c = r.categories
    assert c["PUBLIC"]["shares"] + c["NON_PROMOTER_NON_PUBLIC"]["shares"] == c["TOTAL"]["shares"] == 406129077
    assert c["PUBLIC"]["pct"] == Decimal("0.7943")


def test_x154_shp_promotion_closes_the_old_unknown_taxonomy_finding(market):
    from financials.promoter import _quarantine, promote
    from financials.staging import stage_shareholding

    promote(market.con, market.stage_day("20250228"))
    url = "https://nsearchives.nseindia.com/corporate/xbrl/" + BSE_MAR26.name
    kw = dict(data=BSE_MAR26.read_bytes(), source_url=url,
              fetched_at=datetime(2026, 11, 14, 3, 27), broadcast_ts=datetime(2026, 4, 17, 6, 51),
              broadcast_ts_source="API_FIELD")  # fmt: skip
    first = stage_shareholding(market.vault, market.stage_root, **kw)
    ns = "https://www.sebi.gov.in/xbrl/SHP_Exchange_Specific/2025-10-31/in-capmkt"
    _quarantine(market.con, stage="PARSE", reason_code="UNKNOWN_TAXONOMY", filing_id=first.name,
                details={"namespaces": [ns]})  # fmt: skip
    again = stage_shareholding(market.vault, market.stage_root, run_suffix="0.10.5", **kw)
    assert promote(market.con, again).status == "PROMOTED"
    open_, note = market.con.execute(
        "SELECT count(*) FILTER (WHERE resolved_at IS NULL), any_value(resolution_note) FROM quarantine_queue "
        "WHERE filing_id = ? AND reason_code = 'UNKNOWN_TAXONOMY'", [first.name]).fetchone()  # fmt: skip
    assert open_ == 0 and "SHP_EXCHANGE_SPECIFIC_TAXONOMY" in note


# ── X155 ─────────────────────────────────────────────────────────────────────


def test_x155_insurance_service_other_adjustments():
    """Niva Bupa Q2 FY27 (first Ind AS 117 quarter): claims 1,533.35 + employees 217.56 + commission 565.78 +
    other 176.08 + acquisition amortisation 704.48 + OtherAdjustments (949.08) = 2,248.17 Cr = filed
    InsuranceServiceExpenses; the adjustments are labelled (acquisition cash flows, onerous release, costs not
    directly attributable) on OtherAdjustmentsAxis."""
    r = parse_integrated_results(NIVA.read_bytes(), NIVA.name)
    assert r.profile == "INDAS_INSURANCE" and not r.issues
    q, h1 = (date(2026, 7, 1), date(2026, 9, 30)), (date(2026, 4, 1), date(2026, 9, 30))
    assert _value(r, "insurance_service_other_adjustments", *q) == Decimal("-9490800000")
    assert _value(r, "insurance_service_other_adjustments", *h1) == Decimal("-17899400000")
    assert _value(r, "insurance_service_expenses", *q) == Decimal("22481700000")


# ── X156 ─────────────────────────────────────────────────────────────────────

KIMS_JUN26 = XBRL_DIR / "SHP_1697747_21072026110424_WEB.xml"


def test_x156_shp_company_name_lets_x88_resolve_a_garbled_isin(market):
    """KIMS 2026-06-30 states ISIN INE007C01025 (no security has it; KIMS is INE967H01025, another issuer code).
    The Reg. 31 parser now passes NameOfTheCompany, so X88's name test ("KRISHNA INSTITUTE OF MEDICAL SCIENCES
    LIMITED" vs the exchange's "KRISHNA INST OF MED SCI L") applies to shareholding as it does to results."""
    from financials.promoter import promote
    from financials.staging import stage_shareholding

    data = KIMS_JUN26.read_bytes()
    assert b">INE007C01025<" in data
    assert parse_shareholding(data).meta["company_name"] == "KRISHNA INSTITUTE OF MEDICAL SCIENCES LIMITED"
    promote(market.con, market.stage_day("20250228"))
    st = stage_shareholding(market.vault, market.stage_root, data=data,
                            source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + KIMS_JUN26.name,
                            fetched_at=datetime(2026, 11, 14, 4, 8), broadcast_ts=datetime(2026, 7, 21, 5, 34),
                            broadcast_ts_source="API_FIELD")  # fmt: skip
    r = promote(market.con, st)
    assert r.status == "PROMOTED", r
    ent = market.con.execute("SELECT entity_id FROM shareholding_meta WHERE filing_id = ?", [r.message]).fetchone()
    want = market.con.execute("SELECT entity_id FROM securities WHERE security_id = ?",
                              [market.security_id("KIMS")]).fetchone()  # fmt: skip
    assert ent == want
