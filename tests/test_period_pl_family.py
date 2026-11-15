"""Ratio catalogue Batch 0 (DSL / CLI: aliases, book value per share, trade-to-trade flag, output columns, saved
ratios) and Batch 1 (period P&L family: quarter and fiscal-year lines, quarter YoY growth, result dates, and the
history-gated FY windows) [features_pl].

Expected values are read from the committed fixtures themselves (the stdlib XBRL reader in _fixture_helpers), never
from our parser: Finolex Cables' consolidated Q4 FY25 (+ FY25), Q1 FY26 and Q2 FY26 results; TCS consolidated Q4 FY26
(+ FY26) and Q2 FY27 results and its FY26 Reg. 34 annual report (FY25 comparatives). The history-gated columns are
NULL on every real fixture (no fiscal year before FY25 is in scope, C9) and are pinned on synthetic in-scope years.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import XBRL_DIR, load_instance
from financials import features_pl as F
from financials.cli import main
from financials.dsl import ALIASES, DslError, compile_screen, run_screen, save_custom_ratio, split_columns
from financials.features import compute_rows, materialize
from financials.fundamentals import FactBook, _add_months, cagr
from financials.parsers.integrated import parse_integrated_results
from financials.promoter import promote
from financials.staging import stage_results_xbrl

FINCABLES = {  # consolidated, three consecutive quarters
    date(2025, 3, 31): "INTEGRATED_FILING_INDAS_1456174_29052025103806_WEB.xml",  # Q4 FY25 + FY25
    date(2025, 6, 30): "INTEGRATED_FILING_INDAS_1510705_13082025092940_WEB.xml",  # Q1 FY26
    date(2025, 9, 30): "INTEGRATED_FILING_INDAS_1571804_11112025093544_WEB.xml",  # Q2 FY26 + H1
}
Q2, Q1, Q4 = date(2025, 9, 30), date(2025, 6, 30), date(2025, 3, 31)
TCS_Q4FY26 = "INTEGRATED_FILING_INDAS_1648408_09042026114218_WEB.xml"
TCS_AR26 = "AR_XBRL_TCS_09082026012216.xml"
TCS_Q2FY27 = "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
OWNERS = "ProfitOrLossAttributableToOwnersOfParent"
EBITDA_ADDS = ("ProfitBeforeExceptionalItemsAndTax", "FinanceCosts", "DepreciationDepletionAndAmortisationExpense")


def _filed(name: str, start: str, end: str, element: str) -> Decimal:
    """Value of `element` in the undimensioned context (start, end) of fixture `name`, straight from the XML."""
    inst = load_instance(XBRL_DIR / name)
    (v,) = {v for (n, ctx), v in inst.numeric.items() if n == element and not inst.contexts[ctx].has_dimensions
            and (inst.contexts[ctx].start, inst.contexts[ctx].end) == (start, end)}  # fmt: skip
    return v


def _ar(element: str, context: str = "FROM_Apr01_2024_TO_Mar31_2025") -> Decimal:
    """TCS FY26 annual report: the plain FY context by id (its typed-member contexts carry the same dates)."""
    return load_instance(XBRL_DIR / TCS_AR26).numeric[(element, context)]


def _fin(end: date, element: str, months: int = 3) -> Decimal:
    first = _add_months(date(end.year, end.month, 1), -(months - 1))
    return _filed(FINCABLES[end], str(first), str(end), element)


def _ebitda(get) -> Decimal:
    return sum(get(e) for e in EBITDA_ADDS) - get("OtherIncome")


@pytest.fixture(scope="module")
def fincables() -> FactBook:
    book = FactBook("FINCABLES", "CONSOLIDATED")
    for name in FINCABLES.values():
        r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
        assert not r.issues and r.meta["scope"] == "CONSOLIDATED"
        for f in r.facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


@pytest.fixture(scope="module")
def fin_cols(fincables):
    return F.period_values(None, fincables, Q2)


# ── quarter lines ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_quarter_lines_for_the_latest_preceding_and_2_quarters_back(fin_cols):
    c = fin_cols["cols"]
    for col, end in (("latest_quarter", Q2), ("preceding_quarter", Q1), ("2quarters_back", Q4)):
        assert c[f"sales_{col}"] == _fin(end, "RevenueFromOperations")  # no excise line: sales = revenue [X40]
        assert c[f"operating_profit_{col}"] == _ebitda(lambda e, end=end: _fin(end, e))
        assert c[f"net_profit_{col}"] == _fin(end, OWNERS)
    assert c["sales_latest_quarter"] == Decimal("13757900000")  # 1,375.79 Cr
    assert c["operating_profit_latest_quarter"] == Decimal("1680900000") + Decimal("4400000") + Decimal(
        "140400000") - Decimal("374600000")  # fmt: skip
    # Dec-2024 (3 quarters back) and Sep-2024 (same quarter last year) end before the financials cutoff (C9).
    for line in F.DEEP_LINES:
        assert c[f"{line}_3quarters_back"] is None and c[f"{line}_preceding_year_quarter"] is None


def test_every_quarter_line_is_the_filed_element(fin_cols):
    c = fin_cols["cols"]
    filed = {"other_income": "OtherIncome", "depreciation": "DepreciationDepletionAndAmortisationExpense",
             "interest": "FinanceCosts", "pbt": "ProfitBeforeTax", "tax": "TaxExpense", "pat": "ProfitLossForPeriod",
             "exceptional_items": "ExceptionalItemsBeforeTax"}  # fmt: skip
    for line, element in filed.items():
        assert c[f"{line}_latest_quarter"] == _fin(Q2, element), line
        assert c[f"{line}_preceding_quarter"] == _fin(Q1, element), line
    assert c["exceptional_items_latest_quarter"] == Decimal("381100000")  # the JV share booked as exceptional [X102]
    assert c["ebit_latest_quarter"] == c["operating_profit_latest_quarter"] - _fin(
        Q2, "DepreciationDepletionAndAmortisationExpense")  # fmt: skip
    assert c["equity_capital_latest_quarter"] == _fin(Q2, "PaidUpValueOfEquityShareCapital") == Decimal("305900000")
    assert fin_cols["eps"]["eps_latest_quarter"] == (_fin(Q2, "BasicEarningsLossPerShareFromContinuingAndDiscontinued"
                                                           "Operations"), None)  # fmt: skip
    assert fin_cols["eps"]["eps_preceding_year_quarter"] is None


def test_quarter_margins(fin_cols):
    c = fin_cols["cols"]
    sales = _fin(Q2, "RevenueFromOperations")
    assert c["opm_latest_quarter_pct"] == _ebitda(lambda e: _fin(Q2, e)) / sales
    assert c["npm_latest_quarter_pct"] == _fin(Q2, OWNERS) / sales
    assert c["opm_preceding_quarter_pct"] == _ebitda(lambda e: _fin(Q1, e)) / _fin(Q1, "RevenueFromOperations")
    # Materials 1,130.97 + purchases 14.73 Cr are >= 10% of sales, so GPM is defined [C6].
    cogs = sum(_fin(Q2, e) for e in ("CostOfMaterialsConsumed", "PurchasesOfStockInTrade",
                                     "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade"))  # fmt: skip
    assert c["gpm_latest_quarter_pct"] == (sales - cogs) / sales
    assert c["npm_preceding_year_quarter_pct"] is None


def test_quarter_yoy_growth_needs_the_same_quarter_last_year(fincables, fin_cols):
    c = fin_cols["cols"]
    assert c["sales_growth_yoy_quarter_pct"] is None and c["profit_growth_yoy_quarter_pct"] is None
    assert c["operating_profit_growth_yoy_quarter_pct"] is None
    # Were Q4 FY26 the latest quarter, Q4 FY25 (filed) would be its same quarter last year: Q4 FY26 is not filed
    # here, so growth is still NULL, while the base is picked up as the preceding year quarter.
    later = F.period_values(None, fincables, date(2026, 3, 31))["cols"]
    assert later["sales_preceding_year_quarter"] == _fin(Q4, "RevenueFromOperations")
    assert later["sales_growth_yoy_quarter_pct"] is None
    assert later["net_profit_2quarters_back"] == _fin(Q2, OWNERS)  # Sep-2025 is 2 quarters before Mar-2026


# ── fiscal-year lines ─────────────────────────────────────────────────────────────────────────────────────────────


def test_last_year_is_the_filed_fy25_and_the_preceding_year_is_out_of_scope(fin_cols):
    c = fin_cols["cols"]

    def fy(e):
        return _fin(Q4, e, months=12)

    assert c["sales_last_year"] == fy("RevenueFromOperations") == Decimal("53188900000")
    assert c["operating_profit_last_year"] == _ebitda(fy)
    assert c["net_profit_last_year"] == fy(OWNERS) == Decimal("7007700000")
    assert c["pbt_last_year"] == fy("ProfitBeforeTax") and c["tax_last_year"] == fy("TaxExpense")
    assert c["interest_last_year"] == fy("FinanceCosts") and c["other_income_last_year"] == fy("OtherIncome")
    assert c["opm_last_year_pct"] == _ebitda(fy) / fy("RevenueFromOperations")
    assert c["npm_last_year_pct"] == fy(OWNERS) / fy("RevenueFromOperations")
    assert fin_cols["eps"]["eps_last_year"] == (fy("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"),
                                                None)  # fmt: skip
    # FY24 ends before MIN_PERIOD_END_DATE: never parsed, so every preceding-year column is NULL [C9].
    assert all(c[f"{line}_preceding_year"] is None for line in F.MONEY_LINES)
    assert c["opm_preceding_year_pct"] is None and fin_cols["eps"]["eps_preceding_year"] is None
    assert c["sales_ttm_1y_back"] is None  # TTM Sep-2024 needs quarters before the cutoff


def test_opm_last_year_is_the_fiscal_year_not_the_same_quarter(fincables):
    """The finding in master_backlog §2 (G175): Screener's "OPM last year" is the FY's OPM. The same-quarter value
    is opm_preceding_year_quarter_pct (features._quarterly_columns)."""
    from financials.features import _quarterly_columns
    from financials.fundamentals import quarter_opm

    mar26 = date(2026, 3, 31)
    fy = F.period_values(None, fincables, mar26)["cols"]["opm_last_year_pct"]
    same_q = _quarterly_columns(fincables, mar26)["opm_preceding_year_quarter_pct"]
    assert same_q == pytest.approx(float(quarter_opm(fincables, Q4)))
    assert fy == _ebitda(lambda e: _fin(Q4, e, months=12)) / _fin(Q4, "RevenueFromOperations", months=12)
    assert float(fy) != pytest.approx(same_q)


# ── history-gated windows: NULL on real data now ──────────────────────────────────────────────────────────────────

HISTORY_COLUMNS = (
    *(f"{k}_growth_{n}y_pct" for k in ("sales", "profit", "operating_profit") for n in F.GROWTH_YEARS),
    "sales_growth_median_5y_pct", "sales_growth_median_10y_pct", "avg_earnings_5y", "avg_earnings_10y",
    "avg_ebit_5y", "avg_ebit_10y", "opm_5y_pct", "opm_10y_pct",
)  # fmt: skip


def test_history_gated_columns_are_null_on_the_fixtures(fin_cols):
    assert {c: fin_cols["cols"][c] for c in HISTORY_COLUMNS} == dict.fromkeys(HISTORY_COLUMNS)
    for n in F.GROWTH_YEARS:
        assert F.eps_cagr(fin_cols["eps_fy"], fin_cols["fy_end"], n, [], date(2025, 11, 15)) is None


# ── history-gated windows: values on synthetic in-scope fiscal years ──────────────────────────────────────────────


def _fy(end_year: int) -> tuple[date, date]:
    return date(end_year - 1, 4, 1), date(end_year, 3, 31)


def synthetic_book(last_fy: int) -> FactBook:
    """FY25 .. FY`last_fy` as filed 12-month values only. Sales 100 growing 10% a year (+ a 20% year in FY28),
    owners' profit 10 + year index, EBITDA from its parts, EPS = profit / 2 shares."""
    book = FactBook("SYN", "CONSOLIDATED")
    d = book.durations
    sales = Decimal(100)
    for i, y in enumerate(range(2025, last_fy + 1)):
        p = _fy(y)
        if i:
            sales = sales * (Decimal("1.2") if y == 2028 else Decimal("1.1"))
        profit = Decimal(10 + i)
        for tag, v in (("revenue_from_operations", sales), ("pat", profit + 1), ("pat_owners", profit),
                       ("profit_before_exceptional_and_tax", profit + 5), ("finance_costs", Decimal(1)),
                       ("depreciation_amortisation", Decimal(2)), ("other_income", Decimal(3)),
                       ("eps_basic", profit / 2)):  # fmt: skip
            d.setdefault(tag, {})[p] = v
    return book


