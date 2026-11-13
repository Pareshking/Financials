"""Fundamentals engine on synthetic fact rows (pure arithmetic; no exchange-format claims)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from financials.db import apply_schema, connect, insert_rows
from financials.fundamentals import (
    altman_z_double_prime,
    building_blocks,
    choose_scope,
    load_factbook,
    yoy_growth,
)

D = Decimal
E = "ent_test"
QEND = [date(2024, 6, 30), date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31),
        date(2025, 6, 30), date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31),
        date(2026, 6, 30), date(2026, 9, 30)]  # fmt: skip
QSTART = {e: date(e.year, e.month - 2, 1) for e in QEND}
VISIBLE = datetime(2020, 1, 1)


def fy_start(end: date) -> date:
    return date(end.year if end.month > 3 else end.year - 1, 4, 1)


@pytest.fixture
def con():
    c = connect()
    apply_schema(c)
    insert_rows(c, "entity_master", [{"entity_id": E, "legal_name": "Test"}])
    insert_rows(c, "blobs", [{"sha256": "x", "byte_size": 1, "media_type": "t", "storage_path": "p",
                              "first_fetched_at": VISIBLE}])  # fmt: skip
    insert_rows(c, "filings", [{"filing_id": f, "sha256": "x", "exchange": "NSE", "category": "T",
                                "source_url": f, "broadcast_ts_source": "UNKNOWN", "fetched_at": VISIBLE}
                               for f in ("f1", "f2", "f3")])  # fmt: skip
    return c


def fact(tag, start, end, value, *, scope="STANDALONE", filing="f1", visible=VISIBLE, unit="INR"):
    instant = start is None
    months = None if instant else (end.year - start.year) * 12 + end.month - start.month + 1
    return {
        "filing_id": filing, "parser_version": "t", "entity_id": E, "scope": scope, "canonical_tag": tag,
        "period_type": "INSTANT" if instant else "DURATION", "period_start": end if instant else start,
        "period_end": end, "period_months": months, "unit": unit,
        "value_inr": D(value) if unit == "INR" else None, "value_other": None if unit == "INR" else D(value),
        "source_element": "test", "visible_from_ts": visible,
    }  # fmt: skip


def quarterly_revenue(scope="STANDALONE", base=100, filing="f1"):
    """Quarters reported directly except Q4, which is only reported as FY (Q4 = FY - 9M)."""
    rows, ytd = [], {}
    for i, e in enumerate(QEND):
        v = D(base + 10 * i)
        fs = fy_start(e)
        ytd[fs] = ytd.get(fs, D(0)) + v
        if e.month == 3:
            rows.append(fact("revenue_from_operations", fs, e, ytd[fs], scope=scope, filing=filing))  # FY only
            rows.append(
                fact("revenue_from_operations", fs, date(e.year - 1, 12, 31), ytd[fs] - v, scope=scope, filing=filing)
            )
        else:
            rows.append(fact("revenue_from_operations", QSTART[e], e, v, scope=scope, filing=filing))
    return rows


def test_q4_is_derived_from_fy_minus_9m(con):
    insert_rows(con, "fact_observations", quarterly_revenue())
    book = load_factbook(con, E, "STANDALONE", datetime(2030, 1, 1))
    assert book.quarter("revenue_from_operations", date(2025, 3, 31)) == D(130)
    assert book.quarter("revenue_from_operations", date(2026, 3, 31)) == D(170)


def test_ttm_and_yoy_need_enough_quarters(con):
    insert_rows(con, "fact_observations", quarterly_revenue())
    book = load_factbook(con, E, "STANDALONE", datetime(2030, 1, 1))
    end = date(2026, 9, 30)
    assert book.ttm("revenue_from_operations", end) == D(160 + 170 + 180 + 190)
    assert yoy_growth(book, "revenue_from_operations", end) == D(700) / D(120 + 130 + 140 + 150) - 1
    assert yoy_growth(book, "revenue_from_operations", date(2025, 9, 30)) is None  # only 6 quarters before


def test_point_in_time_ignores_later_revision(con):
    rows = quarterly_revenue()
    late = fact("revenue_from_operations", QSTART[QEND[-1]], QEND[-1], 999, filing="f2",
                visible=datetime(2027, 1, 1))  # fmt: skip
    insert_rows(con, "fact_observations", [*rows, late])
    before = load_factbook(con, E, "STANDALONE", datetime(2026, 12, 31))
    after = load_factbook(con, E, "STANDALONE", datetime(2027, 1, 1))
    assert before.quarter("revenue_from_operations", QEND[-1]) == D(190)
    assert after.quarter("revenue_from_operations", QEND[-1]) == D(999)


def test_scope_prefers_consolidated_only_with_four_quarters(con):
    insert_rows(con, "fact_observations", quarterly_revenue("STANDALONE"))
    cons = [r for r in quarterly_revenue("CONSOLIDATED", base=1000, filing="f2") if r["period_end"] >= date(2026, 4, 1)]
    insert_rows(con, "fact_observations", cons)
    scope, _ = choose_scope(con, E, datetime(2030, 1, 1), date(2026, 9, 30))
    assert scope == "STANDALONE"  # only 2 consolidated quarters
    more = [r for r in quarterly_revenue("CONSOLIDATED", base=1000, filing="f2") if r["period_end"] < date(2026, 4, 1)]
    insert_rows(con, "fact_observations", more)
    scope, _ = choose_scope(con, E, datetime(2030, 1, 1), date(2026, 9, 30))
    assert scope == "CONSOLIDATED"


def test_semi_annual_cfo_bridge(con):
    rows = [
        fact("cfo", date(2025, 4, 1), date(2025, 9, 30), 40),  # H1 FY26
        fact("cfo", date(2025, 4, 1), date(2026, 3, 31), 100),  # FY26
        fact("cfo", date(2026, 4, 1), date(2026, 9, 30), 55),  # H1 FY27
    ]
    insert_rows(con, "fact_observations", rows)
    book = load_factbook(con, E, "STANDALONE", datetime(2030, 1, 1))
    assert book.ttm_from_ytd("cfo", date(2026, 9, 30)) == D(55 + 100 - 40)
    assert book.ttm_from_ytd("cfo", date(2026, 3, 31)) == D(100)
    assert book.ttm_from_ytd("cfo", date(2025, 9, 30)) is None  # no FY25 / H1 FY25


def _full_quarter(end, *, rev, materials, purchases, inv, pbeit, fin, dep, oth, pbt, tax, pat, scope="STANDALONE"):
    s = QSTART[end]
    vals = dict(revenue_from_operations=rev, cost_of_materials_consumed=materials,
                purchases_of_stock_in_trade=purchases, changes_in_inventories=inv,
                profit_before_exceptional_and_tax=pbeit, finance_costs=fin, depreciation_amortisation=dep,
                other_income=oth, pbt=pbt, tax_expense=tax, pat=pat)  # fmt: skip
    return [fact(k, s, end, v, scope=scope) for k, v in vals.items()]


def test_building_blocks(con):
    rows = []
    for e in QEND[-4:]:
        rows += _full_quarter(e, rev=1000, materials=400, purchases=50, inv=-10, pbeit=150, fin=20, dep=30, oth=10,
                              pbt=150, tax=40, pat=110)  # fmt: skip
    end = QEND[-1]
    bs = dict(total_assets=5000, borrowings_noncurrent=300, borrowings_current=200, cash_and_equivalents=100,
              bank_balances_other=20, current_investments=80, total_equity=3000, current_assets=2000,
              current_liabilities=1200, total_liabilities=2000, other_equity=2500)  # fmt: skip
    rows += [fact(k, None, end, v) for k, v in bs.items()]
    rows += [fact("cfo", date(2025, 4, 1), date(2026, 3, 31), 600), fact("capex_ppe", date(2025, 4, 1),
             date(2026, 3, 31), 250)]  # fmt: skip
    insert_rows(con, "fact_observations", rows)
    b = building_blocks(load_factbook(con, E, "STANDALONE", datetime(2030, 1, 1)), end)
    assert b["rev_ops"] == 4000
    assert b["gross_profit"] == 4000 - (1600 + 200 - 40)
    assert b["ebitda"] == 4 * (150 + 20 + 30 - 10)
    assert b["ebit"] == 4 * (150 + 20 - 10)
    assert b["etr"] == D(160) / D(600)
    assert b["nopat"] == b["ebit"] * (1 - b["etr"])
    assert (b["total_debt"], b["cash_liquid"], b["net_debt"]) == (500, 200, 300)
    assert b["invested_capital"] == 3000 + 500 - 200
    assert b["bs_as_of"] == end
    assert b["cf_as_of"] == date(2026, 3, 31) and b["fcf"] == 350
    z = altman_z_double_prime(b)
    expected = (
        D("3.25")
        + D("6.56") * D(800) / 5000
        + D("3.26") * D(2500) / 5000
        + D("6.72") * D(640) / 5000
        + D("1.05") * D(3000) / 2000
    )
    assert z == expected


def test_services_company_has_no_gross_profit_and_losses_get_no_tax_shield(con):
    rows = []
    for e in QEND[-4:]:
        rows += _full_quarter(e, rev=1000, materials=0, purchases=20, inv=0, pbeit=-50, fin=10, dep=20, oth=5,
                              pbt=-50, tax=0, pat=-50)  # fmt: skip
    insert_rows(con, "fact_observations", rows)
    b = building_blocks(load_factbook(con, E, "STANDALONE", datetime(2030, 1, 1)), QEND[-1])
    assert b["gross_profit"] is None  # COGS lines < 10% of revenue [C6]
    assert b["etr"] == 0 and b["nopat"] == b["ebit"]  # [C5]
