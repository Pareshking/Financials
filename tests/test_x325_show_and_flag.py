"""X325 (rule SHOW_AND_FLAG, owner decision V 2026-11-19): show every number the filings state, flag the suspect.

For each withholding class the validated reader still gives NULL (the rules are unchanged), while the feature layer's
as-filed mode (`FactBook.fill_as_filed`) shows the figure as filed and records the class code in `FactBook.dq`.
Genuine absence (a missing quarter) stays NULL in both modes. Fixtures are the ones that pin each rule: NAZARA
(X226, `ytd_misfiled/`), Tech Mahindra Q4 FY25 (X86), Muthoot Finance Q2 FY27 (X94), Ajax Engineering Q3 FY26 (X173,
`ytd_copy/`), Swiggy standalone (X301, `operating_bridge/`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from test_x84_x86_attribution import TECHM_Q4FY25
from test_x94_tax_copied_from_prior_year import H1, Q2, Q2FY26, Q2FY27
from test_x94_tax_copied_from_prior_year import _book as muthoot
from test_x173_ytd_copies_quarter import M9, Q3P
from test_x173_ytd_copies_quarter import _book as ajax
from test_x226_misfiled_ytd import AFTER_AR, BEFORE_AR, Q2_FY27, _nazara
from test_x300_operating_lines_bridge import _swiggy
from test_x301_guarded_bridge_one_basis import CR, END, H1_FY26

import financials.fundamentals as F
from financials import dirty, features
from financials.db import apply_schema, connect, insert_rows
from financials.dsl import ALIASES, run_screen
from financials.fundamentals import FactBook, load_factbook
from financials.parsers.indas_corp import parse_indas_corp_results

REV = "revenue_from_operations"


def _sum_quarters(book: FactBook, tag: str, end: date) -> Decimal:
    return sum((book._quarter(tag, F._add_months(end, -3 * i)) for i in range(4)), Decimal(0))


# ── X226: a bridge on a proven mis-filed YTD ─────────────────────────────────────────────────────────────────────


def test_x226_nazara_ttm_is_the_quarters_as_filed_and_flagged(market):
    ent = _nazara(market)
    book = load_factbook(market.con, ent, "CONSOLIDATED", AFTER_AR)
    owners = book.coalesced("pat_owners", "pat")
    assert book.ttm("pat", Q2_FY27) is None and book.ttm(owners, Q2_FY27) is None  # validated: withheld (X226)
    assert not book.dq
    book.fill_as_filed = True
    assert book.ttm("pat", Q2_FY27) == Decimal("174300000")  # 8.84 + 55.70 - 82.47 + 35.36 Cr, the 4 quarters
    assert book.ttm(owners, Q2_FY27) == _sum_quarters(book, owners, Q2_FY27)
    assert book.ttm(book.continuing_owners(), Q2_FY27) is not None
    assert book.dq == {F.DQ_TTM_MISFILED}
    # the feature block: PAT TTM, owners' profit (EPS, P/E) shown, the row flagged
    fund = features._fundamentals(market.con, ent, AFTER_AR, Q2_FY27)
    assert fund["pat_ttm"] == Decimal("174300000") and fund["_pat_owners_total"] is not None
    assert F.DQ_TTM_MISFILED in fund["_dq"]
    findings = features.open_findings(market.con, AFTER_AR)[ent]
    assert ("YTD_QUARTER_MISMATCH", "CONSOLIDATED", date(2026, 3, 31)) in findings
    cols = features.dq_columns(fund, findings, None, Q2_FY27)
    assert cols["dq_suspect"] is True
    assert cols["dq_flags"].split(",") == sorted(cols["dq_flags"].split(","))
    assert {F.DQ_TTM_MISFILED, "OPEN_FINDING:YTD_QUARTER_MISMATCH"} <= set(cols["dq_flags"].split(","))


def test_x226_before_the_evidence_nothing_is_withheld_only_x301_flags(market):
    ent = _nazara(market)
    book = load_factbook(market.con, ent, "CONSOLIDATED", BEFORE_AR)
    book.fill_as_filed = True
    assert book.ttm("pat", Q2_FY27) == Decimal("174300000")  # X301 quarter sum, a validated value (unchanged)
    assert book.dq == {F.DQ_TTM_MIXED}  # the sum spans a YTD-identity break: flagged, never blanked


# ── X86: attribution withheld ────────────────────────────────────────────────────────────────────────────────────


def _techm() -> FactBook:
    r = parse_indas_corp_results(TECHM_Q4FY25.read_bytes())
    book = FactBook("TECHM", "CONSOLIDATED", fy_starts=frozenset({date(2024, 4, 1)}))
    for f in r.facts:
        if f.period_type == "DURATION":
            book.durations.setdefault(f.canonical_tag, {})[(f.period_start, f.period_end)] = f.value
    return book


def test_x86_owners_profit_shows_pat_as_filed_flagged():
    q4, fy = (date(2025, 1, 1), date(2025, 3, 31)), (date(2024, 4, 1), date(2025, 3, 31))
    book = _techm()
    owners = book.coalesced("pat_owners", "pat")
    assert q4 not in book.durations[owners] and fy not in book.durations[owners]  # X86 unchanged: no fallback
    assert book.quarter(owners, q4[1]) is None and F._owners_fy(book, fy) is None
    book.fill_as_filed = True
    pat = book.durations["pat"]
    assert book.quarter(owners, q4[1]) == pat[q4] == Decimal("11418960000")
    assert book.stated(owners, fy) == pat[fy]
    assert F._owners_fy(book, fy) == pat[fy]
    assert book.stated(book.continuing_owners(), fy) == pat[fy] - book.durations.get("pat_discontinued", {}).get(
        fy, Decimal(0)
    )
    assert book.dq == {F.DQ_ATTRIBUTION}
    assert owners not in book.durations or q4 not in book.durations[owners]  # the book itself is not changed


def test_x86_filed_owners_of_another_filing_win_and_are_not_flagged():
    """X319: where another filing states the owners for the period, the validated value stands, unflagged."""
    q4 = (date(2026, 1, 1), date(2026, 3, 31))
    b = FactBook("e", "CONSOLIDATED")
    b.durations["pat"] = {q4: Decimal(120)}
    b.durations["pat_owners"] = {q4: Decimal(110)}
    b.durations["attribution_withheld"] = {q4: Decimal(1)}
    b.fill_as_filed = True
    assert b.quarter(b.coalesced("pat_owners", "pat"), q4[1]) == Decimal(110)
    assert F._owners_fy(b, q4) == Decimal(110) and not b.dq


# ── X94: tax copied from the prior year ──────────────────────────────────────────────────────────────────────────


def test_x94_copied_tax_period_shows_pat_as_filed_flagged():
    book = muthoot([Q2FY26, Q2FY27])
    book.withhold_tax_copies()
    assert book.quarter("pat", Q2[1]) is None and book.stated("pat", H1) is None  # validated: withheld
    book.fill_as_filed = True
    assert book.quarter("pat", Q2[1]) == Decimal("31862530000")  # PBT - the copied tax, as filed
    assert book.stated("tax_expense", Q2) == book.durations["pbt"][Q2] - Decimal("31862530000")
    owners = book.coalesced("pat_owners", "pat")
    assert book.quarter(owners, Q2[1]) == Decimal("31862530000")
    assert book.dq == {F.DQ_TAX_COPY}
    assert book.durations["pbt"][Q2] == Decimal("39925220000") and Q2 not in book.durations["pat"]


# ── X173: a YTD context copying its quarter ──────────────────────────────────────────────────────────────────────


def test_x173_validated_quarters_win_the_copied_ytd_is_shown_only_where_nothing_else_is():
    book = ajax()
    book.withhold_ytd_copies()
    book.fill_as_filed = True
    assert book.quarter(REV, Q3P[1]) == Decimal("4335480000")  # the filed quarter: validated, unflagged
    assert book.ttm_from_ytd(REV, M9[1]) is None
    assert not book.dq
    assert book.stated(REV, M9) == Decimal("4335480000")  # the 9M as filed (= the quarter: the copy)
    assert book.dq == {F.DQ_YTD}
    book.fill_as_filed = False
    assert book.stated(REV, M9) is None  # validated: withheld


# ── X301: bridge on two bases ────────────────────────────────────────────────────────────────────────────────────


def test_x301_quarter_sum_is_flagged_mixed_basis():
    b = _swiggy()
    assert b.ttm(REV, END) / CR == Decimal("10468") and not b.dq  # validated mode records nothing
    b.fill_as_filed = True
    assert b.ttm(REV, END) / CR == Decimal("10468")  # the same value
    assert b.dq == {F.DQ_TTM_MIXED}


def test_x301_quarter_derived_from_a_misfiled_ytd_is_shown_flagged():
    b = _swiggy()
    rev = b.durations[REV]
    del rev[(date(2025, 10, 1), date(2025, 12, 31))]  # Q3 FY26 now derived: 9M - H1 FY26
    b.later_filed[REV] = {H1_FY26: [rev[H1_FY26]]}
    rev[H1_FY26] += 500 * CR  # H1 FY26 proven mis-filed (LATER_FILING_AGREES)
    # X301's quarter sum refuses a quarter derived from the mis-filed YTD (validated: NULL, as in test_x301)
    assert b.mixed_basis_quarter_sum(REV, END) is None
    assert b._as_filed_ttm(REV, END, F.DQ_TTM_MIXED) is None and not b.dq  # validated mode never fills
    b.fill_as_filed = True
    assert b._as_filed_ttm(REV, END, F.DQ_TTM_MIXED) / CR == Decimal("9968")  # the quarters as filed: 10,468 - 500
    assert b.dq == {F.DQ_TTM_MIXED}


def test_genuine_absence_stays_null_in_as_filed_mode():
    """A missing quarter: fewer than 4 quarters (invariant 6). The refused mixed-basis bridge is never shown."""
    b = _swiggy()
    del b.durations[REV][(date(2026, 4, 1), date(2026, 6, 30))]  # Q1 FY27 (H1 FY27 stays)
    b.fill_as_filed = True
    assert b.ttm(REV, END) is None and b.ttm_from_ytd(REV, END) is not None
    assert not b.dq
    empty = FactBook("e", "STANDALONE")
    empty.fill_as_filed = True
    assert empty.ttm("pat", END) is None and empty.quarter("pat", END) is None and not empty.dq


# ── open findings: PIT window, scope, dirty marking ──────────────────────────────────────────────────────────────


def test_open_findings_flag_only_their_window_and_scope():
    fund = {"fundamentals_end": date(2026, 9, 30), "scope_used": "CONSOLIDATED", "_dq": ()}
    findings = [
        ("YTD_QUARTER_MISMATCH", "CONSOLIDATED", date(2025, 9, 30)),  # 12 months back: in the 5-quarter window
        ("ANNUAL_PRIOR_YEAR_DIFFERS", "STANDALONE", date(2026, 3, 31)),  # other scope
        ("TAX_COPIED_FROM_PRIOR_YEAR", None, date(2025, 6, 30)),  # 15 months back: outside
        ("CROSS_CHECK_FAILED", None, date(2026, 6, 30)),  # no scope: any
        ("ATTRIBUTION_WITHHELD", "CONSOLIDATED", date(2026, 12, 31)),  # after the row's quarter
    ]
    cols = features.dq_columns(fund, findings, None, date(2026, 11, 13))
    assert cols == {"dq_suspect": True,
                    "dq_flags": "OPEN_FINDING:CROSS_CHECK_FAILED,OPEN_FINDING:YTD_QUARTER_MISMATCH"}  # fmt: skip
    assert features.dq_columns(fund, [], None, date(2026, 11, 13)) == {"dq_suspect": False, "dq_flags": None}
    gap = features.dq_columns(fund, [], date(2026, 11, 1), date(2026, 11, 13))
    assert gap == {"dq_suspect": True, "dq_flags": "PRICE_GAP_UNRESOLVED"}


def test_resolving_a_finding_unflags_and_marks_its_entity(market):
    ent = _nazara(market)
    con = market.con
    qid, end = con.execute(
        "SELECT quarantine_id, CAST(details->>'$.ytd_period[1]' AS DATE) FROM quarantine_queue WHERE entity_id = ? "
        "AND reason_code = 'YTD_QUARTER_MISMATCH' AND resolved_at IS NULL ORDER BY 1 LIMIT 1",
        [ent],
    ).fetchone()
    con.execute("DELETE FROM materialize_dirty")
    assert dirty.mark_finding_changes(con) == 1  # nothing stored yet: every open finding of the entity is new
    assert con.execute("SELECT entity_id, reason FROM materialize_dirty").fetchall() == [(ent, "DQ_FINDINGS")]
    dirty.store_finding_state(con)
    con.execute("DELETE FROM materialize_dirty")
    assert dirty.mark_finding_changes(con) == 0  # the stored rows reflect today's findings
    con.execute("UPDATE quarantine_queue SET resolved_at = ?, resolution = 'ACCEPTED' WHERE quarantine_id = ?",
                [datetime(2026, 11, 18), qid])  # fmt: skip
    assert dirty.mark_finding_changes(con) == 1
    assert con.execute("SELECT from_date FROM materialize_dirty WHERE entity_id = ?", [ent]).fetchone()[0] == end
    flagged = {r for r, _s, _e in features.open_findings(con, AFTER_AR)[ent]}
    assert "YTD_QUARTER_MISMATCH" in flagged or not con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE entity_id = ? AND reason_code = 'YTD_QUARTER_MISMATCH' "
        "AND resolved_at IS NULL", [ent]).fetchone()[0]  # fmt: skip


# ── screens ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _screen_db():
    con = connect()
    apply_schema(con)
    base = {"as_of_date": date(2026, 11, 13), "series": "EQ", "close": Decimal(100), "pat_ttm": Decimal(10**9)}
    insert_rows(con, "screener_features", [
        {**base, "security_id": "s1", "entity_id": "e1", "symbol": "CLEAN", "dq_suspect": False, "dq_flags": None},
        {**base, "security_id": "s2", "entity_id": "e2", "symbol": "FLAGGED", "dq_suspect": True,
         "dq_flags": "ATTRIBUTION_AS_FILED,OPEN_FINDING:YTD_QUARTER_MISMATCH"},
        {**base, "security_id": "s3", "entity_id": "e3", "symbol": "OLDROW", "dq_suspect": None, "dq_flags": None},
    ])  # fmt: skip
    return con


def test_screens_include_flagged_rows_and_can_exclude_them():
    con = _screen_db()
    rows = run_screen(con, "Net Profit > 50")
    assert [r["symbol"] for r in rows] == ["CLEAN", "FLAGGED", "OLDROW"]  # flagged rows are shown by default
    flagged = next(r for r in rows if r["symbol"] == "FLAGGED")
    assert flagged["dq_suspect"] is True and flagged["dq_flags"].startswith("ATTRIBUTION_AS_FILED")
    assert [r["symbol"] for r in run_screen(con, "Net Profit > 50 AND Data Suspect = 0")] == ["CLEAN", "OLDROW"]
    assert [r["symbol"] for r in run_screen(con, "Data Flag Attribution As Filed = 1")] == ["FLAGGED"]
    assert [r["symbol"] for r in run_screen(con, "Data Flag Open Finding Ytd Quarter Mismatch = 1")] == ["FLAGGED"]
    assert [r["symbol"] for r in run_screen(con, "Data Open Finding = 0")] == ["CLEAN", "OLDROW"]
    assert "data flag ttm mixed basis" in ALIASES and "data flag price gap unresolved" in ALIASES