def _cagr(end: Decimal, start: Decimal, years: int) -> Decimal:
    return (end / start) ** (Decimal(1) / Decimal(years)) - 1


@pytest.mark.parametrize("years", F.GROWTH_YEARS)
def test_fy_cagr_switches_on_when_the_base_year_is_in_scope(years):
    """FY CAGR over `years` needs FY(25 + years): one year short it is NULL, never a shorter window."""
    short = F.period_values(None, synthetic_book(2025 + years - 1), date(2025 + years - 1, 3, 31))
    assert short["cols"][f"sales_growth_{years}y_pct"] is None
    assert short["cols"][f"profit_growth_{years}y_pct"] is None
    assert short["cols"][f"operating_profit_growth_{years}y_pct"] is None
    assert F.eps_cagr(short["eps_fy"], short["fy_end"], years, [], date(2040, 1, 1)) is None
    end_year = 2025 + years
    book = synthetic_book(end_year)
    out = F.period_values(None, book, date(end_year, 6, 30))  # a quarter after the FY: last year = FY(end_year)
    c = out["cols"]
    d = book.durations
    last, base = _fy(end_year), _fy(2025)
    assert c[f"sales_growth_{years}y_pct"] == _cagr(d["revenue_from_operations"][last],
                                                   d["revenue_from_operations"][base], years)  # fmt: skip
    assert c[f"profit_growth_{years}y_pct"] == _cagr(Decimal(10 + years), Decimal(10), years)
    ebitda = {p: d["profit_before_exceptional_and_tax"][p] + 1 + 2 - 3 for p in (last, base)}
    assert c[f"operating_profit_growth_{years}y_pct"] == _cagr(ebitda[last], ebitda[base], years)
    assert c[f"operating_profit_growth_{years}y_pct"] == cagr(book, F.EBITDA, last[1], years,
                                                              min_periods_required=4 * years + 1)  # fmt: skip
    eps = F.eps_cagr(out["eps_fy"], out["fy_end"], years, [], date(2040, 1, 1))
    assert eps == _cagr(Decimal(10 + years) / 2, Decimal(5), years)


