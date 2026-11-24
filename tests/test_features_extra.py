"""Batch G: the remaining Phase 2 ratios [features_extra].

Expected values are read from the committed fixtures themselves (the stdlib XBRL reader in _fixture_helpers), never
from our parser, except the labelled other-expense lines, whose parser values are already pinned as VERIFIED facts
(X50 AIA, X68 Paytm). Fixtures: Eternal and TCS FY26 Reg. 34 annual reports (A&P, power & fuel, freight,
business-combination outflows FY26 + FY25 comparatives), Reliance Q2 FY27 consolidated + standalone (profit leakage),
AIA Engineering and Paytm Q2 FY27 (cost shares), ELIN Q2 FY27 (RPT). The YoY / acceleration / history-gated columns
have no year-apart quarter pair in the fixtures and are pinned on synthetic books (NULL on the fixtures, C9).
"""

from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal

import pytest
from conftest import Market

from _fixture_helpers import XBRL_DIR, load_instance
from financials import features_extra as X
from financials.cli import main
from financials.db import apply_schema, connect, declared_columns, table_columns
from financials.dsl import ALIASES, compile_screen
from financials.features import compute_rows
from financials.features_store import write_rows as write_history
from financials.fundamentals import FactBook, _add_months, building_blocks
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.kpis import parse_kpis

ETERNAL_AR = "AR_XBRL_ETERNAL_23092026175418.xml"
TCS_AR = "AR_XBRL_TCS_09082026012216.xml"
REL_CONS = "INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml"
REL_SA = "INTEGRATED_FILING_INDAS_1750535_30102026093155_WEB.xml"
AIA = "INTEGRATED_FILING_INDAS_1751861_03112026045154_WEB.xml"
PAYTM = "INTEGRATED_FILING_INDAS_1746348_26102026105317_WEB.xml"
ELIN = "INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml"
FY26, FY25 = ("2025-04-01", "2026-03-31"), ("2024-04-01", "2025-03-31")
Q2 = ("2026-07-01", "2026-09-30")
MAR26, SEP26 = date(2026, 3, 31), date(2026, 9, 30)
ACQ = "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities"
Q = Decimal


def _filed(name: str, element: str, period: tuple[str, str], ctx: str | None = None) -> Decimal:
    """`element` in the undimensioned duration context `period` of fixture `name`, straight from the XML; `ctx` names
    the plain context where typed-member (scenario) contexts carry the same dates (TCS annual report, RPT rows)."""
    inst = load_instance(XBRL_DIR / name)
    if ctx is not None:
        assert (inst.contexts[ctx].start, inst.contexts[ctx].end) == period
        return inst.numeric[(element, ctx)]
    (v,) = {v for (n, c), v in inst.numeric.items() if n == element and not inst.contexts[c].has_dimensions
            and (inst.contexts[c].start, inst.contexts[c].end) == period}  # fmt: skip
    return v


TCS_CTX = {FY26: "FROM_Apr01_2025_TO_Mar31_2026", FY25: "FROM_Apr01_2024_TO_Mar31_2025"}


def _tcs(element: str, period: tuple[str, str]) -> Decimal:
    return _filed(TCS_AR, element, period, TCS_CTX[period])


def _book(name: str) -> FactBook:
    r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
    assert not r.issues
    book = FactBook(name, r.meta["scope"])
    for f in r.facts:
        if f.period_type == "INSTANT":
            book.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
        else:
            book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def _values(name: str, end: date) -> dict:
    book = _book(name)
    return X.period_values(None, book, end, building_blocks(book, end))


# ── fixtures: annual cost shares, marketing efficiency, perimeter ─────────────────────────────────────────────────


