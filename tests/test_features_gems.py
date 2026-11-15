"""Batch D: ownership (ratio catalogue Batch 5) and the hidden-gem signals, hats and scores (docs/hidden_gems.md)
[features_gems].

Ownership values are read from the committed Reg. 31 fixtures themselves (a stdlib reader below), never from our
parser: HDFC Bank 2026-06-30 / 2026-09-30 (adjacent quarters), JSW Steel 2026-09-30 (pledge), Reliance 2025-03-31 /
2025-06-30 (percent-point filings, SHP18). Industries come from the committed Nifty 500 list. The core-profit
signals, ranks, scores and hats are pinned on synthetic books and cross-sections (no committed industrial company
has the same quarter a year apart yet, so the YoY signals are NULL on every fixture); the history-gated columns are
NULL on the fixtures and switch on with synthetic in-scope history.
"""

from __future__ import annotations

import csv
import random
import statistics
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials import features_gems as G
from financials.db import apply_schema, connect, declared_columns, insert_rows
from financials.dsl import ALIASES, load_saved_screens, run_saved_screen
from financials.features import compute_rows
from financials.fundamentals import FactBook, _add_months, building_blocks
from financials.parsers.shareholding import parse_shareholding
from financials.promoter import promote
from financials.sources import ROOT
from financials.staging import stage_shareholding

HDFC_JUN = XBRL_DIR / "SHP_1687801_03072026023346_WEB.xml"
HDFC_SEP = XBRL_DIR / "SHP_1733480_06102026050037_WEB.xml"
JSW_SEP = XBRL_DIR / "SHP_1743210_21102026055808_WEB.xml"
REL_MAR25 = XBRL_DIR / "SHP_198754_1421266_21042025041033_WEB.xml"
REL_JUN25 = XBRL_DIR / "SHP_1489727_21072025081003_WEB.xml"
NIFTY500 = FIXTURES / "indices" / "ind_nifty500list_20261113.csv"
XBRLI, XBRLDI = "http://www.xbrl.org/2003/instance", "http://xbrl.org/2006/xbrldi"


def _member_value(path, element: str, member: str) -> Decimal | None:
    """`element` on the CategoryOfShareholdersAxis member `member`, straight from the XML (stdlib)."""
    root = ET.parse(path).getroot()
    ctxs = {
        c.get("id")
        for c in root.iter(f"{{{XBRLI}}}context")
        if [m.text.split(":")[-1] for m in c.iter(f"{{{XBRLDI}}}explicitMember")
            if m.get("dimension", "").endswith("CategoryOfShareholdersAxis")] == [member]
        and len(list(c.iter(f"{{{XBRLDI}}}explicitMember"))) == 1
    }  # fmt: skip
    vals = {Decimal(el.text.strip()) for el in root if el.tag.endswith("}" + element) and el.get("contextRef") in ctxs}
    assert len(vals) <= 1, (element, member, vals)
    return vals.pop() if vals else None


TOTAL = "ShareholdingPatternMember"


def _promote_shp(m: Market, path, ts: datetime) -> None:
    st = stage_shareholding(m.vault, m.stage_root, data=path.read_bytes(),
                            source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + path.name,
                            fetched_at=FETCHED_AT, broadcast_ts=ts, broadcast_ts_source="API_FIELD")  # fmt: skip
    assert promote(m.con, st).status == "PROMOTED"


@pytest.fixture(scope="module")
def shp_market(tmp_path_factory):
    m = Market(tmp_path_factory.mktemp("gems_shp"))
    for d in ("20250919", "20261112"):
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"
    for path, ts in ((HDFC_JUN, datetime(2026, 7, 3, 9, 3, 54)), (HDFC_SEP, datetime(2026, 10, 6, 11, 30, 45)),
                     (JSW_SEP, datetime(2026, 10, 21, 9, 0)), (REL_MAR25, datetime(2025, 4, 21, 11, 0)),
                     (REL_JUN25, datetime(2025, 7, 21, 9, 0))):  # fmt: skip
        _promote_shp(m, path, ts)
    m.rows_nov = {r["symbol"]: r for r in compute_rows(m.con, date(2026, 11, 12))}
    m.rows_sep25 = {r["symbol"]: r for r in compute_rows(m.con, date(2025, 9, 19))}
    yield m
    m.con.close()


# ── ownership (Batch 5) ───────────────────────────────────────────────────────────────────────────────────────────


