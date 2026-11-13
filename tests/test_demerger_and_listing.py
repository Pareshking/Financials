"""Tata Motors demerger [X52, C10]: PE earnings exclude discontinued (scheme) gains; the CV company's pre-listing
history is visible only from the first filing that published it (no backdating)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.db import apply_schema, connect, insert_rows
from financials.fundamentals import FactBook, building_blocks, load_factbook
from financials.parsers.indas_corp import parse_indas_corp_results

CR = Decimal(10) ** 7
TMPV_Q2FY26 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1574923_14112025041850_WEB.xml"
TMCV_Q2FY26 = XBRL_DIR / "INTEGRATED_FILING_INDAS_1574016_13112025070452_WEB.xml"
Q = (date(2025, 7, 1), date(2025, 9, 30))
H1 = (date(2025, 4, 1), date(2025, 9, 30))
TMCV_BROADCAST_UTC = datetime(2025, 11, 13, 13, 34, 53)  # 13-Nov-2025 19:04:53 IST (NSE listing)


def _book(r, scope="CONSOLIDATED") -> FactBook:
    b = FactBook("e", scope)
    for f in r.facts:
        if f.period_type == "DURATION":
            b.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
        else:
            b.instants.setdefault(f.canonical_tag, {})[f.period_end] = f.value
    return b


def test_tmpv_scheme_gain_is_tagged_discontinued():
    r = parse_indas_corp_results(TMPV_Q2FY26.read_bytes())
    assert r.ok, r.issues
    assert r.value("pat_discontinued", *Q) / CR == Decimal("82616")
    assert r.value("pat_owners", *Q) / CR == Decimal("76170")
    assert r.value("pat_continuing", *Q) / CR == Decimal("-6406")


def test_pe_earnings_exclude_discontinued_per_filing():
    book = _book(parse_indas_corp_results(TMPV_Q2FY26.read_bytes()))
    assert book.quarter(book.continuing_owners(), Q[1]) / CR == Decimal("-6446")  # 76170 - 82616


def test_ttm_pe_earnings_on_a_mixed_window():
    """Four quarters, one with a scheme gain: PE earnings exclude it, owners' profit (for ROE) keeps it."""
    b = FactBook("e", "CONSOLIDATED")
    qs = [(date(2024, 10, 1), date(2024, 12, 31)), (date(2025, 1, 1), date(2025, 3, 31)),
          (date(2025, 4, 1), date(2025, 6, 30)), (date(2025, 7, 1), date(2025, 9, 30))]  # fmt: skip
    b.durations["pat"] = {p: Decimal(100) for p in qs}
    b.durations["pat"][qs[3]] = Decimal(10100)
    b.durations["pat_owners"] = {qs[3]: Decimal(10090)}  # only the demerger quarter attributes
    b.durations["pat_discontinued"] = {qs[3]: Decimal(10000)}
    blocks = building_blocks(b, qs[3][1])
    assert blocks["pat_owners"] == Decimal(300 + 10090)
    assert blocks["pat_owners_continuing"] == Decimal(300 + 90)


def test_tmcv_filing_has_only_current_period_contexts():
    """No restated pre-listing quarter exists in the XBRL: every fact is the Q2 FY26 quarter, H1 FY26, or a
    balance-sheet instant (30-Sep-2025 and the comparative 31-Mar-2025)."""
    r = parse_indas_corp_results(TMCV_Q2FY26.read_bytes())
    assert r.ok, r.issues
    periods = {(f.period_start, f.period_end) for f in r.facts}
    assert periods <= {Q, H1, (date(2025, 9, 30),) * 2, (date(2025, 3, 31),) * 2}


@pytest.fixture
def tmcv_db():
    con = connect()
    apply_schema(con)
    insert_rows(con, "entity_master", [{"entity_id": "tmcv", "legal_name": "Tata Motors Limited"}])
    insert_rows(con, "blobs", [{"sha256": "x", "byte_size": 1, "media_type": "t", "storage_path": "p",
                                "first_fetched_at": TMCV_BROADCAST_UTC}])  # fmt: skip
    insert_rows(con, "filings", [{"filing_id": "tmcv_q2fy26", "sha256": "x", "exchange": "NSE", "category": "T",
                                  "source_url": TMCV_Q2FY26.name, "broadcast_ts_source": "NSE",
                                  "fetched_at": TMCV_BROADCAST_UTC}])  # fmt: skip
    r = parse_indas_corp_results(TMCV_Q2FY26.read_bytes())
    rows = [
        {"filing_id": "tmcv_q2fy26", "parser_version": "t", "entity_id": "tmcv", "scope": "CONSOLIDATED",
         "canonical_tag": f.canonical_tag, "period_type": f.period_type, "period_start": f.period_start,
         "period_end": f.period_end, "period_months": f.period_months, "unit": f.unit,
         "value_inr": f.value if f.unit == "INR" else None, "value_other": None if f.unit == "INR" else f.value,
         "source_element": f.source_element, "visible_from_ts": TMCV_BROADCAST_UTC}
        for f in r.facts
    ]  # fmt: skip
    insert_rows(con, "fact_observations", rows)
    return con


def test_pre_listing_history_is_invisible_before_the_first_filing(tmcv_db):
    before = load_factbook(tmcv_db, "tmcv", "CONSOLIDATED", datetime(2025, 11, 13, 13, 0))
    assert before.durations == {} and before.instants == {}


def test_derived_pre_listing_quarter_is_visible_only_from_that_filing(tmcv_db):
    after = load_factbook(tmcv_db, "tmcv", "CONSOLIDATED", TMCV_BROADCAST_UTC)
    q2 = after.quarter("revenue_from_operations", date(2025, 9, 30))
    assert q2 / CR == Decimal("18585")
    q1 = after.quarter("revenue_from_operations", date(2025, 6, 30))  # H1 - Q2 is not a reported quarter
    assert q1 is None  # no 3-month context for Apr-Jun 2025 and no earlier YTD to difference against
    assert after.ttm("revenue_from_operations", date(2025, 9, 30)) is None
    assert all(e >= date(2025, 6, 30) for (_, e) in after.durations["revenue_from_operations"])
