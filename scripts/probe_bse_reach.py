"""Can this machine reach BSE, and how? (owner 2026-11-17: Permitted securities join rule U1 and their filings come
from BSE; "we already have BSE working using headless chrome browser"). Two transports, so one run says which works:

  curl      plain HTTP through the project's polite fetcher (>= 1.5 s spacing per host, max 2 attempts)
  browser   headless Chromium (Playwright): open https://www.bseindia.com/ for the session, then visit two of
            BSE's own pages and record every api.bseindia.com call the page makes (URL, status, size), then ask the
            sample API URLs and download one XBRL file from inside the same browser context (>= 1.5 s apart)

Every URL below is UNVERIFIED (docs/references.md A16-A18) until a run of this probe returns it. Nothing is written
to any database. With --out DIR each 200 body is saved under DIR (the workflow uploads it as a private artifact so
real files can become fixtures); the log prints status, size and sha256 only.

    python scripts/probe_bse_reach.py --mode curl --out bse_probe/curl
    python scripts/probe_bse_reach.py --mode browser --out bse_probe/browser
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

HOME = "https://www.bseindia.com/"
API = "https://api.bseindia.com/BseIndiaAPI/api"
# Scrip codes: TCS 532540 is VERIFIED from its own filing (X111, ScripCode); ABBOTINDIA (NSE Category `Permitted`,
# Rs 56,183 Cr on 2026-11-13) 500488 is UNVERIFIED: the scrip master sample below must confirm it by ISIN.
SCRIPS = {"TCS": "532540", "ABBOTINDIA": "500488"}

# UNVERIFIED candidates (seen used against bseindia.com; not yet proven). The browser mode also records the API
# calls BSE's own pages make, which is how the real endpoints are learnt if these are wrong.
SAMPLES = [
    ("scrip master (equity, active)",
     f"{API}/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"),
    ("scrip header ABBOTINDIA", f"{API}/getScripHeaderData/w?Debtflag=&scripcode=500488&seriesid="),
    ("announcements ABBOTINDIA (results, Oct-Nov 2026)",
     f"{API}/AnnSubCategoryGetData/w?pageno=1&strCat=Result&strPrevDate=20261001&strScrip=500488&strSearch=P"
     "&strToDate=20261117&strType=C&subcategory=-1"),
    ("bhavcopy 2026-11-13 (UDiFF name)",
     "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV"),
]  # fmt: skip
PAGES = [  # BSE's own pages for the two scrips; their XHRs show the listing endpoints and the XBRL links
    ("stock page ABBOTINDIA results", "https://www.bseindia.com/stock-share-price/abbott-india-ltd/abbotindia/500488/financials-results/"),
    ("stock page TCS announcements", "https://www.bseindia.com/stock-share-price/tata-consultancy-services-ltd/tcs/532540/corp-announcements/"),
]  # fmt: skip
XBRL_LINK = re.compile(r"https?://[^\s\"'<>]*?(?:xbrl|XBRL)[^\s\"'<>]*?\.(?:xml|XML)")
MIN_INTERVAL = 1.5


def _name(url: str) -> str:
    s = urlsplit(url)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (s.netloc + s.path + ("_" + s.query if s.query else "")))[:180]


def _record(log: list, out: Path | None, label: str, url: str, status: int | None, body: bytes | None, ctype=""):
    sha = hashlib.sha256(body).hexdigest() if body else None
    log.append({"label": label, "url": url, "status": status, "bytes": len(body or b""), "sha256": sha,
                "content_type": ctype})  # fmt: skip
    print(f"{'OK  ' if status == 200 else 'FAIL'}  {label}: status {status} {len(body or b'')} bytes "
          f"sha256 {(sha or '')[:16]}  {url}")  # fmt: skip
    if out and status == 200 and body:
        (out / _name(url)).write_bytes(body)


def run_curl(out: Path | None) -> list:
    from financials.fetch.http import FetchError, PoliteFetcher

    f = PoliteFetcher(min_interval=MIN_INTERVAL, max_attempts=2, base_backoff=3.0, timeout=30.0)
    log: list = []
    for label, url in [("home page", HOME), *SAMPLES]:
        try:
            _record(log, out, label, url, 200, f.get(url, accept="application/json" if "/api/" in url else "*/*"))
        except FetchError as exc:
            _record(log, out, label, url, exc.status, None)
    return log


_FETCH_JS = """async (url) => {
  const r = await fetch(url, {credentials: 'include'});
  const b = new Uint8Array(await r.arrayBuffer());
  let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768));
  return {status: r.status, b64: btoa(s), ctype: r.headers.get('content-type') || ''};
}"""


def _page_fetch(page, url: str) -> tuple[int, bytes, str]:
    import base64

    r = page.evaluate(_FETCH_JS, url)
    return r["status"], base64.b64decode(r["b64"]), r["ctype"]


def run_browser(out: Path | None) -> list:
    from playwright.sync_api import sync_playwright

    log: list = []
    seen_api: list = []
    xbrl_links: set[str] = set()
    with sync_playwright() as p:
        try:  # the runner's preinstalled Google Chrome, else Playwright's Chromium
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-IN")
        page = ctx.new_page()

        def on_response(r):
            if "api.bseindia.com" in r.url:
                try:
                    body = r.body()
                except Exception:
                    body = b""
                seen_api.append({"url": r.url, "status": r.status, "bytes": len(body),
                                 "content_type": r.headers.get("content-type", "")})  # fmt: skip
                xbrl_links.update(XBRL_LINK.findall(body.decode("utf-8", "replace")))
                if out and r.status == 200 and body and len(body) < 5_000_000:
                    (out / ("xhr_" + _name(r.url))).write_bytes(body)

        page.on("response", on_response)
        for label, url in [("home page", HOME), *PAGES]:
            try:
                r = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(8_000)  # the Angular pages load their data by XHR after the shell
                html = page.content().encode()
                xbrl_links.update(XBRL_LINK.findall(html.decode("utf-8", "replace")))
                _record(log, out, label, url, r.status if r else None, html, "text/html")
            except Exception as exc:
                _record(log, out, f"{label} ({type(exc).__name__})", url, None, None)
            time.sleep(MIN_INTERVAL)
        try:  # fetch() from a www.bseindia.com page
            page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"home page reload failed: {exc}")
        for label, url in [*SAMPLES, ("one XBRL file", None)]:
            if url is None:  # one XBRL file only: the first link seen in any page, XHR or sample answer
                if not xbrl_links:
                    _record(log, out, "one XBRL file (no XBRL link seen)", "", None, None)
                    break
                url = sorted(xbrl_links)[0]
            for how in ("page fetch", "context request"):  # page fetch = the site's own Origin / Referer / cookies
                try:
                    if how == "page fetch":
                        status, body, ctype = _page_fetch(page, url)
                    else:
                        r = ctx.request.get(url, headers={"Referer": HOME}, timeout=60_000)
                        status, body, ctype = r.status, r.body(), r.headers.get("content-type", "")
                    _record(log, out if how == "page fetch" or status == 200 else None, f"{label} [{how}]", url,
                            status, body, ctype)  # fmt: skip
                except Exception as exc:
                    _record(log, out, f"{label} [{how}] ({type(exc).__name__}: {str(exc)[:80]})", url, None, None)
                time.sleep(MIN_INTERVAL)
        browser.close()
    print(f"{len(seen_api)} api.bseindia.com calls made by the pages:")
    for a in seen_api:
        print(f"  {a['status']} {a['bytes']:>8} {a['url']}")
    print(f"{len(xbrl_links)} XBRL links seen; first: {sorted(xbrl_links)[:3]}")
    log.append({"label": "page api calls", "calls": seen_api, "xbrl_links": sorted(xbrl_links)})
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["curl", "browser"], required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
    log = run_curl(a.out) if a.mode == "curl" else run_browser(a.out)
    if a.out:
        (a.out / "probe_summary.json").write_text(json.dumps(log, indent=1))
    ok = sum(1 for r in log if r.get("status") == 200)
    print(f"{ok}/{sum(1 for r in log if 'status' in r)} answered 200 ({a.mode})")
    return 0  # a probe: the log is the result, a 403 is an answer, not a failure


if __name__ == "__main__":
    sys.exit(main())
