"""X81, rule ISIN_TYPO_SYMBOL_MATCH: results filings whose stated ISIN is the security's own ISIN with the letter O
typed for 0 (AVANTIFEED `INE871CO1038` for INE871C01038) or two adjacent characters swapped (OBEROIRLTY
`INE903I01010` for INE093I01010), confirmed by the stated symbol naming exactly one security on the period end.
Anything looser stays UNKNOWN_ISIN."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from _fixture_helpers import XBRL_DIR
from financials.promoter import is_isin_typo, promote
from financials.staging import stage_results_xbrl

AVANTI = "INTEGRATED_FILING_INDAS_1511655_13082025060450_WEB.xml"
OBEROI = "INTEGRATED_FILING_INDAS_1489565_21072025071304_WEB.xml"


@pytest.mark.parametrize(
    ("stated", "actual", "ok"),
    [
        ("INE871CO1038", "INE871C01038", True),  # O for 0
        ("INE903I01010", "INE093I01010", True),  # adjacent swap
        ("INE0663A1033", "INE663A01033", False),  # shifted digit (SPLPETRO, live): not a swap
        ("INED50D01014", "INE850D01014", False),  # D for 8 (GODREJAGRO, live)
        ("INE756I08058", "INE756I01012", False),  # a debt ISIN (HDBFS, live)
        ("INE871C01038", "INE871C01038", False),  # identical is not a typo
    ],
)
def test_typo_shapes(stated, actual, ok):
    assert is_isin_typo(stated, actual) is ok


def _stage(market, name, data=None):
    return stage_results_xbrl(market.vault, market.stage_root, data=data or (XBRL_DIR / name).read_bytes(),
                              source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                              fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=datetime(2025, 8, 13, 0, 34),
                              broadcast_ts_source="API_FIELD")  # fmt: skip


@pytest.mark.parametrize(("name", "symbol"), [(AVANTI, "AVANTIFEED"), (OBEROI, "OBEROIRLTY")])
def test_typo_filings_promote_to_the_symbols_entity(market, name, symbol):
    promote(market.con, market.stage_day("20250228"))
    r = promote(market.con, _stage(market, name))
    assert r.status == "PROMOTED", r
    ent = market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [r.message]).fetchone()[0]
    want = market.con.execute("SELECT entity_id FROM securities WHERE security_id = ?",
                              [market.security_id(symbol)]).fetchone()[0]  # fmt: skip
    assert ent == want
    (params,) = market.con.execute(
        "SELECT params FROM admin_log WHERE action = 'RULE:ISIN_TYPO_SYMBOL_MATCH'"
    ).fetchone()
    assert json.loads(params)["symbol"] == symbol


def test_a_looser_mismatch_stays_quarantined(market):
    """Not an X81 typo; since X88 an unregistered ISIN with the symbol's issuer code is accepted, so the boundary is
    now: another issuer code (INE999Z) and another company name stay UNKNOWN_ISIN."""
    promote(market.con, market.stage_day("20250228"))
    data = (XBRL_DIR / AVANTI).read_bytes().replace(b"INE871CO1038", b"INE999Z01019")  # in-memory only
    data = data.replace(b"Avanti Feeds Limited", b"Avanti Industries Limited").replace(
        b"AVANTI FEEDS LIMITED", b"AVANTI INDUSTRIES LIMITED"
    )
    r = promote(market.con, _stage(market, AVANTI, data))
    assert r.status == "QUARANTINED"
    assert market.con.execute(
        "SELECT reason_code FROM quarantine_queue WHERE filing_id = ?", [r.message]
    ).fetchone() == ("UNKNOWN_ISIN",)
