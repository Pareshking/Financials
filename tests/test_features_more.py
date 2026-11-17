"""Batch I: the last BUILDABLE NOW rows of docs/ratio_catalogue.md [features_more].

Real fixtures where the data exists: TCS FY26 Reg. 34 annual report (Beneish / Piotroski components behind the
pinned beneish_m -2.3193 and piotroski_f 5, accruals, depreciation rate, asset age, FY days changes) and Cummins Q2
FY27 consolidated (segment count and largest-segment share, promoted point in time). Price windows (252 bars),
PEAD (index closes), index events (90 days of snapshots), H1 YoY days and segment YoY have no in-scope history in
the fixtures (C9): they are NULL on the full market and pinned on synthetic inputs.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials import features_more as M
from financials.db import apply_schema, connect, declared_columns, table_columns
from financials.dsl import ALIASES, compile_screen
from financials.features import compute_rows
from financials.features_audit import COLUMNS as AUDIT_COLUMNS
from financials.features_disclosures import COLUMNS as DISCLOSURE_COLUMNS
from financials.features_rpt import RPT_COLUMNS
from financials.features_store import write_rows as write_history
from financials.fundamentals import BENEISH, FactBook, _add_months, annual_ratios, building_blocks, load_segments
from financials.parsers.reg34_annual import parse_reg34_annual

Q = Decimal
TCS26 = XBRL_DIR / "AR_XBRL_TCS_09082026012216.xml"
MAR26, MAR25 = date(2026, 3, 31), date(2025, 3, 31)
FY26 = (date(2025, 4, 1), MAR26)


def _book(r, scope=None) -> FactBook:
    b = FactBook("e", scope or r.meta["scope"])
    for f in r.facts:
        if f.period_type == "INSTANT":
            b.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
        else:
            b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return b


@pytest.fixture(scope="module")
def tcs() -> FactBook:
    return _book(parse_reg34_annual(TCS26.read_bytes(), TCS26.name))


# ── B1.2 / B1.3 / B1.7 / B2.12 / B3.2 on TCS FY26 (real) ──────────────────────────────────────────────────────────


def test_beneish_and_piotroski_components_rebuild_the_pinned_scores(tcs):
    end = date(2026, 9, 30)
    out = M.forensic_components(tcs, end)
    scores = annual_ratios(tcs, end)
    m = BENEISH["const"] + sum(BENEISH[k] * Q(str(out[f"beneish_{k.lower()}"])) for k in M.BENEISH_KEYS)
    assert float(m) == pytest.approx(float(scores["beneish_m"]), abs=1e-9)
    assert float(scores["beneish_m"]) == pytest.approx(-2.3193, abs=1e-4)  # test_batch9_annual pin
    rev = tcs.durations["revenue_from_operations"]
    assert out["beneish_sgi"] == pytest.approx(float(rev[FY26] / rev[(date(2024, 4, 1), MAR25)]))
    flags = [out[c] for c in M.PIOTROSKI_COLUMNS]
    assert all(isinstance(f, bool) for f in flags) and sum(flags) == scores["piotroski_f"] == 5
    assert out["piotroski_roa_positive"] is True and out["piotroski_cfo_positive"] is True
    # FY25 alone (prior year before the cutoff): all components NULL, like the scores
    fy25 = FactBook("e", tcs.scope)
    fy25.durations = {t: {p: v for p, v in d.items() if p[1] <= MAR25} for t, d in tcs.durations.items()}
    fy25.instants = {t: {p: v for p, v in d.items() if p <= MAR25} for t, d in tcs.instants.items()}
    assert set(M.forensic_components(fy25, end).values()) == {None}


def test_accruals_depreciation_rate_and_asset_age(tcs):
    end = date(2026, 9, 30)
    v = M.period_values(tcs, end, building_blocks(tcs, end))
    g = lambda t, d: tcs.instants[t][d]  # noqa: E731

    def noa(d):
        debt = (
            g("borrowings_noncurrent", d)
            + g("borrowings_current", d)
            + sum(
                tcs.instants.get(t, {}).get(d) or 0
                for t in ("lease_liabilities_noncurrent", "lease_liabilities_current")
            )
        )
        cash = g("cash_and_equivalents", d) + g("bank_balances_other", d) + g("current_investments", d)
        return g("total_equity", d) + debt - cash  # fmt: skip

    avg_ta = (g("total_assets", MAR26) + g("total_assets", MAR25)) / 2
    assert v["bs_accruals"] == pytest.approx(float((noa(MAR26) - noa(MAR25)) / avg_ta))
    gb = tcs.instants["ppe_gross_block"]
    assert gb[MAR26] / Q(10) ** 7 == pytest.approx(39208, abs=1)  # test_batch9_annual
    dep = tcs.durations["depreciation_amortisation"][FY26]
    if MAR25 in gb:
        assert v["depreciation_rate"] == pytest.approx(float(dep / ((gb[MAR26] + gb[MAR25]) / 2)))
    else:
        assert v["depreciation_rate"] is None
    acc = tcs.instants.get("ppe_accumulated_depreciation", {}).get(MAR26)
    assert v["asset_age_proxy"] == (None if acc is None else pytest.approx(float(acc / gb[MAR26])))
    # TCS FY26 consolidated, pinned: accruals 8.23%, D&A / avg gross block 14.54%, 71.86% of the block depreciated
    assert (v["bs_accruals"], v["depreciation_rate"], v["asset_age_proxy"]) == pytest.approx(
        (0.0823, 0.1454, 0.7186), abs=1e-4)  # fmt: skip
    assert v["_altman"] is None  # services: COGS < 10% of sales, not a manufacturer (C6 guard)


def test_fy_days_changes_tcs(tcs):
    from financials.features_bs import _days

    v = M.days_columns(tcs, date(2026, 9, 30), FY26)
    now, before = _days(tcs, MAR26), _days(tcs, MAR25)
    assert v["debtor_days_change_yoy"] == pytest.approx(float(now["debtor_days"] - before["debtor_days"]))
    # services: inventory / payable days blank, so the cycle is the debtor days (S23)
    assert v["ccc_change_yoy"] == pytest.approx(v["debtor_days_change_yoy"])
    assert v["debtor_days_change_yoy"] == pytest.approx(8.15, abs=0.01)
    assert v["h1_bs_as_of"] is None  # an annual report has no half-year balance sheet


# ── synthetic books: H1 days, original Altman Z ───────────────────────────────────────────────────────────────────


def _h1_book() -> FactBook:
    book = FactBook("SYN", "CONSOLIDATED")
    for q, rev, mat in ((date(2025, 6, 30), 900, 400), (date(2025, 9, 30), 1100, 500), (date(2026, 6, 30), 1000, 450),
                        (date(2026, 9, 30), 1400, 550)):  # fmt: skip
        p = (_add_months(date(q.year, q.month, 1), -2), q)
        book.durations.setdefault("revenue_from_operations", {})[p] = Q(rev)
        book.durations.setdefault("cost_of_materials_consumed", {})[p] = Q(mat)
        book.durations.setdefault("pat", {})[p] = Q(10)
    for d, rec, inv in ((date(2025, 9, 30), 400, 300), (date(2026, 9, 30), 600, 250)):
        book.instants.setdefault("total_assets", {})[d] = Q(5000)
        book.instants.setdefault("trade_receivables_current", {})[d] = Q(rec)
        book.instants.setdefault("inventories", {})[d] = Q(inv)
    book.instants["total_assets"][MAR26] = Q(5000)  # a fiscal-year end is never the "half year"
    book.durations["pat"][FY26] = Q(40)
    return book


def test_half_year_days_and_yoy():
    book = _h1_book()
    v = M.days_columns(book, date(2026, 9, 30), None)
    assert v["h1_bs_as_of"] == date(2026, 9, 30)
    assert v["debtor_days_h1"] == pytest.approx(600 * 365 / (2 * 2400))
    assert v["inventory_days_h1"] == pytest.approx(250 * 365 / (2 * 1000))
    assert v["debtor_days_h1_change_yoy"] == pytest.approx(600 * 365 / 4800 - 400 * 365 / 4000)
    assert v["inventory_days_h1_change_yoy"] == pytest.approx(250 * 365 / 2000 - 300 * 365 / 1800)
    v = M.days_columns(book, date(2026, 6, 30), None)  # latest non-FY balance sheet within 12 months: Sep-2025
    assert v["h1_bs_as_of"] == date(2025, 9, 30) and v["debtor_days_h1_change_yoy"] is None  # Sep-2024: before C9


def test_original_altman_z():
    b = {"gross_profit": Q(1), "current_assets": Q(500), "current_liabilities": Q(300), "other_equity": Q(400),
         "ebit": Q(150), "total_assets": Q(1000), "total_liabilities": Q(600), "rev_ops": Q(1200)}  # fmt: skip
    z = M.altman_z_original(M.altman_inputs(b), Q(900))
    assert z == Q("1.2") * Q("0.2") + Q("1.4") * Q("0.4") + Q("3.3") * Q("0.15") + Q("0.6") * Q("1.5") + Q("1.2")
    assert M.altman_inputs({**b, "gross_profit": None}) is None  # not a manufacturer (C6 guard)
    assert M.altman_z_original(M.altman_inputs(b), None) is None


# ── price: volatility, drawdown, delivery spike, PEAD ─────────────────────────────────────────────────────────────

DAYS = [date(2025, 1, 1) + timedelta(days=i) for i in range(300)]


def _bars(closes, vols=None, deliv=None):
    vols = vols or [1000] * len(closes)
    deliv = deliv or [500] * len(closes)
    return [(d, Q(str(c)), v, dv) for d, c, v, dv in zip(DAYS, closes, vols, deliv, strict=False)]


def test_volatility_and_drawdown_need_a_full_year():
    closes = [100 * (1.01 if i % 2 else 0.99) ** (i % 7) for i in range(260)]
    adj = M.adjust(_bars(closes), [], None)
    rets = [math.log(b / a) for a, b in zip(closes[-253:-1], closes[-252:], strict=True)]
    assert M.volatility([b[1] for b in adj]) == pytest.approx(statistics.stdev(rets) * math.sqrt(252))
    path = [100] * 100 + [120] * 50 + [90] * 110
    assert M.max_drawdown([float(c) for c in path]) == pytest.approx(90 / 120 - 1)
    assert M.volatility(closes[:252]) is None and M.max_drawdown(path[:251]) is None


def test_split_adjusts_closes_and_delivery():
    bars = _bars([200] * 10 + [100] * 10, deliv=[100] * 10 + [200] * 10)
    adj = M.adjust(bars, [(DAYS[10], Q("0.5"), Q(2))], None)
    assert {b[1] for b in adj} == {100.0} and {b[3] for b in adj} == {200.0}
    assert M.adjust(bars, [], DAYS[5])[-1][0] == DAYS[4]  # frozen from the gap: stop before it


def test_new_52w_high_on_delivery_spike():
    closes = [100] * 251 + [110]
    spike = M.adjust(_bars(closes, deliv=[100] * 251 + [201]), [], None)
    assert M.delivery_spike_high(spike) is True
    assert M.delivery_spike_high(M.adjust(_bars(closes, deliv=[100] * 251 + [200]), [], None)) is False
    lower = M.adjust(_bars([100] * 251 + [99], deliv=[100] * 251 + [999]), [], None)
    assert M.delivery_spike_high(lower) is False  # not a new high
    assert M.delivery_spike_high(spike[:200]) is None  # fewer than 252 bars
    holes = M.adjust(_bars(closes, deliv=[None] * 252), [], None)
    assert M.delivery_spike_high(holes) is None


def test_pead_abnormal_return_and_relative_volume():
    closes = [100] * 30 + [110, 112] + [115] * 30
    vols = [1000] * 30 + [5000, 3000] + [1000] * 30
    adj = M.adjust(_bars(closes, vols), [], None)
    index = {d: 1000.0 for d in DAYS[:62]}
    index[DAYS[30]], index[DAYS[31]], index[DAYS[35]], index[DAYS[50]] = 1010.0, 1020.0, 1000.0, 1050.0
    out = M.pead(adj[:52], DAYS[30], index)
    assert out["pead_event_date"] == DAYS[30]
    assert out["pead_ar_t0"] == pytest.approx(0.10 - 0.01)
    assert out["pead_ar_t1"] == pytest.approx(0.12 - 0.02)
    assert out["pead_ar_t5"] == pytest.approx(0.15)
    assert out["pead_ar_t20"] == pytest.approx(0.15 - 0.05)
    assert out["pead_relvol_t0"] == pytest.approx(5.0) and out["pead_relvol_t1"] == pytest.approx(3.0)
    early = M.pead(adj[:33], DAYS[30], index)  # as of T+2: T+5 and T+20 have not traded yet
    assert early["pead_ar_t1"] is not None and early["pead_ar_t5"] is None and early["pead_relvol_t20"] is None
    del index[DAYS[29]]
    assert M.pead(adj, DAYS[30], index)["pead_ar_t0"] is None  # index close missing at the base
    assert M.pead(adj, DAYS[30], index)["pead_relvol_t0"] == pytest.approx(5.0)
    assert M.pead(adj, None, index) == dict.fromkeys(M.PEAD_COLUMNS)


def test_momentum_and_frozen_rows():
    row = {"return_12m": 0.32, "return_1m": 0.10, "last_result_date": None}
    out = M.price_columns(row, _bars([100] * 5), [], DAYS[4], {})
    assert out["momentum_12m_1m"] == pytest.approx(1.32 / 1.10 - 1)
    assert out["volatility_1y"] is None and out["high_52w_on_delivery_spike"] is None  # today frozen


# ── corporate actions, index events ───────────────────────────────────────────────────────────────────────────────


def test_action_columns():
    as_of = date(2026, 11, 12)
    acts = [(date(2026, 8, 1), "DIVIDEND", True, True), (date(2026, 9, 1), "SPLIT", False, True),  # split pending
            (date(2026, 11, 20), "BONUS", False, True), (date(2026, 11, 20), "DIVIDEND", False, True),
            (date(2026, 11, 15), "SPLIT", False, False)]  # fmt: skip
    out = M.action_columns(acts, as_of)
    assert (out["dividend_365d"], out["bonus_365d"], out["split_365d"]) == (True, False, False)
    assert out["days_to_next_ex_date"] == 8 and out["next_ex_date_action"] == "BONUS+DIVIDEND"  # SPLIT not visible
    early = M.action_columns(acts, date(2025, 6, 30))  # 365-day window starts before 2024-10-01 (C9)
    assert early["dividend_365d"] is None


def _con():
    con = connect()
    apply_schema(con)
    return con


def test_index_inclusion_exclusion_window():
    con = _con()
    rows = [("A", date(2026, 1, 5), date(2026, 9, 20)), ("A", date(2026, 9, 20), None),  # backfill -> snapshot
            ("B", date(2026, 9, 1), None), ("C", date(2026, 1, 5), date(2026, 10, 1))]  # fmt: skip
    con.execute("INSERT INTO entity_master (entity_id, legal_name) VALUES ('e', 'E')")
    for sec, vf, vt in rows:
        con.execute("INSERT OR IGNORE INTO securities VALUES (?, 'e', 'EQ')", [sec])
        con.execute("INSERT INTO index_constituents_history VALUES ('NIFTY 500', ?, ?, ?, 'SNAPSHOT')", [sec, vf, vt])
    covered, ev = M.index_events(con, date(2026, 11, 12))
    assert covered and ev == {"A": (False, False), "B": (True, False), "C": (False, True)}
    covered, ev = M.index_events(con, date(2026, 3, 1))  # history starts 2026-01-05: 90 days not covered
    assert not covered


# ── segments ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _seg(metric, end, key, value, months=3):
    p = (_add_months(date(end.year, end.month, 1), -months + 1), end)
    return (metric, p, months, key.lower(), key, Q(value))


def test_segment_mix_and_yoy():
    sep26, sep25 = date(2026, 9, 30), date(2025, 9, 30)
    rows = [_seg("REVENUE", sep26, "Engines", 700), _seg("REVENUE", sep26, "Lubes", 300),
            _seg("RESULT", sep26, "Engines", 140), _seg("REVENUE", sep25, "Engines", 600),
            _seg("REVENUE", sep25, "Lubes", 200), _seg("RESULT", sep25, "Engines", 90),
            _seg("REVENUE", sep26, "Engines", 1300, months=6)]  # fmt: skip
    out = M.segment_columns(rows)
    assert out["segment_period_end"] == sep26 and out["segment_count"] == 2
    assert out["largest_segment_revenue_share"] == pytest.approx(0.7)
    assert out["fastest_growing_segment"] == "Lubes" and out["fastest_growing_segment_growth_yoy"] == pytest.approx(0.5)
    assert out["largest_segment_margin_change_yoy_pp"] == pytest.approx(0.20 - 0.15)
    assert M.segment_columns(None) == dict.fromkeys(M.SEGMENT_COLUMNS)


def test_cummins_segments_point_in_time(market):
    from conftest import FETCHED_AT

    from financials.promoter import promote
    from financials.staging import stage_results_xbrl

    path = XBRL_DIR / "INTEGRATED_FILING_INDAS_1753292_04112026105837_WEB.xml"
    promote(market.con, market.stage_day("20261112"))
    seen = datetime(2026, 11, 4, 6, 0)
    s = stage_results_xbrl(market.vault, market.stage_root, data=path.read_bytes(),
                           source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + path.name,
                           fetched_at=FETCHED_AT, broadcast_ts=seen, broadcast_ts_source="API_FIELD")  # fmt: skip
    assert promote(market.con, s).status == "PROMOTED"
    ent = market.con.execute("SELECT DISTINCT entity_id FROM filing_meta").fetchone()[0]
    assert M.segment_inputs(market.con, datetime(2026, 11, 3), {ent}) == {}  # before the broadcast
    seg = M.segment_inputs(market.con, datetime(2026, 11, 13), {ent})
    out = M.segment_columns(seg[(ent, "CONSOLIDATED")])
    # Q2 FY27 segment revenue: Engines 3,247.47 Cr, Lubes 1,014.56 Cr (test_segment_observations pins the XML)
    assert out["segment_count"] == 2 and out["segment_period_end"] == date(2026, 9, 30)
    assert out["largest_segment_revenue_share"] == pytest.approx(32474700000 / 42620300000)
    assert out["fastest_growing_segment"] is None  # no Q2 FY26 breakdown in the fixtures
    rows = load_segments(market.con, ent, "CONSOLIDATED", datetime(2026, 11, 13), axis_kind="BUSINESS")
    assert {r.label for r in rows if r.member_role == "SEGMENT"} == {"Engines", "Lubes"}


# ── cross-section: RS rank, industry earnings breadth ─────────────────────────────────────────────────────────────


def test_cross_section_rank_and_breadth():
    end, older = date(2026, 9, 30), date(2026, 6, 30)

    def r(sec, ent, ind, core, mom, mcap=1, fe=end):
        return {"security_id": sec, "entity_id": ent, "nse_industry": ind, "core_profit_yoy_latest_q": core,
                "momentum_12m_1m": mom, "market_cap": mcap, "fundamentals_end": fe}  # fmt: skip

    rows = [r("a", "A", "Cement", 0.2, 0.5), r("b", "B", "Cement", -0.1, 0.1), r("c", "C", "Cement", 0.3, -0.2),
            r("d", "D", "Cement", 0.4, None, fe=older),  # previous season: not counted
            r("c2", "C", "Cement", 0.3, 0.0, mcap=0),  # a second share class: one value per company
            r("e", "E", "IT", 0.1, 0.3), r("f", "F", "IT", 0.2, None)]  # fmt: skip
    M.cross_section(rows)
    by = {x["security_id"]: x for x in rows}
    assert by["a"]["industry_earnings_breadth"] == pytest.approx(2 / 3) and by["a"]["industry_earnings_breadth_n"] == 3
    assert by["e"]["industry_earnings_breadth"] is None  # fewer than 3 companies
    # momentum: -0.2, 0.0, 0.1, 0.3, 0.5 -> share of the others below
    assert [by[s]["rs_rank_12m_1m"] for s in ("c", "c2", "b", "e", "a")] == [0, 0.25, 0.5, 0.75, 1.0]
    assert by["d"]["rs_rank_12m_1m"] is None


def test_percentiles_against_own_quarter_ends():
    hist = {"pb": [2.0, 3.0, 4.0, 5.0], "price_to_sales": [1.0, 2.0, 3.0], "ev_to_sales": [1.0, 1.0, 1.0, 1.0]}
    row = {"security_id": "s", "as_of_date": date(2026, 11, 12), "pb": 3.5, "price_to_sales": 2.5,
           "ev_to_sales": 0.5, "market_cap": None}  # fmt: skip
    out = M.row_columns(row, {}, hist, [], [], None, {}, (False, {}), [], None)
    assert out["pb_percentile"] == 0.5 and out["price_to_sales_percentile"] is None  # 3 quarters < 4
    assert out["ev_to_sales_percentile"] == 0.0


def test_percentile_history_is_read_from_prior_quarter_ends():
    con = _con()
    rows = [{"as_of_date": d, "security_id": "s", "entity_id": "e", "symbol": "S", "series": "EQ", "pb": pb}
            for d, pb in ((date(2026, 3, 30), 2.0), (date(2026, 3, 31), 3.0), (date(2026, 6, 30), 4.0),
                          (date(2026, 10, 1), 9.0))]  # fmt: skip
    write_history(con, rows)
    assert M.valuation_history(con, date(2026, 11, 12))["s"]["pb"] == [3.0, 4.0]


# ── integration: full market, schema, DSL ─────────────────────────────────────────────────────────────────────────


def test_rows_on_the_full_market(full_market):
    rows = {r["symbol"]: r for r in compute_rows(full_market.con, date(2026, 11, 12))}
    assert all(set(M.MORE_COLUMNS) <= set(r) for r in rows.values())
    for r in rows.values():  # C9: no full year of bars, no 90 days of index snapshots, no prior quarter-ends
        assert r["volatility_1y"] is None and r["max_drawdown_1y"] is None and r["rs_rank_12m_1m"] is None
        assert r["nifty500_inclusion_90d"] is None and r["pb_percentile"] is None
        assert r["dividend_365d"] is not None  # window 2025-11-13 .. 2026-11-12 is in scope
    con = connect()
    apply_schema(con)
    cols = table_columns(con, "screener_features_history")
    write_history(con, [{c: r.get(c) for c in cols} for r in rows.values()])
    M.refresh_cross_section(con, date(2026, 11, 12))
    assert con.execute("SELECT count(*) FROM screener_features_history").fetchone()[0] == len(rows)


def test_every_column_is_appended_in_both_tables_and_has_an_alias():
    for t in ("screener_features",):  # the history view has its columns (test_features_store)
        names = [c for c, _ in declared_columns()[t]]
        start = names.index(M.MORE_COLUMNS[0])  # batch I block, followed by batch J (features_rpt), then 18D
        assert names[start : start + len(M.MORE_COLUMNS)] == list(M.MORE_COLUMNS), t
        end = start + len(M.MORE_COLUMNS) + len(RPT_COLUMNS)
        assert names[start + len(M.MORE_COLUMNS) : end] == list(RPT_COLUMNS), t
        assert names[end:] == [*DISCLOSURE_COLUMNS, *AUDIT_COLUMNS], t
    used = " ".join(sql for sql, _ in ALIASES.values())
    text = {"next_ex_date_action", "fastest_growing_segment"}  # labels, shown with `screen --columns`
    assert [c for c in M.MORE_COLUMNS if c not in used and c not in text] == []
    sql = compile_screen("Beneish dsri > 1.2 AND Piotroski cfo above pat = 1 AND Altman z original > 3 AND "
                         "PB percentile < 20 AND RS rank > 80 AND Volatility 1year < 30 AND New high on delivery = 1 "
                         "AND PEAD abnormal return t5 > 5 AND Days to next ex date < 30 AND Number of segments > 1 "
                         "AND Industry earnings breadth > 60").where_sql  # fmt: skip
    for col in ("beneish_dsri", "piotroski_cfo_above_pat", "altman_z_original", "pb_percentile", "rs_rank_12m_1m",
                "volatility_1y", "high_52w_on_delivery_spike", "pead_ar_t5", "days_to_next_ex_date",
                "segment_count", "industry_earnings_breadth"):  # fmt: skip
        assert col in sql, col
