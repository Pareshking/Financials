"""Owner requirements items 1, 3 and 4 (docs/owner_requirements.md): QoQ sales and profit growth, NPM, interest
coverage, OPM of the same quarter last year, dividend yield and payout, promoter holding QoQ change.

Every expected value is read from the committed fixture itself (the stdlib XBRL reader in _fixture_helpers, or the
corporate-actions JSON as filed), never from our parser: Finolex Cables' Q4 FY25, Q1 FY26 and Q2 FY26 consolidated
results (three consecutive quarters), the NSE corporate-actions files (ABINFRA dividend then 10:1 split; ONGC
dividend ex 12 Nov 2026), and Reliance's Reg. 31 patterns for 2025-03-31 and 2025-06-30.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES, XBRL_DIR, load_instance
from financials.features import (
    _dividend_columns,
    _preload,
    _quarterly_columns,
    compute_rows,
    shareholding_columns,
    trailing_dividend_per_share,
)
from financials.fundamentals import (
    FactBook,
    _add_months,
    building_blocks,
    interest_coverage,
    qoq_growth,
    quarter_opm,
    quarter_rev_ops,
    safe_div,
)
from financials.parsers.integrated import parse_integrated_results
from financials.promoter import promote
from financials.scope import MIN_TRADE_DATE
from financials.staging import stage_corp_actions, stage_shareholding

FINCABLES = {  # consolidated, three consecutive quarters
    date(2025, 3, 31): "INTEGRATED_FILING_INDAS_1456174_29052025103806_WEB.xml",  # Q4 FY25 + FY25
    date(2025, 6, 30): "INTEGRATED_FILING_INDAS_1510705_13082025092940_WEB.xml",  # Q1 FY26
    date(2025, 9, 30): "INTEGRATED_FILING_INDAS_1571804_11112025093544_WEB.xml",  # Q2 FY26 + H1
}
CA_2025 = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
CA_NOV_2026 = FIXTURES / "corp_actions" / "nse_corporateActions_equities_21-10-2026_19-11-2026.json"
REL_MAR25 = XBRL_DIR / "SHP_198754_1421266_21042025041033_WEB.xml"
REL_JUN25 = XBRL_DIR / "SHP_1489727_21072025081003_WEB.xml"


def _filed(end: date, element: str, months: int = 3) -> Decimal:
    """Value of `element` in the undimensioned `months`-long context ending `end`, straight from the XML."""
    first = _add_months(date(end.year, end.month, 1), -(months - 1))
    inst = load_instance(XBRL_DIR / FINCABLES[end])
    (v,) = [v for (name, ctx), v in inst.numeric.items() if name == element and not inst.contexts[ctx].has_dimensions
            and (inst.contexts[ctx].start, inst.contexts[ctx].end) == (str(first), str(end))]  # fmt: skip
    return v


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


# ── item 1: QoQ sales / profit, OPM last year, NPM, interest coverage ─────────────────────────────────────────────


def test_qoq_sales_and_profit_growth_compare_the_two_latest_quarters(fincables):
    q2, q1 = date(2025, 9, 30), date(2025, 6, 30)
    assert quarter_rev_ops(fincables, q2) == _filed(q2, "RevenueFromOperations") == Decimal("13757900000")
    assert quarter_rev_ops(fincables, q1) == _filed(q1, "RevenueFromOperations") == Decimal("13955200000")
    cols = _quarterly_columns(fincables, q2)
    assert cols["sales_growth_qoq_pct"] == pytest.approx(float(Decimal("13757.9") / Decimal("13955.2") - 1))
    owners = "ProfitOrLossAttributableToOwnersOfParent"
    assert cols["profit_growth_qoq_pct"] == pytest.approx(float(_filed(q2, owners) / _filed(q1, owners) - 1))
    assert cols["profit_growth_qoq_pct"] == pytest.approx(1626.4 / 1626.2 - 1)
    # Q1 FY26 vs Q4 FY25 crosses a fiscal year: still the adjacent quarter, still the same scope.
    assert _quarterly_columns(fincables, q1)["sales_growth_qoq_pct"] == pytest.approx(13955.2 / 15945.8 - 1)
    # The quarter before Q4 FY25 is outside the data (C9): no QoQ, never a longer-gap change.
    first = _quarterly_columns(fincables, date(2025, 3, 31))
    assert first["sales_growth_qoq_pct"] is None and first["profit_growth_qoq_pct"] is None


def test_qoq_growth_is_null_on_a_missing_or_non_positive_base():
    assert qoq_growth(Decimal(5), None) is None and qoq_growth(None, Decimal(5)) is None
    assert qoq_growth(Decimal(5), Decimal(0)) is None and qoq_growth(Decimal(5), Decimal(-1)) is None
    assert qoq_growth(Decimal(-3), Decimal(2)) == Decimal("-2.5")


def test_opm_preceding_year_quarter_is_the_same_quarter_one_year_earlier(fincables):
    """Built as `opm_last_year_pct` in features 2026.11.15-3; renamed in -4A (Screener's "OPM last year" is the
    fiscal year's OPM, now `opm_last_year_pct`, see tests/test_period_pl_family.py). Same definition."""
    q4 = date(2025, 3, 31)
    adds = ("ProfitBeforeExceptionalItemsAndTax", "FinanceCosts", "DepreciationDepletionAndAmortisationExpense")
    ebitda = sum(_filed(q4, e) for e in adds) - _filed(q4, "OtherIncome")
    assert ebitda == Decimal("1708400000")  # 2,126.8 + 5.0 + 124.2 - 547.6 crore
    assert quarter_opm(fincables, q4) == ebitda / Decimal("15945800000")
    # Were Q4 FY26 the latest quarter, OPM of the preceding year quarter would be Q4 FY25's quarterly OPM...
    assert _quarterly_columns(fincables, date(2026, 3, 31))["opm_preceding_year_quarter_pct"] == pytest.approx(
        float(ebitda / Decimal("15945800000"))
    )
    # ... while for Q2 FY26 the same quarter of FY25 is before the financials cutoff, so it stays NULL.
    assert _quarterly_columns(fincables, date(2025, 9, 30))["opm_preceding_year_quarter_pct"] is None


def test_npm_and_interest_coverage_use_the_ttm_window(fincables):
    """FY25 is the TTM to Q4 FY25 (the filing's own 12-month context, §6.5 bridge)."""
    b = building_blocks(fincables, date(2025, 3, 31))
    fy = {e: _filed(date(2025, 3, 31), e, months=12) for e in ("RevenueFromOperations", "ProfitBeforeTax",
          "FinanceCosts", "ProfitOrLossAttributableToOwnersOfParent")}  # fmt: skip
    assert (b["rev_ops"], b["pbt"], b["finance_costs"]) == (
        fy["RevenueFromOperations"], fy["ProfitBeforeTax"], fy["FinanceCosts"])  # fmt: skip
    assert safe_div(b["pat_owners"], b["rev_ops"]) == Decimal("7007700000") / Decimal("53188900000")
    ic = interest_coverage(b["pbt"], b["finance_costs"])
    assert ic == (Decimal("9224500000") + Decimal("16700000")) / Decimal("16700000")  # 553.4x: almost debt-free
    assert interest_coverage(b["pbt"], Decimal(0)) is None and interest_coverage(b["pbt"], Decimal(-1)) is None
    assert interest_coverage(None, b["finance_costs"]) is None


# ── item 4: dividend yield and payout ─────────────────────────────────────────────────────────────────────────────


def _row(rows, symbol):
    (r,) = [r for r in rows if r["symbol"] == symbol]
    return r


@pytest.fixture(scope="module")
def dividends_2025(tmp_path_factory):
    from conftest import Market

    m = Market(tmp_path_factory.mktemp("div2025"))
    for d in ("20250919", "20250922", "20250923", "20251013", "20251014", "20251017", "20251020", "20251021",
              "20251023"):  # fmt: skip
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"
    st = stage_corp_actions(m.vault, m.stage_root, data=CA_2025.read_bytes(), source_url="nse-ca",
                            fetched_at=FETCHED_AT)  # fmt: skip
    assert promote(m.con, st).status == "PROMOTED"
    yield m
    m.con.close()


def test_dividend_yield_restates_a_dividend_to_todays_share_basis(dividends_2025):
    """ABINFRA: 'Dividend - Re 0.05 Per Share' ex 22-Sep-2025, then a 10:1 face-value split ex 17-Oct-2025. On
    23 Oct 2025 a holder of one pre-split share holds ten, so the trailing dividend is Rs 0.005 per share held now."""
    con = dividends_2025.con
    ledger = con.execute(
        "SELECT DISTINCT c.action_type, c.ex_date, c.cash_per_share, c.eps_factor, c.status FROM corp_actions c "
        "JOIN security_identifier_history h USING (security_id) WHERE h.symbol = 'ABINFRA' ORDER BY 2"
    ).fetchall()
    assert ledger == [("DIVIDEND", date(2025, 9, 22), Decimal("0.0500"), 1.0, "UNOBSERVABLE"),
                      ("SPLIT", date(2025, 10, 17), None, 0.1, "VERIFIED")]  # fmt: skip
    r = _row(compute_rows(con, date(2025, 10, 23)), "ABINFRA")
    assert r["dividend_yield_pct"] == pytest.approx(float(Decimal("0.005") / r["close"]))
    assert r["dividend_payout_pct"] is None  # no results filing: no EPS
    before_split = _row(compute_rows(con, date(2025, 10, 14)), "ABINFRA")
    assert before_split["dividend_yield_pct"] == pytest.approx(float(Decimal("0.05") / before_split["close"]))


def test_only_dividends_the_total_return_index_uses_count(dividends_2025):
    """SHILPAMED: 'Dividend - Re 1 Per Share' ex 17-Sep-2025 is still PENDING (no bar on its ex-date in these
    fixtures), so the TR index does not add it; its 1:1 bonus ex 3-Oct-2025 is PENDING too, so the halved open on
    13 Oct is an unexplained gap that freezes the series: NULL, like momentum, never a yield on an unadjusted basis.
    RELIANCE has no dividend ex in the window: 0, not NULL (the window is fully inside the data)."""
    con = dividends_2025.con
    assert con.execute(
        "SELECT DISTINCT c.action_type, c.status FROM corp_actions c JOIN security_identifier_history h "
        "USING (security_id) WHERE h.symbol = 'SHILPAMED' ORDER BY 1"
    ).fetchall() == [("BONUS", "PENDING"), ("DIVIDEND", "PENDING")]
    assert con.execute(
        "SELECT q.reason_code FROM quarantine_queue q JOIN security_identifier_history h USING (security_id) "
        "WHERE h.symbol = 'SHILPAMED' AND q.stage = 'GAP'"
    ).fetchall() == [("UNEXPLAINED_GAP",)]
    rows = compute_rows(con, date(2025, 10, 23))
    assert _row(rows, "SHILPAMED")["dividend_yield_pct"] is None
    assert _row(rows, "RELIANCE")["dividend_yield_pct"] == 0.0


def test_ongc_interim_dividend_and_payout_without_ttm_eps(tmp_path):
    """ONGC 'Interim Dividend - Rs 8 Per Share' ex 12-Nov-2026 (NSE corporate-actions file). Yield = 8 / close on
    12 Nov 2026; payout stays NULL: only Q2 FY27 results are committed for ONGC, so there is no TTM EPS."""
    from conftest import Market

    from financials.staging import stage_results_xbrl

    m = Market(tmp_path)
    for d in ("20251023", "20261112"):  # the ex-date bar and a previous close: the dividend is then UNOBSERVABLE
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"
    st = stage_corp_actions(m.vault, m.stage_root, data=CA_NOV_2026.read_bytes(), source_url="nse-ca",
                            fetched_at=FETCHED_AT)  # fmt: skip
    assert promote(m.con, st).status == "PROMOTED"
    ongc = next(XBRL_DIR.glob("INTEGRATED_FILING_INDAS_1753920_*.xml"))
    promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=ongc.read_bytes(), source_url="nse-ongc",
                                      fetched_at=FETCHED_AT, broadcast_ts=datetime(2026, 11, 6),
                                      broadcast_ts_source="API_FIELD"))  # fmt: skip
    assert m.con.execute(
        "SELECT DISTINCT c.cash_per_share, c.status FROM corp_actions c JOIN security_identifier_history h "
        "USING (security_id) WHERE h.symbol = 'ONGC' AND c.action_type = 'DIVIDEND'"
    ).fetchall() == [(Decimal("8.0000"), "UNOBSERVABLE")]
    r = _row(compute_rows(m.con, date(2026, 11, 12)), "ONGC")
    assert r["dividend_yield_pct"] == pytest.approx(float(Decimal(8) / r["close"]))
    assert r["eps_ttm"] is None and r["dividend_payout_pct"] is None
    m.con.close()