def test_fii_dii_mf_changes_between_adjacent_quarters(shp_market):
    r = shp_market.rows_nov["HDFCBANK"]
    sep, jun = (lambda e, mem: _member_value(HDFC_SEP, e, mem)), (lambda e, mem: _member_value(HDFC_JUN, e, mem))
    pct = "ShareholdingAsAPercentageOfTotalNumberOfShares"
    for col, member in (("fii_holding_change_qoq_pct", "InstitutionsForeignMember"),
                        ("dii_holding_change_qoq_pct", "InstitutionsDomesticMember"),
                        ("mf_holding_change_qoq_pct", "MutualFundsOrUTIMember")):  # fmt: skip
        assert r[col] == float(sep(pct, member) - jun(pct, member)), col
    assert r["fii_holding_change_qoq_pct"] == pytest.approx(0.394 - 0.4183)
    assert r["dii_holding_change_qoq_pct"] == pytest.approx(0.4363 - 0.4192)
    # The two add up to the combined change built earlier (fii_dii_qoq_change_pct, SHP14).
    assert r["fii_holding_change_qoq_pct"] + r["dii_holding_change_qoq_pct"] == pytest.approx(
        r["fii_dii_qoq_change_pct"]
    )
    assert r["inst_holding_pct"] == float(
        sep(pct, "InstitutionsForeignMember") + sep(pct, "InstitutionsDomesticMember")
    )
    assert r["mf_holding_pct"] == float(sep(pct, "MutualFundsOrUTIMember")) == 0.3188


def test_shareholder_counts_and_member_holdings(shp_market):
    r = shp_market.rows_nov["HDFCBANK"]
    holders = "NumberOfShareholders"
    now, prev = _member_value(HDFC_SEP, holders, TOTAL), _member_value(HDFC_JUN, holders, TOTAL)
    assert r["num_shareholders"] == now == 4807998
    assert r["num_shareholders_preceding_quarter"] == prev == 4532753
    assert r["num_shareholders_change_qoq_pct"] == pytest.approx(float(now / prev - 1))
    assert r["num_shareholders_1y_back"] is None  # no Sep-2025 pattern committed
    pct = "ShareholdingAsAPercentageOfTotalNumberOfShares"
    assert r["insurance_holding_pct"] == float(_member_value(HDFC_SEP, pct, G.INSURANCE_MEMBER)) == 0.0747
    assert r["retail_holding_pct"] == float(_member_value(HDFC_SEP, pct, G.RETAIL_MEMBER)) == 0.1087
    assert r["unpledged_promoter_holding_pct"] == 0.0  # no promoter group [SHP11]


def test_percent_point_filings_are_scaled_to_fractions(shp_market):
    """SHP18: Reliance's 2025 patterns state percentages in points (TOTAL = 100); member line items too."""
    r = shp_market.rows_sep25["RELIANCE"]
    pct = "ShareholdingAsAPercentageOfTotalNumberOfShares"
    assert _member_value(REL_JUN25, pct, TOTAL) == 100
    assert r["insurance_holding_pct"] == float(_member_value(REL_JUN25, pct, G.INSURANCE_MEMBER) / 100)
    assert r["retail_holding_pct"] == float(_member_value(REL_JUN25, pct, G.RETAIL_MEMBER) / 100)
    assert 0 < r["insurance_holding_pct"] < 0.2 and 0 < r["retail_holding_pct"] < 0.2
    assert r["num_shareholders"] == _member_value(REL_JUN25, "NumberOfShareholders", TOTAL)
    assert r["num_shareholders_preceding_quarter"] == _member_value(REL_MAR25, "NumberOfShareholders", TOTAL)
    assert r["mf_holding_pct"] == float(_member_value(REL_JUN25, pct, "MutualFundsOrUTIMember") / 100)
    # The 2022-09-30 taxonomy spells the member MutualFundsOrUtiMember; mapped since parser 0.10.4 [SHP20], so the
    # Mar-2025 pattern has an MF category and the Jun-2025 change is defined.
    mar = _member_value(REL_MAR25, pct, "MutualFundsOrUtiMember")
    assert mar == Decimal("9.21")
    assert r["mf_holding_change_qoq_pct"] == pytest.approx(
        float(_member_value(REL_JUN25, pct, "MutualFundsOrUTIMember") / 100 - mar / 100)
    )
    assert r["fii_holding_change_qoq_pct"] is not None


def test_unpledged_promoter_holding_and_under_owned(shp_market):
    r = shp_market.rows_nov["JSWSTEEL"]
    p = parse_shareholding(JSW_SEP.read_bytes())
    promoter = p.categories["PROMOTER"]
    pledge = Decimal(p.meta["promoter_pledged_shares"]) / promoter["shares"]
    assert r["promoter_pledge_pct"] == pytest.approx(float(pledge))
    assert r["unpledged_promoter_holding_pct"] == pytest.approx(float(promoter["pct"] * (1 - pledge)))
    assert r["under_owned"] is False  # promoter 44.3% < 50% and a pledge
    assert r["num_shareholders"] == _member_value(JSW_SEP, "NumberOfShareholders", TOTAL)
    assert r["fii_holding_change_qoq_pct"] is None  # Jun-2026 pattern not committed: no change, never a longer gap