def test_eternal_ad_promo_power_freight_shares_and_marketing_efficiency():
    """[X68, X74] Eternal FY26: A&P 3,350 Cr, power & fuel 355 Cr, freight 480 Cr on 54,364 Cr revenue (no excise)."""
    v = _values(ETERNAL_AR, MAR26)
    rev26, rev25 = (_filed(ETERNAL_AR, "RevenueFromOperations", p) for p in (FY26, FY25))
    ap26, ap25 = (_filed(ETERNAL_AR, "AdvertisingPromotionalExpenses", p) for p in (FY26, FY25))
    assert ap26 == Q("33500000000") and rev26 == Q("543640000000")
    assert v["ad_promo_last_year_pct"] == ap26 / rev26
    assert v["power_fuel_last_year_pct"] == _filed(ETERNAL_AR, "PowerAndFuel", FY26) / rev26
    assert v["freight_last_year_pct"] == _filed(ETERNAL_AR, "CostFreight", FY26) / rev26
    assert v["employee_cost_last_year_pct"] == _filed(ETERNAL_AR, "EmployeeBenefitExpense", FY26) / rev26
    assert v["marketing_efficiency_last_year"] == (rev26 - rev25) / ap25  # 17.3x: 34,121 Cr of new sales / 1,972 Cr
    assert v["ad_promo_latest_quarter_pct"] is None  # an annual report has no quarter
    assert v.get("marketing_efficiency_latest_quarter") is None


def test_business_combination_outflows_and_the_inorganic_flag():
    """[G276] Eternal: nothing in FY26, 2,005 Cr in FY25 (9.9% of FY25 sales) -> inorganic. TCS: 6,768 Cr in FY26
    (2.5% of sales), nil in FY25 -> below the 5% C26 threshold."""
    et, tcs = _values(ETERNAL_AR, MAR26), _values(TCS_AR, MAR26)
    assert et["acquisition_outflow_last_year"] == _filed(ETERNAL_AR, ACQ, FY26) == 0
    assert et["acquisition_outflow_preceding_year"] == _filed(ETERNAL_AR, ACQ, FY25) == Q("20050000000")
    assert _filed(ETERNAL_AR, ACQ, FY25) / _filed(ETERNAL_AR, "RevenueFromOperations", FY25) > X.INORGANIC_MIN_SHARE
    assert et["inorganic_growth_flag"] is True
    acq = _tcs(ACQ, FY26)
    assert tcs["acquisition_outflow_last_year"] == acq == Q("67680000000")
    assert tcs["acquisition_outflow_to_sales_last_year"] == acq / _tcs("RevenueFromOperations", FY26)
    assert tcs["acquisition_outflow_preceding_year"] == 0
    assert tcs["inorganic_growth_flag"] is False


def test_tcs_annual_notes_and_fiscal_year_lines():
    v = _values(TCS_AR, MAR26)
    pat = _tcs("ProfitLossForPeriod", FY26)
    assert v["managerial_remuneration_to_pat"] == _tcs("ManagerialRemuneration", FY26) / pat
    assert v["dividends_paid_last_year"] == _tcs("DividendsPaidClassifiedAsFinancingActivities", FY26)
    assert v["minority_share_last_year"] == _tcs("ProfitOrLossAttributableToNonControllingInterests", FY26)
    assert v["employee_cost_preceding_year"] == _tcs("EmployeeBenefitExpense", FY25)
    assert v["unquoted_investments"] == 0  # filed nil (non-current and current)
    assert v["quoted_investments_market_value"] == Q("2180000000") + Q("337700000000")
    assert v["audit_fees_to_sales"] is None  # filed 0.00: rounded to nil, never a 0% ratio
    assert v["incremental_asset_turnover_3y"] is None  # FY23 base is before the cutoff (C9)


# ── fixtures: quarter cost shares, RPT, profit leakage ────────────────────────────────────────────────────────────


