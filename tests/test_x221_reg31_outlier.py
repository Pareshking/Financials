"""Rule SHARES_REG31_OUTLIER [X221] (owner decision S, 2026-11-18): "When the results filing and NSE agree and Reg. 31
doesn't, use NSE's count. A named rule; keep a finding open for HMT, where all three differ."

- MBL Infrastructure (MBLINFRA), 30-Jun-2026: Reg. 31 (1696707, visible 20-Jul-2026) totals 155,879,256 shares; the
  standalone Q1 FY27 results (1700387, 23-Jul-2026) state paid-up 152.53 Cr of Rs 10 = 152,530,000; NSE's Issue Size
  is 152,529,256 in the PR-zip file of 25-Sep-2026 and 155,879,256 in that of 30-Sep-2026 (the allotted shares were
  listed in between). From 23-Jul to 29-Sep the rule takes the Issue Size; from 30-Sep all three agree within 0.5%
  except paid-up, so Reg. 31 is used again.
- HMT, 30-Sep-2026: Reg. 31 (1739920) 1,204,091,640; results (1755096) paid-up 355.60 Cr / Rs 10 = 355,600,000;
  Issue Size 470,670,740 (PR-zip 30-Sep-2026 and 13-Nov-2026). No two agree: Reg. 31 stays and the share
  cross-check's CROSS_CHECK_FAILED finding stays open.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from _fixture_helpers import FIXTURES
from financials import features
from financials.features import ISSUE_SIZE_MAX_AGE_DAYS, issue_sizes, market_cap_shares, reg31_outlier
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.pr_mcap import parse_pr_mcap
from financials.parsers.shareholding import parse_shareholding
from financials.promoter import SHARE_CROSS_CHECK_TOLERANCE, close_resolved_share_findings, promote
from financials.staging import stage_mcap_day, stage_results_xbrl, stage_shareholding
from financials.timeutil import ist_to_utc

DIR = FIXTURES / "shares_outlier"
PR = FIXTURES / "pr_zip"
XBRL = "https://nsearchives.nseindia.com/corporate/xbrl/"
PR_URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/{}.zip"
KW = dict(fetched_at=datetime(2026, 11, 18, 6), broadcast_ts_source="API_FIELD")
MBL_SHP, MBL_RES = "SHP_1696707_20072026025841_WEB.xml", "INTEGRATED_FILING_INDAS_1700387_23072026082824_WEB.xml"
HMT_SHP, HMT_RES = "SHP_1739920_16102026040314_WEB.xml", "INTEGRATED_FILING_INDAS_1755096_06112026073646_WEB.xml"
JUN, SEP = date(2026, 6, 30), date(2026, 9, 30)


def _issue(name: str, symbol: str) -> int:
    return {r.symbol: r for r in parse_pr_mcap((PR / f"{name}.zip").read_bytes())}[symbol].issue_size


def _paid_up(name: str) -> set[tuple[date, Decimal]]:
    r = parse_integrated_results((DIR / name).read_bytes(), name)
    assert r.ok
    return {(f.period_end, f.value) for f in r.facts if f.canonical_tag == "shares_from_paid_up"}


# ── the fixtures' three counts ──


def test_x221_fixture_counts():
    shp = parse_shareholding((DIR / MBL_SHP).read_bytes())
    assert (shp.meta["as_of_date"], shp.categories["TOTAL"]["shares"]) == (JUN, 155879256)
    assert _paid_up(MBL_RES) == {(JUN, Decimal(152530000))}
    assert (_issue("PR250926", "MBLINFRA"), _issue("PR300926", "MBLINFRA")) == (152529256, 155879256)
    shp = parse_shareholding((DIR / HMT_SHP).read_bytes())
    assert (shp.meta["as_of_date"], shp.categories["TOTAL"]["shares"]) == (SEP, 1204091640)
    assert _paid_up(HMT_RES) == {(SEP, Decimal(355600000))}
    assert _issue("PR300926", "HMT") == _issue("PR131126", "HMT") == 470670740


# ── the decision (pure) ──

R_MBL, P_MBL = (Decimal(155879256), JUN), (Decimal(152530000), JUN)


def test_x221_reg31_outlier_takes_the_issue_size():
    lagging, listed = (Decimal(152529256), date(2026, 9, 25)), (Decimal(155879256), date(2026, 9, 30))
    assert reg31_outlier(R_MBL, P_MBL, lagging, []) == "REG31_OUTLIER"
    assert market_cap_shares(R_MBL, P_MBL, [], date(2026, 9, 28), lagging) == (
        Decimal(152529256), date(2026, 9, 25), "ISSUE_SIZE")  # fmt: skip
    assert reg31_outlier(R_MBL, P_MBL, listed, []) is None  # NSE agrees with Reg. 31 again
    assert market_cap_shares(R_MBL, P_MBL, [], SEP, listed) == (R_MBL[0], JUN, "REG31")
    assert market_cap_shares(R_MBL, P_MBL, [], date(2026, 9, 28)) == (R_MBL[0], JUN, "REG31")  # no file: as before
    # a later split divides the Issue Size like any count: ex-date after the file, on or before as-of
    split = (date(2026, 9, 27), Decimal("0.2"), Decimal("0.2"))
    assert market_cap_shares(R_MBL, P_MBL, [split], date(2026, 9, 28), lagging)[0] == 152529256 * 5


def test_x221_hmt_all_three_differ_keeps_reg31():
    r, p, i = (Decimal(1204091640), SEP), (Decimal(355600000), SEP), (Decimal(470670740), date(2026, 11, 13))
    assert reg31_outlier(r, p, i, []) == "ALL_DIFFER"
    assert market_cap_shares(r, p, [], date(2026, 11, 13), i) == (r[0], SEP, "REG31")


def test_x221_only_like_with_like():
    lagging = (Decimal(152529256), date(2026, 9, 25))
    # results of another period end: an allotment between the two dates explains the difference
    assert reg31_outlier(R_MBL, (P_MBL[0], date(2026, 3, 31)), lagging, []) is None
    # a share-count action between the pattern and the file (SEPC: rights ex 23-May-2025 after the 31-Mar pattern)
    assert reg31_outlier(R_MBL, P_MBL, lagging, [(date(2026, 8, 1), Decimal("0.9"), Decimal("0.9"))]) is None
    assert reg31_outlier(R_MBL, P_MBL, lagging, [(JUN, Decimal("0.9"), Decimal("0.9"))]) == "REG31_OUTLIER"
    assert reg31_outlier(R_MBL, P_MBL, lagging, [], partly_paid=True) is None
    assert reg31_outlier(R_MBL, P_MBL, lagging, [], entity_listings=2) is None
    assert reg31_outlier(None, P_MBL, lagging, []) is None and reg31_outlier(R_MBL, None, lagging, []) is None
    # X103: Reg. 31 less the employee-trust shares equals paid-up / face value (UGROCAP 30-Jun-2025): explained
    r, p = (Decimal(116684957), JUN), (Decimal(114212200), JUN)
    assert reg31_outlier(r, p, (Decimal(114212137), JUN), []) == "REG31_OUTLIER"
    assert reg31_outlier(r, p, (Decimal(114212137), JUN), [], trust_shares=Decimal(2472820)) is None


def test_x221_tolerance_is_the_share_cross_check_tolerance():
    assert features.SHARES_REG31_OUTLIER_TOLERANCE == SHARE_CROSS_CHECK_TOLERANCE == Decimal("0.005")
    p = (Decimal(100000000), JUN)
    assert reg31_outlier((Decimal(100500000), JUN), p, (Decimal(100000000), JUN), []) is None  # 0.5%: agrees
    assert reg31_outlier((Decimal(100500001), JUN), p, (Decimal(100000000), JUN), []) == "REG31_OUTLIER"  # just over
    assert reg31_outlier((Decimal(101100000), JUN), p, (Decimal(100500000), JUN), []) == "REG31_OUTLIER"  # P, I 0.5%


# ── the pipeline: promoted fixtures, point-in-time reads ──


@pytest.fixture(scope="module")
def omarket(tmp_path_factory):
    from conftest import Market

    m = Market(tmp_path_factory.mktemp("x221"))
    for day in ("20251014", "20261112"):  # identifiers valid from 14-Oct-2025 (the PR-zip files are mapped by date)
        assert promote(m.con, m.stage_day(day)).status == "PROMOTED"
    filings = ((MBL_SHP, datetime(2026, 7, 20, 9, 28, 46)), (MBL_RES, datetime(2026, 7, 23, 14, 58, 24)),
               (HMT_SHP, datetime(2026, 10, 16, 10, 33, 17)), (HMT_RES, datetime(2026, 11, 6, 14, 6, 47)))  # fmt: skip
    for name, ts in filings:
        stage = stage_shareholding if name.startswith("SHP_") else stage_results_xbrl
        r = promote(m.con, stage(m.vault, m.stage_root, data=(DIR / name).read_bytes(), source_url=XBRL + name,
                                 broadcast_ts=ts, **KW))  # fmt: skip
        assert r.status == "PROMOTED", r
    m.con.execute("DELETE FROM materialize_dirty")
    for f in ("PR250926", "PR300926", "PR131126"):
        st = stage_mcap_day(m.vault, m.stage_root, data=(PR / f"{f}.zip").read_bytes(), source_url=PR_URL.format(f),
                            fetched_at=datetime(2026, 11, 18, 6))  # fmt: skip
        assert promote(m.con, st).status == "PROMOTED"
    yield m
    m.con.close()


def _entity(m, symbol):
    return m.con.execute(
        "SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s USING (security_id) "
        "WHERE h.symbol = ?",
        [symbol],
    ).fetchone()[0]


def _shares(m, symbol, as_of):
    """market_cap_shares exactly as compute_rows calls it (same preload and Issue Size read)."""
    sec, ent = m.security_id(symbol), _entity(m, symbol)
    shp, paid_up, _ = features._preload(m.con, ist_to_utc(as_of + timedelta(days=1), time(0, 0)))
    s = shp.get(ent, {})
    reg31 = (Decimal(s["TOTAL"][1]), s["_as_of"]) if "TOTAL" in s else None
    iss = issue_sizes(m.con, as_of).get(sec)
    return market_cap_shares(reg31, paid_up.get(ent), [], as_of, None if iss is None else iss[:2],
                             partly_paid=s.get("_partly_paid", False),
                             entity_listings=1 if iss is None else iss[2])  # fmt: skip


def test_x221_mblinfra_point_in_time(omarket):
    assert _shares(omarket, "MBLINFRA", date(2026, 7, 22)) == (Decimal(155879256), JUN, "REG31")  # no file yet
    assert _shares(omarket, "MBLINFRA", date(2026, 9, 24)) == (Decimal(155879256), JUN, "REG31")  # file of 25 Sep
    assert _shares(omarket, "MBLINFRA", date(2026, 9, 28)) == (Decimal(152529256), date(2026, 9, 25), "ISSUE_SIZE")
    assert _shares(omarket, "MBLINFRA", SEP) == (Decimal(155879256), JUN, "REG31")  # listed: all agree
    # the 30-Sep file ages out after ISSUE_SIZE_MAX_AGE_DAYS; the 13-Nov file is not visible before 13 Nov
    sec = omarket.security_id("MBLINFRA")
    assert sec in issue_sizes(omarket.con, SEP + timedelta(days=ISSUE_SIZE_MAX_AGE_DAYS - 1))
    assert sec not in issue_sizes(omarket.con, SEP + timedelta(days=ISSUE_SIZE_MAX_AGE_DAYS))
    assert issue_sizes(omarket.con, date(2026, 11, 13))[sec] == (Decimal(155879256), date(2026, 11, 13), 1)


def test_x221_hmt_keeps_reg31_and_its_finding(omarket):
    assert _shares(omarket, "HMT", date(2026, 11, 13)) == (Decimal(1204091640), SEP, "REG31")
    ent = _entity(omarket, "HMT")
    open_ = "SELECT count(*) FROM quarantine_queue WHERE reason_code = 'CROSS_CHECK_FAILED' AND resolved_at IS NULL "
    assert omarket.con.execute(open_ + "AND entity_id = ?", [ent]).fetchone()[0] == 1
    close_resolved_share_findings(omarket.con)
    assert omarket.con.execute(open_ + "AND entity_id = ?", [ent]).fetchone()[0] == 1


def test_x221_materialised_row_and_dirty_marker(omarket):
    # PR-zip promotion marks every row from the file's trade date (the rule reads Issue Size)
    marks = omarket.con.execute("SELECT reason, min(from_date), count(*) FROM materialize_dirty GROUP BY 1").fetchall()
    assert marks == [("MCAP_DAY", date(2026, 9, 25), 3)]
    rows = {r["symbol"]: r for r in features.compute_rows(omarket.con, date(2026, 11, 12))}
    assert (rows["HMT"]["shares"], rows["HMT"]["shares_source"]) == (1204091640, "REG31")
    assert (rows["MBLINFRA"]["shares"], rows["MBLINFRA"]["shares_source"]) == (155879256, "REG31")
