"""X346: `discover-filings --since D` fetches only filings broadcast on or after D (runner sweeps with an empty vault).

A listing row whose broadcast / visibility time is before D is not downloaded; a row with no time is (never skipped on
missing evidence). Paging stops early only when a whole listing page is before D: the listing is not reliably
newest-first (COALINDIA 2026-11-15 fixture is not sorted), so one older row on a page proves nothing about the next.
"""

from datetime import date

from _fixture_helpers import FIXTURES
from financials.fetch.http import PoliteFetcher, Response
from financials.fetch.jobs import Jobs, results_listing_url
from financials.parsers.discovery import parse_integrated_filing_listing
from financials.vault import Vault

A7 = FIXTURES / "discovery" / "nse_integrated-filing-results_equities_TCS_20261113.json"
A7_PAGE2 = FIXTURES / "discovery" / "nse_integrated-filing-results_equities_TCS_page2_20261114.json"
COAL = FIXTURES / "discovery" / "nse_integrated-filing-results_equities_COALINDIA_20261115.json"


class Routes:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, headers, timeout):
        self.calls.append(url)
        return self.routes.get(url, Response(404, b""))


def _jobs(tmp_path, since):
    t = Routes({results_listing_url("TCS"): Response(200, A7.read_bytes()),
                results_listing_url("TCS", 2): Response(200, A7_PAGE2.read_bytes())})  # fmt: skip
    jobs = Jobs(PoliteFetcher(t, sleep=lambda s: None), Vault(tmp_path / "vault"), tmp_path / "staging")
    jobs.since = since
    return jobs, t


def test_listing_order_is_not_reliable_evidence():
    rows = parse_integrated_filing_listing(COAL.read_bytes(), results_only=False)
    ts = [r.visible_ts_ist for r in rows]
    assert ts != sorted(ts, reverse=True)  # why paging stops only on a page wholly before `since`


def test_since_downloads_only_newer_rows(tmp_path):
    jobs, t = _jobs(tmp_path, date(2026, 10, 1))
    jobs.discover(["TCS"], ["results"], events=False)
    files = [u for u in t.calls if u.endswith(".xml")]
    rows = parse_integrated_filing_listing(A7.read_bytes()) + parse_integrated_filing_listing(A7_PAGE2.read_bytes())
    newer = {r.xbrl_url for r in rows if r.visible_ts_ist.date() >= date(2026, 10, 1)}
    assert newer and set(files) == newer  # Q2 FY27 standalone + consolidated (8 Oct 2026) only
    assert len(files) < len(rows)


def test_page_wholly_before_since_stops_paging(tmp_path):
    jobs, t = _jobs(tmp_path, date(2027, 1, 1))
    jobs.discover(["TCS"], ["results"], events=False)
    assert results_listing_url("TCS", 2) not in t.calls  # page 1 all older than since: page 2 not asked
    assert [u for u in t.calls if u.endswith(".xml")] == []


def test_without_since_everything_in_scope_is_asked(tmp_path):
    jobs, t = _jobs(tmp_path, None)
    jobs.discover(["TCS"], ["results"], events=False)
    assert results_listing_url("TCS", 2) in t.calls
    assert len([u for u in t.calls if u.endswith(".xml")]) == 14  # every in-scope Financials row of both pages