def test_quarter_cost_shares_from_label_rules():
    """[X50] AIA labels power & fuel (82.5 Cr) and freight (120.2 Cr); [X68] Paytm labels A&P (194 Cr)."""
    aia, paytm = _values(AIA, SEP26), _values(PAYTM, SEP26)
    sales = _filed(AIA, "RevenueFromOperations", Q2)
    assert aia["power_fuel_latest_quarter_pct"] == Q("825033000") / sales
    assert aia["freight_latest_quarter_pct"] == Q("1201982000") / sales
    assert aia["ad_promo_latest_quarter_pct"] is None  # not labelled: not disclosed, never 0
    cogs = ("CostOfMaterialsConsumed", "PurchasesOfStockInTrade",
            "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade")  # fmt: skip
    mats = sum(_filed(AIA, e, Q2) for e in cogs)
    assert aia["material_cost_latest_quarter_pct"] == mats / sales
    assert paytm["ad_promo_latest_quarter_pct"] == Q("1940000000") / _filed(PAYTM, "RevenueFromOperations", Q2)
    for c in ("opm_acceleration_pp", "gpm_change_yoy_pp", "sales_growth_streak_quarters"):
        assert aia[c] is None, c  # one quarter only


def test_rpt_intensity_on_the_same_period():
    v = _values(ELIN, SEP26)
    rpt = _filed(ELIN, "AmountOfRelatedPartyTransactionDuringTheReportingPeriod", Q2, "OneD")
    assert v["rpt_to_sales"] == rpt / _filed(ELIN, "RevenueFromOperations", Q2)


def test_reliance_profit_leakage_latest_quarter():
    """[G278] Consolidated owners' profit exceeds standalone PAT (subsidiaries add): negative leakage."""
    cons, sa = _book(REL_CONS), _book(REL_SA)
    owners = _filed(REL_CONS, "ProfitOrLossAttributableToOwnersOfParent", Q2)
    standalone = _filed(REL_SA, "ProfitLossForPeriod", Q2)
    sa_ttm, ttm, quarter = X.profit_leakage(cons, sa, SEP26)
    assert quarter == 1 - owners / standalone and quarter < 0
    assert sa_ttm is None and ttm is None  # one quarter of each scope: no TTM
    v = X.period_values(None, cons, SEP26, building_blocks(cons, SEP26), other=sa)
    assert v["profit_leakage_latest_quarter_pct"] == quarter
    assert X.period_values(None, sa, SEP26, building_blocks(sa, SEP26), other=cons)[
        "profit_leakage_latest_quarter_pct"] == quarter  # same from either scope's row  # fmt: skip


# ── synthetic books: margin deltas, streaks, TTM leakage, history-gated turnover ──────────────────────────────────


def _quarter_book(quarters: dict[date, dict], scope: str = "CONSOLIDATED") -> FactBook:
    book = FactBook("SYN", scope)
    tags = {"rev": "revenue_from_operations", "pbeit": "profit_before_exceptional_and_tax", "mat": (
        "cost_of_materials_consumed"), "pat": "pat", "owners": "pat_owners"}  # fmt: skip
    for end, v in quarters.items():
        p = (_add_months(date(end.year, end.month, 1), -2), end)
        for k, tag in tags.items():
            if k in v:
                book.durations.setdefault(tag, {})[p] = Q(v[k])
        for tag in ("finance_costs", "depreciation_amortisation", "other_income", "purchases_of_stock_in_trade",
                    "changes_in_inventories"):  # fmt: skip
            book.durations.setdefault(tag, {})[p] = Q(0)
        book.durations.setdefault("pbt", {})[p] = Q(v.get("pbeit", 0))
    return book


QS = [_add_months(date(2025, 3, 31), 3 * i) for i in range(7)]  # Mar-2025 .. Sep-2026


