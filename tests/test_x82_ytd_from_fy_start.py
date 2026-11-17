"""X82 YTD_FROM_FY_START: NETWEB filed its Q4 FY26 standalone results first as "Half Yearly" / "Yearly", with the
Jan-Mar quarter (PAT 705,930,000) in an Oct 2025 - Mar 2026 context, then re-filed on 16 May 2026 as "Fourth quarter"
with the same figure in a Jan-Mar context. A six-month duration that does not start on the declared fiscal-year start
(DateOfStartOfFinancialYear 2025-04-01) is not a YTD: it must neither break the YTD identity [X80] nor be used to
derive a quarter by subtraction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from _fixture_helpers import XBRL_DIR
from financials.fundamentals import FactBook
from financials.parsers.integrated import parse_integrated_results

Q3 = "INTEGRATED_FILING_INDAS_1603408_17012026050918_WEB.xml"  # Oct-Dec + Apr-Dec
HALF_YEARLY = "INTEGRATED_FILING_INDAS_1663034_02052026072054_WEB.xml"  # Oct-Mar (really Jan-Mar) + FY
REFILED = "INTEGRATED_FILING_INDAS_1668217_16052026103806_WEB.xml"  # Jan-Mar + FY
FY_START = date(2025, 4, 1)
OCT_MAR = (date(2025, 10, 1), date(2026, 3, 31))


def _book(names: list[str], fy_starts: frozenset[date]) -> FactBook:
    book = FactBook("NETWEB", "STANDALONE", fy_starts=fy_starts)
    for name in names:
        r = parse_integrated_results((XBRL_DIR / name).read_bytes(), name)
        assert not r.issues and r.meta["scope"] == "STANDALONE"
        assert r.meta["fy_start"] == FY_START
        for f in r.facts:
            if f.period_type == "DURATION":
                book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def test_half_yearly_filing_carries_the_quarter_in_an_oct_mar_context():
    book = _book([HALF_YEARLY, REFILED], frozenset())
    pat = book.durations["pat"]
    assert pat[OCT_MAR] == pat[(date(2026, 1, 1), date(2026, 3, 31))] == Decimal("705930000")


def test_oct_mar_context_is_not_a_ytd():
    names = [Q3, HALF_YEARLY, REFILED]
    unchecked = _book(names, frozenset())
    assert [b["ytd_period"] for b in unchecked.ytd_breaks("pat")] == [[str(OCT_MAR[0]), str(OCT_MAR[1])]]
    assert _book(names, frozenset({FY_START})).ytd_breaks("pat") == []


def test_quarter_is_not_derived_from_a_non_ytd_duration():
    # Without the corrected re-filing, Jan-Mar must come from FY - 9M, never Oct-Mar - Oct-Dec (= -27,180,000).
    book = _book([Q3, HALF_YEARLY], frozenset({FY_START}))
    assert book.quarter("pat", date(2026, 3, 31)) == Decimal("2058160000") - Decimal("1352230000")
    assert book.quarter("pat", date(2026, 3, 31)) == Decimal("705930000")


def test_re_audit_closes_a_ytd_finding_that_no_longer_reproduces():
    """A YTD_QUARTER_MISMATCH raised before X82 (NETWEB's Oct-Mar "YTD") is closed when the audit of that entity and
    scope no longer raises it; findings of entities not audited stay open."""
    from financials.db import apply_schema, connect
    from financials.promoter import _quarantine_many, _quarantine_row, audit_ytd_identity

    con = connect()
    apply_schema(con)
    old = _quarantine_row(
        stage="CONSISTENCY",
        reason_code="YTD_QUARTER_MISMATCH",
        entity_id="ent_netweb",
        details={"scope": "STANDALONE", "tag": "pat", "ytd_period": ["2025-10-01", "2026-03-31"]},
    )
    other = _quarantine_row(
        stage="CONSISTENCY",
        reason_code="YTD_QUARTER_MISMATCH",
        entity_id="ent_other",
        details={"scope": "STANDALONE", "tag": "pat", "ytd_period": ["2025-04-01", "2026-03-31"]},
    )
    _quarantine_many(con, [old, other])
    assert audit_ytd_identity(con, [("ent_netweb", "STANDALONE")]) == []
    status = dict(con.execute("SELECT entity_id, resolution FROM quarantine_queue").fetchall())
    assert status == {"ent_netweb": "FIXED_BY_RULE", "ent_other": None}