def test_trailing_dividends_window_and_payout_rules():
    divs = [(date(2025, 9, 22), Decimal("0.05"))]  # ABINFRA, as filed
    split = [(date(2025, 10, 17), Decimal("0.1"), Decimal("0.1"))]
    # C9: a window reaching before MIN_TRADE_DATE (no corporate actions held) is NULL, not a partial sum.
    first_full = MIN_TRADE_DATE + timedelta(days=364)
    assert trailing_dividend_per_share(divs, split, first_full - timedelta(days=1)) is None
    assert trailing_dividend_per_share([], split, first_full) == 0
    assert trailing_dividend_per_share(divs, split, date(2025, 10, 16)) == Decimal("0.05")
    assert trailing_dividend_per_share(divs, split, date(2025, 10, 17)) == Decimal("0.005")
    bars = [(date(2025, 10, 23), Decimal("2.50"), None)]
    d = date(2025, 10, 23)
    cols = _dividend_columns(divs, split, d, bars, None, Decimal("0.02"))
    assert cols["dividend_yield_pct"] == pytest.approx(0.002) and cols["dividend_payout_pct"] == pytest.approx(0.25)
    assert _dividend_columns(divs, split, d, bars, None, Decimal("-0.02"))["dividend_payout_pct"] is None
    assert _dividend_columns(divs, split, d, bars, None, Decimal(0))["dividend_payout_pct"] is None
    # An unexplained price gap freezes the series: a missed split would mis-state the yield.
    frozen = _dividend_columns(divs, split, date(2025, 10, 23), bars, date(2025, 10, 20), Decimal("0.02"))
    assert frozen == {"dividend_yield_pct": None, "dividend_payout_pct": None}