def test_margin_acceleration_and_gross_margin_change():
    # OPM: Jun-25 10%, Sep-25 12%, Jun-26 14%, Sep-26 20% -> (20 - 12) - (14 - 10) = +4 pp
    opm = dict(zip(QS, (8, 10, 12, 11, 9, 14, 20), strict=True))
    mats = {QS[2]: 650, QS[6]: 600}  # GPM Sep-25 35%, Sep-26 40%
    book = _quarter_book({q: {"rev": 1000, "pbeit": 10 * opm[q], "mat": mats.get(q, 500), "pat": 50 + i}
                          for i, q in enumerate(QS)})  # fmt: skip
    assert X.margin_acceleration(book, SEP26) == (Q("0.20") - Q("0.12")) - (Q("0.14") - Q("0.10"))
    v = X.period_values(None, book, SEP26, building_blocks(book, SEP26))
    assert v["gpm_change_yoy_pp"] == Q("0.40") - Q("0.35")
    # Profit grew YoY in Sep-26, Jun-26 and Mar-26; Dec-25's year-earlier quarter is before the cutoff (C9).
    assert v["profit_growth_streak_quarters"] == 3
    assert v["sales_growth_streak_quarters"] == 0  # flat sales
    del book.durations["pat"][(date(2025, 7, 1), SEP26.replace(year=2025))]
    assert X.growth_streak(book, "pat", SEP26) is None  # the latest quarter cannot be measured
    low = _quarter_book({q: {"rev": 1000, "pbeit": 100, "mat": 50} for q in QS})  # materials 5% < 10% (C6)
    assert X.period_values(None, low, SEP26, building_blocks(low, SEP26))["gpm_change_yoy_pp"] is None


def test_ttm_profit_leakage():
    cons = _quarter_book({q: {"pat": 90, "owners": 75} for q in QS[3:]})
    sa = _quarter_book({q: {"pat": 100} for q in QS[3:]}, "STANDALONE")
    sa_ttm, ttm, quarter = X.profit_leakage(cons, sa, SEP26)
    assert sa_ttm == 400 and ttm == 1 - Q(300) / Q(400) and quarter == Q("0.25")
    loss = _quarter_book({q: {"pat": -10} for q in QS[3:]}, "STANDALONE")
    assert X.profit_leakage(cons, loss, SEP26)[1:] == (None, None)  # standalone loss: undefined
    assert X.profit_leakage(cons, None, SEP26) == (None, None, None)  # one scope only


def _fy_book(years: dict[int, tuple[int, int]]) -> FactBook:
    book = FactBook("SYN", "CONSOLIDATED")
    for fy, (sales, assets) in years.items():
        p = (date(fy - 1, 4, 1), date(fy, 3, 31))
        book.durations.setdefault("revenue_from_operations", {})[p] = Q(sales)
        book.durations.setdefault("pat", {})[p] = Q(1)
        book.instants.setdefault("total_assets", {})[p[1]] = Q(assets)
    return book


def test_incremental_asset_turnover_switches_on_with_fy28():
    book = _fy_book({2025: (1000, 2000), 2026: (1200, 2300), 2027: (1500, 2600), 2028: (1900, 2800)})
    nb = lambda b, d: b.instants["total_assets"].get(d)  # noqa: E731  (a net block stand-in: one instant per FY end)
    assert X.incremental_asset_turnover(book, date(2027, 3, 31), fixed_assets=nb) is None  # base FY24 (C9)
    assert X.incremental_asset_turnover(book, date(2028, 3, 31), fixed_assets=nb) == Q(900) / Q(800)
    shrink = _fy_book({2025: (1000, 3000), 2026: (1, 1), 2027: (1, 1), 2028: (1900, 2800)})
    assert X.incremental_asset_turnover(shrink, date(2028, 3, 31), fixed_assets=nb) is None  # did not grow
    assert X.incremental_asset_turnover(book, date(2028, 3, 31)) is None  # no filed balance sheet: no net block


def test_inorganic_flag_is_three_valued():
    assert X.inorganic_flag([Q("0.06"), None]) is True
    assert X.inorganic_flag([Q("0.01"), Q("0.049")]) is False
    assert X.inorganic_flag([Q("0.01"), None]) is None


# ── per-row: KPIs, ownership flow, Reg. 30, raw inputs ────────────────────────────────────────────────────────────


def _qp(end: date) -> tuple[date, date]:
    return (_add_months(date(end.year, end.month, 1), -2), end)