def test_ownership_changes_need_the_immediately_preceding_quarter():
    own = {"dates": {1: date(2026, 9, 30), 2: date(2026, 3, 31)},
           "cats": {1: {"FII": (0.3, None), "TOTAL": (1, 100)}, 2: {"FII": (0.2, None), "TOTAL": (1, 90)}},
           "members": {}}  # fmt: skip
    out = G.ownership_columns({"fii_holding_pct": 0.3, "dii_holding_pct": 0.1}, own)
    assert out["fii_holding_change_qoq_pct"] is None and out["num_shareholders_change_qoq_pct"] is None
    assert out["num_shareholders"] == 100 and out["inst_holding_pct"] == pytest.approx(0.4)
    own["dates"][2] = date(2026, 6, 30)
    out = G.ownership_columns({"fii_holding_pct": 0.3, "dii_holding_pct": 0.1}, own)
    assert out["fii_holding_change_qoq_pct"] == pytest.approx(0.1)
    assert out["num_shareholders_change_qoq_pct"] == pytest.approx(100 / 90 - 1)
    own["dates"][3], own["cats"][3] = date(2025, 9, 30), {"TOTAL": (1, 70)}
    assert G.ownership_columns({}, own)["num_shareholders_1y_back"] == 70


# ── industry and cyclical flag ────────────────────────────────────────────────────────────────────────────────────


def _nifty500() -> dict[str, str]:
    with NIFTY500.open(encoding="utf-8") as fh:
        return {r["Symbol"]: r["Industry"] for r in csv.DictReader(fh)}


def test_curated_cyclicals_are_nifty500_members_outside_the_cyclical_industries():
    listed, curated = _nifty500(), G.curated_cyclicals()
    assert curated == {"GESHIP": "SHIPPING", "SCI": "SHIPPING"}
    for symbol in curated:
        assert symbol in listed and listed[symbol] not in G.CYCLICAL_INDUSTRIES, symbol
    assert set(listed.values()) >= G.CYCLICAL_INDUSTRIES  # the industry names exist in the NSE list verbatim


def test_industry_is_point_in_time_from_the_snapshot(full_market):
    listed = _nifty500()
    rows = {r["symbol"]: r for r in compute_rows(full_market.con, date(2026, 11, 12))}
    for sym, cyclical in (("JSWSTEEL", True), ("RELIANCE", True), ("HINDALCO", True), ("SCI", True),
                          ("GESHIP", True), ("TCS", False), ("HDFCBANK", False)):  # fmt: skip
        assert rows[sym]["industry"] == listed[sym], sym
        assert rows[sym]["cyclical_flag"] is cyclical, sym
    assert rows["ELIN"]["industry"] is None and rows["ELIN"]["cyclical_flag"] is None  # not a Nifty 500 member
    assert sum(r["industry"] is not None for r in rows.values()) >= 495
    # Before the snapshot date nothing is known (the list is dated 2026-11-12): no look-ahead.
    early = {r["symbol"]: r for r in compute_rows(full_market.con, date(2025, 10, 14))}
    assert all(r["industry"] is None for r in early.values())
    assert early["SCI"]["cyclical_flag"] is True  # the curated list is a standing classification


# ── core profit signals (synthetic books) ─────────────────────────────────────────────────────────────────────────

Q = Decimal


def _quarter(end: date) -> tuple[date, date]:
    return (_add_months(date(end.year, end.month, 1), -2), end)


def synthetic_book(quarters: dict[date, dict[str, Decimal]]) -> FactBook:
    book = FactBook("SYN", "CONSOLIDATED")
    for end, vals in quarters.items():
        for tag, v in vals.items():
            book.durations.setdefault(tag, {})[_quarter(end)] = v
    return book


ZERO, TAX = Q(0), Q("0.25")


def _q(sales, pbt, oi, exc=ZERO, tax_rate=TAX, nci=ZERO) -> dict[str, Decimal]:
    """One quarter: PBT = profit before exceptional + exceptional; EBITDA = PBT - exc + fin + dep - oi."""
    pat = pbt * (1 - tax_rate)
    return {"revenue_from_operations": sales, "pbt": pbt, "other_income": oi, "exceptional_items": exc,
            "profit_before_exceptional_and_tax": pbt - exc, "finance_costs": Q(10), "depreciation_amortisation": Q(20),
            "tax_expense": pbt * tax_rate, "pat": pat, "pat_owners": pat - nci}  # fmt: skip


SEP26, JUN26, SEP25, JUN25 = date(2026, 9, 30), date(2026, 6, 30), date(2025, 9, 30), date(2025, 6, 30)


