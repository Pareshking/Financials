"""NSE PR-zip market-cap file [X130-X133] and the sticky Rs 500 Cr universe (rule U1) [X134]."""

from __future__ import annotations

import collections
import io
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import CORP, FIXTURES, XBRL_DIR
from financials import universe
from financials.parsers import ParseError
from financials.parsers.pr_mcap import HEADER, mcap_member, parse_mcap_csv, parse_pr_mcap
from financials.parsers.shareholding import parse_shareholding, parse_shp_master
from financials.promoter import promote
from financials.staging import stage_holidays, stage_mcap_day, stage_results_xbrl, stage_shareholding

PR = FIXTURES / "pr_zip"
FILES = ("PR011024", "PR300625", "PR300926", "PR131126")
URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/{}.zip"
CR500 = Decimal("5000000000")


def raw(name: str) -> bytes:
    return (PR / f"{name}.zip").read_bytes()


def rows(name: str) -> dict[tuple[str, str], object]:
    return {(r.symbol, r.series): r for r in parse_pr_mcap(raw(name))}


# ── X130: the file and its format across the whole scope ──


def test_x130_member_name_case_changes_header_does_not():
    names = {}
    for f in FILES:
        with zipfile.ZipFile(PR / f"{f}.zip") as z:
            mc = [n for n in z.namelist() if n.lower().startswith("mcap")]
            names[f] = (len(z.namelist()), mc)
            head = z.read(mc[0]).decode("ascii").splitlines()[0]
            assert tuple(h.strip() for h in head.split(",")) == HEADER
    assert names == {
        "PR011024": (15, ["MCAP01102024.csv"]),  # 2024 zips also carry PE_ddmmyy.csv
        "PR300625": (14, ["MCAP30062025.csv"]),
        "PR300926": (14, ["mcap30092026.csv"]),
        "PR131126": (14, ["mcap13112026.csv"]),
    }


def test_x130_counts_series_and_category():
    got = {f: parse_pr_mcap(raw(f)) for f in FILES}
    assert {f: len(v) for f, v in got.items()} == {"PR011024": 2448, "PR300625": 2628, "PR300926": 3195,
                                                   "PR131126": 3246}  # fmt: skip
    big = {f: sum(r.series in ("EQ", "BE", "BZ") and r.market_cap_inr >= CR500 for r in v) for f, v in got.items()}
    assert big == {"PR011024": 1514, "PR300625": 1536, "PR300926": 1798, "PR131126": 1823}
    nov = got["PR131126"]
    assert collections.Counter(r.series for r in nov).most_common(7) == [
        ("EQ", 2391), ("SM", 479), ("BE", 210), ("ST", 103), ("BZ", 34), ("IV", 21), ("RR", 6)]  # fmt: skip
    assert collections.Counter(r.category for r in nov) == {"Listed": 2996, "Permitted": 250}
    assert {r.trade_date for r in nov} == {date(2026, 11, 13)}


def test_x130_reliance_row_exact():
    r = rows("PR131126")[("RELIANCE", "EQ")]
    assert (r.issue_size, r.close, r.market_cap_inr, r.face_value) == (
        13532538722, Decimal("1339.70"), Decimal("18129542125863.40"), Decimal("10.00"))  # fmt: skip
    assert (r.security_name, r.category, r.last_trade_date) == ("RELIANCE INDUSTRIES LTD", "Listed", date(2026, 11, 13))


def test_x131_not_traded_and_summary_rows():
    r = rows("PR011024")[("ABNINT", "IT")]
    assert r.last_trade_date is None and r.issue_size == 419532
    _, data = mcap_member(raw("PR131126"))
    lines = data.decode("ascii").splitlines()
    assert [ln.split(",")[1].strip() for ln in lines[-3:]] == ["Listed", "Permitted", "Total"]
    with pytest.raises(ParseError, match="sum to"):  # one security row missing: the summary sums disagree
        parse_mcap_csv("\n".join(lines[:5] + lines[6:]).encode())
    with pytest.raises(ParseError, match="summary rows"):  # cut before the summary rows
        parse_mcap_csv("\n".join(lines[:-3]).encode())


