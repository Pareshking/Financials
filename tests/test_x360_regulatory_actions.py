"""X360: Reg. 30 regulatory actions (AIATOP, E12) and restructuring (REG30_Restructuring, E13); X361: Reg. 30 90-day
columns are NULL until their window lies inside the announcements-RSS capture.

Fixtures: tests/fixtures/events_x360 (real files from the archive links of the vaulted announcements RSS).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from _fixture_helpers import FIXTURES
from financials.features import EVENT_COLUMNS, _event_counts
from financials.features_extra import event_columns, event_window_complete
from financials.fetch.jobs import EVENT_PREFIXES
from financials.parsers.reg30_events import parse_reg30_event
from financials.promoter import promote
from financials.staging import stage_raw_only, stage_reg30_event
from financials.timeutil import ist_to_utc

EV = FIXTURES / "events_x360"
FILES = sorted(EV.glob("*.xml"))
D = Decimal


def _events(name: str) -> list[dict]:
    r = parse_reg30_event((EV / name).read_bytes())
    assert r.ok
    return r.events


def _one(name: str) -> dict:
    (e,) = _events(name)
    return e


def test_both_families_are_fetched():
    assert all(f.name.startswith(EVENT_PREFIXES) for f in FILES) and len(FILES) == 8


def test_fines_and_other_actions_taken():
    e = _one("AIATOP_19759_WebXMLFile_20261113_171940576.xml")  # One Mobikwik
    assert (e["event_type"], e["event_subtype"], e["counterparty"], e["amount_inr"]) == (
        "REGULATORY_ACTION",
        "Imposition of fine or penalty",
        "The Reserve Bank of India",
        D(900000),
    )
    e = _one("AIATOP_1042_WebXMLFile_20261119_184853217.xml")  # D S Kulkarni: both exchanges' fine
    assert (e["amount_inr"], e["occurred_on"]) == (D(696200), date(2026, 11, 18))
    assert e["details"]["persons_against"] == ["D S KULKARNI DEVELOPERS LIMITED"]
    e = _one("AIATOP_753_WebXMLFile_20261113_152634093.xml")  # Styrenix: an ITAT order, no amount
    assert (e["event_type"], e["event_subtype"], e["amount_inr"]) == (
        "REGULATORY_ACTION",
        "Any other similar action(s)",
        None,
    )


def test_an_action_initiated_is_its_own_type():
    e = _one("AIATOP_25794_WebXMLFile_20261119_200300649.xml")  # Om Freight: state tax search
    assert (e["event_type"], e["event_subtype"], e["amount_inr"]) == (
        "REGULATORY_ACTION_INITIATED",
        "Search or seizure",
        None,
    )
    assert e["counterparty"] == "Assistant Commissioner of State Tax, Maharashtra State, Mumbai"


def test_restructuring_types_and_cash_consideration():
    e = _one("REG30_Restructuring_19784_WebXMLFile_20261119_193423456.xml")  # Paytm buys CardUp
    assert (e["event_type"], e["amount_inr"], e["counterparty"]) == (
        "ACQUISITION",
        D(1620000000),
        "CardUp Pte. Ltd. (“CardUp”)",
    )
    e = _one("REG30_Restructuring_21609_WebXMLFile_20261123_215959359.xml")  # SecMark: new subsidiary
    assert (e["event_type"], e["amount_inr"]) == ("INCORPORATION", D(100000))
    e = _one("REG30_Restructuring_1224_WebXMLFile_20261120_145330703.xml")  # Ipca: unit sold, no cash element
    assert (e["event_type"], e["amount_inr"]) == ("SALE_OR_DISPOSAL", None)
    e = _one("REG30_Restructuring_19784_WebXMLFile_20261119_192832871.xml")  # Paytm: update, no event type
    assert (e["event_type"], e["event_subtype"], e["amount_inr"]) == ("RESTRUCTURING_UPDATE", None, None)


def _broadcast(name: str) -> datetime:
    stamp = name.rsplit("_", 2)[-2:]  # ..._<YYYYMMDD>_<HHMMSSmmm>.xml: the exchange's file time (IST)
    d, t = datetime.strptime(stamp[0], "%Y%m%d").date(), datetime.strptime(stamp[1][:6], "%H%M%S").time()
    return ist_to_utc(d, t)


@pytest.fixture
def x360_market(market):
    from conftest import FETCHED_AT

    promote(market.con, market.stage_day("20261112"))
    market.status = {}
    for f in FILES:
        stage = stage_reg30_event(market.vault, market.stage_root, data=f.read_bytes(),
                                  source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + f.name,
                                  fetched_at=FETCHED_AT, broadcast_ts=_broadcast(f.name),
                                  broadcast_ts_source="RSS_PUBDATE")  # fmt: skip
        market.status[f.name] = promote(market.con, stage).status
    return market


def _by_symbol(con) -> dict[str, str]:
    return dict(con.execute(
        "SELECT DISTINCT h.symbol, s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id)"
    ).fetchall())  # fmt: skip


def test_ninety_day_counts(x360_market):
    m = x360_market
    promoted = {n for n, s in m.status.items() if s == "PROMOTED"}
    ents = _by_symbol(m.con)
    counts = _event_counts(m.con, date(2026, 11, 24), ist_to_utc(date(2026, 11, 24), time(12, 0)))
    got = {sym: counts.get(ents[sym]) for sym in ("MOBIKWIK", "DSKULKARNI", "STYRENIX", "OMFREIGHT", "PAYTM", "IPCALAB")
           if sym in ents}  # fmt: skip
    assert {"MOBIKWIK", "STYRENIX", "PAYTM", "IPCALAB"} <= set(got), sorted(promoted)
    pick = ("penalties_90d", "penalty_amount_90d", "regulatory_actions_90d", "acquisitions_90d",
            "acquisition_value_90d")  # fmt: skip
    assert tuple(got["MOBIKWIK"][c] for c in pick) == (1, D(900000), 1, 0, None)
    assert tuple(got["STYRENIX"][c] for c in pick) == (0, None, 1, 0, None)  # not a fine, still an action
    assert tuple(got["PAYTM"][c] for c in pick) == (0, None, 0, 1, D(1620000000))  # the update is not counted
    assert tuple(got["IPCALAB"][c] for c in pick) == (0, None, 0, 0, None)  # a sale is not an acquisition
    if "OMFREIGHT" in got:
        assert tuple(got["OMFREIGHT"][c] for c in pick) == (0, None, 1, 0, None)
    assert set(EVENT_COLUMNS) == set(got["MOBIKWIK"])
    later = _event_counts(m.con, date(2027, 3, 1), ist_to_utc(date(2027, 3, 1), time(0, 0)))
    assert later == {}  # every window has passed


def _rss_capture(m, fetched_at: datetime) -> None:
    rss = (FIXTURES / "events" / "nse_Online_announcements_20261113.xml").read_bytes()
    promote(m.con, stage_raw_only(m.vault, m.stage_root, data=rss, ext="xml", media_type="application/rss+xml",
                                  category="ANNOUNCEMENTS_RSS", source_url="memory://rss-" + fetched_at.isoformat(),
                                  fetched_at=fetched_at))  # fmt: skip


def test_x361_windows_outside_the_rss_capture_are_null(market):
    m = market
    promote(m.con, m.stage_day("20261112"))
    as_of, ts = date(2026, 11, 24), ist_to_utc(date(2026, 11, 24), time(23, 0))
    assert not event_window_complete(m.con, as_of, ts)  # nothing captured: no window is complete
    _rss_capture(m, datetime(2026, 11, 14, 3, 0))
    assert not event_window_complete(m.con, as_of, ts)  # 10 of 90 days captured
    first_full = date(2026, 11, 14) + timedelta(days=89)
    assert event_window_complete(m.con, first_full, ts + timedelta(days=89))
    assert not event_window_complete(m.con, first_full - timedelta(days=1), ts + timedelta(days=88))
    # point in time: a capture fetched after the as-of does not count for it
    _rss_capture(m, datetime(2026, 8, 1, 3, 0))
    assert event_window_complete(m.con, as_of, ts)
    assert not event_window_complete(m.con, as_of, datetime(2026, 7, 31))


def test_x361_extra_event_columns_are_null_when_incomplete():
    row = dict.fromkeys(("auditor_resignations_90d", "kmp_resignations_90d", "fraud_or_default_90d"))
    out = event_columns(row, None, {}, complete=False)
    assert all(out[c] is None for c in ("litigations_90d", "allotments_90d", "fund_raising_events_90d",
                                        "rf_litigation_90d", "rf_auditor_resignation_90d"))  # fmt: skip
    out = event_columns({**row, "auditor_resignations_90d": 0}, None, {}, complete=True)
    assert out["litigations_90d"] == 0 and out["rf_litigation_90d"] is False
