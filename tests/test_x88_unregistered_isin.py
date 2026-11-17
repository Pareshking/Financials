"""X88, rule UNREGISTERED_ISIN_SYMBOL_MATCH. Live backfill: 20 results / SHP filings of 10 Nifty 500 companies were
UNKNOWN_ISIN although the stated symbol is right: the stated ISIN belongs to no security at all (garbled, a bond ISIN,
a pre-split ISIN). Accepted when the symbol names exactly one security and that security shares the ISIN issuer code
or the company name (exchange names are abbreviated: "KRISHNA INST OF MED SCI L")."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from _fixture_helpers import XBRL_DIR
from financials.promoter import names_agree, promote
from financials.staging import stage_results_xbrl

GODREJAGRO = "INTEGRATED_FILING_INDAS_1662668_30042026100228_WEB.xml"  # INED50D01014 for INE850D01014 (D for 8)
HDBFS = "INTEGRATED_FILING_NBFC_INDAS_1483684_15072025082343_WEB.xml"  # INE756I08058: its own bond ISIN
PERSISTENT = "INTEGRATED_FILING_INDAS_1491776_23072025083000_WEB.xml"  # INE262H01016: the pre-split ISIN


@pytest.mark.parametrize(
    ("stated", "legal", "ok"),
    [
        ("KRISHNA INSTITUTE OF MEDICAL SCIENCES LIMITED", "KRISHNA INST OF MED SCI L", True),
        ("E.I.D.- PARRY (INDIA) LIMITED", "EID PARRY INDIA LTD", True),
        ("Godrej Agrovet Limited", "GODREJ AGROVET LIMITED", True),
        ("TATA TELESERVICES (MAHARASHTRA) LIMITED", "TATA TELESERV(MAHARASTRA)", False),  # exchange misspelling
        ("Godrej Industries Limited", "GODREJ AGROVET LIMITED", False),
        (None, "GODREJ AGROVET LIMITED", False),
    ],
)
def test_names_agree(stated, legal, ok):
    assert names_agree(stated, legal) is ok


def _stage(market, name, data=None):
    return stage_results_xbrl(market.vault, market.stage_root, data=data or (XBRL_DIR / name).read_bytes(),
                              source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + name,
                              fetched_at=datetime(2026, 11, 14, 6), broadcast_ts=datetime(2025, 7, 15, 9),
                              broadcast_ts_source="API_FIELD")  # fmt: skip


@pytest.mark.parametrize(
    ("name", "symbol", "day", "stated"),
    [
        (GODREJAGRO, "GODREJAGRO", "20250228", "INED50D01014"),  # issuer code differs; the name agrees
        (HDBFS, "HDBFS", "20250919", "INE756I08058"),  # same issuer code
        (PERSISTENT, "PERSISTENT", "20250228", "INE262H01016"),  # same issuer code
    ],
)
def test_unregistered_isin_promotes_to_the_symbols_entity(market, name, symbol, day, stated):
    assert stated.encode() in (XBRL_DIR / name).read_bytes()
    promote(market.con, market.stage_day(day))
    r = promote(market.con, _stage(market, name))
    assert r.status == "PROMOTED", r
    ent = market.con.execute("SELECT DISTINCT entity_id FROM filing_meta WHERE filing_id = ?", [r.message]).fetchone()
    want = market.con.execute("SELECT entity_id FROM securities WHERE security_id = ?",
                              [market.security_id(symbol)]).fetchone()  # fmt: skip
    assert ent == want
    (params,) = market.con.execute(
        "SELECT params FROM admin_log WHERE action = 'RULE:UNREGISTERED_ISIN_SYMBOL_MATCH'"
    ).fetchone()
    assert json.loads(params)["stated_isin"] == stated


def test_other_issuer_and_other_name_stays_quarantined(market):
    promote(market.con, market.stage_day("20250228"))
    data = (XBRL_DIR / GODREJAGRO).read_bytes().replace(b"Godrej Agrovet Limited", b"Godrej Industries Limited")
    r = promote(market.con, _stage(market, GODREJAGRO, data))  # in-memory only; the fixture is untouched
    assert r.status == "QUARANTINED"
    assert market.con.execute("SELECT reason_code FROM quarantine_queue WHERE filing_id = ?",
                              [r.message]).fetchone() == ("UNKNOWN_ISIN",)  # fmt: skip