def test_x131_zip_without_mcap_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z, zipfile.ZipFile(PR / "PR131126.zip") as src:
        z.writestr("readme.txt", src.read("readme.txt"))
    with pytest.raises(ParseError, match="one mcap file"):
        parse_pr_mcap(buf.getvalue())
    with pytest.raises(ParseError):
        parse_pr_mcap(b"not a zip")


def test_x132_market_cap_is_issue_size_times_a_price_within_two_paise():
    for f in FILES:
        got = parse_pr_mcap(raw(f))
        for r in got:
            # implied price (market cap / issue size) is the close +/- 0, 1 or 2 paise (paisa rounding of the cap)
            assert abs(r.market_cap_inr / r.issue_size - r.close) <= Decimal("0.0200001")
        exact = sum(r.market_cap_inr == r.issue_size * r.close for r in got)
        assert exact == {"PR011024": 1718, "PR300625": 1783, "PR300926": 2133, "PR131126": 2106}[f]


def test_x133_issue_size_follows_share_count_events():
    oct24, jun25, sep26 = rows("PR011024"), rows("PR300625"), rows("PR300926")
    # ADANIPOWER 1:5 split (ex 2025-09-22, CA fixture): five times the shares, face value 10 -> 2
    a, b = oct24[("ADANIPOWER", "EQ")], sep26[("ADANIPOWER", "EQ")]
    assert (a.issue_size * 5, a.face_value, b.face_value) == (b.issue_size, Decimal("10.00"), Decimal("2.00"))
    # RELIANCE 1:1 bonus (Oct 2024) plus allotments: 6,765,817,114 -> 13,532,472,634
    assert (oct24[("RELIANCE", "EQ")].issue_size, jun25[("RELIANCE", "EQ")].issue_size) == (6765817114, 13532472634)


def test_x133_elin_issue_size_matches_reg31_and_annual_counts():
    # FY25 issued shares in the Reg. 34 annual XBRL are 49,659,220 [X114]; the Reg. 31 total on 2026-09-30 is the
    # SHP fixture's TOTAL. NSE's Issue Size equals both on the same dates.
    assert rows("PR011024")[("ELIN", "EQ")].issue_size == 49659220
    shp = parse_shareholding((XBRL_DIR / "SHP_1739151_15102026054406_WEB.xml").read_bytes())
    assert shp.meta["as_of_date"] == date(2026, 9, 30)
    assert rows("PR300926")[("ELIN", "EQ")].issue_size == shp.categories["TOTAL"]["shares"] == 49709220


# ── pipeline: stage -> promote -> universe ──


@pytest.fixture(scope="module")
def umarket(tmp_path_factory):
    m = Market(tmp_path_factory.mktemp("mcap_universe"))

    def ok(stage, status=("PROMOTED",)):
        r = promote(m.con, stage)
        assert r.status in status, r
        return r

    ok(m.stage_day("20251014"))
    ok(m.stage_day("20261112"))
    hol = FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json"
    ok(stage_holidays(m.vault, m.stage_root, data=hol.read_bytes(), source_url="nse-hol", fetched_at=FETCHED_AT))
    ok(stage_results_xbrl(m.vault, m.stage_root, data=CORP.read_bytes(), source_url="nse-xbrl-corp",
                          fetched_at=FETCHED_AT))  # fmt: skip
    master = parse_shp_master(
        (FIXTURES / "shareholding" / "nse_corporate-share-holdings-master_ELIN_20261113.json").read_bytes()
    )[0]
    ok(stage_shareholding(m.vault, m.stage_root, data=(XBRL_DIR / "SHP_1739151_15102026054406_WEB.xml").read_bytes(),
                          source_url=master.xbrl_url, fetched_at=FETCHED_AT,
                          broadcast_ts=master.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None),
                          broadcast_ts_source="API_FIELD"), ("PROMOTED", "QUARANTINED"))  # fmt: skip
    m.mcap = {}
    for f in ("PR300926", "PR131126"):
        stage = stage_mcap_day(m.vault, m.stage_root, data=raw(f), source_url=URL.format(f), fetched_at=FETCHED_AT)
        m.mcap[f] = ok(stage)
    yield m
    m.con.close()