def test_kpi_ttm_yoy_and_valuation_columns():
    gov = {_qp(_add_months(SEP26, -3 * i)): Q(100 + 10 * i) for i in range(5)}  # Sep-25 .. Sep-26
    assert X.kpi_ttm(gov) == Q(100 + 110 + 120 + 130)
    assert X.kpi_yoy(gov) == (Q(100), Q(140))
    assert X.kpi_ttm({(date(2025, 4, 1), MAR26): Q(999), _qp(MAR26): Q(1)}) == Q(999)  # a filed 12-month period
    assert X.kpi_ttm({_qp(SEP26): Q(1)}) is None  # never a partial year
    kpis = {"gov": gov, "arpu": {_qp(SEP26): Q(250), _qp(date(2025, 9, 30)): Q(200)},
            "mtu": {_qp(SEP26): Q(1200000)}, "contribution_margin": {_qp(SEP26): Q("0.05"),
            _qp(date(2025, 9, 30)): Q("0.03")}, "casa_pct": {_qp(SEP26): Q("0.42")}}  # fmt: skip
    row = {"market_cap": Q(9000), "enterprise_value": Q(8000), "sales_ttm": Q(2000), "embedded_value": Q(3000)}
    v = X.valuation_columns(row, kpis)
    assert v["price_to_sales"] == 4.5 and v["ev_to_sales"] == 4.0 and v["price_to_embedded_value"] == 3.0
    assert v["gov_ttm"] == Q(460) and v["ev_to_gov"] == pytest.approx(8000 / 460)
    assert v["gov_growth_yoy_pct"] == pytest.approx(100 / 140 - 1)
    assert v["arpu"] == Q(250) and v["arpu_growth_yoy_pct"] == pytest.approx(0.25)
    assert v["mtu"] == 1200000 and v["mtu_growth_yoy_pct"] is None  # no period a year earlier
    assert v["contribution_margin_change_yoy_pp"] == pytest.approx(0.02) and v["casa_pct"] == 0.42
    assert X.valuation_columns({}, None)["ev_to_gov"] is None


def test_institutional_absorption_and_pledge_change():
    flow = {"dates": {1: SEP26, 2: date(2026, 6, 30)}, "inst": {1: 1_300_000, 2: 1_000_000},
            "promoter": {1: 5000, 2: 5000}, "pledged": {1: 500, 2: 250}, "holders_1pct": 4}  # fmt: skip
    v = X.flow_columns({}, flow, 100_000.0, [], date(2026, 11, 12))
    assert v["inst_shares_change_qoq"] == 300_000 and v["institutional_absorption_90d"] == 3.0
    assert v["promoter_pledge_change_qoq_pp"] == pytest.approx(0.05) and v["public_holders_above_1pct"] == 4
    split = [(date(2026, 8, 1), Q("0.5"), Q("0.5"))]  # a 1:2 split after the earlier pattern: bases differ
    assert X.flow_columns({}, flow, 100_000.0, split, date(2026, 11, 12))["institutional_absorption_90d"] is None
    gap = {**flow, "dates": {1: SEP26, 2: date(2026, 3, 31)}}  # not adjacent quarters
    assert X.flow_columns({}, gap, 100_000.0, [], date(2026, 11, 12))["inst_shares_change_qoq"] is None