def test_eps_growth_restates_the_base_year_for_a_later_bonus():
    """A 1:1 bonus (EPS factor 0.5) going ex after FY25's EPS was visible halves FY25 EPS on today's basis, while
    FY28 EPS (visible after the bonus) is already on the new basis: growth is on comparable per-share figures."""
    eps_fy = {0: (Decimal("6.5"), date(2028, 5, 20)), 3: (Decimal(5), date(2025, 5, 20))}
    bonus = [(date(2026, 9, 1), Decimal("0.5"), Decimal("0.5"))]
    assert F.restated_eps(eps_fy[3], bonus, date(2028, 6, 1)) == Decimal("2.5000")
    assert F.restated_eps(eps_fy[0], bonus, date(2028, 6, 1)) == Decimal("6.5000")
    assert F.restated_eps(eps_fy[3], bonus, date(2026, 8, 31)) == Decimal("5.0000")  # before the ex-date
    g = F.eps_cagr(eps_fy, date(2028, 3, 31), 3, bonus, date(2028, 6, 1))
    assert g == _cagr(Decimal("6.5"), Decimal("2.5"), 3)
    assert (
        F.eps_cagr({0: (Decimal(-1), None), 3: (Decimal(5), None)}, date(2028, 3, 31), 3, [], date(2028, 6, 1)) is None
    )


