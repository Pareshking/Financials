"""X320 / X321: a security back after inactivity in another series keeps its identity (BCG, Brightcom Group).

Real NSE days (tests/fixtures/identity, MANIFEST section QE): BCG traded in BZ (FinInstrmId 23580) until
30 Dec 2024, was absent on 27 Feb 2025 (tests/fixtures/bhavcopy), and came back in BE with a new FinInstrmId
(8841) and the same ISIN INE425B01027 on 14 Jul 2025. close_inactive_securities closes the BZ interval in between.
Before X320 the returning row matched neither key (its FinInstrmId was new, the ISIN belonged to no open interval)
and created a second security and entity; X321 merges such a duplicate back into the original.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import ARCHIVE, FETCHED_AT, Market, bhav_bytes, bhav_url

from financials.admin import AdminError, duplicate_entity_isins, merge_duplicate_entity
from financials.identity import Interval, SecurityRegistry
from financials.parsers.udiff import BhavRow
from financials.promoter import close_inactive_securities, promote
from financials.staging import stage_market_day

IDENTITY_DIR = Path(__file__).parent / "fixtures" / "identity"
BCG_ISIN = "INE425B01027"


def _stage(m: Market, yyyymmdd: str) -> Path:
    name = f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
    if (IDENTITY_DIR / name).exists():
        data, url = (IDENTITY_DIR / name).read_bytes(), f"{ARCHIVE}/content/cm/{name}"
    else:
        data, url = bhav_bytes(yyyymmdd), bhav_url(yyyymmdd)
    return stage_market_day(
        m.vault, m.stage_root, bhavcopy=data, bhavcopy_url=url, delivery=None, delivery_url=None, fetched_at=FETCHED_AT
    )


def _bcg_through_suspension(m: Market) -> None:
    for d in ("20241230", "20250227"):
        assert promote(m.con, _stage(m, d)).status == "PROMOTED"
    assert close_inactive_securities(m.con, "NSE", date(2025, 2, 27), threshold=1) > 0
    closed = m.con.execute(
        "SELECT series, fin_instrm_id, valid_to FROM security_identifier_history WHERE isin = ?", [BCG_ISIN]
    ).fetchall()
    assert closed == [("BZ", "23580", date(2024, 12, 31))]
    assert promote(m.con, _stage(m, "20250714")).status == "PROMOTED"


def _state(m: Market) -> dict:
    con = m.con
    return {
        "history": con.execute(
            "SELECT security_id, series, fin_instrm_id, valid_from, valid_to FROM security_identifier_history "
            "WHERE isin = ? ORDER BY valid_from",
            [BCG_ISIN],
        ).fetchall(),
        "bars": con.execute(
            "SELECT security_id, trade_date, open FROM ohlcv WHERE security_id IN (SELECT security_id FROM "
            "security_identifier_history WHERE isin = ?) ORDER BY 2",
            [BCG_ISIN],
        ).fetchall(),
        "gaps": con.execute(
            "SELECT quarantine_id, security_id, details FROM quarantine_queue WHERE stage = 'GAP' AND security_id IN "
            "(SELECT security_id FROM security_identifier_history WHERE isin = ?) ORDER BY 1",
            [BCG_ISIN],
        ).fetchall(),
    }


def test_bcg_fixture_rows_characterise_the_series_switch():
    """The returning BE row has a FinInstrmId never seen before and the ISIN of the closed BZ interval."""
    import zipfile

    def bcg(name):
        with zipfile.ZipFile(IDENTITY_DIR / name) as zf:
            (inner,) = zf.namelist()
            lines = zf.read(inner).decode("utf-8-sig").splitlines()
        head = lines[0].split(",")
        rows = [dict(zip(head, ln.split(","), strict=False)) for ln in lines[1:]]
        return [(r["FinInstrmId"], r["ISIN"], r["SctySrs"], r["OpnPric"]) for r in rows if r["TckrSymb"] == "BCG"]

    assert bcg("BhavCopy_NSE_CM_0_0_0_20241230_F_0000.csv.zip") == [("23580", BCG_ISIN, "BZ", "10.31")]
    assert bcg("BhavCopy_NSE_CM_0_0_0_20250714_F_0000.csv.zip") == [("8841", BCG_ISIN, "BE", "21.80")]


def test_x320_reopens_the_closed_security_by_isin(market):
    m = market
    _bcg_through_suspension(m)
    s = _state(m)
    (sec,) = {r[0] for r in s["history"]}
    assert [r[1:] for r in s["history"]] == [
        ("BZ", "23580", date(2024, 12, 30), date(2024, 12, 31)),
        ("BE", "8841", date(2025, 7, 14), None),
    ]
    assert [r[1] for r in s["bars"]] == [date(2024, 12, 30), date(2025, 7, 14)]
    assert m.con.execute("SELECT count(*) FROM securities WHERE security_id = ?", [sec]).fetchone()[0] == 1
    # The six-month suspension gap (10.25 -> 21.80) is audited like any other return, never hidden.
    (gap,) = s["gaps"]
    assert json.loads(gap[2])["trade_date"] == "2025-07-14"
    assert duplicate_entity_isins(m.con) == []


def _registry_without_x320(monkeypatch):
    init = SecurityRegistry.__init__

    def old_init(self, exchange, intervals=()):
        init(self, exchange, intervals)
        self._closed_isin, self._closed_isin_owners = {}, {}

    monkeypatch.setattr(SecurityRegistry, "__init__", old_init)


def test_x321_merge_repairs_a_pre_x320_duplicate_to_the_replay_state(tmp_path, monkeypatch):
    (tmp_path / "replay").mkdir()
    (tmp_path / "old").mkdir()
    replay = Market(tmp_path / "replay")
    _bcg_through_suspension(replay)
    expected = _state(replay)
    replay.con.close()

    with monkeypatch.context() as mp:
        _registry_without_x320(mp)
        m = Market(tmp_path / "old")
        _bcg_through_suspension(m)
    before = _state(m)
    assert len({r[0] for r in before["history"]}) == 2 and before["gaps"] == []  # the defect
    dups = {d["isin"]: d for d in duplicate_entity_isins(m.con)}  # threshold 1 also closes 3 other returners
    assert len(dups) == 4
    dup = dups[BCG_ISIN]
    assert dup["isin"] == BCG_ISIN and dup["names"] == ["BRIGHTCOM GROUP LIMITED"]

    with pytest.raises(AdminError, match="note"):
        merge_duplicate_entity(m.con, BCG_ISIN, note=" ")
    r = merge_duplicate_entity(m.con, BCG_ISIN, note="QE: BCG BZ -> BE after suspension")
    assert r["kept"] == expected["history"][0][0] and r["gap_finding"] == expected["gaps"][0][0]
    assert r["rebound"]["security_identifier_history.security_id"] == 1
    assert r["rebound"]["ohlcv.security_id"] == 1
    assert _state(m) == expected  # same ids, intervals, bars and gap finding as a replay under X320
    left = {d["isin"] for d in duplicate_entity_isins(m.con)}
    assert len(left) == 3 and BCG_ISIN not in left
    status = m.con.execute("SELECT status, exit_reason FROM entity_master WHERE entity_id = ?",
                           [r["merged_entity"]]).fetchone()  # fmt: skip
    assert status[0] == "MERGED" and "X321" in status[1]
    log = m.con.execute("SELECT action, note FROM admin_log WHERE action = 'MERGE_DUPLICATE_ENTITY'").fetchall()
    assert log == [("MERGE_DUPLICATE_ENTITY", "QE: BCG BZ -> BE after suspension")]
    assert m.con.execute("SELECT count(*) FROM materialize_dirty WHERE entity_id IN (?, ?)",
                         [r["kept_entity"], r["merged_entity"]]).fetchone()[0] >= 2  # fmt: skip
    with pytest.raises(AdminError, match="1 securities"):
        merge_duplicate_entity(m.con, BCG_ISIN, note="again")
    m.con.close()


def test_x320_two_closed_holders_of_one_isin_are_quarantined_not_guessed():
    ivs = [
        Interval("sec_a", "NSE", "1", "AAA", "BZ", "INE000A01011", date(2024, 10, 1), date(2024, 11, 1)),
        Interval("sec_b", "NSE", "2", "AAA", "BE", "INE000A01011", date(2024, 12, 1), date(2025, 1, 1)),
    ]
    reg = SecurityRegistry("NSE", ivs)
    row = BhavRow(
        trade_date=date(2025, 7, 14), exchange="NSE", fin_instrm_id="3", isin="INE000A01011", symbol="AAA",
        series="EQ", name="A", open=None, high=None, low=None, close=None, last=None, prev_close_reported=None,
        volume=None, turnover_inr=None, trades=None,
    )  # fmt: skip
    out = reg.observe([row])
    assert out.new_securities == [] and out.resolved == {}
    assert [i.reason_code for i in out.issues] == ["AMBIGUOUS_REOPEN"]
    assert out.issues[0].details["candidates"] == ["sec_a", "sec_b"]