def gsk_like() -> FactBook:
    """Principle 6 of hidden_gems.md: reported profit +30% while core profit (ex other income) grows +21%."""
    return synthetic_book({
        JUN25: _q(Q(1000), Q(200), Q(20)), SEP25: _q(Q(1000), Q(200), Q(20)),
        date(2025, 12, 31): _q(Q(1050), Q(210), Q(20)), date(2026, 3, 31): _q(Q(1100), Q(220), Q(20)),
        JUN26: _q(Q(1150), Q(225), Q(25)), SEP26: _q(Q(1210), Q(260), Q(42)),
    })  # fmt: skip


def _signals(book: FactBook, end: date, **row) -> tuple[dict, dict]:
    from financials import features_pl

    g = G.period_values(book, end, building_blocks(book, end))
    pl = features_pl.period_values(None, book, end)["cols"]
    base = {k: (float(v) if isinstance(v, Decimal) and k.endswith("_pct") else v) for k, v in pl.items()}
    base |= {"valuation_archetype": "INDUSTRIAL_SERVICES", "fundamentals_end": end, "symbol": "SYN"} | row
    return g, G.signal_columns(base, g, None, {}, None)


def test_core_profit_yoy_strips_other_income_and_flags_the_lift():
    g, s = _signals(gsk_like(), SEP26, market_cap=Q(100000), enterprise_value=Q(100000))
    assert g["core_q"] == {0: Q(218), -3: Q(200), -12: Q(180), -15: Q(180)}
    assert s["core_profit_latest_quarter"] == Q("218.00")
    assert s["core_profit_yoy_latest_q"] == pytest.approx(218 / 180 - 1)  # +21%
    assert s["core_profit_yoy_preceding_q"] == pytest.approx(200 / 180 - 1)
    # Reported owners' profit +30% (260 vs 200 PBT at the same 25% tax): a lift of 8.9 pp over core growth.
    assert s["other_income_lift_pp"] == pytest.approx(0.30 - (218 / 180 - 1))
    assert s["sales_growth_yoy_preceding_quarter_pct"] == pytest.approx(0.15)
    assert s["profit_growth_yoy_preceding_quarter_pct"] == pytest.approx(225 / 200 - 1)
    assert s["growth_sustained"] is True and s["growth_acceleration_pp"] == pytest.approx(0.21 - 0.15)
    assert s["operating_leverage"] == pytest.approx((218 / 180 - 1) / 0.21)
    assert s["forensic_clean"] is False  # lift >= 8 pp: the spike is caught per quarter


def test_pe_core_after_ttm_tax_on_the_owners_share():
    book = gsk_like()
    for p in book.durations["pat_owners"]:  # 10% NCI in every quarter
        book.durations["pat_owners"][p] = book.durations["pat"][p] * Q("0.9")
    g, s = _signals(book, SEP26, market_cap=Q(100000), enterprise_value=Q(120000))
    pre = Q(210 + 220 + 225 + 260) - Q(20 + 20 + 25 + 42)
    assert g["core_earnings_ttm"] == pre * Q("0.75") * Q("0.9")
    assert s["pe_core"] == pytest.approx(float(Q(100000) / (pre * Q("0.75") * Q("0.9"))))
    assert s["peg"] == pytest.approx(s["pe_core"] / (100 * s["core_profit_yoy_latest_q"]))  # quarter growth for now
    ebit = Q(210 + 220 + 225 + 260) + 40 - Q(20 + 20 + 25 + 42)  # PBEIT + finance costs - OI
    assert s["earnings_yield"] == pytest.approx(float(ebit / 120000))
    assert g["core_ttm_yoy"] is None  # TTM-on-TTM needs 8 in-scope quarters [C9]


def test_peg_switches_to_ttm_growth_with_eight_quarters():
    quarters = {}
    for i in range(8):  # Mar-2025 .. Dec-2026: 8 quarters, all in scope
        end = _add_months(date(2025, 3, 31), 3 * i)
        quarters[end] = _q(Q(1000 + 50 * i), Q(200 + 10 * i), Q(20))
    book = synthetic_book(quarters)
    end = date(2026, 12, 31)
    g, s = _signals(book, end, market_cap=Q(50000))
    now, before = sum(Q(180 + 10 * i) for i in range(4, 8)), sum(Q(180 + 10 * i) for i in range(4))
    assert g["core_ttm_yoy"] == now / before - 1
    assert s["peg"] == pytest.approx(s["pe_core"] / (100 * float(now / before - 1)))