def test_mcap_day_promotes_raw_rows_as_sent(umarket):
    con = umarket.con
    assert umarket.mcap["PR131126"].message == "2026-11-13: 2635 EQ/BE/BZ rows"
    n, issue, mcap = con.execute(
        "SELECT count(*), max(issue_size) FILTER (WHERE symbol = 'RELIANCE'), "
        "max(market_cap_inr) FILTER (WHERE symbol = 'RELIANCE') FROM raw_nse_mcap WHERE trade_date = '2026-11-13'"
    ).fetchone()
    assert (n, issue, mcap) == (3246, 13532538722, Decimal("18129542125863.40"))
    f = con.execute("SELECT category, broadcast_ts_source FROM filings WHERE source_url = ?",
                    [URL.format("PR131126")]).fetchone()  # fmt: skip
    assert f == ("PR_MCAP", "EOD_RULE")
    again = stage_mcap_day(umarket.vault, umarket.stage_root, data=raw("PR131126"), source_url=URL.format("PR131126"),
                           fetched_at=FETCHED_AT)  # fmt: skip
    assert promote(con, again).status == "PROMOTED"  # idempotent replay: identical rows are ignored
    assert con.execute("SELECT count(*) FROM raw_nse_mcap WHERE trade_date = '2026-11-13'").fetchone()[0] == 3246


def test_week_ends_need_the_rest_of_the_week_known(umarket):
    ends, unknown = universe.week_end_trading_days(umarket.con, date(2025, 10, 1), date(2026, 11, 15))
    # 2026-11-12 is followed by 2026-11-13 (mcap file); 13 Nov is a Friday of a year the holiday master covers.
    # 2026-09-30 is a Wednesday (Thursday trades); 2025-10-14 has no calendar coverage for the rest of its week.
    assert ends == [date(2026, 11, 13)] and unknown == [date(2025, 10, 14)]


def test_rule_u1p_adds_permitted_joiners_to_a_u1l_database(umarket, monkeypatch):
    """A database built with U1-L (Listed only, before the listing_category column was filled) gains the Permitted
    joiners on the next update-universe; nobody leaves, the old rows get their category from their evidence row."""
    con = umarket.con
    monkeypatch.setattr(universe, "ELIGIBLE_CATEGORIES", ("Listed",))
    monkeypatch.setattr(universe, "RULE_VERSION", "U1-2026.11.17-L")
    con.execute("BEGIN")
    old = universe.update_universe(con, date(2025, 10, 1), date(2026, 11, 15), now=datetime(2026, 11, 16))
    con.execute("UPDATE universe_membership SET listing_category = NULL")  # as written before the column existed
    con.execute("COMMIT")
    monkeypatch.undo()
    before = dict(con.execute("SELECT security_id, joined_date FROM universe_membership").fetchall())
    assert old["permitted_members"] == 0 and len(before) == old["members"]
    con.execute("BEGIN")
    new = universe.update_universe(con, date(2025, 10, 1), date(2026, 11, 15), now=datetime(2026, 11, 17))
    con.execute("COMMIT")
    after = dict(con.execute("SELECT security_id, joined_date FROM universe_membership").fetchall())
    assert all(after[s] == d for s, d in before.items())  # sticky: every U1-L member stays, same join date
    assert new["listing_category_filled"] == old["members"] - 1  # every MCAP_GE_500CR row; the seed has none
    assert new["joined"] == new["permitted_members"] > 90 and new["members"] == old["members"] + new["joined"]
    assert not con.execute("SELECT 1 FROM universe_membership WHERE listing_category IS NULL "
                           "AND reason = 'MCAP_GE_500CR'").fetchall()  # fmt: skip
    con.execute("BEGIN")
    again = universe.update_universe(con, date(2025, 10, 1), date(2026, 11, 15), now=datetime(2026, 11, 18))
    con.execute("COMMIT")
    assert (again["joined"], again["moved_earlier"], again["listing_category_filled"]) == (0, 0, 0)
    # leave the module database as the next test expects it (empty universe)
    con.execute("DELETE FROM universe_membership")
    con.execute("DELETE FROM quarantine_queue WHERE stage = 'UNIVERSE'")
    con.execute("DELETE FROM admin_log WHERE action = 'UPDATE_UNIVERSE'")


