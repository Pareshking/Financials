"""NSE corporate-actions adapters on real API/RSS fixtures, then end-to-end with real ex-dates."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.parsers.nse_corp_actions import parse_corp_action_rss, parse_nse_corp_actions_json, parse_purpose
from financials.promoter import promote
from financials.staging import stage_corp_actions

CA_JSON = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
CA_RSS = FIXTURES / "corp_actions" / "RSS_Corporate_action_20261113.xml"
CA_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=15-09-2025&to_date=17-10-2025"
)
D = Decimal


@pytest.fixture(scope="module")
def records():
    return parse_nse_corp_actions_json(CA_JSON.read_bytes())


def by_symbol(records, symbol):
    return [r for r in records if r.symbol == symbol]


def test_every_equity_record_parses_and_bonds_are_ignored(records):
    assert len(records) == 265
    assert {r.parse_status for r in records if r.series == "EQ"} == {"PARSED"}
    assert {r.series for r in records if r.parse_status == "IGNORED"} == {"GS"}


def test_api_symbol_is_current_but_isin_is_pre_action(records):
    """[CA1, CA2]: Tata Motors' demerger is listed as TMPV; ADANIPOWER carries its pre-split ISIN."""
    (tm,) = by_symbol(records, "TMPV")
    assert (tm.isin, tm.ex_date, tm.components[0].action_type) == ("INE155A01022", date(2025, 10, 14), "DEMERGER")
    (adani,) = by_symbol(records, "ADANIPOWER")
    assert adani.isin == "INE814H01011"
    assert adani.face_value == D(2)  # current face value [CA3]
    c = adani.components[0]
    assert (c.action_type, c.ratio_num, c.ratio_den) == ("SPLIT", D(2), D(10))


def test_bonus_rights_dividend_and_same_day_pair(records):
    (godfrey,) = by_symbol(records, "GODFRYPHLP")
    assert (godfrey.components[0].ratio_num, godfrey.components[0].ratio_den) == (D(2), D(1))
    (cap,) = by_symbol(records, "CAPTRUST")
    assert cap.components[0].issue_price == D(14)  # face value 10 + premium 4 [CA4]
    (mah,) = by_symbol(records, "MAHSCOOTER")
    assert mah.components[0].cash_per_share == D(160)
    nazara = by_symbol(records, "NAZARA")
    assert sorted(r.components[0].action_type for r in nazara) == ["BONUS", "SPLIT"]
    assert {r.ex_date for r in nazara} == {date(2025, 9, 26)}


@pytest.mark.parametrize(
    "subject",
    [
        "Scheme of Arrangement",
        "Bonus 1:1 And Something Else",
        "Rights 1:2",  # no premium
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share",
        "Bonus 0:1",
        "Capital Reduction",
    ],
)
def test_unrecognised_purposes_are_unparsed(subject):
    status, reason, comps = parse_purpose(subject, D(10))
    assert status == "UNPARSED" and reason and comps == ()


def test_combined_purpose_parses_each_part():
    status, _, comps = parse_purpose("Final Dividend - Rs 5 Per Share / Special Dividend - Rs 2 Per Share", D(10))
    assert status == "PARSED"
    assert [c.cash_per_share for c in comps] == [D(5), D(2)]


def test_rights_without_face_value_is_unparsed():
    assert parse_purpose("Rights 1:1 @ Premium Rs 4/-", None)[0] == "UNPARSED"


def test_rss_is_discovery_only():
    """[CA6]: items have company name and purpose but no symbol or ISIN."""
    items = parse_corp_action_rss(CA_RSS.read_bytes())
    assert len(items) == 39
    first = items[0]
    assert first.company == "Star Cement Limited"
    assert first.ex_date == date(2026, 11, 13)
    assert first.purpose == "INTERIM DIVIDEND - RE 1 PER SHARE"
    assert first.pub_date == datetime(2026, 11, 13, 3, 11, 50)
    assert not hasattr(first, "isin") and not hasattr(first, "symbol")


# ── end-to-end with real ex-dates ─────────────────────────────────────────


def stage_ca(market):
    return stage_corp_actions(
        market.vault, market.stage_root, data=CA_JSON.read_bytes(), source_url=CA_URL, fetched_at=FETCHED_AT
    )


def action_status(market, symbol, ex_date):
    sec = market.security_id(symbol)
    return market.con.execute(
        "SELECT action_type, status, price_factor FROM corp_actions WHERE security_id = ? AND ex_date = ? "
        "ORDER BY action_type",
        [sec, ex_date],
    ).fetchall()


def open_gaps(market, symbol, trade_date):
    sec = market.security_id(symbol)
    return market.con.execute(
        "SELECT reason_code FROM quarantine_queue WHERE stage = 'GAP' AND security_id = ? AND resolved_at IS NULL "
        "AND CAST(json_extract_string(details, '$.trade_date') AS DATE) = ?",
        [sec, trade_date],
    ).fetchall()