def test_core_signals_are_null_on_a_loss_base_and_for_lenders():
    book = gsk_like()
    book.durations["pbt"][_quarter(SEP25)] = Q(10)  # core base 10 - 20 < 0
    _, s = _signals(book, SEP26, market_cap=Q(1))
    assert s["core_profit_yoy_latest_q"] is None and s["other_income_lift_pp"] is None and s["peg"] is None
    _, lender = _signals(gsk_like(), SEP26, market_cap=Q(1), valuation_archetype="FINANCIAL_LENDING")
    for c in ("core_profit_yoy_latest_q", "pe_core", "earnings_yield", "other_income_lift_pp", "opm_change_yoy_pp"):
        assert lender[c] is None, c


def test_opm_change_and_flags_from_row_inputs():
    _, s = _signals(gsk_like(), SEP26, opm_preceding_year_quarter_pct=0.2, cfo_to_ebitda=0.71, cwip_to_gross_block=0.3,
                    capex_to_depreciation=2.5, debt_to_equity=0.4, inst_holding_pct=0.1, promoter_holding_pct=0.6,
                    promoter_pledge_pct=0.0)  # fmt: skip
    opm = (Q(260) + 10 + 20 - Q(42)) / 1210  # EBITDA / sales
    assert s["opm_change_yoy_pp"] == pytest.approx(float(opm) - 0.2)
    assert s["cash_conversion_ok"] is True and s["capex_pay_off_signal"] is True and s["under_owned"] is True
    _, s = _signals(gsk_like(), SEP26, inst_holding_pct=0.1, promoter_holding_pct=0.6, debt_to_equity=1.5,
                    cwip_to_gross_block=0.3, capex_to_depreciation=2.5)  # fmt: skip
    assert s["under_owned"] is None and s["capex_pay_off_signal"] is False and s["cash_conversion_ok"] is None


@pytest.mark.parametrize(
    "change, clean",
    [({}, True), ({"restatement_suspected": True}, False), ({"beneish_m": -1.78}, False), ({"beneish_m": -2.5}, True),
     ({"promoter_pledge_pct": 0.05}, False), ({"auditor_resignations_90d": 1}, False),
     ({"fraud_or_default_90d": 1}, False), ({"other_income_lift_pp": 0.08}, False),
     ({"other_income_lift_pp": 0.0799}, True), ({"other_income_to_pbt": 0.3}, False),
     ({"other_income_to_pbt": 0.3, "valuation_archetype": "FINANCIAL_LENDING"}, True),
     ({"fundamentals_end": None}, None)],
)  # fmt: skip
def test_forensic_clean(change, clean):
    base = {"fundamentals_end": SEP26, "valuation_archetype": "INDUSTRIAL_SERVICES", "auditor_resignations_90d": 0,
            "fraud_or_default_90d": 0, "beneish_m": None, "other_income_to_pbt": 0.1}  # fmt: skip
    assert G.forensic_clean(base | change) is clean


# ── history-gated columns ─────────────────────────────────────────────────────────────────────────────────────────


def fy_book(first_fy_end: int, last_fy_end: int) -> FactBook:
    book = FactBook("SYN", "CONSOLIDATED")
    for y in range(first_fy_end, last_fy_end + 1):
        p, end = (date(y - 1, 4, 1), date(y, 3, 31)), date(y, 3, 31)
        k = y - first_fy_end
        for tag, v in {"revenue_from_operations": 1000 + 100 * k, "pbt": 200 + 10 * k, "other_income": 20,
                       "profit_before_exceptional_and_tax": 200 + 10 * k, "finance_costs": 10,
                       "depreciation_amortisation": 30, "pat": 150 + 5 * k, "tax_expense": 50}.items():  # fmt: skip
            book.durations.setdefault(tag, {})[p] = Q(v)
        book.instants.setdefault("total_equity", {})[end] = Q(900 + 50 * k)
        book.instants.setdefault("borrowings_noncurrent", {})[end] = Q(100)
        book.instants.setdefault("borrowings_current", {})[end] = Q(0)
    return book


def test_stability_ratios_switch_on_with_five_in_scope_fiscal_years():
    book = fy_book(2025, 2029)
    end = date(2029, 3, 31)
    ebit = [Q(200 + 10 * k + 10 - 20) for k in range(5)]  # PBEIT + finance costs - other income (EBITDA - D&A)
    roce = [float(e / (900 + 50 * k + 100)) for k, e in enumerate(ebit)]
    assert G.roce_stability(book, end) == pytest.approx(1 - statistics.pstdev(roce) / statistics.fmean(roce))
    opm = [float((e + 30) / (1000 + 100 * k)) for k, e in enumerate(ebit)]
    assert G.opm_stability(book, end) == pytest.approx(1 - statistics.pstdev(opm) / statistics.fmean(opm))
    # FY26-FY29 only (or FY25 out of the window's reach): NULL, never a 4-year number.
    assert G.roce_stability(fy_book(2026, 2029), end) is None
    assert G.opm_stability(fy_book(2024, 2028), date(2028, 3, 31)) is None  # FY24 is before the cutoff [C9]