def test_rule_u1_seed_join_sticky_and_unresolved(umarket, monkeypatch):
    con = umarket.con
    con.execute("BEGIN")
    r = universe.update_universe(con, date(2025, 10, 1), date(2026, 11, 15), now=datetime(2026, 11, 17))
    con.execute("COMMIT")
    assert r["seeded"] == 1 and r["week_ends"] == 1 and r["week_ends_without_mcap_file"] == []
    seed = con.execute("SELECT symbol, joined_date, reason, market_cap_inr FROM universe_membership "
                       "WHERE reason = 'SEED_EXISTING'").fetchall()  # fmt: skip
    assert seed == [("ELIN", date(2025, 10, 14), "SEED_EXISTING", None)]  # ELIN is below Rs 500 Cr: seed only
    # every qualifying row of the week end joins or is quarantined, never guessed: 1,823 = 1,718 Listed + 105
    # Permitted rows >= Rs 500 Cr (rule U1-P, owner 2026-11-17: Permitted securities join too)
    assert r["joined"] + r["unresolved"] == 1823 and r["joined"] == r["members"] - 1
    assert (
        r["unresolved"]
        == con.execute(
            "SELECT count(*) FROM quarantine_queue WHERE stage = 'UNIVERSE' AND reason_code = 'UNRESOLVED_SYMBOL'"
        ).fetchone()[0]
    )
    assert r["unresolved"] <= 0.01 * 1823
    # ABBOTINDIA: Rs 56,183 Cr on a Permitted row joins, and its row says it is Permitted (filings on BSE, X166)
    abbott = rows("PR131126")[("ABBOTINDIA", "EQ")]
    assert (abbott.category, abbott.market_cap_inr) == ("Permitted", Decimal("561831544880.00"))
    assert con.execute("SELECT listing_category, reason, market_cap_inr, rule_version FROM universe_membership "
                       "WHERE symbol = 'ABBOTINDIA'").fetchone() == (
        "Permitted", "MCAP_GE_500CR", Decimal("561831544880.00"), universe.RULE_VERSION)  # fmt: skip
    cats = dict(con.execute("SELECT coalesce(listing_category, reason), count(*) FROM universe_membership "
                            "GROUP BY 1").fetchall())  # fmt: skip
    assert cats["Permitted"] == r["permitted_members"] and cats["SEED_EXISTING"] == 1
    assert cats["Listed"] + cats["Permitted"] == r["joined"]
    unresolved_permitted = 105 - cats["Permitted"]
    assert 0 <= unresolved_permitted <= r["unresolved"]
    # the category on the row is the evidence row's, as filed
    assert not con.execute(
        "SELECT 1 FROM universe_membership u JOIN raw_nse_mcap m ON m.filing_id = u.evidence_filing_id "
        "AND m.symbol = u.symbol AND m.series = u.series WHERE m.category <> u.listing_category"
    ).fetchall()
    bse = universe.bse_members(con, date(2026, 11, 13))
    assert len(bse) == cats["Permitted"] and "ABBOTINDIA" in {b["symbol"] for b in bse}
    assert {b["latest_category"] for b in bse} == {"Permitted"} and all(b["isin"] for b in bse)
    assert universe.bse_members(con, date(2026, 11, 12)) == []  # joined on 13 Nov
    # NSE discovery for new members skips the Permitted ones (no NSE filings, X166)
    new = universe.members(con, date(2026, 11, 13), new_only=True)
    assert "ABBOTINDIA" not in new and "RELIANCE" in new
    assert "ABBOTINDIA" in universe.members(con, date(2026, 11, 13))
    rel = con.execute("SELECT joined_date, reason, market_cap_inr, series FROM universe_membership "
                      "WHERE symbol = 'RELIANCE'").fetchone()  # fmt: skip
    assert rel == (date(2026, 11, 13), "MCAP_GE_500CR", Decimal("18129542125863.40"), "EQ")
    assert not con.execute(
        "SELECT 1 FROM universe_membership WHERE series NOT IN ('EQ', 'BE', 'BZ') OR "
        "(reason = 'MCAP_GE_500CR' AND market_cap_inr < 5000000000)"
    ).fetchall()
    members = universe.members(con, date(2026, 11, 13))
    assert len(members) == r["members"] and "RELIANCE" in members
    assert universe.members(con, date(2026, 11, 12)) == ["ELIN"]  # point in time: joiners count from their week
    assert "ELIN" not in universe.members(con, date(2026, 11, 13), new_only=True)

    # sticky: a later run under which nobody qualifies removes nobody, and adds no finding
    monkeypatch.setattr(universe, "THRESHOLD_INR", Decimal("1000000000000000"))  # Rs 1 crore crore: above every row
    con.execute("BEGIN")
    r2 = universe.update_universe(con, date(2025, 10, 1), date(2026, 11, 15), now=datetime(2026, 11, 18))
    con.execute("COMMIT")
    assert (r2["seeded"], r2["joined"], r2["members"], r2["unresolved"]) == (0, 0, r["members"], 0)
    monkeypatch.undo()
    # a backfill that finds an earlier qualifying week moves the join date earlier (never later)
    con.execute("UPDATE universe_membership SET joined_date = '2026-12-04' WHERE symbol = 'RELIANCE'")
    con.execute("BEGIN")
    r3 = universe.update_universe(con, date(2025, 10, 1), date(2026, 11, 15), now=datetime(2026, 11, 19))
    con.execute("COMMIT")
    assert (r3["joined"], r3["moved_earlier"], r3["members"]) == (0, 1, r["members"])
    assert con.execute("SELECT joined_date FROM universe_membership WHERE symbol = 'RELIANCE'").fetchone()[0] == date(
        2026, 11, 13
    )
    assert con.execute("SELECT count(*) FROM admin_log WHERE action = 'UPDATE_UNIVERSE'").fetchone()[0] == 3