@pytest.mark.parametrize("years", (5, 10))
def test_median_growth_and_averages_switch_on_with_enough_years(years):
    """Median of `years` yearly growth rates needs `years` + 1 FYs; an average of `years` FYs needs `years` FYs."""
    assert F.period_values(None, synthetic_book(2024 + years), date(2024 + years, 3, 31))["cols"][
        f"sales_growth_median_{years}y_pct"] is None  # fmt: skip
    short = F.period_values(None, synthetic_book(2023 + years), date(2023 + years, 3, 31))["cols"]
    assert short[f"avg_earnings_{years}y"] is None and short[f"avg_ebit_{years}y"] is None
    assert short[f"opm_{years}y_pct"] is None

    end_year = 2025 + years
    book = synthetic_book(end_year)
    c = F.period_values(None, book, date(end_year, 3, 31))["cols"]
    rev = book.durations["revenue_from_operations"]
    rates = sorted(rev[_fy(y)] / rev[_fy(y - 1)] - 1 for y in range(end_year - years + 1, end_year + 1))
    assert len(rates) == years
    assert c[f"sales_growth_median_{years}y_pct"] == (rates[years // 2 - 1] + rates[years // 2]) / 2
    assert c[f"sales_growth_median_{years}y_pct"] == pytest.approx(Decimal("0.1"))  # the 20% year is an outlier
    window = range(end_year - years + 1, end_year + 1)
    profits = [book.durations["pat_owners"][_fy(y)] for y in window]
    assert c[f"avg_earnings_{years}y"] == sum(profits) / years
    ebit = [book.durations["profit_before_exceptional_and_tax"][_fy(y)] + 1 + 2 - 3 - 2 for y in window]
    assert c[f"avg_ebit_{years}y"] == sum(ebit) / years
    opm = [(e + 2) / book.durations["revenue_from_operations"][_fy(y)] for e, y in zip(ebit, window, strict=True)]
    assert c[f"opm_{years}y_pct"] == sum(opm) / years
    at_minimum = F.period_values(None, synthetic_book(2024 + years), date(2024 + years, 3, 31))["cols"]
    assert at_minimum[f"avg_earnings_{years}y"] is not None  # FY25..FY(24+years) = exactly `years` FYs


# ── TCS through the pipeline: visibility, dates, EPS, book value per share, screens ──────────────────────────────

TCS_BROADCASTS = ((TCS_Q4FY26, datetime(2026, 4, 9, 6, 12, 18)), (TCS_AR26, datetime(2026, 8, 8, 19, 52, 19)),
                  (TCS_Q2FY27, datetime(2026, 10, 8, 4, 38, 10)))  # UTC (listing / file-name times)  # fmt: skip


@pytest.fixture(scope="module")
def tcs(tmp_path_factory):
    root = tmp_path_factory.mktemp("tcs_pl")
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
    equity = m.con.execute(
        "SELECT value_inr FROM fact_observations WHERE canonical_tag = 'equity_attributable_to_owners' "
        "AND period_end = DATE '2026-09-30'"
    ).fetchone()[0]
    m.con.close()
    return root, row, equity


def test_tcs_quarter_and_year_lines(tcs):
    _, r, _ = tcs
    q = ("2026-07-01", "2026-09-30")
    assert r["sales_latest_quarter"] == _filed(TCS_Q2FY27, *q, "RevenueFromOperations")
    assert r["net_profit_latest_quarter"] == _filed(TCS_Q2FY27, *q, OWNERS)
    assert r["sales_2quarters_back"] == _filed(TCS_Q4FY26, "2026-01-01", "2026-03-31", "RevenueFromOperations")
    assert r["sales_preceding_quarter"] is None  # Q1 FY27 is not committed (H1 - Q2 is not a filed YTD pair)
    # FY26 from the Q4 results (they outrank the annual report on P&L lines [X100]); FY25 from its comparatives.
    fy26 = ("2025-04-01", "2026-03-31")
    assert r["sales_last_year"] == _filed(TCS_Q4FY26, *fy26, "RevenueFromOperations") == Decimal("2670210000000.00")
    assert r["sales_preceding_year"] == _ar("RevenueFromOperations") == Decimal("2553240000000")
    assert r["pat_preceding_year"] == _ar("ProfitLossForPeriod") == Decimal("487970000000")
    assert r["npm_preceding_year_pct"] == pytest.approx(float(Decimal("485530000000") / Decimal("2553240000000")))
    assert r["opm_last_year_pct"] == pytest.approx(float(_ebitda(lambda e: _filed(TCS_Q4FY26, *fy26, e))
                                                         / Decimal("2670210000000")))  # fmt: skip
    assert r["gpm_last_year_pct"] is None  # services: COGS far below 10% of sales [C6]
    assert r["equity_capital_latest_quarter"] == _filed(TCS_Q2FY27, *q, "PaidUpValueOfEquityShareCapital")
    for c in (*HISTORY_COLUMNS, *(f"eps_growth_{n}y_pct" for n in F.GROWTH_YEARS), "sales_ttm_1y_back"):
        assert r[c] is None, c


def test_tcs_eps_result_dates_and_book_value_per_share(tcs):
    _, r, equity = tcs
    eps = "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"
    assert r["eps_latest_quarter"] == _filed(TCS_Q2FY27, "2026-07-01", "2026-09-30", eps) == Decimal("38.37")
    assert r["eps_last_year"] == _filed(TCS_Q4FY26, "2025-04-01", "2026-03-31", eps) == Decimal("136.01")
    # IST dates of the first visibility: 08-Oct-2026 10:08 IST (Q2 FY27); FY26 first seen in the Q4 results.
    assert r["last_result_date"] == date(2026, 10, 8)
    assert r["last_annual_result_date"] == date(2026, 4, 9)
    assert r["shares"] and r["book_value_per_share"] == (Decimal(equity) / r["shares"]).quantize(Decimal("0.0001"))
    assert r["is_trade_to_trade"] is False and r["series"] == "EQ"


def test_dsl_aliases_screen_and_output_columns(tcs):
    root, r, _ = tcs
    from financials.db import connect

    con = connect(root / "market.duckdb", read_only=True)
    try:
        (row,) = run_screen(con, "Sales latest quarter > 70000 AND OPM last year > 25 AND Book value > 0",
                            columns=["Net profit preceding year", "Sales last year / Sales preceding year",
                                     "EPS latest quarter", "Last result date", "Sales growth 3Years"])  # fmt: skip
    finally:
        con.close()
    assert row["symbol"] == "TCS"
    assert float(row["sales latest quarter"]) == pytest.approx(float(r["sales_latest_quarter"]) / 1e7)
    assert row["book value"] == r["book_value_per_share"]
    assert float(row["net profit preceding year"]) == pytest.approx(48553.0)
    assert float(row["sales last year / sales preceding year"]) == pytest.approx(267021 / 255324)
    assert row["last result date"] == 20261008 and row["sales growth 3years"] is None


def test_cli_columns_order_by_and_saved_ratios(tcs):
    root, _, _ = tcs

    def cli(*args) -> tuple[int, str]:
        out = io.StringIO()
        return main(["--data-dir", str(root), *args], out=out), out.getvalue()

    code, out = cli("save-ratio", "fy sales growth", "Sales last year / Sales preceding year - 1")
    assert code == 0, out
    code, out = cli("ratios")
    assert json.loads(out) == {"fy sales growth": "Sales last year / Sales preceding year - 1"}
    assert cli("save-ratio", "bad", "Sales last year / nope")[0] == 2
    code, out = cli("screen", "Current price > 0", "--columns", "fy sales growth, OPM last year, NPM latest quarter",
                    "--order-by", "fy sales growth", "--desc", "--limit", "5")  # fmt: skip
    assert code == 0, out
    rows = json.loads(out)
    assert len(rows) == 5 and rows[0]["symbol"] == "TCS"  # the only company with two fiscal years: NULLs last
    assert float(rows[0]["fy sales growth"]) == pytest.approx(267021 / 255324 - 1)
    assert float(rows[0]["opm last year"]) == pytest.approx(27.11, abs=0.01)
    assert all(r["fy sales growth"] is None for r in rows[1:])
    code, out = cli("screen", "Market cap > 0", "--columns", "nonsense metric")
    assert code == 2 and "unknown metric" in out


# ── Batch 0: aliases, trade-to-trade ──────────────────────────────────────────────────────────────────────────────


def test_trade_to_trade_flag_follows_the_current_series(full_market):
    rows = compute_rows(full_market.con, date(2026, 11, 12))
    by_series: dict[str, set] = {}
    for r in rows:
        by_series.setdefault(r["series"], set()).add(r["is_trade_to_trade"])
    assert by_series["EQ"] == {False}
    assert by_series["BE"] == {True} and by_series["BZ"] == {True}


def test_book_value_alias_is_per_share_and_net_worth_is_crore():
    assert ALIASES["book value"][0] == "book_value_per_share"
    assert ALIASES["net worth"][0] == "(total_equity / 10000000)"
    sql = compile_screen(
        "Shares > 0 AND Restatement suspected = 0 AND Non promoter non public holding < 5 AND Annual FY end > 20250101 "
        "AND Trade to trade = 0 AND OPM same quarter last year > 0 AND Sales 2 quarters back > 0 "
        "AND Sales growth 5Years median > 0 AND Average earnings 5Year > 0 AND YOY Quarterly sales growth > 0 "
        "AND EPS growth 3Years > 0 AND Days since last result < 30"
    ).where_sql
    for col in ("shares", "restatement_suspected", "non_promoter_non_public_pct", "annual_fy_end",
                "is_trade_to_trade", "opm_preceding_year_quarter_pct", "sales_2quarters_back",
                "sales_growth_median_5y_pct", "avg_earnings_5y", "sales_growth_yoy_quarter_pct",
                "eps_growth_3y_pct", "last_result_date"):  # fmt: skip
        assert col in sql, col


def test_every_new_column_has_an_alias_and_a_schema_column():
    from financials.db import declared_columns

    cols = {c for c, _ in declared_columns()["screener_features"]}
    assert set(F.OUTPUT_COLUMNS) | {"opm_preceding_year_quarter_pct"} <= cols
    used = " ".join(sql for sql, _ in ALIASES.values())
    assert [c for c in (*F.OUTPUT_COLUMNS, "opm_preceding_year_quarter_pct") if c not in used] == []


def test_columns_option_parsing_and_validation():
    assert split_columns(" Sales latest quarter , OPM last year,,") == ["Sales latest quarter", "OPM last year"]
    assert split_columns(None) == []
    from financials.db import apply_schema, connect

    con = connect()
    apply_schema(con)
    with pytest.raises(DslError):
        save_custom_ratio(con, "book value", "Sales")  # built-in name
    save_custom_ratio(con, "op margin fy", "Operating profit last year / Sales last year * 100")
    assert run_screen(con, "Market cap > 0", columns=["op margin fy"]) == []  # empty table, valid SQL
    con.close()
