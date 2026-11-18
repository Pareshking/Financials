"""BSE probe through the ported client (financials.fetch.bse: the owner's production method, plain requests with BSE's
own headers, 4-6 s apart, in-page XHR in headless Chrome only after a refusal). Five to seven calls:

  1. list of securities, group A, scrip 500488 (run 2: group A answered 200, A18)    ListofScripData
  2. announcements of ABBOTINDIA (500488, NSE `Permitted`), 15 Oct - 17 Nov 2026     AnnSubCategoryGetData
     (strCat -1; Result rows picked by CATEGORYNAME), and the source client's exact one-day call (13 Nov, page 1)
  3. one of those announcements' attachment                                           xml-data/corpfiling/AttachLive
  4. the shareholding filings of the last year for 500488                             Corp_Shareholding_ng
  5. the latest of those filings' inline XBRL                                         XBRLFILES/SHPXBRLDataXML

`--mode xbrl` (X240, owner 2026-11-18 "BSE website have XBRL filings, check it out") asks instead where BSE serves
results and annual-report XBRL, for the scrips of --scrips (CODE or CODE:GROUP, default 500488:A,505036:B,530745:T):

  1. BSE's financial results RSS feed (www, all companies) and, for one item (a listed scrip first), its linked file
     and that file's `.xml` sibling (a third-party project reports `.html` inline XBRL + `.xml` instance)
  2. per scrip: its list-of-securities row (NSURL = its stock page)
  3. the first scrip's `financials-results/` and `financials-annual-reports/` pages and the scripts they load (at most
     --max-js; BSE's site is a single-page app whose API names live in its JavaScript); the log prints every API name
     around "xbrl", "result" or "annual" and every XBRLFILES folder those scripts name
  4. for at most --max-endpoints of those API names (those containing "xbrl" first), one call per scrip with the
     scrip code in every parameter named like "scrip" (others blank)
  5. the first results-like and the first annual-like XBRL file named in those answers (`.html` also as `.xml`)

Every endpoint of this mode is UNVERIFIED (X240) until its answer is committed as a fixture.

`--mode xbrl2` (X242; after run 44240018334 found the RSS feed empty and BSE's router naming "/corporates/xbrldetails",
"XBRL Filings"): that page, its main bundle, the /corporates routes chunk, the component chunk of each route whose path
contains "xbrl" (the xbrldetails one first, at most 6), every API call and XBRLFILES folder they name (logged with
context), at most --max-endpoints of the xbrldetails component's calls once per scrip, then one results-like and one
annual-like file named in the answers.

Every answer is written byte for byte to the ledger (--out DIR: blobs/<sha256> + ledger.jsonl) before it is read; the
workflow uploads DIR as an artifact, which `python -m financials --data-dir data import-bse DIR` vaults and stages on
the owner's machine. The log prints status, size and sha256 only. A refusal (`Blocked`) ends the probe: no retries
around it (CLAUDE.md, owner decision).

    python scripts/probe_bse_reach.py --out bse_probe
    python scripts/probe_bse_reach.py --out bse_probe --mode xbrl --scrips 500488:A,505036:B,530745:T
    python scripts/probe_bse_reach.py --out bse_probe --mode xbrl2 --scrips 500488:A,505036:B,530745:T
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from financials.fetch.bse import HOME, BadRequest, Blocked, BseClient, Failed, Ledger, Missing

SCRIP = "500488"  # ABBOTINDIA: BSE bhavcopy of 2026-11-13, FinInstrmId for ISIN INE358A01014 [X165]


def _show(label: str, body: bytes | None, extra: str = "") -> None:
    sha = hashlib.sha256(body).hexdigest()[:16] if body is not None else ""
    print(f"OK    {label}: {len(body or b'')} bytes sha256 {sha} {extra}".rstrip())


# ── --mode xbrl (X240): pure helpers, then the calls ──

_ITEM = re.compile(r"<item>(.*?)</item>", re.S | re.I)
_SCRIPT = re.compile(r"""<script[^>]+src=["']([^"']+\.js)["']""", re.I)
_CHUNK = re.compile(r"""["'`(/]((?:[\w.-]+/)*chunk-[A-Za-z0-9_-]+\.js)""")
_API = re.compile(r"""([A-Za-z][A-Za-z0-9_]{2,80})/w\?([^"'`\s]{0,240})""")
_FOLDER = re.compile(r"XBRLFILES/[A-Za-z0-9_]+")
_FILE = re.compile(r"""(?:https?://[^"'\s<>]*?)?/?XBRLFILES/[^"'\s<>]+?\.(?:xml|html)""", re.I)
_WANT = re.compile(r"xbrl|result|annual", re.I)