def test_pe_vs_own_median_needs_five_years_of_stored_pe():
    assert G.pe_history_gate(date(2029, 9, 30)) is None
    assert G.pe_history_gate(date(2029, 10, 1)) == date(2024, 10, 1)
    con = connect()
    apply_schema(con)
    rows = []
    for i, d in enumerate((date(2024, 10, 1), date(2026, 1, 1), date(2028, 1, 1), date(2029, 9, 30))):
        rows.append({"as_of_date": d, "security_id": "S1", "entity_id": "E", "symbol": "A", "series": "EQ",
                     "pe": 10.0 + i})  # fmt: skip
        rows.append({"as_of_date": d, "security_id": "S2", "entity_id": "E", "symbol": "B", "series": "EQ",
                     "pe": None if i == 0 else 20.0})  # fmt: skip
    insert_rows(con, "screener_features_history", rows)
    assert G.pe_medians(con, date(2029, 10, 1)) == {"S1": 11.5}  # S2's history starts too late
    assert G.pe_medians(con, date(2029, 9, 30)) == {}
    out = G.signal_columns({"pe": 23.0, "valuation_archetype": "INDUSTRIAL_SERVICES"}, None, None, {}, 11.5)
    assert out["pe_vs_own_5y_median"] == pytest.approx(2.0)


def test_history_gated_columns_are_null_on_the_fixtures(full_market):
    rows = compute_rows(full_market.con, date(2026, 11, 12))
    for c in ("roce_stability_5y", "opm_stability_5y", "pe_vs_own_5y_median"):
        assert all(r[c] is None for r in rows), c


# ── cross-section (synthetic) ─────────────────────────────────────────────────────────────────────────────────────


def _row(sym: str, **kw) -> dict:
    base = dict.fromkeys(G.CROSS_INPUTS) | {"security_id": sym, "symbol": sym}
    base.update(valuation_archetype="INDUSTRIAL_SERVICES", forensic_clean=True, cyclical_flag=False)
    return base | kw


def test_magic_formula_ranks_within_the_gated_non_financial_universe():
    rows = [_row("A", earnings_yield=0.10, roce=0.30), _row("B", earnings_yield=0.12, roce=0.20),
            _row("C", earnings_yield=0.05, roce=0.40), _row("D", earnings_yield=0.20, roce=0.10),
            _row("BANK", earnings_yield=0.5, roce=0.5, valuation_archetype="FINANCIAL_LENDING"),
            _row("DIRTY", earnings_yield=0.5, roce=0.5, forensic_clean=False), _row("NOEY", roce=0.5)]  # fmt: skip
    G.cross_section(rows)
    rank = {r["symbol"]: r["magic_formula_rank"] for r in rows}
    # EY ranks D1 B2 A3 C4; ROCE ranks C1 A2 B3 D4; sums A5 B5 C5 D5 -> ties broken by EY rank: D, B, A, C
    assert rank == {"D": 1, "B": 2, "A": 3, "C": 4, "BANK": None, "DIRTY": None, "NOEY": None}
    top = {r["symbol"] for r in rows if r["hat_magic_formula"]}
    assert top == {"A", "B", "C"}  # ROCE >= 15% (D has 10%)


def test_magic_formula_hat_takes_the_top_fifteen():
    rows = [_row(f"S{i:02}", earnings_yield=0.01 * i, roce=0.15 + 0.01 * i) for i in range(1, 21)]
    G.cross_section(rows)
    assert {r["symbol"] for r in rows if r["hat_magic_formula"]} == {f"S{i:02}" for i in range(6, 21)}


def test_gem_score_is_a_weighted_clipped_z_blend():
    rows = [_row("A", roce=0.30, earnings_yield=0.08, sales_growth_yoy_quarter_pct=0.2,
                 sales_growth_yoy_preceding_quarter_pct=0.15, inst_holding_pct=0.1, cfo_to_ebitda=0.9,
                 opm_change_yoy_pp=0.01),
            _row("B", roce=0.10, earnings_yield=0.04, sales_growth_yoy_quarter_pct=0.05,
                 sales_growth_yoy_preceding_quarter_pct=0.02, inst_holding_pct=0.5, cfo_to_ebitda=0.5,
                 opm_change_yoy_pp=-0.02),
            _row("C", roce=5.0, earnings_yield=0.06),  # ROCE clipped to 0.75; missing inputs score 0
            _row("CYC", roce=0.5, earnings_yield=0.2, cyclical_flag=True)]  # fmt: skip
    G.cross_section(rows)
    by = {r["symbol"]: r for r in rows}
    assert by["CYC"]["gem_score"] is None

    def z(xs, x):
        return (x - statistics.fmean(xs)) / statistics.pstdev(xs)

    roce, ey = [0.30, 0.10, 0.75], [0.08, 0.04, 0.06]
    total = sum(w for w, _ in G.GEM_WEIGHTS.values())
    expect_c = (1.0 * z(roce, 0.75) + 1.2 * z(ey, 0.06)) / total
    assert by["C"]["gem_score"] == pytest.approx(expect_c)
    expect_a = (1.0 * z(roce, 0.30) + 1.0 * 1 + 1.2 * z(ey, 0.08) + 0.8 * 1 + 0.6 * 1 + 0.6 * 1) / total
    assert by["A"]["gem_score"] == pytest.approx(expect_a)  # two-point inputs: z = +-1
    assert by["A"]["gem_score"] > by["B"]["gem_score"]