@pytest.fixture(scope="module")
def promoted(tmp_path_factory):
    """Read-only shared state: 19 Sep, then the corporate-actions file, then the other fixture days."""
    from conftest import Market

    market = Market(tmp_path_factory.mktemp("ca_market"))
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    result = promote(market.con, stage_ca(market))
    assert result.status == "PROMOTED", result
    for d in ("20250922", "20250923", "20251013", "20251014"):
        assert promote(market.con, market.stage_day(d)).status == "PROMOTED"
    yield market
    market.con.close()


def test_real_actions_verify_against_real_gaps(promoted):
    m = promoted
    assert action_status(m, "ADANIPOWER", date(2025, 9, 22)) == [("SPLIT", "VERIFIED", 0.2)]
    assert action_status(m, "PIDILITIND", date(2025, 9, 23)) == [("BONUS", "VERIFIED", 0.5)]
    assert action_status(m, "TATAINVEST", date(2025, 10, 14)) == [("SPLIT", "VERIFIED", 0.1)]
    ((kind, status, pf),) = action_status(m, "TATAMOTORS", date(2025, 10, 14))  # resolved by ISIN, not TMPV
    assert (kind, status) == ("DEMERGER", "VERIFIED") and pf == pytest.approx(400 / 660.75)
    for sym, d in [
        ("ADANIPOWER", date(2025, 9, 22)),
        ("PIDILITIND", date(2025, 9, 23)),
        ("TATAINVEST", date(2025, 10, 14)),
        ("TATAMOTORS", date(2025, 10, 14)),
    ]:
        assert open_gaps(m, sym, d) == [], sym


def test_dividend_is_unobservable_and_does_not_hide_gaps(promoted):
    assert action_status(promoted, "MAHSCOOTER", date(2025, 9, 22)) == [("DIVIDEND", "UNOBSERVABLE", 1.0)]


def test_actions_before_first_bar_stay_pending(promoted):
    assert action_status(promoted, "GODFRYPHLP", date(2025, 9, 16)) == [("BONUS", "PENDING", None)]


def test_corp_action_promotion_is_idempotent(market):
    promote(market.con, market.stage_day("20250919"))
    promote(market.con, stage_ca(market))
    before = market.con.execute("SELECT count(*), sum(hash(status)) FROM corp_actions").fetchone()
    again = stage_corp_actions(
        market.vault, market.stage_root / "again", data=CA_JSON.read_bytes(), source_url=CA_URL, fetched_at=FETCHED_AT
    )
    assert promote(market.con, again).status == "PROMOTED"
    assert market.con.execute("SELECT count(*), sum(hash(status)) FROM corp_actions").fetchone() == before


def test_stale_api_isin_resolves_by_symbol_only_for_same_issuer(promoted):
    """[CA7] DIXON's API ISIN INE935N01012 is stale (bhavcopy INE935N01020); same issuer code 935N."""
    assert action_status(promoted, "DIXON", date(2025, 9, 16)) == [("DIVIDEND", "PENDING", None)]
    # PREMIERPOL: API INE247401016 vs bhavcopy INE309M01020 -> different issuer: never attached.
    rows = promoted.con.execute(
        "SELECT reason_code FROM quarantine_queue WHERE stage = 'CORP_ACTION' "
        "AND json_extract_string(details, '$.symbol') = 'PREMIERPOL'"
    ).fetchall()
    assert rows == [("STALE_ISIN_OTHER_ISSUER",)]


def test_unparsed_purpose_is_quarantined_and_holds_prices(market):
    import json

    promote(market.con, market.stage_day("20250922"))
    pid = next(r for r in json.loads(CA_JSON.read_bytes()) if r["symbol"] == "PIDILITIND")
    odd = [{**pid, "subject": "Scheme of Arrangement"}]
    stage = stage_corp_actions(
        market.vault, market.stage_root, data=json.dumps(odd).encode(), source_url=CA_URL + "&x", fetched_at=FETCHED_AT
    )
    result = promote(market.con, stage)
    assert result.status == "PROMOTED" and len(result.quarantined) == 1
    assert action_status(market, "PIDILITIND", date(2025, 9, 23)) == [("UNKNOWN", "QUARANTINED", None)]
    promote(market.con, market.stage_day("20250923"))
    assert open_gaps(market, "PIDILITIND", date(2025, 9, 23)) == [("UNEXPLAINED_GAP",)]
    from financials.promoter import adjusted_closes

    assert [d for d, _ in adjusted_closes(market.con, market.security_id("PIDILITIND"))] == [date(2025, 9, 22)]
