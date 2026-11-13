"""Offline fetcher tests and the full CLI chain: fetch → vault → staging → promote → features → screen."""

import io
import json
from datetime import date

import pytest

from _fixture_helpers import BHAV_DIR, CORP, FIXTURES, XBRL_DIR
from financials.cli import main
from financials.fetch.http import FetchError, PoliteFetcher, Response, Transport
from financials.fetch.jobs import (
    bhavcopy_url,
    corp_actions_url,
    delivery_url,
    holidays_url,
    index_list_url,
    shp_master_url,
)


class FakeTransport(Transport):
    def __init__(self, routes: dict[str, list[Response] | Response]) -> None:
        self.routes = {k: (v if isinstance(v, list) else [v]) for k, v in routes.items()}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        seq = self.routes.get(url)
        if not seq:
            return Response(404, b"not found")
        return seq.pop(0) if len(seq) > 1 else seq[0]


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def fetcher(transport, clock, **kw):
    return PoliteFetcher(transport, sleep=clock.sleep, clock=clock.now, **kw)


def test_spacing_per_host_and_user_agent():
    clock = FakeClock()
    t = FakeTransport({"https://a.example/1": Response(200, b"1"), "https://a.example/2": Response(200, b"2"),
                       "https://b.example/1": Response(200, b"3")})  # fmt: skip
    f = fetcher(t, clock, min_interval=1.0)
    assert f.get("https://a.example/1") == b"1"
    assert f.get("https://b.example/1") == b"3"  # other host: no wait
    assert clock.sleeps == []
    clock.t += 0.25
    assert f.get("https://a.example/2") == b"2"
    assert clock.sleeps == [pytest.approx(0.75)]
    assert all("financials-research" in h["User-Agent"] for _, h in t.calls)


def test_retries_with_backoff_then_success():
    clock = FakeClock()
    t = FakeTransport({"https://a.example/x": [Response(429, b""), Response(503, b""), Response(200, b"ok")]})
    f = fetcher(t, clock, base_backoff=2.0)
    assert f.get("https://a.example/x") == b"ok"
    backoffs = [s for s in clock.sleeps if s > 1.0]
    assert len(backoffs) == 2 and 1.0 <= backoffs[0] <= 3.0 and 2.0 <= backoffs[1] <= 6.0


def test_gives_up_and_does_not_retry_client_errors():
    clock = FakeClock()
    t = FakeTransport({"https://a.example/x": Response(403, b"")})
    with pytest.raises(FetchError) as e:
        fetcher(t, clock, max_attempts=3).get("https://a.example/x")
    assert e.value.status == 403 and len(t.calls) == 3
    t2 = FakeTransport({"https://a.example/y": Response(400, b"")})
    with pytest.raises(FetchError):
        fetcher(t2, FakeClock()).get("https://a.example/y")
    assert len(t2.calls) == 1
    assert fetcher(FakeTransport({}), FakeClock()).get("https://a.example/z", allow_404=True) is None


def test_warmup_visited_once_per_host():
    t = FakeTransport({"https://www.nseindia.com/": Response(200, b"<html>"),
                       "https://www.nseindia.com/api/a": Response(200, b"[]"),
                       "https://www.nseindia.com/api/b": Response(200, b"[]")})  # fmt: skip
    f = fetcher(t, FakeClock(), warmup={"www.nseindia.com": "https://www.nseindia.com/"})
    f.get("https://www.nseindia.com/api/a")
    f.get("https://www.nseindia.com/api/b")
    assert [u for u, _ in t.calls] == [
        "https://www.nseindia.com/",
        "https://www.nseindia.com/api/a",
        "https://www.nseindia.com/api/b",
    ]


# ── end-to-end through the CLI ────────────────────────────────────────────

DAYS = [date(2025, 9, 19), date(2025, 9, 22), date(2025, 9, 23), date(2025, 10, 13), date(2025, 10, 14),
        date(2026, 11, 12)]  # fmt: skip
SHP_MASTER = FIXTURES / "shareholding" / "nse_corporate-share-holdings-master_ELIN_20261113.json"
RESULTS_URL = "https://nsearchives.nseindia.com/corporate/xbrl/" + CORP.name