def test_red_flags_are_separate_columns_never_summed():
    row = {
        "auditor_resignations_90d": 1,
        "kmp_resignations_90d": 1,
        "fraud_or_default_90d": 0,
        "audit_opinion": "UNMODIFIED",
        "audit_opinion_quarterly": None,
    }
    ev = {"litigations_90d": 2, "allotments_90d": 1, "fund_raising_events_90d": 0}
    v = X.event_columns(row, ev, {"promoter_pledge_change_qoq_pp": 0.01})
    assert v == {"litigations_90d": 2, "allotments_90d": 1, "fund_raising_events_90d": 0,
                 "rf_auditor_resignation_90d": True, "rf_kmp_resignations_90d": False,
                 "rf_fraud_or_default_90d": False, "rf_litigation_90d": True, "rf_audit_qualified": False,
                 "rf_pledge_increase_qoq": True}  # fmt: skip
    assert not any("score" in c or "count" in c for c in X.EVENT_COLUMNS)
    # rf_audit_qualified = features_audit.modified_opinion: the text / results opinion, never the checkbox [X121]
    rf = lambda **kw: X.event_columns({**row, **kw}, ev, {})["rf_audit_qualified"]  # noqa: E731
    assert rf(audit_opinion=None, audit_opinion_quarterly="QUALIFIED") is True
    assert rf(audit_opinion="DISCLAIMER") is True and rf(audit_opinion="ADVERSE") is True
    assert rf(audit_opinion=None) is None and rf(audit_opinion=None, audit_opinion_quarterly="UNMODIFIED") is False


# ── integration on the real pipeline ──────────────────────────────────────────────────────────────────────────────


def test_rows_on_the_full_market(full_market):
    rows = {r["symbol"]: r for r in compute_rows(full_market.con, date(2026, 11, 12))}
    assert all(set(X.EXTRA_COLUMNS) <= set(r) for r in rows.values())
    elin = rows["ELIN"]
    assert elin["pe_numerator"] == elin["market_cap"]
    if elin["pe"] is not None:
        assert elin["pe"] == pytest.approx(float(elin["pe_numerator"] / elin["pe_denominator"]))
    for r in rows.values():  # every published ratio is exactly its exposed inputs (G244)
        for ratio in ("pe", "roe", "opm", "ev_ebitda"):
            if r[ratio] is not None:
                assert r[ratio] == pytest.approx(float(r[f"{ratio}_numerator"] / r[f"{ratio}_denominator"])), ratio
    assert elin["rpt_to_sales"] == pytest.approx(float(Q("891230000") / Q("2895440000")))
    # X361: this market has no announcements-RSS capture, so no 90-day Reg. 30 window is observed: NULL, never 0
    assert elin["litigations_90d"] is None and elin["rf_litigation_90d"] is None
    assert elin["volume_median_90d"] is not None
    con = connect()
    apply_schema(con)
    cols = table_columns(con, "screener_features_history")
    write_history(con, [{c: r.get(c) for c in cols} for r in rows.values()])
    assert con.execute("SELECT count(*) FROM screener_features_history WHERE pe_numerator IS NOT NULL").fetchone()[0]


def test_capital_allocation_view_lists_components_side_by_side():
    con = connect()
    apply_schema(con)
    con.execute("INSERT INTO screener_features (as_of_date, security_id, entity_id, symbol, series, roic, "
                "incremental_roic_1y, buyback_yield, dilution_1y, inorganic_growth_flag) "
                "VALUES ('2026-11-12', 's', 'e', 'SYM', 'EQ', 0.2, 0.3, 0.01, 0.02, FALSE)")  # fmt: skip
    cur = con.execute("SELECT * FROM capital_allocation_scorecard")
    names = [d[0] for d in cur.description]
    row = dict(zip(names, cur.fetchone(), strict=True))
    assert row["incremental_roic_1y"] == 0.3 and row["buyback_yield"] == 0.01 and row["inorganic_growth_flag"] is False
    assert not any("score" in n for n in names)  # components only (architecture §10.2)