# ── item 3: promoter holding QoQ change ───────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def reliance_shp(tmp_path_factory):
    from conftest import Market

    m = Market(tmp_path_factory.mktemp("rel_shp"))
    assert promote(m.con, m.stage_day("20250919")).status == "PROMOTED"
    for path, ts in ((REL_MAR25, datetime(2025, 4, 21, 4, 10)), (REL_JUN25, datetime(2025, 7, 21, 8, 10))):
        st = stage_shareholding(m.vault, m.stage_root, data=path.read_bytes(), source_url="https://nsearchives."
                                "nseindia.com/corporate/xbrl/" + path.name, fetched_at=FETCHED_AT, broadcast_ts=ts,
                                broadcast_ts_source="API_FIELD")  # fmt: skip
        assert promote(m.con, st).status == "PROMOTED"
    yield m
    m.con.close()


def _promoter_pct(path) -> Decimal:
    """Promoter & promoter group % as filed (percent points in both files, SHP18)."""
    inst = load_instance(path)
    (v,) = [v for (name, ctx), v in inst.numeric.items() if name == "ShareholdingAsAPercentageOfTotalNumberOfShares"
            and ctx.startswith("ShareholdingOfPromoterAndPromoterGroup")]  # fmt: skip
    return v


def test_promoter_holding_change_between_adjacent_reg31_quarters(reliance_shp):
    """Reliance promoter & promoter group 50.11% (2025-03-31) -> 50.07% (2025-06-30): -0.04 percentage points."""
    assert (_promoter_pct(REL_MAR25), _promoter_pct(REL_JUN25)) == (Decimal("50.11"), Decimal("50.07"))
    shp, _, _ = _preload(reliance_shp.con, datetime(2025, 9, 20))
    (cur,) = [v for v in shp.values() if v.get("_as_of")]
    assert (cur["_as_of"], cur["_prev_as_of"]) == (date(2025, 6, 30), date(2025, 3, 31))
    assert shareholding_columns(cur)["promoter_holding_change_qoq_pp"] == pytest.approx(-0.04)
    # Point in time: before the June pattern is broadcast only March is visible, so there is no change.
    shp, _, _ = _preload(reliance_shp.con, datetime(2025, 7, 1))
    (cur,) = [v for v in shp.values() if v.get("_as_of")]
    assert cur["_as_of"] == date(2025, 3, 31) and shareholding_columns(cur)["promoter_holding_change_qoq_pp"] is None
    r = _row(compute_rows(reliance_shp.con, date(2025, 9, 19)), "RELIANCE")
    assert r["promoter_holding_change_qoq_pp"] == pytest.approx(-0.04)


def test_promoter_change_needs_the_immediately_preceding_quarter(reliance_shp):
    shp, _, _ = _preload(reliance_shp.con, datetime(2025, 9, 20))
    (cur,) = [dict(v) for v in shp.values() if v.get("_as_of")]
    cur["_prev_as_of"] = date(2024, 12, 31)  # two quarters back
    assert shareholding_columns(cur)["promoter_holding_change_qoq_pp"] is None


def test_dsl_aliases_reach_the_new_columns():
    from financials.dsl import compile_screen

    sql = compile_screen(
        "QoQ Sales > 5 AND QoQ Profits > 5 AND NPM > 10 AND Interest coverage > 3 AND OPM same quarter last year > 10 "
        "AND Dividend yield > 1 AND Dividend payout < 60 AND Change in promoter holding > 0"
    ).where_sql
    for col in ("sales_growth_qoq_pct", "profit_growth_qoq_pct", "npm_pct", "interest_coverage",
                "opm_preceding_year_quarter_pct",
                "dividend_yield_pct", "dividend_payout_pct", "promoter_holding_change_qoq_pp"):  # fmt: skip
        assert col in sql