def feed_items(data: bytes) -> list[dict]:
    """title / link / description of each RSS item, as sent; the scrip code from a trailing "(NNNNNN)" in the title."""
    out = []
    for item in _ITEM.findall(data.decode("utf-8", errors="replace")):
        f = {}
        for k in ("title", "link", "description"):
            m = re.search(rf"<{k}>(.*?)</{k}>", item, re.S | re.I)
            f[k] = m.group(1).strip() if m else ""
        m = re.search(r"\((\d{6})\)\s*$", f["title"])
        out.append({**f, "scrip": m.group(1) if m else ""})
    return out


def sibling_xml(url: str) -> str | None:
    return url[: -len(".html")] + ".xml" if url.lower().endswith(".html") else None


def api_names(js: str) -> dict[str, str]:
    """API name -> its first query template, for names around "xbrl", "result" or "annual"."""
    out: dict[str, str] = {}
    for name, query in _API.findall(js):
        if _WANT.search(name):
            out.setdefault(name, query)
    return out


def scrip_params(query: str, code: str) -> dict[str, str]:
    keys = dict.fromkeys(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", query))
    return {k: (code if "scrip" in k.lower() else "") for k in keys} or {"scripcode": code}


def _strings(v) -> list[str]:
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return [v] if isinstance(v, str) else []


def xbrl_links(text: str) -> list[str]:
    """XBRLFILES/....xml|html links in a page or an API answer (every string value of a JSON answer)."""
    with contextlib.suppress(ValueError):
        text = "\n".join(_strings(json.loads(text)))
    found = _FILE.findall(text)
    return list(dict.fromkeys(m if m.startswith("http") else HOME.rstrip("/") + "/" + m.lstrip("/") for m in found))


def xbrl_probe(c: BseClient, scrips: list[tuple[str, str]], max_js: int, max_endpoints: int) -> None:
    codes = [code for code, _ in scrips]
    files: dict[str, list[str]] = {"results_xbrl": [], "annual_xbrl": []}

    def fetch_pair(url: str, dataset: str, covers: dict) -> bool:
        """The file and, for `.html`, its `.xml` sibling; True when either answered."""
        ok = False
        for u in dict.fromkeys(x for x in (url, sibling_xml(url)) if x):
            try:
                body = c.xbrl_file(u, dataset, covers)
            except (Missing, BadRequest) as exc:
                print(f"SKIP  {dataset} {u}: {type(exc).__name__}: {exc}")
                continue
            text = body.decode("utf-8", errors="replace")
            ns = sorted(set(re.findall(r'xmlns:[\w-]+="(http[^"]+)"', text[:20000])))
            _show(f"{dataset} {u}", body, f"inline={'ix:header' in text} namespaces={ns[:12]}")
            print(f"      head: {text[:200]!r}")
            ok = True
        return ok

    try:  # 1. the RSS feed
        feed = c.results_feed()
        items = feed_items(feed)
        mine = [i for i in items if i["scrip"] in codes]
        _show("results feed", feed, f"{len(items)} items, {len(mine)} for {codes}; first: {items[:2]}")
        for i in (mine or items)[:1]:
            covers = {"scrip": i["scrip"], "from": "results_feed", "description": i["description"]}
            fetch_pair(urljoin(HOME, i["link"]), "results_xbrl", covers)
    except (Missing, BadRequest) as exc:
        print(f"SKIP  results feed: {type(exc).__name__}: {exc}")

    pages: list[str] = []
    for code, group in scrips:  # 2. list-of-securities rows: each scrip's stock page
        try:
            row = next((r for r in c.list_securities(group, scrip=code) if str(r.get("SCRIP_CD")) == code), None)
        except BadRequest as exc:
            print(f"SKIP  securities {code}: {exc}")
            continue
        print(f"OK    securities {code} (group {group}): {row and (row.get('ISIN_NUMBER'), row.get('NSURL'))}")
        if row and row.get("NSURL"):
            pages.append(str(row["NSURL"]))

    names: dict[str, str] = {}
    if pages:  # 3. the first scrip's stock pages and the scripts they load
        js_urls: list[str] = []
        for tail in ("financials-results/", "financials-annual-reports/"):
            url = pages[0].rstrip("/") + "/" + tail
            try:
                html = c.fetch_url(url, {}, "site_page", {"scrip": codes[0]}, file=True).decode("utf-8", "replace")
            except (Missing, BadRequest) as exc:
                print(f"SKIP  page {url}: {exc}")
                continue
            found = [urljoin(url, s) for s in _SCRIPT.findall(html)]
            js_urls += found
            print(f"OK    page {url}: {len(html)} chars, {len(found)} scripts, XBRL links {xbrl_links(html)[:4]}")
        seen: set[str] = set()
        folders: set[str] = set()
        while js_urls and len(seen) < max_js:
            u = js_urls.pop(0)
            if u in seen or "bseindia.com" not in u:
                continue
            seen.add(u)
            try:
                js = c.fetch_url(u, {}, "site_js", {}, file=True).decode("utf-8", "replace")
            except (Missing, BadRequest) as exc:
                print(f"SKIP  script {u}: {exc}")
                continue
            js_urls += [urljoin(u, x) for x in _CHUNK.findall(js)]
            got = api_names(js)
            folders |= set(_FOLDER.findall(js))
            for n, q in got.items():
                names.setdefault(n, q)
            if got or "xbrl" in js.lower():
                print(f"OK    script {u}: {len(js)} chars, API {sorted(got)}")
                for m in list(re.finditer("xbrl", js, re.I))[:6]:
                    print(f"      ...{js[max(0, m.start() - 120) : m.end() + 120]!r}")
        print(f"API names (xbrl / result / annual) in {len(seen)} scripts: {json.dumps(names, sort_keys=True)}")
        print(f"XBRLFILES folders named in the scripts: {sorted(folders)}")

    for name in sorted(names, key=lambda n: ("xbrl" not in n.lower(), n))[:max_endpoints]:  # 4. one call per scrip
        for code in codes:
            try:
                body = c.get(f"{name}/w", scrip_params(names[name], code), "xbrl_listing", {"api": name, "scrip": code})
            except (Missing, BadRequest) as exc:
                print(f"SKIP  {name} {code}: {type(exc).__name__}: {exc}")
                continue
            links = xbrl_links(body.decode("utf-8", "replace"))
            _show(f"{name} {code}", body, f"{len(links)} XBRL links: {links[:4]}")
            for link in links:
                annual = re.search("annual", link, re.I) or re.search(r"(^|[/_])AR_", link)
                files["annual_xbrl" if annual else "results_xbrl"].append(link)
    for dataset, links in files.items():  # 5. one file of each kind (at most 3 links tried)
        if not any(fetch_pair(link, dataset, {"from": "xbrl_listing"}) for link in list(dict.fromkeys(links))[:3]):
            print(f"NONE  {dataset}: no file named by any answer could be fetched ({len(links)} named)")


# ── --mode xbrl2 (X242): BSE's own "XBRL Filings" page (/corporates/xbrldetails) and the API calls it makes ──
# Run 44240018334 (mode xbrl): the results RSS feed answered 200 with 0 items; the stock pages are the Angular shell
# (<base href="/">, main-*.js) whose router sends /corporates to a lazy chunk (`path:"corporates",loadChildren:()=>
# import("./chunk-....js")`), which names the route "/corporates/xbrldetails" ("XBRL Filings"). Chunks resolve against
# the script directory (the xbrl mode resolved them against the page: those answers were the shell again).

_MAIN = re.compile(r"""<script[^>]+src=["']([^"']*main-[A-Za-z0-9]+\.js)["']""", re.I)
_CORP_ROUTES = re.compile(r"""path:"corporates",loadChildren:\(\)=>import\("\./(chunk-[A-Za-z0-9_-]+\.js)"\)""")
_IMPORT = re.compile(r"""import\("\./(chunk-[A-Za-z0-9_-]+\.js)"\)""")
_ENDPOINT = re.compile(r""""/?(?:BseIndiaAPI/api/)?([A-Za-z][A-Za-z0-9_]{2,80})/w(\?[^"]*)?\"""")
_PAGE_URL = re.compile(r"""https?://www\.bseindia\.com/[^"'\s]*xbrl[^"'\s]*\.aspx[^"'\s]*""", re.I)
_FILE_NAME = re.compile(r"""[A-Za-z0-9_./:-]+\.(?:xml|html)""", re.I)
JS_DIR = HOME + "assets/includenew/js/"


def route_chunks(routes_js: str, word: str = "xbrl") -> dict[str, str]:
    """Route path -> the chunk its component loads ("" when none: an eager component), for route paths containing
    `word`: the first `import("./chunk-...")` after `path:"..."` and before the next route's `path:`, else the last
    one between the previous route's `path:` and this one."""
    out: dict[str, str] = {}
    paths = list(re.finditer(r'path:"([^"]*)"', routes_js))
    for i, m in enumerate(paths):
        if word not in m.group(1).lower():
            continue
        nxt = paths[i + 1].start() if i + 1 < len(paths) else len(routes_js)
        imp = _IMPORT.search(routes_js, m.end(), nxt)
        if imp is None:
            before = list(_IMPORT.finditer(routes_js, paths[i - 1].end() if i else 0, m.start()))
            imp = before[-1] if before else None
        out[m.group(1)] = imp.group(1) if imp else ""
    return out


def endpoints(js: str) -> dict[str, list[str]]:
    """API name -> the query keys of its first call (its template plus the `&key=` that follow within 300 chars)."""
    out: dict[str, list[str]] = {}
    for m in _ENDPOINT.finditer(js):
        name = m.group(1)
        if name in out or name in ("api", "BseIndiaAPI"):
            continue
        ctx = (m.group(2) or "") + js[m.end() : m.end() + 300]
        out[name] = list(dict.fromkeys(re.findall(r"[?&]([A-Za-z_][A-Za-z0-9_]*)=", ctx)))
    return out


def _context(js: str, pattern: str, n: int = 8, width: int = 160) -> list[str]:
    found = (js[max(0, m.start() - width) : m.end() + width] for m in re.finditer(pattern, js, re.I))
    return list(dict.fromkeys(found))[:n]


def xbrl2_probe(c: BseClient, scrips: list[tuple[str, str]], max_chunks: int, max_endpoints: int) -> None:
    codes = [code for code, _ in scrips]

    def text(url: str, dataset: str) -> str | None:
        try:
            return c.fetch_url(url, {}, dataset, {}, file=True).decode("utf-8", "replace")
        except (Missing, BadRequest) as exc:
            print(f"SKIP  {url}: {type(exc).__name__}: {exc}")
            return None

    page = HOME + "corporates/xbrldetails"  # 1. the page (the Angular shell) and its main bundle
    html = text(page, "site_page")
    if html is None:
        return
    mains = [urljoin(HOME, s) for s in _MAIN.findall(html)]
    print(f"OK    page {page}: {len(html)} chars, main bundle {mains}, XBRL links {xbrl_links(html)[:4]}")
    main_js = text(mains[0], "site_js") if mains else None
    corp = _CORP_ROUTES.search(main_js or "")
    if not corp:
        print("NONE  no /corporates route chunk in the main bundle")
        return
    routes_js = text(JS_DIR + corp.group(1), "site_js")  # 2. the /corporates routes
    if routes_js is None:
        return
    routes = route_chunks(routes_js)
    calls: dict[str, list[str]] = {}
    print(f"OK    /corporates routes ({corp.group(1)}): XBRL routes -> chunks {routes}")
    chunks = list(dict.fromkeys(ch for path, ch in sorted(routes.items(), key=lambda kv: kv[0] != "xbrldetails") if ch))
    if not routes.get("xbrldetails"):  # no lazy chunk for the page: its component is in the routes chunk itself
        calls = dict(endpoints(routes_js))
        print(f"      routes chunk endpoints {json.dumps(calls, sort_keys=True)}")
        for ctx in _context(routes_js, r"xbrldetails|XBRLFILES", 6):
            print(f"      ...{ctx!r}")
    folders: set[str] = set(_FOLDER.findall(routes_js))
    pages: list[str] = []
    for ch in chunks[:max_chunks]:  # 3. each XBRL route's component: the API calls and file folders it names
        js = text(JS_DIR + ch, "site_js")
        if js is None:
            continue
        got = endpoints(js)
        folders |= set(_FOLDER.findall(js))
        pages += _PAGE_URL.findall(js)
        print(f"OK    chunk {ch}: {len(js)} chars, endpoints {json.dumps(got, sort_keys=True)}")
        for ctx in _context(js, r"/w\?|/w\"|XBRLFILES|\.aspx|iframe", 12):
            print(f"      ...{ctx!r}")
        if ch == routes.get("xbrldetails"):
            for name, keys in got.items():
                calls.setdefault(name, keys)
    print(f"XBRLFILES folders named: {sorted(folders)}; xbrl .aspx pages named: {sorted(set(pages))}")
    for p in list(dict.fromkeys(pages))[:2]:  # an embedded legacy page, if the component points to one
        h = text(p, "site_page")
        if h is not None:
            print(f"OK    page {p}: {len(h)} chars, XBRL links {xbrl_links(h)[:6]}")

    named: dict[str, list[str]] = {"results_xbrl": [], "annual_xbrl": []}
    for name in list(calls)[:max_endpoints]:  # 4. the xbrldetails page's calls, once per scrip
        for code in codes:
            params = {k: (code if "scrip" in k.lower() else "") for k in calls[name]} or {"scripcode": code}
            try:
                body = c.get(f"{name}/w", params, "xbrl_listing", {"api": name, "scrip": code})
            except (Missing, BadRequest) as exc:
                print(f"SKIP  {name} {code}: {type(exc).__name__}: {exc}")
                continue
            s = body.decode("utf-8", "replace")
            links = xbrl_links(s)
            bare = [n for n in _FILE_NAME.findall(s) if "/" not in n]
            _show(
                f"{name} {params}",
                body,
                f"{len(links)} XBRL links {links[:3]}; bare names {bare[:3]}; head {s[:300]!r}",
            )
            for link in links + [f"{HOME}{f}/{n}" for n in bare[:2] for f in sorted(folders)[:2]]:
                annual = re.search("annual", link, re.I) or re.search(r"(^|[/_])AR_", link)
                named["annual_xbrl" if annual else "results_xbrl"].append(link)
    for dataset, links in named.items():  # 5. one file of each kind (at most 3 links tried)
        ok = False
        for link in list(dict.fromkeys(links))[:3]:
            for u in dict.fromkeys(x for x in (link, sibling_xml(link)) if x):
                try:
                    body = c.xbrl_file(u, dataset, {"from": "xbrldetails"})
                except (Missing, BadRequest) as exc:
                    print(f"SKIP  {dataset} {u}: {type(exc).__name__}: {exc}")
                    continue
                t = body.decode("utf-8", errors="replace")
                ns = sorted(set(re.findall(r'xmlns:[\w-]+="(http[^"]+)"', t[:20000])))
                _show(f"{dataset} {u}", body, f"inline={'ix:header' in t} namespaces={ns[:12]}")
                ok = True
            if ok:
                break
        if not ok:
            print(f"NONE  {dataset}: none of {len(links)} named files could be fetched")


def _scrips(text: str) -> list[tuple[str, str]]:
    out = []
    for part in (p.strip() for p in text.split(",") if p.strip()):
        code, _, group = part.partition(":")
        if not code.isdigit():
            raise SystemExit(f"--scrips: {part!r} is not CODE or CODE:GROUP")
        out.append((code, group or "A"))
    return out


def _summary(led: Ledger) -> None:
    recs = led.records()
    print(f"{len(recs)} answers in the ledger (via {sorted({r['via'] for r in recs}) or '-'}):")
    for r in recs:
        print(f"  {r['status']} {r['bytes']:>9} {r['sha256'][:16]} {r['via']:<12} {r['dataset']:<20} {r['url']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=("reach", "xbrl", "xbrl2"), default="reach")
    ap.add_argument("--scrips", default="500488:A,505036:B,530745:T", help="--mode xbrl: CODE or CODE:GROUP list")
    ap.add_argument("--max-js", type=int, default=30)
    ap.add_argument("--max-endpoints", type=int, default=4)
    a = ap.parse_args(argv)
    led = Ledger(a.out)
    c = BseClient(ledger=led)
    if a.mode in ("xbrl", "xbrl2"):
        try:
            if a.mode == "xbrl":
                xbrl_probe(c, _scrips(a.scrips), a.max_js, a.max_endpoints)
            else:
                xbrl2_probe(c, _scrips(a.scrips), 6, a.max_endpoints)
        except (Blocked, Failed) as exc:
            print(f"STOP  {type(exc).__name__}: {exc}")
        finally:
            c.close()
        _summary(led)
        return 0
    found: dict = {}

    def step(label: str, fn) -> None:
        """One call; a 400 (BadRequest) or a 404 file ends that call only, a refusal (Blocked) ends the probe."""
        try:
            fn()
        except (BadRequest, Missing) as exc:
            print(f"SKIP  {label}: {type(exc).__name__}: {exc}")

    def securities() -> None:
        sec = c.list_securities("A", scrip=SCRIP)
        _show("list of securities, group A, scrip 500488", None,
              f"{len(sec)} rows: {[(r.get('ISIN_NUMBER'), r.get('Mktcap')) for r in sec[:3]]}")  # fmt: skip

    def announcements() -> None:
        # strCat -1 (every category, as the source client) with strScrip; results are picked by CATEGORYNAME. Run 2:
        # strCat=Result with strScrip=500488 answered 400.
        ann, total = c.announcements(date(2026, 10, 15), date(2026, 11, 17), scrip=SCRIP)
        res = [r for r in ann if str(r.get("CATEGORYNAME", "")).strip() == "Result"]
        found["ann"] = res or ann
        top = [(r.get("NEWS_DT"), r.get("SUBCATNAME"), r.get("ATTACHMENTNAME")) for r in res[:4]]
        _show("announcements 500488 (15 Oct - 17 Nov)", None,
              f"{len(ann)} rows (BSE count {total}), {len(res)} Result: {top}")  # fmt: skip

    def announcements_day() -> None:  # the source client's exact call: one day, every company
        ann, total = c.announcements(date(2026, 11, 13), date(2026, 11, 13))
        mine = [r for r in ann if str(r.get("SCRIP_CD")) == SCRIP]
        found.setdefault("ann", mine or ann[:1])
        _show("announcements 13 Nov, page 1 (source client's exact call)", None, f"{len(ann)} rows (BSE count "
              f"{total}); {len(mine)} for 500488")  # fmt: skip

    def attachment() -> None:
        att = next((r for r in found.get("ann", []) if r.get("ATTACHMENTNAME")), None)
        if att:
            body = c.attachment(att["ATTACHMENTNAME"], {"news_id": att.get("NEWSID"), "scrip": str(att["SCRIP_CD"])})
            _show("one announcement attachment", body, f"Fld_Attachsize {att.get('Fld_Attachsize')}")

    def shareholding() -> None:
        shp = c.shareholding_filings(6, scrip=SCRIP)
        mine = [r for r in shp if str(r.get("FLD_ScripCode")) == SCRIP] or shp
        found["shp"] = mine
        _show("shareholding filings (flag 6) 500488", None, f"{len(shp)} rows, {len(mine)} for 500488; "
              f"{[(r.get('EndDate'), r.get('IsXBRL'), r.get('XBRLAttachment')) for r in mine[:4]]}")  # fmt: skip

    def shp_xbrl() -> None:
        x = next((r for r in found.get("shp", []) if r.get("IsXBRL") == 1 and r.get("XBRLAttachment")), None)
        if x:
            body = c.shareholding_xbrl(x["XBRLAttachment"], {"scrip": str(x.get("FLD_ScripCode")),
                                                             "end": x.get("EndDate")})  # fmt: skip
            _show("one shareholding inline XBRL", body)

    try:
        for label, fn in (("securities", securities), ("announcements", announcements),
                          ("announcements (day)", announcements_day), ("attachment", attachment),
                          ("shareholding", shareholding), ("shareholding XBRL", shp_xbrl)):  # fmt: skip
            step(label, fn)
    except (Blocked, Failed) as exc:
        print(f"STOP  {type(exc).__name__}: {exc}")
    finally:
        c.close()
    _summary(led)
    return 0  # a probe: the log is the result


if __name__ == "__main__":
    sys.exit(main())