def test_issue_size_cross_check_on_fixtures(umarket):
    r = universe.issue_size_check(umarket.con, date(2026, 9, 30), include_agreeing=True)
    assert (r["mcap_file_date"], r["pairs"], r["exact"], r["within_tolerance"]) == (date(2026, 9, 30), 1, 1, 1)
    assert r["rows"][0]["symbol"] == "ELIN" and r["rows"][0]["issue_size"] == r["rows"][0]["reg31_total"]
    assert universe.issue_size_check(umarket.con, date(2024, 1, 1))["pairs"] == 0


def test_fetch_job_vaults_once_and_restages_from_vault(tmp_path):
    from test_fetch_and_e2e import FakeClock, FakeTransport

    from financials.fetch.http import PoliteFetcher, Response
    from financials.fetch.jobs import Jobs, pr_zip_url
    from financials.vault import Vault

    d = date(2026, 11, 13)
    t = FakeTransport({pr_zip_url(d): Response(200, raw("PR131126"))})
    clock = FakeClock()
    jobs = Jobs(PoliteFetcher(t, sleep=clock.sleep, clock=clock.now), Vault(tmp_path / "vault"), tmp_path / "staging")
    assert pr_zip_url(d) == URL.format("PR131126")
    first = jobs.mcap_day(d)
    assert [p.parent.name for p in first] == ["mcap_day"]
    assert jobs.mcap_day(d) == [] and len(t.calls) == 1  # vaulted and staged: no second request
    import shutil

    shutil.rmtree(first[0])
    assert len(jobs.mcap_day(d)) == 1 and len(t.calls) == 1  # staged again from the vault, not downloaded
    assert jobs.mcap_day(date(2026, 11, 14)) == []  # 404 (no file): nothing staged
