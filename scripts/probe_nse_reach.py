"""Can this machine reach NSE? One request per sample URL (plus the jobs' one warm-up page for www) through the
project's polite fetcher (>= 1.5 s spacing, max 2 attempts). Prints status, size and sha256 only: nothing is
saved, so no data leaves the run in logs.

    python scripts/probe_nse_reach.py
    python scripts/probe_nse_reach.py --domains   # does www.nseindia.com now redirect to www.nseindia.in?

`--domains` (2026-11-18, a public note said NSE moved to nseindia.in with a redirect): for the home page and the
holiday API on both hosts, one request each WITHOUT following redirects, >= 2 s apart; prints status, Location and
whether the answer is JSON. Nothing is saved.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import date

from financials.fetch.http import FetchError, PoliteFetcher
from financials.fetch.jobs import WARMUP, bhavcopy_url, holidays_url, quote_url, results_listing_url

SAMPLES = [  # the production URL builders, so the probe asks exactly what the jobs ask
    ("archive: bhavcopy 2026-11-13", bhavcopy_url(date(2026, 11, 13))),
    ("archive: announcements RSS", "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"),
    ("www api: holiday master", holidays_url()),
    ("www api: results listing RELIANCE", results_listing_url("RELIANCE")),
    ("www api: quote RELIANCE", quote_url("RELIANCE")),
]


DOMAIN_PATHS = ("/", "/api/holiday-master?type=trading")
DOMAIN_HOSTS = ("https://www.nseindia.com", "https://www.nseindia.in")


def domains(sleep=None) -> int:
    import time
    import urllib.error
    import urllib.request

    from financials.fetch.http import DEFAULT_USER_AGENT

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    pause = sleep or time.sleep
    for host in DOMAIN_HOSTS:
        for path in DOMAIN_PATHS:
            url = host + path
            req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"})
            try:
                with opener.open(req, timeout=30) as r:
                    status, headers, body = r.status, r.headers, r.read(4096)
            except urllib.error.HTTPError as e:
                status, headers, body = e.code, e.headers, (e.read(4096) if e.fp else b"")
            except OSError as e:
                print(f"ERR   {url}: {e}")
                pause(2.0)
                continue
            loc = headers.get("Location", "") if headers else ""
            kind = "json" if body[:1] in (b"{", b"[") else "html/other"
            print(f"{status}   {url} -> Location {loc or '-'}; {len(body)} bytes {kind}")
            pause(2.0)
    return 0


def main() -> int:
    if "--domains" in sys.argv[1:]:
        return domains()
    f = PoliteFetcher(warmup=WARMUP, min_interval=1.5, max_attempts=2, base_backoff=3.0, timeout=30.0)
    ok = 0
    for name, url in SAMPLES:
        try:
            body = f.get(url, accept="application/json" if "/api/" in url else "*/*")
            print(f"OK    {name}: {len(body)} bytes sha256 {hashlib.sha256(body).hexdigest()[:16]}")
            ok += 1
        except FetchError as exc:
            print(f"FAIL  {name}: status {exc.status} {exc}")
    print(f"{ok}/{len(SAMPLES)} reachable")
    return 0 if ok == len(SAMPLES) else 1


if __name__ == "__main__":
    sys.exit(main())
