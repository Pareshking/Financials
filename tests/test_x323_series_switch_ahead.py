"""X323: the PR-zip mcap file lists a symbol in its new series a few sessions before the bhavcopy switches it.

Real NSE files (tests/fixtures/series_switch, MANIFEST section QE): PR301026.zip (week end Fri 30 Oct 2026) lists
GFLLIMITED, NSIL, PILANIINVS, TVSHLTD, MAHSCOOTER and KAMAHOLD in series BE; the bhavcopy last has them in EQ
on 29 Oct (no bar on 30 Oct) and has them in BE from 2 or 3 Nov 2026. ELCIDIN (BE in the mcap file, EQ in every
bhavcopy here) and KICL (BE in the bhavcopy only from 9 Nov) stay unresolved: no switch within the window is on record.
"""

from datetime import date, datetime
from pathlib import Path

import pytest
from conftest import ARCHIVE, FETCHED_AT, Market

from _fixture_helpers import FIXTURES
from financials import universe
from financials.promoter import promote
from financials.staging import stage_holidays, stage_market_day, stage_mcap_day

DIR = Path(__file__).parent / "fixtures" / "series_switch"
SWITCHED = {"GFLLIMITED", "KAMAHOLD", "MAHSCOOTER", "NSIL", "PILANIINVS", "TVSHLTD"}


@pytest.fixture
def m(tmp_path):
    m = Market(tmp_path)
    hol = FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json"
    assert promote(m.con, stage_holidays(m.vault, m.stage_root, data=hol.read_bytes(), source_url="nse-hol",
                                         fetched_at=FETCHED_AT)).status == "PROMOTED"  # fmt: skip
    for d in ("20261029", "20261102", "20261103"):
        name = f"BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
        stage = stage_market_day(m.vault, m.stage_root, bhavcopy=(DIR / name).read_bytes(),
                                 bhavcopy_url=f"{ARCHIVE}/content/cm/{name}", delivery=None, delivery_url=None,
                                 fetched_at=FETCHED_AT)  # fmt: skip
        assert promote(m.con, stage).status == "PROMOTED"
    stage = stage_mcap_day(
        m.vault,
        m.stage_root,
        data=(DIR / "PR301026.zip").read_bytes(),
        source_url=f"{ARCHIVE}/archives/equities/bhavcopy/pr/PR301026.zip",
        fetched_at=FETCHED_AT,
    )
    assert promote(m.con, stage).status == "PROMOTED"
    yield m
    m.con.close()


def _run(con, now):
    con.execute("BEGIN")
    r = universe.update_universe(con, date(2026, 10, 26), date(2026, 11, 1), now=now)
    con.execute("COMMIT")
    return r


def _open(con) -> set[str]:
    return {s for (s,) in con.execute(
        "SELECT json_extract_string(details, '$.symbol') FROM quarantine_queue WHERE reason_code = "
        "'UNRESOLVED_SYMBOL' AND resolved_at IS NULL").fetchall()}  # fmt: skip


def test_fixture_rows_characterise_the_switch(m):
    mcap = dict(m.con.execute("SELECT symbol, series FROM raw_nse_mcap WHERE symbol IN (SELECT unnest(?))",
                              [sorted(SWITCHED | {"ELCIDIN", "KICL"})]).fetchall())  # fmt: skip
    assert set(mcap.values()) == {"BE"} and len(mcap) == 8
    hist = m.con.execute(
        "SELECT symbol, list(series || ' ' || valid_from ORDER BY valid_from) FROM security_identifier_history "
        "WHERE symbol IN (SELECT unnest(?)) GROUP BY 1 ORDER BY 1", [sorted(SWITCHED | {"ELCIDIN", "KICL"})]
    ).fetchall()  # fmt: skip
    for sym, h in hist:
        assert h[0] == "EQ 2026-10-29", sym
        assert (len(h) == 2 and h[1].startswith("BE 2026-11-0")) == (sym in SWITCHED), (sym, h)


def test_x323_resolves_the_row_to_the_security_that_switches(m, monkeypatch):
    con = m.con
    with monkeypatch.context() as mp:  # without the rule: one finding per row, as before
        mp.setattr(universe, "SERIES_SWITCH_SESSIONS", 0)
        before = _run(con, datetime(2026, 11, 2))
    assert SWITCHED | {"ELCIDIN", "KICL"} <= _open(con)
    assert not SWITCHED & {s for (s,) in con.execute("SELECT symbol FROM universe_membership").fetchall()}

    after = _run(con, datetime(2026, 11, 3))
    assert after["series_switch_resolved"] == len(SWITCHED)
    assert after["unresolved"] == before["unresolved"] - len(SWITCHED)
    assert after["joined"] == len(SWITCHED) and after["findings_closed"] == len(SWITCHED)
    assert not SWITCHED & _open(con) and {"ELCIDIN", "KICL"} <= _open(con)
    joined = con.execute(
        "SELECT u.symbol, u.series, u.joined_date, h.series FROM universe_membership u JOIN "
        "security_identifier_history h ON h.security_id = u.security_id AND h.valid_from = DATE '2026-10-29' "
        "WHERE u.symbol IN (SELECT unnest(?)) ORDER BY 1", [sorted(SWITCHED)]
    ).fetchall()  # fmt: skip
    # joined on the week end as filed (series BE), as the security that held the symbol in EQ that day
    assert joined == [(s, "BE", date(2026, 10, 30), "EQ") for s in sorted(SWITCHED)]
    notes = {r[0] for r in con.execute(
        "SELECT resolution_note FROM quarantine_queue WHERE json_extract_string(details, '$.symbol') "
        "IN (SELECT unnest(?))", [sorted(SWITCHED)]).fetchall()}  # fmt: skip
    assert notes == {universe.SERIES_SWITCH_NOTE}
