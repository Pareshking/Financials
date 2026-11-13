"""Q4 = FY - 9M (P&L) and H2 = FY - H1 (cash flow) through the database, the FactBook and the statement builders.

No real 9-month (Q3) filing, and no same-year H1 + FY pair, is among the fixtures: the facts below are synthetic rows
in `fact_observations`, written through the real schema and read through `load_factbook` exactly as promoted facts
are. The arithmetic and the rules (single scope, visibility = the later broadcast) are what is pinned here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from financials.db import apply_schema, connect, insert_rows
from financials.fundamentals import BookAsResult, building_blocks, load_factbook
from financials.statements.cashflow import cashflow
from financials.statements.quarterly import corp_quarter

CR = Decimal(10) ** 7
ENT = "ent_q4"
FY = (date(2025, 4, 1), date(2026, 3, 31))
NINE = (date(2025, 4, 1), date(2025, 12, 31))
H1 = (date(2025, 4, 1), date(2025, 9, 30))
Q = [
    (date(2025, 4, 1), date(2025, 6, 30)),
    (date(2025, 7, 1), date(2025, 9, 30)),
    (date(2025, 10, 1), date(2025, 12, 31)),
]
SEEN_9M, SEEN_FY = datetime(2026, 2, 10, 12, 0), datetime(2026, 5, 20, 12, 0)  # UTC broadcast times


def _months(p):
    return (p[1].year - p[0].year) * 12 + p[1].month - p[0].month + 1


@pytest.fixture
def con():
    c = connect()
    apply_schema(c)
    insert_rows(c, "entity_master", [{"entity_id": ENT, "legal_name": "Synthetic Ltd"}])
    filings = {"q1": datetime(2025, 7, 20), "q2": datetime(2025, 10, 20), "q3": SEEN_9M, "fy": SEEN_FY,
               "fy_sa": SEEN_FY}  # fmt: skip
    insert_rows(
        c,
        "blobs",
        [
            {
                "sha256": f"sha_{k}",
                "byte_size": 1,
                "media_type": "application/xml",
                "storage_path": f"x/{k}",
                "first_fetched_at": v,
            }
            for k, v in filings.items()
        ],
    )
    insert_rows(
        c,
        "filings",
        [
            {
                "filing_id": f"fil_{k}",
                "sha256": f"sha_{k}",
                "exchange": "NSE",
                "category": "RESULTS_XBRL",
                "source_url": f"memory://{k}",
                "broadcast_ts": v,
                "broadcast_ts_source": "API_FIELD",
                "fetched_at": v,
            }
            for k, v in filings.items()
        ],
    )
    rows = []

    def fact(fil, scope, tag, period, crore):
        rows.append({"filing_id": f"fil_{fil}", "parser_version": "test", "entity_id": ENT, "scope": scope,
                     "canonical_tag": tag, "period_type": "DURATION", "period_start": period[0],
                     "period_end": period[1], "period_months": _months(period), "unit": "INR",
                     "value_inr": Decimal(crore) * CR, "value_other": None, "source_element": tag,
                     "visible_from_ts": filings[fil], "line_item_category": None, "parent_subtotal": None})  # fmt: skip

    for fil, (q, rev, pat) in zip(("q1", "q2", "q3"), ((Q[0], 100, 10), (Q[1], 110, 11), (Q[2], 120, 12)), strict=True):
        fact(fil, "CONSOLIDATED", "revenue_from_operations", q, rev)
        fact(fil, "CONSOLIDATED", "pat", q, pat)
    fact("q2", "CONSOLIDATED", "cfo", H1, 40)  # H1 cash flow, filed with Q2
    fact("q3", "CONSOLIDATED", "revenue_from_operations", NINE, 330)  # Q3 filings carry 9M YTD
    fact("q3", "CONSOLIDATED", "pat", NINE, 33)
    fact("fy", "CONSOLIDATED", "revenue_from_operations", FY, 460)  # FY only: Q4 = 460 - 330 = 130
    fact("fy", "CONSOLIDATED", "pat", FY, 47)
    fact("fy", "CONSOLIDATED", "cfo", FY, 100)  # H2 = 100 - 40 = 60
    fact("fy_sa", "STANDALONE", "revenue_from_operations", FY, 400)  # no standalone 9M: no standalone Q4
    insert_rows(c, "fact_observations", rows)
    return c


Q4 = (date(2026, 1, 1), date(2026, 3, 31))
H2 = (date(2025, 10, 1), date(2026, 3, 31))


def test_q4_is_fy_minus_9m_in_the_book_ttm_and_quarterly_statement(con):
    book = load_factbook(con, ENT, "CONSOLIDATED", datetime(2026, 6, 1))
    assert book.quarter("revenue_from_operations", Q4[1]) == 130 * CR
    assert book.ttm("revenue_from_operations", Q4[1]) == (100 + 110 + 120 + 130) * CR == 460 * CR
    assert building_blocks(book, Q4[1])["rev_ops"] == 460 * CR  # sales_ttm in screener_features
    st = corp_quarter(BookAsResult(book), *Q4)
    assert st.rows["Sales"].value == 130 * CR and st.rows["Net Profit"].value == 14 * CR


def test_h2_cash_flow_is_fy_minus_h1(con):
    book = load_factbook(con, ENT, "CONSOLIDATED", datetime(2026, 6, 1))
    assert BookAsResult(book).value("cfo", *H2) == 60 * CR
    assert cashflow(BookAsResult(book), *H2).rows["Cash from Operating Activity"].value == 60 * CR
    assert book.ttm_from_ytd("cfo", FY[1]) == 100 * CR  # an FY flow is its own TTM


def test_derivation_never_mixes_scopes(con):
    sa = load_factbook(con, ENT, "STANDALONE", datetime(2026, 6, 1))
    assert sa.quarter("revenue_from_operations", Q4[1]) is None  # standalone FY - consolidated 9M is never formed
    assert BookAsResult(sa).value("revenue_from_operations", *Q4) is None


def test_derived_q4_is_visible_only_once_both_filings_are(con):
    between = load_factbook(con, ENT, "CONSOLIDATED", SEEN_FY.replace(day=19))  # 9M visible, FY not yet
    assert between.quarter("revenue_from_operations", Q4[1]) is None
    assert BookAsResult(between).value("cfo", *H2) is None
    at = load_factbook(con, ENT, "CONSOLIDATED", SEEN_FY)  # = max(broadcast 9M, broadcast FY)
    assert at.quarter("revenue_from_operations", Q4[1]) == 130 * CR