def fixture_routes() -> dict[str, Response]:
    r: dict[str, Response] = {}
    for d in DAYS:
        r[bhavcopy_url(d)] = Response(200, (BHAV_DIR / f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip").read_bytes())
        p = BHAV_DIR / f"sec_bhavdata_full_{d:%d%m%Y}.csv"
        if p.exists():
            r[delivery_url(d)] = Response(200, p.read_bytes())
    r[corp_actions_url(date(2025, 9, 15), date(2025, 10, 17))] = Response(
        200, (FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json").read_bytes()
    )
    r[holidays_url()] = Response(200, (FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json").read_bytes())
    r[index_list_url()] = Response(200, (FIXTURES / "indices" / "ind_nifty500list_20261113.csv").read_bytes())
    r[shp_master_url("ELIN")] = Response(200, SHP_MASTER.read_bytes())
    master = json.loads(SHP_MASTER.read_bytes())[0]
    r[master["xbrl"]] = Response(200, (XBRL_DIR / "SHP_1739151_15102026054406_WEB.xml").read_bytes())
    r[RESULTS_URL] = Response(200, CORP.read_bytes())
    return r


def cli(data_dir, *args, transport=None):
    out = io.StringIO()
    code = main(["--data-dir", str(data_dir), *args], transport=transport, out=out)
    return code, out.getvalue()


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    data = tmp_path_factory.mktemp("e2e_data")
    t = FakeTransport(fixture_routes())
    fast = {"transport": t}
    import financials.cli as cli_mod

    # Keep the polite spacing logic, but without real sleeping in tests.
    orig = cli_mod.PoliteFetcher
    cli_mod.PoliteFetcher = lambda transport: orig(transport, sleep=lambda s: None)
    try:
        assert cli(data, "fetch-days", "2025-09-19", "2025-09-23", **fast)[0] == 0  # 20/21 Sep: weekend 404s
        assert cli(data, "fetch-days", "2025-10-13", "2025-10-14", **fast)[0] == 0
        assert cli(data, "fetch-days", "2026-11-12", **fast)[0] == 0
        assert cli(data, "fetch-corp-actions", "2025-09-15", "2025-10-17", **fast)[0] == 0
        assert cli(data, "fetch-holidays", **fast)[0] == 0
        assert cli(data, "fetch-index", "--as-of", "2026-11-12", **fast)[0] == 0
        assert cli(data, "fetch-shareholding", "ELIN", **fast)[0] == 0
        assert cli(data, "fetch-results", RESULTS_URL, **fast)[0] == 0
    finally:
        cli_mod.PoliteFetcher = orig
    code, out = cli(data, "promote")
    assert code == 0, out
    return data, t, out


def test_e2e_fetchers_never_touched_unlisted_urls(e2e):
    _, t, _ = e2e
    routes = fixture_routes()
    misses = {u for u, _ in t.calls if u not in routes}
    weekend = {bhavcopy_url(date(2025, 9, 20)), bhavcopy_url(date(2025, 9, 21))}
    no_delivery_fixture = {delivery_url(d) for d in DAYS if delivery_url(d) not in routes}
    assert misses == weekend | no_delivery_fixture  # every other request was a known fixture URL


def test_e2e_promotion_order_and_idempotency(e2e):
    data, _, out = e2e
    lines = out.strip().splitlines()
    jobs = [ln.split()[1] for ln in lines]
    assert jobs[0] == "holidays" and jobs[1:7] == ["market_day"] * 6
    assert jobs[7:] == ["index_snapshot", "corp_actions", "results_xbrl", "shareholding", "raw_only"]
    code, again = cli(data, "promote")
    assert code == 0 and again == ""  # nothing pending


def test_e2e_features_and_screens(e2e):
    data, _, _ = e2e
    assert cli(data, "materialize", "2025-10-14")[0] == 0
    code, out = cli(data, "materialize", "2026-11-12")
    assert code == 0 and "PROMOTED" in out
    code, out = cli(data, "screen", "Market Cap > 100 AND Promoter holding > 30")
    assert code == 0
    rows = json.loads(out)
    assert [r["symbol"] for r in rows] == ["ELIN"]
    code, out = cli(data, "screen", "Price to book value > 0", "--as-of", "2025-10-14")
    assert json.loads(out) == []  # ELIN's Q2 FY27 balance sheet was not public in Oct 2025


def test_e2e_vault_holds_every_raw_file(e2e):
    data, _, _ = e2e
    blobs = list((data / "vault").rglob("*.*"))
    assert len(blobs) == len(fixture_routes())  # each distinct response stored once
