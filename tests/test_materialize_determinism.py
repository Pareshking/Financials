"""Feature reads that must not depend on DuckDB's scan order (found by scripts/compare_materialize.py on the live
database, 2026-11-16: the same query returned different rows run to run, so the legacy and run-level paths
"differed" on a handful of rows; both read these through the same code).

1. `features._preload` paid-up share count: `arg_max(value_other, period_end)` over every scope tied when the
   STANDALONE and CONSOLIDATED filings of one quarter both tag the capital (225.4 vs 225.5 million shares: rounding
   of the capital in crore; one consolidated filing tagged 0). Now: latest period end, STANDALONE first, then
   latest visible, then filing_id; a count <= 0 is never used.
2. `features_more.segment_columns`: two members filed under one label ("Others" twice) collided in a dict and the
   last row of an unordered scan won (largest_segment_revenue_share 0.6971 vs 0.6751). Now: rows in a fixed order,
   members sharing a label add up, a member reported by two elements counts once.
"""

from __future__ import annotations

import random
from datetime import date, datetime
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import XBRL_DIR
from financials import features
from financials import features_more as M
from financials.db import apply_schema, connect, insert_rows
from financials.promoter import promote
from financials.staging import stage_results_xbrl

E, VIS = "ent", datetime(2026, 1, 1)


def _paid_up_db(values: dict[str, Decimal]):
    """One entity, one filing per scope, each tagging the paid-up share count for the same quarter end."""
    con = connect()
    apply_schema(con)
    insert_rows(con, "entity_master", [{"entity_id": E, "legal_name": "Test"}])
    insert_rows(con, "blobs", [{"sha256": "x", "byte_size": 1, "media_type": "t", "storage_path": "p",
                                "first_fetched_at": VIS}])  # fmt: skip
    insert_rows(con, "filings", [{"filing_id": f"f_{s}", "sha256": "x", "exchange": "NSE", "category": "T",
                                  "source_url": s, "broadcast_ts_source": "UNKNOWN", "fetched_at": VIS}
                                 for s in values])  # fmt: skip
    insert_rows(con, "fact_observations", [{
        "filing_id": f"f_{s}", "parser_version": "t", "entity_id": E, "scope": s,
        "canonical_tag": "shares_from_paid_up", "period_type": "INSTANT", "period_start": date(2025, 3, 31),
        "period_end": date(2025, 3, 31),
        "period_months": None, "unit": "SHARES", "value_inr": None, "value_other": v, "source_element": "t",
        "visible_from_ts": VIS,
    } for s, v in values.items()])  # fmt: skip
    return con


def test_paid_up_share_count_prefers_standalone_and_skips_non_positive():
    as_of_ts = datetime(2026, 1, 2)
    # The live case: the two scopes of one quarter disagree (225.4 vs 225.5 million): the standalone count, always.
    con = _paid_up_db({"CONSOLIDATED": Decimal(225_400_000), "STANDALONE": Decimal(225_500_000)})
    assert {features._preload(con, as_of_ts)[1][E] for _ in range(20)} == {(Decimal(225_500_000), date(2025, 3, 31))}
    con.close()
    # A consolidated filing tagging paid-up capital 0 is no share count, whatever the other scope says.
    con = _paid_up_db({"CONSOLIDATED": Decimal(0)})
    assert E not in features._preload(con, as_of_ts)[1]
    con.close()
    con = _paid_up_db({"CONSOLIDATED": Decimal(599_300_000), "STANDALONE": Decimal(0)})
    assert features._preload(con, as_of_ts)[1][E] == (Decimal(599_300_000), date(2025, 3, 31))
    con.close()


def _row(key, value, member, months=12, metric="REVENUE"):
    return (metric, (date(2024, 4, 1), date(2025, 3, 31)), months, key.lower(), key, Decimal(value), member)


def test_segment_members_sharing_a_label_add_up_in_any_order():
    rows = [
        _row("Electrical cables", 44990, ("ax", "S1")),
        _row("Copper rods", 16841, ("ax", "S3")),
        _row("Others", 2561, ("ax", "S4")),
        _row("Others", 0, ("ax", "S5")),  # a second "Others" member (the live case)
        _row("Others", 2561, ("ax", "S4")),  # S4 again from another element: counted once
        _row("Electrical cables", 9000, ("ax", "S1"), metric="RESULT"),
    ]
    first = M.segment_columns(rows)
    assert first["segment_count"] == 3
    assert first["largest_segment_revenue_share"] == float(Decimal(44990) / Decimal(44990 + 16841 + 2561))
    rng = random.Random(3)
    for _ in range(20):  # the first row of a member wins only between rows of that member; the rest is order-free
        shuffled = rows[:]
        rng.shuffle(shuffled)
        assert M.segment_columns(shuffled) == first


def test_segment_inputs_are_ordered(market):
    """segment_inputs returns rows in a fixed order (metric, period, axis, element, member), whatever the scan."""
    path = XBRL_DIR / "INTEGRATED_FILING_INDAS_1753292_04112026105837_WEB.xml"  # Cummins Q2 FY27 (segments)
    promote(market.con, market.stage_day("20261112"))
    st = stage_results_xbrl(market.vault, market.stage_root, data=path.read_bytes(),
                            source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + path.name,
                            fetched_at=FETCHED_AT, broadcast_ts=datetime(2026, 11, 4, 6, 0),
                            broadcast_ts_source="API_FIELD")  # fmt: skip
    assert promote(market.con, st).status == "PROMOTED"
    seg = M.segment_inputs(market.con, datetime(2026, 11, 13))
    assert seg
    for rows in seg.values():
        keys = [(r[0], r[1][1], r[1][0]) for r in rows]
        assert keys == sorted(keys)
        assert all(len(r) == 7 for r in rows)