def test_every_column_is_appended_in_both_tables_and_has_an_alias():
    for t in ("screener_features",):  # the history view has its columns (test_features_store)
        names = [c for c, _ in declared_columns()[t]]
        start = names.index(X.EXTRA_COLUMNS[0])  # one contiguous block (batch I appends after it)
        assert names[start : start + len(X.EXTRA_COLUMNS)] == list(X.EXTRA_COLUMNS), t
    used = " ".join(sql for sql, _ in ALIASES.values())
    assert [c for c in X.EXTRA_COLUMNS if c not in used] == []
    sql = compile_screen("Margin acceleration > 0 AND Gross margin expansion bps > 50 AND Ad promo intensity > 5 "
                         "AND Profit leakage < 20 AND Institutional absorption > 1 AND Red flag litigation 90days = 0 "
                         "AND Price to embedded value < 3 AND CASA > 40 AND PE numerator > 0").where_sql  # fmt: skip
    for col in ("opm_acceleration_pp", "gpm_change_yoy_pp", "ad_promo_last_year_pct", "profit_leakage_pct",
                "institutional_absorption_90d", "rf_litigation_90d", "price_to_embedded_value", "casa_pct",
                "pe_numerator"):  # fmt: skip
        assert col in sql, col


# ── supplemental KPIs: new names, sample CSV through load-kpis ────────────────────────────────────────────────────

SRC = "https://example.invalid/"
HEADER = "symbol,kpi,period_start,period_end,value,unit,source_kind,source_url,visible_from_utc,notes"


def _kpi(sym, kpi, end: date, value, unit, seen="2026-10-25T12:00:00"):
    start = _add_months(date(end.year, end.month, 1), -2)
    return ",".join(
        [sym, kpi, str(start), str(end), str(value), unit, "INVESTOR_PRESENTATION", SRC + "p.pdf", seen, ""]
    )


KPI_CSV = "\n".join([
    HEADER,
    *(_kpi("ETERNAL", "gov", _add_months(SEP26, -3 * i), 200000000000 + 10000000000 * i, "INR",
           seen=f"{_add_months(SEP26, -3 * i + 1)}T12:00:00") for i in range(5)),
    _kpi("ETERNAL", "arpu", SEP26, "300", "INR"), _kpi("ETERNAL", "arpu", date(2025, 9, 30), "240", "INR"),
    _kpi("ETERNAL", "mtu", SEP26, "25000000", "COUNT"), _kpi("ETERNAL", "mtu", date(2025, 9, 30), "20000000", "COUNT"),
    _kpi("HDFCBANK", "casa", SEP26, "0.34", "RATIO"),
    _kpi("ETERNAL", "mtu", SEP26, "1", "INR"),  # wrong unit
]) + "\n"  # fmt: skip


def test_kpi_parser_accepts_arpu_mtu_and_casa():
    rows = parse_kpis(KPI_CSV.encode())
    assert [r.issue for r in rows] == [None] * 10 + ["WRONG_UNIT"]
    assert {r.kpi for r in rows} == {"gov", "arpu", "mtu", "casa_pct"}  # casa -> casa_pct


def test_kpis_round_trip_into_columns_and_screens(tmp_path):
    m = Market(tmp_path)
    m.stage_day("20261112")
    m.con.close()
    path = tmp_path / "kpis.csv"
    path.write_text(KPI_CSV, encoding="utf-8")
    assert main(["--data-dir", str(tmp_path), "load-kpis", str(path)], out=io.StringIO()) == 0
    assert main(["--data-dir", str(tmp_path), "promote"], out=(log := io.StringIO())) == 0, log.getvalue()
    assert main(["--data-dir", str(tmp_path), "materialize", "2026-11-12"], out=io.StringIO()) == 0

    def screen(query):
        out = io.StringIO()
        assert main(["--data-dir", str(tmp_path), "screen", query], out=out) == 0, out.getvalue()
        return json.loads(out.getvalue())

    (et,) = screen("GOV TTM > 0 AND ARPU growth > 0")
    assert et["symbol"] == "ETERNAL"
    assert et["gov ttm"] == pytest.approx((200000000000 * 4 + 10000000000 * 6) / 1e7)  # Dec-25 .. Sep-26
    assert et["arpu growth"] == pytest.approx(25.0)
    (mtu,) = screen("MTU growth > 0")
    assert mtu["mtu growth"] == pytest.approx(25.0)
    (bank,) = screen("CASA > 30")
    assert bank["symbol"] == "HDFCBANK" and bank["casa"] == pytest.approx(34.0)