def test_universe_medians_and_hats_passed():
    rows = [_row("A", pe_core=10.0, market_cap=Q(100)), _row("B", pe_core=20.0, market_cap=Q(300)),
            _row("C", pe_core=40.0, market_cap=Q(200)),
            _row("BANK", pe_core=1.0, market_cap=Q(1), valuation_archetype="FINANCIAL_LENDING")]  # fmt: skip
    G.cross_section(rows)
    assert {r["pe_core_universe_median"] for r in rows} == {20.0}
    assert {r["market_cap_universe_median"] for r in rows} == {Q("200.00")}
    assert all(r["hats_passed"] == sum(r[h] is True for h in G.HAT_COLUMNS) for r in rows)


# ── saved screens = hat booleans ──────────────────────────────────────────────────────────────────────────────────

CR = Q(10_000_000)
PASSING = {  # one crafted row per hat, every condition met
    "hat_hidden_compounder": dict(market_cap=5000 * CR, inst_holding_pct=0.2, roce=0.25, growth_sustained=True,
                                  opm_change_yoy_pp=0.0, cfo_to_ebitda=0.9, debt_to_equity=0.2, pe_core=25.0,
                                  return_6m=0.1, earnings_yield=0.05),
    "hat_quality_fair_price": dict(roce=0.25, roe=0.2, debt_to_equity=0.1, cfo_to_ebitda=0.8, pe_core=5.0,
                                   core_profit_yoy_latest_q=0.2, market_cap=100 * CR),
    "hat_garp": dict(sales_growth_yoy_quarter_pct=0.25, sales_growth_yoy_preceding_quarter_pct=0.2,
                     core_profit_yoy_latest_q=0.4, roce=0.2, peg=0.8),
    "hat_turnaround": dict(opm_change_yoy_pp=0.05, sales_growth_yoy_quarter_pct=0.12, pe=20.0, return_6m=0.05),
    "hat_under_owned": dict(under_owned=True, roce=0.2, core_profit_yoy_latest_q=0.2, market_cap=1 * CR,
                            pe_core=60.0),
    "hat_cash_machine": dict(fcf_to_pat=0.9, roic=0.3, price_to_cfo=20.0, working_capital_days=10.0),
    "hat_fallen_quality": dict(dist_52w_high=-0.4, roce=0.2, debt_to_equity=0.1, core_profit_yoy_latest_q=0.0),
    "hat_capex_pay_off": dict(capex_pay_off_signal=True, roce=0.16, sales_growth_yoy_quarter_pct=0.11),
    "hat_cyclical": dict(cyclical_flag=True, roce=0.16, sales_growth_yoy_quarter_pct=0.16),
    "hat_lender": dict(valuation_archetype="FINANCIAL_LENDING", roa=0.02, pb=2.0, profit_growth_yoy_quarter_pct=0.2),
}  # fmt: skip


