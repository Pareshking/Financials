"""Mandate 3: per-company default scope; one scope per TTM window, never mixed [C18]."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from financials.admin import AdminError, set_scope_override
from financials.db import apply_schema, connect, insert_rows
from financials.fundamentals import resolve_scope, scope_policy

E = "ent"
VIS = datetime(2026, 1, 1)
AS_OF = datetime(2030, 1, 1)
END = date(2026, 9, 30)
Q = {  # quarter end -> start
    date(2025, 12, 31): date(2025, 10, 1), date(2026, 3, 31): date(2026, 1, 1),
    date(2026, 6, 30): date(2026, 4, 1), date(2026, 9, 30): date(2026, 7, 1),
}  # fmt: skip


@pytest.fixture
def con():
    c = connect()
    apply_schema(c)
    insert_rows(c, "entity_master", [{"entity_id": E, "legal_name": "Test"}])
    insert_rows(c, "blobs", [{"sha256": "x", "byte_size": 1, "media_type": "t", "storage_path": "p",
                              "first_fetched_at": VIS}])  # fmt: skip
    insert_rows(
        c,
        "filings",
        [
            {
                "filing_id": f"f_{s}",
                "sha256": "x",
                "exchange": "NSE",
                "category": "T",
                "source_url": s,
                "broadcast_ts_source": "UNKNOWN",
                "fetched_at": VIS,
            }
            for s in ("CONSOLIDATED", "STANDALONE")
        ],
    )  # fmt: skip (one filing per scope)
    return c


def add(con, scope, ends, tag="pat", value=100, months=3):
    rows = []
    for e in ends:
        start = Q[e] if months == 3 else date(e.year - 1 if e.month < 4 else e.year, 4, 1)
        rows.append({
            "filing_id": f"f_{scope}", "parser_version": "t", "entity_id": E, "scope": scope, "canonical_tag": tag,
            "period_type": "DURATION", "period_start": start, "period_end": e, "period_months": months, "unit": "INR",
            "value_inr": Decimal(value), "value_other": None, "source_element": "t", "visible_from_ts": VIS,
        })  # fmt: skip
    insert_rows(con, "fact_observations", rows)


def test_consolidated_filer_defaults_to_consolidated(con):
    add(con, "CONSOLIDATED", Q)
    add(con, "STANDALONE", Q, value=60)
    d = resolve_scope(con, E, AS_OF, END)
    assert (d.scope, d.reason) == ("CONSOLIDATED", "DEFAULT")
    assert (d.policy.default_quarterly_scope, d.policy.default_annual_scope, d.policy.source) == (
        "CONSOLIDATED", "CONSOLIDATED", "DERIVED")  # fmt: skip
    assert d.book.ttm("pat", END) == Decimal(400)


def test_standalone_only_filer(con):
    add(con, "STANDALONE", Q)
    d = resolve_scope(con, E, AS_OF, END)
    assert (d.scope, d.reason, d.policy.default_quarterly_scope) == ("STANDALONE", "DEFAULT", "STANDALONE")


def test_never_mixes_standalone_q1_q3_with_consolidated_q2_q4(con):
    """Consolidated filed only for Q4 and Q2; standalone every quarter: the TTM is all-standalone, flagged."""
    add(con, "CONSOLIDATED", [date(2026, 3, 31), date(2026, 9, 30)], value=1000)
    add(con, "STANDALONE", Q, value=100)
    d = resolve_scope(con, E, AS_OF, END)
    assert d.policy.default_quarterly_scope == "CONSOLIDATED"  # latest quarter has a consolidated version
    assert (d.scope, d.reason) == ("STANDALONE", "FALLBACK_DEFAULT_INCOMPLETE")
    assert d.book.ttm("pat", END) == Decimal(400)  # never 100 + 1000 + 100 + 1000


def test_no_complete_scope_means_no_mixed_ttm(con):
    add(con, "CONSOLIDATED", [date(2026, 3, 31), date(2026, 9, 30)], value=1000)
    add(con, "STANDALONE", [date(2025, 12, 31), date(2026, 6, 30)], value=100)
    assert resolve_scope(con, E, AS_OF, END) is None  # half the quarters in each scope: no TTM at all


def test_annual_default_can_differ_from_quarterly(con):
    add(con, "STANDALONE", Q)
    add(con, "CONSOLIDATED", [date(2026, 3, 31)], months=12)  # consolidated published annually only
    p = scope_policy(con, E, AS_OF)
    assert (p.default_quarterly_scope, p.default_annual_scope) == ("STANDALONE", "CONSOLIDATED")


def test_override_pins_the_scope_and_is_audited(con):
    add(con, "CONSOLIDATED", Q)
    add(con, "STANDALONE", Q, value=60)
    set_scope_override(con, E, quarterly="STANDALONE", annual="STANDALONE", reason="holding company: compare parent")
    d = resolve_scope(con, E, AS_OF, END)
    assert (d.scope, d.reason, d.policy.source) == ("STANDALONE", "OVERRIDE", "OVERRIDE")
    audit = con.execute("SELECT field, reason FROM company_overrides WHERE entity_id = ?", [E]).fetchall()
    assert audit == [("scope_policy", "holding company: compare parent")]
    set_scope_override(con, E, quarterly=None, annual=None, reason="back to derived")
    assert scope_policy(con, E, AS_OF).source == "DERIVED"
    assert con.execute("SELECT count(*) FROM company_overrides").fetchone()[0] == 2


def test_override_with_missing_data_is_not_silently_replaced(con):
    add(con, "CONSOLIDATED", Q)
    set_scope_override(con, E, quarterly="STANDALONE", annual="STANDALONE", reason="pin")
    assert resolve_scope(con, E, AS_OF, END) is None  # no standalone data: no fallback to consolidated


def test_override_validation(con):
    with pytest.raises(AdminError):
        set_scope_override(con, E, quarterly="GROUP", annual="GROUP", reason="x")
    with pytest.raises(AdminError):
        set_scope_override(con, E, quarterly="STANDALONE", annual=None, reason="x")
    with pytest.raises(AdminError):
        set_scope_override(con, "nobody", quarterly="STANDALONE", annual="STANDALONE", reason="x")


def test_banks_and_insurers_get_a_ttm_window(con):
    """Regression: the old chooser anchored on revenue_from_operations, which banks and insurers do not file."""
    add(con, "STANDALONE", Q, tag="pat")
    add(con, "STANDALONE", Q, tag="interest_earned", value=900)
    d = resolve_scope(con, E, AS_OF, END)
    assert (d.scope, d.reason) == ("STANDALONE", "DEFAULT")
