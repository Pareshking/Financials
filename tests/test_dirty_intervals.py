"""Market-state diff of interval states (dirty._interval_changes): a changed identifier or Nifty 500 interval marks
its security from the first date whose coverage differs, not from the interval's start (a symbol change on the
last day used to send `materialize --incremental` back over every materialised day)."""

from __future__ import annotations

from datetime import date

from financials.dirty import _interval_changes

D = date


def test_closing_an_open_interval_marks_from_its_new_end():
    before = {("S1", "NSE", "OLD", "EQ", D(2024, 10, 1), None)}
    after = {("S1", "NSE", "OLD", "EQ", D(2024, 10, 1), D(2026, 11, 13)),
             ("S1", "NSE", "NEW", "EQ", D(2026, 11, 13), None)}  # fmt: skip
    assert _interval_changes(before, after) == {"S1": D(2026, 11, 13)}


def test_new_and_removed_intervals_mark_from_their_start():
    assert _interval_changes(set(), {("S2", D(2025, 6, 2), None)}) == {"S2": D(2025, 6, 2)}
    assert _interval_changes({("S3", D(2025, 1, 6), D(2025, 3, 3))}, set()) == {"S3": D(2025, 1, 6)}


def test_moved_start_marks_from_the_earlier_of_the_two():
    before = {("S4", D(2025, 5, 1), None)}
    assert _interval_changes(before, {("S4", D(2025, 4, 1), None)}) == {"S4": D(2025, 4, 1)}
    assert _interval_changes(before, {("S4", D(2025, 6, 1), None)}) == {"S4": D(2025, 5, 1)}


def test_same_coverage_marks_from_the_moved_end():
    before = {("S5", D(2024, 10, 1), None)}
    after = {("S5", D(2024, 10, 1), D(2025, 9, 1)), ("S5", D(2025, 9, 1), None)}  # a split, same coverage
    assert _interval_changes(before, after) == {"S5": D(2025, 9, 1)}


def test_unchanged_securities_are_not_marked():
    same = {("S6", D(2024, 10, 1), None)}
    assert _interval_changes(same | {("S7", D(2024, 10, 1), None)}, same) == {"S7": D(2024, 10, 1)}


def test_finding_markers_start_at_the_filing_visibility_and_skip_findings_without_a_period(market):
    """dirty.mark_finding_changes: a changed finding can flag rows only from its filing's visibility (and its period
    end); one without a period end flags none (features.dq_columns), so it marks nothing."""
    from datetime import timedelta

    from test_x226_misfiled_ytd import _nazara

    from financials import dirty
    from financials.timeutil import utc_to_ist_date

    ent = _nazara(market)
    con = market.con
    con.execute("DELETE FROM materialize_dirty")
    con.execute("DELETE FROM features_dq_findings")
    assert dirty.mark_finding_changes(con) == 1
    (got,) = con.execute("SELECT from_date FROM materialize_dirty WHERE entity_id = ?", [ent]).fetchone()
    vis = con.execute(
        "SELECT min(fm.visible_from_ts) FROM quarantine_queue q JOIN filing_meta fm USING (filing_id) "
        "WHERE q.entity_id = ? AND q.resolved_at IS NULL", [ent]).fetchone()[0]  # fmt: skip
    assert got >= utc_to_ist_date(vis) - timedelta(days=1)
    dirty.store_finding_state(con)
    con.execute("DELETE FROM materialize_dirty")
    con.execute(
        "INSERT INTO quarantine_queue (quarantine_id, stage, reason_code, entity_id, details, created_at) "
        "VALUES ('no-period', 'TEST', 'CROSS_CHECK_FAILED', ?, '{}', TIMESTAMP '2026-01-01 00:00:00')",
        [ent],
    )
    assert dirty.mark_finding_changes(con) == 0