def _random_rows(n: int, seed: int = 7) -> list[dict]:
    rnd = random.Random(seed)

    def maybe(x):
        return None if rnd.random() < 0.1 else x

    rows = []
    for i in range(n):
        rows.append(_row(
            f"R{i:03}", valuation_archetype=rnd.choice(["INDUSTRIAL_SERVICES"] * 4 + ["FINANCIAL_LENDING", "INSURANCE",
                                                                                     None]),
            forensic_clean=rnd.choice([True, True, True, False, None]), cyclical_flag=rnd.choice([True, False, None]),
            market_cap=maybe(Q(rnd.randint(500, 100000)) * CR), inst_holding_pct=maybe(rnd.uniform(0, 0.6)),
            roce=maybe(rnd.uniform(-0.1, 0.5)), roe=maybe(rnd.uniform(-0.1, 0.4)), roic=maybe(rnd.uniform(0, 0.5)),
            growth_sustained=rnd.choice([True, False, None]), opm_change_yoy_pp=maybe(rnd.uniform(-0.05, 0.08)),
            cfo_to_ebitda=maybe(rnd.uniform(0, 1.5)), debt_to_equity=maybe(rnd.uniform(0, 2)),
            pe_core=maybe(rnd.uniform(5, 80)), pe=maybe(rnd.uniform(5, 80)), pb=maybe(rnd.uniform(0.5, 5)),
            return_6m=maybe(rnd.uniform(-0.4, 0.6)), earnings_yield=maybe(rnd.uniform(-0.05, 0.2)),
            sales_growth_yoy_quarter_pct=maybe(rnd.uniform(-0.1, 0.4)),
            sales_growth_yoy_preceding_quarter_pct=maybe(rnd.uniform(-0.1, 0.4)),
            core_profit_yoy_latest_q=maybe(rnd.uniform(-0.3, 0.6)), peg=maybe(rnd.uniform(0.2, 3)),
            profit_growth_yoy_quarter_pct=maybe(rnd.uniform(-0.3, 0.6)), under_owned=rnd.choice([True, False, None]),
            fcf_to_pat=maybe(rnd.uniform(0, 1.5)), price_to_cfo=maybe(rnd.uniform(5, 60)),
            working_capital_days=maybe(rnd.uniform(-20, 120)), dist_52w_high=maybe(rnd.uniform(-0.6, 0)),
            piotroski_f=maybe(rnd.randint(0, 9)), capex_pay_off_signal=rnd.choice([True, False, None]),
            roa=maybe(rnd.uniform(0, 0.03)), gnpa_pct=maybe(rnd.uniform(0, 0.06)),
        ))  # fmt: skip
    for hat, kw in PASSING.items():
        rows.append(_row(f"P_{hat}", **kw))
    return rows


def test_every_saved_screen_matches_its_hat_boolean():
    rows = _random_rows(600)
    G.cross_section(rows)
    con = connect()
    apply_schema(con)
    keep = set(G.CROSS_INPUTS) | set(G.CROSS_COLUMNS)
    insert_rows(con, "screener_features", [
        {"as_of_date": date(2026, 11, 13), "entity_id": r["symbol"], "series": "EQ",
         **{k: v for k, v in r.items() if k in keep}} for r in rows])  # fmt: skip
    screens = load_saved_screens()
    assert {s.hat_column for s in screens.values()} == set(G.HAT_COLUMNS)
    for s in screens.values():
        got = {r["symbol"] for r in run_saved_screen(con, s.name, limit=10_000 if s.limit == 500 else None)}
        want = {r["symbol"] for r in rows if r[s.hat_column] is True}
        assert got == want, s.name
        assert f"P_{s.hat_column}" in got or s.hat_column == "hat_magic_formula", s.name


def test_refresh_cross_section_rewrites_the_stored_day():
    rows = _random_rows(80, seed=3)
    con = connect()
    apply_schema(con)
    day = date(2026, 11, 13)
    stored = [{"as_of_date": day, "entity_id": r["symbol"], "series": "EQ",
               **{k: v for k, v in r.items() if k in G.CROSS_INPUTS}} for r in rows]  # fmt: skip
    insert_rows(con, "screener_features_history", stored)
    G.refresh_cross_section(con, day)
    G.cross_section(rows)
    cur = con.execute(f"SELECT symbol, {', '.join(G.CROSS_COLUMNS)} FROM screener_features_history")
    names = [d[0] for d in cur.description]
    got = {r[0]: dict(zip(names, r, strict=True)) for r in cur.fetchall()}
    for r in rows:
        for c in G.CROSS_COLUMNS:
            assert got[r["symbol"]][c] == (pytest.approx(r[c]) if isinstance(r[c], float) else r[c]), (r["symbol"], c)


# ── schema, aliases, saved screens file ───────────────────────────────────────────────────────────────────────────


def test_every_column_is_in_both_tables_in_order_and_has_an_alias():
    cols = declared_columns()
    for t in ("screener_features", "screener_features_history"):
        names = [c for c, _ in cols[t]]
        assert names[-len(G.GEM_COLUMNS) :] == list(G.GEM_COLUMNS), t
    used = " ".join(sql for sql, _ in ALIASES.values())
    assert [c for c in G.GEM_COLUMNS if c not in used and c != "industry"] == []
    for name in ("fii holding", "change in fii holding", "dii holding", "change in dii holding",
                 "unpledged promoter holding", "public holding", "number of shareholders"):  # fmt: skip
        assert name in ALIASES, name


def test_saved_screens_file():
    path = ROOT / "reference" / "saved_screens.csv"
    with path.open(encoding="utf-8") as fh:
        names = [r["name"] for r in csv.DictReader(fh)]
    assert len(names) == len(set(names)) == len(G.HATS) == 11
    assert all(s.expression.startswith("Forensic clean = 1") for s in load_saved_screens().values())
