"""Ratio catalogue Batches 2-3 (features_bs): balance-sheet lines and their preceding-year / N-years-back forms,
liquidity, leverage and return ratios, annual notes, fiscal-year cash-flow lines and multi-year sums, FCF valuation,
payout yields, dilution, reinvestment rate and incremental ROIC.

Expected values are read from the committed fixtures themselves (the stdlib XBRL reader in _fixture_helpers), never
from our parser: TCS consolidated Q4 FY26 (+ FY26, Mar-2026 balance sheet), Q2 FY27 (Sep-2026 balance sheet) and the
FY26 Reg. 34 annual report (FY25 comparatives, PPE schedule, contingent liabilities, advance from customers,
geography). History-gated columns are NULL on every real fixture (no fiscal year before FY25 is in scope, C9) and
are pinned on synthetic in-scope years.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import XBRL_DIR, load_instance
from financials import features_bs as B
from financials.dsl import ALIASES, compile_screen, run_screen
from financials.features import compute_rows, materialize
from financials.fundamentals import FactBook, _add_months, building_blocks, screener_convention_ratios
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.promoter import promote
from financials.staging import stage_results_xbrl

TCS_Q4FY26 = "INTEGRATED_FILING_INDAS_1648408_09042026114218_WEB.xml"
TCS_AR26 = "AR_XBRL_TCS_09082026012216.xml"
TCS_Q2FY27 = "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
FY26, FY25 = ("2025-04-01", "2026-03-31"), ("2024-04-01", "2025-03-31")
MAR26, MAR25, SEP26 = "2026-03-31", "2025-03-31", "2026-09-30"


def _raw(name: str, element: str, *, instant: str | None = None, period: tuple[str, str] | None = None) -> Decimal:
    """The undimensioned value of `element` for `instant` or (start, end) in fixture `name`, straight from the XML."""
    inst = load_instance(XBRL_DIR / name)
    if name == TCS_AR26:  # its typed-member contexts carry the same dates: read the plain context by id
        ctx = f"AS_OF_{_ctx(instant)}" if instant else f"FROM_{_ctx(period[0], start=True)}_TO_{_ctx(period[1])}"
        return inst.numeric[(element, ctx)]
    vals = {
        v for (n, ctx), v in inst.numeric.items()
        if n == element and not inst.contexts[ctx].has_dimensions
        and ((inst.contexts[ctx].instant == instant) if instant else
             ((inst.contexts[ctx].start, inst.contexts[ctx].end) == period))
    }  # fmt: skip
    (v,) = vals
    return v


def _ctx(d: str, *, start: bool = False) -> str:
    y, m, day = d.split("-")
    return f"{date(int(y), int(m), int(day)):%b}{day}_{y}"


def _ebit(name: str, period) -> Decimal:
    """EBIT = PBEIT + finance costs - other income (EBITDA - D&A, features_pl)."""
    g = lambda e: _raw(name, e, period=period)  # noqa: E731
    return g("ProfitBeforeExceptionalItemsAndTax") + g("FinanceCosts") - g("OtherIncome")


# ── TCS through the pipeline (Nov 2026: latest BS Sep-2026, last FY = FY26, preceding FY = FY25) ──────────────────

TCS_BROADCASTS = ((TCS_Q4FY26, datetime(2026, 4, 9, 6, 12, 18)), (TCS_AR26, datetime(2026, 8, 8, 19, 52, 19)),
                  (TCS_Q2FY27, datetime(2026, 10, 8, 4, 38, 10)))  # UTC (listing / file-name times)  # fmt: skip


@pytest.fixture(scope="module")
def tcs(tmp_path_factory):
    root = tmp_path_factory.mktemp("tcs_bs")
    m = Market(root)
    for d in ("20260227", "20261112"):  # Feb 2026 first, so the annual report's symbol resolves on its date [X70]
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"
    for name, ts in TCS_BROADCASTS:
        st = stage_results_xbrl(m.vault, m.stage_root, data=(XBRL_DIR / name).read_bytes(),
                                source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                                fetched_at=FETCHED_AT, broadcast_ts=ts, broadcast_ts_source="API_FIELD")  # fmt: skip
        assert promote(m.con, st).status == "PROMOTED"
    assert materialize(m.con, date(2026, 11, 12)).status == "PROMOTED"
    (row,) = [r for r in compute_rows(m.con, date(2026, 11, 12)) if r["symbol"] == "TCS"]
    m.con.close()
    return root, row


def test_tcs_latest_balance_sheet_lines(tcs):
    _, r = tcs
    q2 = lambda e: _raw(TCS_Q2FY27, e, instant=SEP26)  # noqa: E731
    assert r["bs_as_of"] == date(2026, 9, 30)
    assert r["equity_capital"] == q2("EquityShareCapital") == Decimal("3620000000")
    assert r["reserves"] == q2("OtherEquity")
    assert r["current_assets"] == q2("CurrentAssets") and r["current_liabilities"] == q2("CurrentLiabilities")
    assert r["inventory"] == q2("Inventories")
    assert r["trade_receivables"] == q2("TradeReceivablesCurrent") + q2("TradeReceivablesNoncurrent")
    assert r["trade_payables"] == q2("TradePayablesCurrent")  # no non-current payables line filed: nil [C23]
    assert r["cash_equivalents"] == q2("CashAndCashEquivalents")
    # TCS files zero borrowings: debt is its lease liabilities, and debt - net debt = the liquid cash lines.
    assert q2("BorrowingsCurrent") == q2("BorrowingsNoncurrent") == 0
    assert r["debt"] == r["lease_liabilities"] == Decimal("118080000000.00")
    liquid = q2("CashAndCashEquivalents") + q2("BankBalanceOtherThanCashAndCashEquivalents") + q2("CurrentInvestments")
    assert r["debt"] - r["net_debt"] == liquid
    assert r["balance_sheet_total"] <= q2("Assets")  # Screener nets DTA against DTL [S10]
    assert r["current_ratio"] == pytest.approx(float(q2("CurrentAssets") / q2("CurrentLiabilities")))
    assert r["quick_ratio"] == pytest.approx(
        float((q2("CurrentAssets") - q2("Inventories")) / q2("CurrentLiabilities"))
    )
    assert r["net_debt_to_equity"] == pytest.approx(float(r["net_debt"] / q2("Equity")))
    assert 0 < r["long_term_debt_to_equity"] < float(r["debt"] / q2("Equity"))  # non-current leases only
    assert r["face_value"] == _raw(TCS_Q2FY27, "FaceValueOfEquityShareCapital", period=("2026-07-01", SEP26))


def test_tcs_annual_notes_at_the_last_fiscal_year_end(tcs):
    _, r = tcs
    ar = lambda e, d=MAR26: _raw(TCS_AR26, e, instant=d)  # noqa: E731
    assert r["contingent_liabilities"] == ar("ContingentLiabilities") == Decimal("23300000000")
    assert r["advance_from_customers"] == ar("AdvanceReceivedFromCustomers")
    # PPE schedule tie-out [X71]: gross block - accumulated depreciation = net PPE on the face of the balance sheet.
    assert r["gross_block"] - r["accumulated_depreciation"] == ar("PropertyPlantAndEquipment")
    ppe = load_instance(XBRL_DIR / TCS_AR26).numeric  # gross / accumulated members of the PPE schedule axis
    assert r["gross_block"] == ppe[("PropertyPlantAndEquipment", "AS_OF_Mar31_2026_3941_1307")]
    assert r["accumulated_depreciation"] == ppe[("PropertyPlantAndEquipment", "AS_OF_Mar31_2026_3941_1308")]
    assert r["gross_block_preceding_year"] == ppe[("PropertyPlantAndEquipment", "AS_OF_Mar31_2025_3941_1307")]
    # Geography (Ind AS 108.33): domestic + foreign = FY26 revenue from operations [X75].
    domestic = Decimal("157750000000")  # India, test_segment_observations pins it on the same file
    sales = _raw(TCS_Q4FY26, "RevenueFromOperations", period=FY26)
    assert r["exports_pct"] == pytest.approx(float(1 - domestic / sales))


def test_tcs_preceding_year_balance_sheet(tcs):
    _, r = tcs
    ar = lambda e: _raw(TCS_AR26, e, instant=MAR25)  # noqa: E731
    assert r["working_capital_preceding_year"] is not None
    assert _raw(TCS_AR26, "BorrowingsCurrent", instant=MAR25) == 0 and r["debt_preceding_year"] > 0  # leases only
    assert r["debt_to_equity_preceding_year"] == pytest.approx(float(r["debt_preceding_year"] / ar("Equity")))
    owners_fy25 = _raw(TCS_AR26, "ProfitOrLossAttributableToOwnersOfParent", period=FY25)
    assert r["roe_preceding_year"] == pytest.approx(float(owners_fy25 / ar("EquityAttributableToOwnersOfParent")))
    assert r["roce_preceding_year"] == pytest.approx(float(_ebit(TCS_AR26, FY25) / (r["debt_preceding_year"]
                                                                                    + ar("Equity"))))  # fmt: skip
    assert r["roa_preceding_year"] is None  # average assets need the Mar-2024 balance sheet (C9)
    assert r["cwip_preceding_year"] > 0 and r["net_block_preceding_year"] > 0


def test_tcs_fiscal_year_cash_flow(tcs):
    _, r = tcs
    q4 = lambda e: _raw(TCS_Q4FY26, e, period=FY26)  # noqa: E731
    ar = lambda e: _raw(TCS_AR26, e, period=FY25)  # noqa: E731
    assert r["cfo_last_year"] == q4("CashFlowsFromUsedInOperatingActivities")
    assert r["cfo_preceding_year"] == ar("CashFlowsFromUsedInOperatingActivities")
    assert r["cfi_last_year"] == q4("CashFlowsFromUsedInInvestingActivities")
    assert r["cff_preceding_year"] == ar("CashFlowsFromUsedInFinancingActivities")
    assert r["net_cash_flow_last_year"] == q4("IncreaseDecreaseInCashAndCashEquivalents")  # after FX [S12]
    assert r["cash_end_last_year"] == _raw(TCS_AR26, "CashAndCashEquivalentsCashFlowStatement", instant=MAR26)
    assert r["cash_beginning_last_year"] == r["cash_end_preceding_year"] == _raw(
        TCS_AR26, "CashAndCashEquivalentsCashFlowStatement", instant=MAR25)  # fmt: skip
    # FY25's opening cash (Mar-2024) is out of scope and never parsed; the statement's identity reproduces the value
    # the annual report files for it.
    assert r["cash_beginning_preceding_year"] == r["cash_end_preceding_year"] - r["net_cash_flow_preceding_year"]
    assert r["cash_beginning_preceding_year"] == _raw(TCS_AR26, "CashAndCashEquivalentsCashFlowStatement",
                                                      instant="2024-03-31")  # fmt: skip

    def capex(g):
        ppe, intangibles = "PurchaseOfPropertyPlantAndEquipment", "PurchaseOfIntangibleAssets"
        return sum(g(e + "ClassifiedAsInvestingActivities") for e in (ppe, intangibles))

    assert r["fcf_last_year"] == q4("CashFlowsFromUsedInOperatingActivities") - capex(
        lambda e: _raw(TCS_AR26, e, period=FY26))  # fmt: skip
    assert r["fcf_preceding_year"] == ar("CashFlowsFromUsedInOperatingActivities") - capex(ar)
    ebitda26 = _ebit(TCS_Q4FY26, FY26) + q4("DepreciationDepletionAndAmortisationExpense")
    assert r["cfo_to_ebitda_last_year"] == pytest.approx(float(r["cfo_last_year"] / ebitda26))


def test_tcs_capital_allocation(tcs):
    """FY26 vs FY25 (both in scope): reinvestment rate and 1Y incremental ROIC are on now; NOPAT = EBIT x (1 - ETR)."""
    _, r = tcs

    def nopat(name, p):
        g = lambda e: _raw(name, e, period=p)  # noqa: E731
        return _ebit(name, p) * (1 - g("TaxExpense") / g("ProfitBeforeTax"))

    n26, n25 = nopat(TCS_Q4FY26, FY26), nopat(TCS_AR26, FY25)
    assert r["reinvestment_rate"] is not None and r["incremental_roic_1y"] is not None
    # invested capital = equity + debt - liquid cash on each FY end; check the sign / scale against NOPAT growth.
    assert (r["incremental_roic_1y"] > 0) == (n26 > n25)


def test_tcs_history_gated_columns_are_null(tcs):
    _, r = tcs
    gated = [c for c in B.OUTPUT_COLUMNS if "_back" in c or c.endswith(("_3y", "_5y", "_7y", "_10y"))
             or c in ("incremental_roic_3y", "incremental_roic_5y")]  # fmt: skip
    assert len(gated) == 47
    assert {c: r[c] for c in gated} == dict.fromkeys(gated)


def test_tcs_lines_need_their_inputs(tcs):
    """No Reg. 31 pattern is promoted for TCS: share counts a year back, dilution and per-share book value back stay
    NULL (paid-up capital is not used: TCS states it in rounded crore). The Sep-2025 balance sheet and the H1 FY26
    cash flow are not committed: average-balance ratios and the TTM FCF are NULL, so are P/FCF and payout yields."""
    _, r = tcs
    assert r["shares_source"] == "PAID_UP"
    for c in ("shares_preceding_year", "dilution_1y", "book_value_preceding_year", "financial_leverage",
              "asset_turnover", "price_to_fcf", "equity_fcf_yield", "shareholder_yield", "buyback_yield"):  # fmt: skip
        assert r[c] is None, c


# ── average-balance ratios on the Mar-2026 balance sheet (TCS Q4 FY26 + FY26 annual report) ───────────────────────


@pytest.fixture(scope="module")
def tcs_book() -> FactBook:
    book = FactBook("TCS", "CONSOLIDATED")
    for name, parse in ((TCS_AR26, parse_reg34_annual), (TCS_Q4FY26, parse_integrated_results)):
        res = parse((XBRL_DIR / name).read_bytes(), name)  # results last: they outrank the annual report [X100]
        for f in res.facts:
            if f.period_type == "INSTANT":
                book.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
            else:
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def test_tcs_average_balance_ratios_on_the_fy_balance_sheet(tcs_book):
    end = date(2026, 3, 31)
    v = B.period_values(tcs_book, end, building_blocks(tcs_book, end))
    c = v["cols"]
    ta = lambda d: _raw(TCS_AR26, "Assets", instant=d)  # noqa: E731
    eq = lambda d: _raw(TCS_AR26, "EquityAttributableToOwnersOfParent", instant=d)  # noqa: E731
    avg_ta = (ta(MAR25) + ta(MAR26)) / 2
    assert c["financial_leverage"] == avg_ta / ((eq(MAR25) + eq(MAR26)) / 2)
    assert c["asset_turnover"] == _raw(TCS_Q4FY26, "RevenueFromOperations", period=FY26) / avg_ta
    assert v["roa"] == _raw(TCS_Q4FY26, "ProfitOrLossAttributableToOwnersOfParent", period=FY26) / avg_ta
    assert c["earning_power"] == _ebit(TCS_Q4FY26, FY26) / ta(MAR26)
    assert c["debt_preceding_year"] is not None and c["cash_end_last_year"] is not None


# ── synthetic in-scope fiscal years: history-gated forms switch on with enough years ─────────────────────────────


def _fy(y: int) -> tuple[date, date]:
    return date(y - 1, 4, 1), date(y, 3, 31)


def synthetic_book(last_fy: int) -> FactBook:
    """FY25 .. FY`last_fy` (12-month flows, March balance sheets); year index i = 0 for FY25."""
    book = FactBook("SYN", "CONSOLIDATED")
    d, s = book.durations, book.instants
    for i, y in enumerate(range(2025, last_fy + 1)):
        p, e = _fy(y), date(y, 3, 31)
        flows = {
            "revenue_from_operations": Decimal(1000 + 100 * i), "pat": Decimal(105 + 10 * i),
            "pat_owners": Decimal(100 + 10 * i), "profit_before_exceptional_and_tax": Decimal(150 + 10 * i),
            "finance_costs": Decimal(20), "depreciation_amortisation": Decimal(30), "other_income": Decimal(10),
            "pbt": Decimal(150 + 10 * i), "tax_expense": Decimal(30 + 2 * i), "cfo": Decimal(120 + 10 * i),
            "cfi": Decimal(-60), "cff": Decimal(-50), "capex_ppe": Decimal(50), "net_cash_flow_after_fx": Decimal(10),
            "cost_of_materials_consumed": Decimal(400), "revenue_foreign": Decimal(300 + 10 * i),
            "revenue_domestic": Decimal(700 + 90 * i),
        }  # fmt: skip
        stocks = {
            "total_assets": Decimal(1000 + 100 * i), "equity_share_capital": Decimal(10),
            "other_equity": Decimal(490 + 50 * i), "total_equity": Decimal(500 + 50 * i),
            "borrowings_noncurrent": Decimal(200 + 10 * i), "borrowings_current": Decimal(50),
            "cash_and_equivalents": Decimal(40 + 5 * i), "current_assets": Decimal(400 + 20 * i),
            "current_liabilities": Decimal(200 + 10 * i), "inventories": Decimal(100 + i),
            "trade_receivables_current": Decimal(150 + 10 * i), "trade_payables_current": Decimal(80),
            "ppe_net": Decimal(300 + 30 * i), "cash_cf_statement": Decimal(40 + 5 * i),
            "bank_balances_other": Decimal(0), "current_investments": Decimal(0),
        }  # fmt: skip
        for tag, v in flows.items():
            d.setdefault(tag, {})[p] = v
        for tag, v in stocks.items():
            s.setdefault(tag, {})[e] = v
    return book


def _values(last_fy: int) -> dict:
    book = synthetic_book(last_fy)
    end = date(last_fy, 3, 31)
    return B.period_values(book, end, building_blocks(book, end))["cols"]


@pytest.mark.parametrize("years", B.SUM_YEARS)
def test_cash_flow_sums_need_every_fiscal_year(years):
    assert _values(2025 + years - 2)[f"fcf_{years}y"] is None  # one fiscal year short: NULL, never a shorter sum
    c = _values(2025 + years - 1)
    window = range(years)
    assert c[f"cfo_{years}y"] == sum(Decimal(120 + 10 * i) for i in window)
    assert c[f"fcf_{years}y"] == sum(Decimal(70 + 10 * i) for i in window)
    assert c[f"cfi_{years}y"] == Decimal(-60 * years)


def test_three_year_conversions():
    assert _values(2026)["fcf_conversion_3y"] is None
    c = _values(2027)
    assert c["fcf_conversion_3y"] == Decimal(70 + 80 + 90) / Decimal(100 + 110 + 120)
    ebitda = sum(Decimal(150 + 10 * i) + 20 + 30 - 10 for i in range(3))
    assert c["cfo_to_ebitda_3y"] == Decimal(120 + 130 + 140) / ebitda
    net_debt = Decimal(220 + 50 - 50)  # FY27: borrowings 220 + 50, cash 50
    assert c["net_debt_to_fcf_3y"] == net_debt / (Decimal(240) / 3)


@pytest.mark.parametrize("years", B.BACK_YEARS)
def test_values_n_years_back_switch_on_when_that_year_is_in_scope(years):
    short = _values(2025 + years - 1)
    assert short[f"debt_{years}y_back"] is None and short[f"inventory_turnover_{years}y_back"] is None
    c = _values(2025 + years)
    assert c[f"debt_{years}y_back"] == Decimal(250)  # FY25: borrowings 200 + 50, no leases
    assert c[f"net_block_{years}y_back"] == Decimal(300)
    book = synthetic_book(2025)
    wc25 = screener_convention_ratios(book, date(2025, 3, 31))["working_capital"]
    assert c[f"working_capital_{years}y_back"] == wc25
    assert c[f"inventory_turnover_{years}y_back"] == Decimal(1000) / Decimal(100)
    if years in B.CASH_BACK_YEARS:
        assert c[f"cash_{years}y_back"] == Decimal(40)
    if years in B.DEBTOR_BACK_YEARS:
        assert c[f"debtor_days_{years}y_back"] == Decimal(150) / (Decimal(1000) / 365)
    if years in B.EXPORT_BACK_YEARS:
        assert c[f"exports_pct_{years}y_back"] == Decimal(300) / Decimal(1000)


def test_three_year_average_days():
    assert _values(2026)["avg_debtor_days_3y"] is None
    c = _values(2027)
    book = synthetic_book(2027)
    days = [screener_convention_ratios(book, date(y, 3, 31)) for y in (2025, 2026, 2027)]
    assert c["avg_debtor_days_3y"] == sum(x["debtor_days"] for x in days) / 3
    assert c["avg_working_capital_days_3y"] == sum(x["working_capital_days"] for x in days) / 3


@pytest.mark.parametrize("years", B.INCREMENTAL_ROIC_YEARS)
def test_incremental_roic_needs_the_base_year_in_scope(years):
    if years > 1:
        assert _values(2025 + years - 1)[f"incremental_roic_{years}y"] is None

    def nopat(i):
        ebit = Decimal(150 + 10 * i) + 20 - 10
        return ebit * (1 - Decimal(30 + 2 * i) / Decimal(150 + 10 * i))

    def ic(i):
        return Decimal(500 + 50 * i) + Decimal(250 + 10 * i) - Decimal(40 + 5 * i)

    c = _values(2025 + years)
    assert c[f"incremental_roic_{years}y"] == (nopat(years) - nopat(0)) / (ic(years) - ic(0))


def test_reinvestment_rate():
    c = _values(2026)

    def wc(i):  # (CA - cash) - (CL - current borrowings)
        return (Decimal(400 + 20 * i) - Decimal(40 + 5 * i)) - (Decimal(200 + 10 * i) - 50)

    nopat = Decimal(170) * (1 - Decimal(32) / Decimal(160))
    assert c["reinvestment_rate"] == (Decimal(50) - 30 + wc(1) - wc(0)) / nopat
    assert c["debt_preceding_year"] == Decimal(250) and c["roe_preceding_year"] == Decimal(100) / Decimal(500)
    assert c["roa_preceding_year"] is None  # FY25 needs the Mar-2024 balance sheet
    assert _values(2027)["roa_preceding_year"] == Decimal(110) / ((Decimal(1000) + Decimal(1100)) / 2)


# ── per-security finish: share counts, dilution, Graham number, FCF valuation, payout yields, lender NULLs ─────────


class _Con:  # an identity for the prefetch cache; never queried
    pass


def test_share_counts_dilution_and_per_share_values():
    con, ts, as_of = _Con(), datetime(2026, 11, 12, 18, 30), date(2026, 11, 12)
    bonus = [(date(2026, 1, 15), Decimal("0.5"), Decimal("0.5"))]  # 1:1 bonus between the two patterns
    B._PREFETCH[(id(con), ts)] = {"E": {date(2025, 9, 30): Decimal(100), date(2026, 9, 30): Decimal(240)}}
    try:
        row = {"entity_id": "E", "shp_as_of": date(2026, 9, 30), "eps_ttm": Decimal(10),
               "book_value_per_share": Decimal(90), "market_cap": Decimal(1000), "fcf_ttm": Decimal(50),
               "net_debt": Decimal(-20), "ebitda_ttm": Decimal(40), "roa": None,
               "valuation_archetype": "INDUSTRIAL_SERVICES"}  # fmt: skip
        out = B.row_columns(con, ts, None, row, bonus, as_of)
    finally:
        B.clear(con, ts)
    assert out["shares_preceding_year"] == 200  # 100 before the bonus = 200 on today's basis
    assert out["dilution_1y"] == pytest.approx(0.2)
    assert out["shares_10y_back"] is None and out["dilution_5y"] is None  # Sep-2016 / Sep-2021: before C9
    assert out["graham_number"] == Decimal(20250).sqrt().quantize(Decimal("0.0001"))
    assert out["price_to_fcf"] == 20.0 and out["equity_fcf_yield"] == 0.05
    assert out["net_debt_to_ebitda"] == -0.5
    assert list(out) == [*B.OUTPUT_COLUMNS, "roa"]  # same keys in the same order for every row (insert_rows)
    assert B.graham_number(Decimal(-1), Decimal(90)) is None
    later = {date(2026, 9, 30): Decimal(100), date(2031, 9, 30): Decimal(130)}  # five years on, no action between
    B._PREFETCH[(id(con), ts)] = {"E": later}
    try:
        five = B.row_columns(con, ts, None, row | {"shp_as_of": date(2031, 9, 30)}, bonus, date(2031, 11, 12))
    finally:
        B.clear(con, ts)
    assert five["dilution_5y"] == pytest.approx(0.3)  # the Jan-2026 bonus went ex before both counts
    row["fcf_ttm"] = Decimal(-50)
    neg = B.row_columns(None, ts, None, row, [], as_of)
    assert neg["price_to_fcf"] is None and neg["equity_fcf_yield"] == -0.05


def test_payout_yields_sum_the_ttm_cash_flow_window():
    """TTM = H1 FY27 + FY26 - H1 FY26 (the CFO bridge); a line a filing omits is nil in that filing."""
    book = FactBook("E", "CONSOLIDATED")
    h1, fy26, h1_prev = (date(2026, 4, 1), date(2026, 9, 30)), _fy(2026), (date(2025, 4, 1), date(2025, 9, 30))
    d = book.durations
    d["cfo"] = {h1: Decimal(60), fy26: Decimal(100), h1_prev: Decimal(40)}
    d["dividends_paid"] = {h1: Decimal(30), fy26: Decimal(20)}
    d[B.BUYBACK_TAG] = {h1: Decimal(5), fy26: Decimal(0), h1_prev: Decimal(0)}
    d["share_issue_proceeds"] = {fy26: Decimal(2), h1_prev: Decimal(2)}
    assert B.cf_window(book, date(2026, 9, 30)) == [(h1, 1), (fy26, 1), (h1_prev, -1)]
    v = B.period_values(book, date(2026, 9, 30), {"cf_as_of": date(2026, 9, 30)})
    assert v["payouts"] == {"dividends": Decimal(50), "buyback": Decimal(5), "issued": Decimal(0)}
    row = {"entity_id": "E", "shp_as_of": None, "market_cap": Decimal(1000), "roa": None,
           "valuation_archetype": "INDUSTRIAL_SERVICES"}  # fmt: skip
    out = B.row_columns(None, datetime(2026, 11, 12), v, row, [], date(2026, 11, 12))
    assert out["shareholder_yield"] == pytest.approx(0.055) and out["buyback_yield"] == pytest.approx(0.005)
    assert B.period_values(book, date(2026, 9, 30), {"cf_as_of": None})["payouts"]["dividends"] is None


def test_lenders_keep_capital_and_cash_flow_lines_only():
    v = {"cols": dict.fromkeys(B.OUTPUT_COLUMNS, Decimal(1)), "lender": True, "roa": Decimal("0.5"),
         "equity_at": {}, "payouts": {"dividends": None}}  # fmt: skip
    for k in ("graham_number", "price_to_fcf", "equity_fcf_yield", "shareholder_yield", "buyback_yield",
              "dilution_1y", "net_debt_to_ebitda", *B.COUNT_COLUMNS):  # fmt: skip
        v["cols"].pop(k)
    row = {"entity_id": "L", "shp_as_of": None, "roa": 0.012, "valuation_archetype": "FINANCIAL_LENDING"}
    out = B.row_columns(None, datetime(2026, 11, 12), v, row, [], date(2026, 11, 12))
    assert out["roa"] == 0.012  # the lenders' own definition
    assert all(out[c] is None for c in B.NOT_FOR_LENDERS)
    assert out["equity_capital"] == Decimal("1.00") and out["cfo_last_year"] == Decimal("1.00")
    assert {"debt", "current_ratio", "fcf_last_year", "reinvestment_rate", "inventory"} <= set(B.NOT_FOR_LENDERS)


def test_industrial_rows_get_liquidity_ratios(full_market):
    """Lender and insurer rows are pinned on every real financial fixture in test_phase1_phase2_e2e."""
    rows = [r for r in compute_rows(full_market.con, date(2026, 11, 12)) if r["bs_as_of"]]
    assert rows and all(r["current_ratio"] is not None and r["debt"] is not None for r in rows)


# ── DSL ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_new_column_has_an_alias_and_a_schema_column():
    from financials.db import declared_columns

    for table in ("screener_features", "screener_features_history"):
        cols = [c for c, _ in declared_columns()[table]]
        block = [*B.OUTPUT_COLUMNS, "ev_ebitda_percentile_20q"]  # appended as one contiguous block, in order
        start = cols.index(block[0])
        assert cols[start : start + len(block)] == block, table
    used = " ".join(sql for sql, _ in ALIASES.values())
    assert [c for c in (*B.OUTPUT_COLUMNS, "ev_ebitda_percentile_20q") if c not in used] == []
    sql = compile_screen(
        "Debt < Debt preceding year AND Current ratio > 1.5 AND Quick ratio > 1 AND Free cash flow 3years > 0 "
        "AND Price to Free Cash Flow < 30 AND Return on assets > 10 AND Graham Number > Current price "
        "AND Net block 5Years back > 0 AND Incremental ROIC 3Years > 15 AND Exports percentage > 50"
    ).where_sql
    for col in ("debt_preceding_year", "current_ratio", "quick_ratio", "fcf_3y", "price_to_fcf", "roa",
                "graham_number", "net_block_5y_back", "incremental_roic_3y", "exports_pct"):  # fmt: skip
        assert col in sql, col


def test_screen_with_balance_sheet_and_cash_flow_aliases(tcs):
    root, r = tcs
    from financials.db import connect

    con = connect(root / "market.duckdb", read_only=True)
    try:
        rows = run_screen(con, "Current ratio > 2 AND Cash from operations last year > 50000 AND Debt < Reserves",
                          columns=["Exports percentage", "Free cash flow last year", "Contingent liabilities",
                                   "Free cash flow 3years"])  # fmt: skip
    finally:
        con.close()
    (row,) = [x for x in rows if x["symbol"] == "TCS"]
    assert float(row["exports percentage"]) == pytest.approx(r["exports_pct"] * 100)
    assert float(row["free cash flow last year"]) == pytest.approx(float(r["fcf_last_year"]) / 1e7)
    assert float(row["contingent liabilities"]) == pytest.approx(2330.0)
    assert row["free cash flow 3years"] is None


def test_preceding_year_is_the_fiscal_year_before_the_last():
    """'preceding year' = the end of the FY before the last FY (as sales_preceding_year), whatever the latest BS."""
    book = synthetic_book(2026)
    book.instants["total_assets"][date(2026, 9, 30)] = Decimal(1200)  # an H1 balance sheet after FY26
    book.instants["borrowings_noncurrent"][date(2026, 9, 30)] = Decimal(999)
    end = date(2026, 9, 30)
    c = B.period_values(book, end, building_blocks(book, end))["cols"]
    assert c["debt"] == Decimal(999)  # latest balance sheet (no current borrowings line on it: nil)
    assert c["debt_preceding_year"] == Decimal(250)  # Mar-2025
    assert _add_months(end, -12) not in book.instants["total_assets"]


def test_ev_ebitda_band_of_20_quarter_ends_needs_20_of_them():
    """G240: the 5-year band ranks today's EV/EBITDA among the last 20 prior quarter-ends (oldest first from
    _valuation_history); fewer than 20 stored quarter-ends (C9: first possible ~2031) is NULL."""
    from financials.db import apply_schema, connect, insert_rows
    from financials.features import _valuation_history
    from financials.fundamentals import percentile_rank

    con = connect()
    apply_schema(con)
    ends = [_add_months(date(2026, 3, 31), 3 * i) for i in range(22)]
    rows = [{"as_of_date": d, "security_id": "S", "entity_id": "E", "symbol": "X", "series": "EQ",
             "ev_ebitda": float(i + 1)} for i, d in enumerate(ends)]  # fmt: skip
    insert_rows(con, "screener_features_history", list(reversed(rows)))
    hist = _valuation_history(con, date(2031, 9, 1))["S"]["ev_ebitda"]
    con.close()
    assert hist == [float(i + 1) for i in range(22)]  # oldest first, whatever the insert order
    assert percentile_rank(12.5, hist[-20:], min_periods_required=20) == 10 / 20  # 3..22: ten are <= 12.5
    assert percentile_rank(12.5, hist[-19:], min_periods_required=20) is None
