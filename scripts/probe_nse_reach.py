"""Can this machine reach NSE? One request per sample URL (plus the jobs' one warm-up page for www) through the
project's polite fetcher (>= 1.5 s spacing, max 2 attempts). Prints status, size and sha256 only: nothing is
saved, so no data leaves the run in logs.

    python scripts/probe_nse_reach.py
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


def main() -> int:
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
