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

`--mode xbrl3` (X243; run 44245923545 found no "xbrldetails" route and an XBRL-figures "results" view, not files):
the stock-share-price routes chunk named by the main bundle, the components of its routes around "financ", "annual"
and "result" (at most 6 chunks), the url-map modules they import (at most 3), every call they make with its parameter
keys and every XBRL link field / folder prefix (logged with context), at most 8 of those calls once per scrip (the
scrip code in scrip-like keys), then one results and one annual file named in the answers (+ the `.xml` beside an
`.html`).

`--mode xbrl4` (X244; the owner's four BSE pointers of 2026-11-18, UNVERIFIED): (a) `AnnGetData/w` with
strCat=Result once per scrip (20 Oct - 18 Nov 2026), then `Msource/90D/CorpXbrlGen.aspx?Bsenewid=<NEWSID>` for at most
3 NEWSIDs (fresh rows first, then KNOWN_RESULT_NEWSIDS read offline) and, when that answers an HTML viewer, one link in
it (at most 2 such fetches); (b) `/corporates/comp_resultsnew`: the component behind its route, its date format and
calls, at most 2 listing calls for 12-14 Nov 2026 (all companies), one "Std" and one "Con" XBRL file the answer names;
(c) the `/corporates/xbrldetails` component, if its route is found: one call for the first scrip, category Annual
Reports (the option value found next to that label), 1 Apr 2025 - 18 Nov 2026. At most 40 calls (CALL_BUDGET).

Every answer is written byte for byte to the ledger (--out DIR: blobs/<sha256> + ledger.jsonl) before it is read; the
workflow uploads DIR as an artifact, which `python -m financials --data-dir data import-bse DIR` vaults and stages on
the owner's machine. The log prints status, size and sha256 only. A refusal (`Blocked`) ends the probe: no retries
around it (CLAUDE.md, owner decision).

    python scripts/probe_bse_reach.py --out bse_probe
    python scripts/probe_bse_reach.py --out bse_probe --mode xbrl --scrips 500488:A,505036:B,530745:T
    python scripts/probe_bse_reach.py --out bse_probe --mode xbrl2 --scrips 500488:A,505036:B,530745:T
    python scripts/probe_bse_reach.py --out bse_probe --mode xbrl3 --scrips 500488:A,505036:B,530745:T
    python scripts/probe_bse_reach.py --out bse_probe --mode xbrl4 --scrips 500488:A,505036:B,530745:T
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

from financials.fetch.bse import HOME, BadRequest, Blocked, BseClient, Failed, Ledger, Missing, ymd

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
            # only an import inside this route's own object literal (no "},{" between it and this path)
            imp = before[-1] if before and "},{" not in routes_js[before[-1].end() : m.start()] else None
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


# ── --mode xbrl3 (X243): the stock page's own results / annual-report components ──
# Run 44245923545 (xbrl2): the /corporates routes chunk has no "xbrldetails" route; its "results" component shows
# figures "as per XBRL submission" (Corp_BSEDnBResults_SEBI_Consolidated_Res_ng, Corp_detailedResult_Transpose_ng:
# parsed values keyed by a quarter code, not files), its API paths are template literals
# (`${I.BSE_Domain_APIUrl}/<Name>/w`) or `_.url.<Key>` entries of an imported url map, and XBRL links are row fields
# (`ae("href",n.IXBRLFileName,...)`, `n.xbrlurl`). The stock pages load the "stock-share-price" routes chunk.

_LAZY = re.compile(r"""\{path:"([^"]+)",loadChildren:\(\)=>import\("\./(chunk-[A-Za-z0-9_-]+\.js)"\)""")
_TEMPLATE = re.compile(r"""\$\{[\w.]+\}/([A-Za-z][A-Za-z0-9_]{2,80})/w(\?[^`]*)?`""")
_URLKEY = re.compile(r"""\b([A-Za-z_$][\w$]*)\.url\.([A-Za-z_]\w*)""")
_STATIC_IMPORT = re.compile(r"""import\{([^}]*)\}from"\./(chunk-[A-Za-z0-9_-]+\.js)\"""")
_HREF_FIELD = re.compile(r"""(?:"href"|"routerLink"),\s*(?:"([^"]*)"\+)?\w+\.(\w*(?:xbrl|XBRL|Xbrl)\w*)""")
_PREFIX_FIELD = re.compile(r""""([^"]*XBRLFILES/[^"]*)"\+\w+\.(\w+)""")


def component_code(routes_js: str, path: str) -> tuple[str, str]:
    """(code, chunk) of an eager route's component (`{component:X,path:"..."}`): the code from the class before
    `X=class` to the next class, so its template functions (emitted before the class) come with it; or, when X is
    imported, the chunk it comes from."""
    m = re.search(r'\{component:([\w$]+),path:"' + re.escape(path) + '"', routes_js)
    if not m:
        return "", ""
    cls = re.search(r"\b" + re.escape(m.group(1)) + r"=class\b", routes_js)
    if not cls:  # imported from another chunk: `import{a as X}from"./chunk-..."`
        alias = re.escape(m.group(1))
        found = (ch for names, ch in _STATIC_IMPORT.findall(routes_js) if re.search(rf"\bas {alias}\b", names))
        return "", next(found, "")
    starts = [x.start() for x in re.finditer(r"\b[\w$]+=class\b", routes_js)]
    prev = max((x for x in starts if x < cls.start()), default=0)
    nxt = min((x for x in starts if x > cls.start()), default=len(routes_js))
    return routes_js[prev:nxt], ""


def lazy_routes(main_js: str) -> dict[str, str]:
    return dict(_LAZY.findall(main_js))


def url_map(js: str) -> dict[str, str]:
    """`Key:"/Name/w..."` entries of an url-map module (any object literal: its exact shape is not known yet)."""
    return dict(re.findall(r'([A-Za-z_]\w*):"(/?(?:BseIndiaAPI/api/)?[A-Za-z]\w*/w\b[^"]*)"', js))


def url_map_chunks(js: str) -> list[str]:
    """The chunks a component imports the alias of `<alias>.url.<Key>` from."""
    aliases = {a for a, _ in _URLKEY.findall(js)}
    out = []
    for names, chunk in _STATIC_IMPORT.findall(js):
        if any(re.search(rf"\bas {re.escape(a)}\b", names) for a in aliases):
            out.append(chunk)
    return list(dict.fromkeys(out))


def calls_in(js: str, urls: dict[str, str]) -> dict[str, list[str]]:
    """API name -> parameter keys, for template-literal, quoted and url-map calls; the keys are those of the query
    template plus the last object literal within 600 characters before the call."""
    out: dict[str, list[str]] = {}
    found = [(m.start(), m.group(1), m.group(2) or "") for m in _TEMPLATE.finditer(js)]
    found += [(m.start(), m.group(1), m.group(2) or "") for m in _ENDPOINT.finditer(js)]
    for m in _URLKEY.finditer(js):
        path = urls.get(m.group(2), "")
        name = re.search(r"([A-Za-z][A-Za-z0-9_]{2,80})/w(\?.*)?$", path)
        if name:
            found.append((m.start(), name.group(1), name.group(2) or ""))
    for pos, name, query in sorted(found):
        if name in out or name in ("api", "BseIndiaAPI"):
            continue
        objs = re.findall(r"\{([^{}]{0,400})\}", js[max(0, pos - 600) : pos])
        keys = re.findall(r"[?&]([A-Za-z_]\w*)=", query + js[pos : pos + 300].split(";")[0])
        for o in reversed(objs):  # `new HttpParams({fromObject:n})` wraps the literal that holds the keys
            ks = [k for k in re.findall(r"([A-Za-z_]\w*):", o) if k != "fromObject"]
            if ks:
                keys += ks
                break
        out[name] = list(dict.fromkeys(keys))
    return out


def _rows(v) -> list[dict]:
    if isinstance(v, dict):
        return [v] + [r for x in v.values() for r in _rows(x)]
    if isinstance(v, list):
        return [r for x in v for r in _rows(x)]
    return []


def answer_links(body: bytes, prefixes: list[tuple[str, str]], fields: set[str]) -> list[str]:
    """XBRL file links in one API answer: XBRLFILES links anywhere, the values of the fields the page shows as XBRL
    links, and a folder prefix + field value where the page builds the link that way."""
    text = body.decode("utf-8", "replace")
    links = xbrl_links(text)
    try:
        rows = _rows(json.loads(text))
    except ValueError:
        rows = []
    for r in rows:
        for f in fields:
            v = r.get(f)
            if isinstance(v, str) and v.strip():
                links.append(urljoin(HOME, v.strip()))
        for prefix, f in prefixes:
            v = r.get(f)
            if isinstance(v, str) and v.strip():
                links.append(urljoin(HOME, prefix + v.strip()))
    return list(dict.fromkeys(links))


QTR = re.compile(r"qtr|quarter|quater", re.I)


def scrip_value(key: str, code: str) -> str:
    return code if re.search(r"scrip|scr_?cd|sc_cd|^code$|scode|scripcode", key, re.I) else ""


def xbrl3_probe(c: BseClient, scrips: list[tuple[str, str]], max_chunks: int, max_endpoints: int) -> None:
    codes = [code for code, _ in scrips]

    def text(url: str) -> str | None:
        try:
            return c.fetch_url(url, {}, "site_js" if url.endswith(".js") else "site_page", {}, file=True).decode(
                "utf-8", "replace"
            )
        except (Missing, BadRequest) as exc:
            print(f"SKIP  {url}: {type(exc).__name__}: {exc}")
            return None

    shell = text(HOME + "corporates/xbrldetails")  # 1. the shell, its main bundle, the stock-page routes
    mains = [urljoin(HOME, s) for s in _MAIN.findall(shell or "")]
    main_js = text(mains[0]) if mains else None
    lazy = lazy_routes(main_js or "")
    print(f"OK    main bundle {mains[:1]}: lazy routes {lazy}")
    if "stock-share-price" not in lazy:
        print("NONE  no stock-share-price routes chunk")
        return
    routes_js = text(JS_DIR + lazy["stock-share-price"])
    if routes_js is None:
        return
    routes = {
        **route_chunks(routes_js, "financ"),
        **route_chunks(routes_js, "annual"),
        **route_chunks(routes_js, "result"),
    }
    print(f"OK    stock-share-price routes ({lazy['stock-share-price']}): {routes}")
    comps: dict[str, str] = {}  # route paths -> component code (a lazy chunk, else the routes chunk itself)
    by_chunk: dict[str, list[str]] = {}
    for path, ch in routes.items():
        by_chunk.setdefault(ch, []).append(path)
    for path in by_chunk.pop("", []):  # eager components: their code in the routes chunk, else the chunk it imports
        code, imported = component_code(routes_js, path)
        if code:
            comps[path] = code
        elif imported:
            by_chunk.setdefault(imported, []).append(path)
        else:
            print(f"NONE  component of route {path} not found")
    for ch, paths in list(by_chunk.items())[:max_chunks]:  # 2. each lazy component chunk once
        js = text(JS_DIR + ch)
        if js is not None:
            comps[",".join(paths)] = js
    urls: dict[str, str] = {}
    for ch in list(dict.fromkeys(x for js in comps.values() for x in url_map_chunks(js)))[:3]:  # 3. url maps
        js = text(JS_DIR + ch)
        urls.update(url_map(js or ""))
    print(f"OK    url map entries: {len(urls)}; xbrl / result / annual ones: "
          f"{ {k: v for k, v in urls.items() if _WANT.search(k + v)} }")  # fmt: skip
    plan: list[tuple[str, str, list[str]]] = []  # (route path, API name, keys)
    prefixes: list[tuple[str, str]] = []
    fields: set[str] = set()
    for path, js in comps.items():
        calls = calls_in(js, urls)
        prefixes += _PREFIX_FIELD.findall(js)
        fields |= {f for _, f in _HREF_FIELD.findall(js)}
        print(f"OK    component {path}: {len(js)} chars, calls {json.dumps(calls, sort_keys=True)}")
        for ctx in _context(js, r"xbrl|XBRLFILES|/w`|/w\?|\.url\.", 16):
            print(f"      ...{ctx!r}")
        plan += [(path, n, k) for n, k in calls.items() if (path, n) not in {(p, m) for p, m, _ in plan}]
    print(f"XBRL link fields {sorted(fields)}; folder + field {prefixes}")
    ranked = sorted(plan, key=lambda p: ("financ" not in p[0].lower(), not re.search("xbrl", p[1], re.I),
                                         not _WANT.search(p[1])))  # fmt: skip
    named: dict[str, list[str]] = {"results_xbrl": [], "annual_xbrl": []}
    qvals: dict[str, str] = {}  # scrip -> a quarter code seen in an earlier answer (for Qtr / QuarterID keys)
    chosen = ranked[:max_endpoints]
    chosen.sort(key=lambda p: any(QTR.search(k) for k in p[2]))  # calls without a quarter key first
    for path, name, keys in chosen:  # 4. the calls, once per scrip
        for code in codes:
            params = {k: (qvals.get(code, "") if QTR.search(k) else scrip_value(k, code)) for k in keys}
            params = params or {"scripcode": code}
            try:
                body = c.get(f"{name}/w", params, "xbrl_listing", {"api": name, "scrip": code, "route": path})
            except (Missing, BadRequest) as exc:
                print(f"SKIP  {name} {params}: {type(exc).__name__}: {exc}")
                continue
            links = answer_links(body, prefixes, fields)
            if code not in qvals:
                with contextlib.suppress(ValueError):
                    for r in _rows(json.loads(body.decode("utf-8", "replace"))):
                        q = next((str(v) for k, v in r.items() if QTR.search(k) and v not in (None, "")), None)
                        if q:
                            qvals[code] = q
                            print(f"      quarter code for {code}: {q!r} (from {name})")
                            break
            head = body[:400].decode("utf-8", "replace")
            _show(f"{name} {params}", body, f"{len(links)} links {links[:3]}; head {head!r}")
            kind = "annual_xbrl" if re.search("annual", path + name, re.I) else "results_xbrl"
            named[kind] += links
    for dataset, links in named.items():  # 5. one file of each kind (+ the .xml beside an .html)
        ok = False
        for link in list(dict.fromkeys(links))[:3]:
            for u in dict.fromkeys(x for x in (link, sibling_xml(link)) if x):
                try:
                    body = c.xbrl_file(u, dataset, {"from": "stock page"})
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


# ── --mode xbrl4 (X244): the owner's four BSE pointers (2026-11-18), all UNVERIFIED until this run's answers ──
# 1. /corporates/comp_resultsnew lists results with direct "Std XBRL" / "Con XBRL" links; 2. /corporates/xbrldetails
# filters XBRL filings by security, category and From/To (DD/MM/YYYY); 3. AnnGetData/w (strCat=Result) announcements;
# 4. Msource/90D/CorpXbrlGen.aspx?Bsenewid=<NEWSID> serves the XBRL of an announcement that has one.
# NEWSIDs of Result rows read offline (the 3 probe scrips are absent from the 2026-11-18 bse-fetch ledgers):
KNOWN_RESULT_NEWSIDS = (
    ("500488", "6fa639f3-1cba-42e1-a341-ab46e27899e6"),  # 2026-11-05 18:55, tests/fixtures/bse (A18 run 3)
    ("590041", "287a3321-71de-4a52-9089-083b8e94337f"),  # 2026-11-14 18:15, bse-fetch ledger r44229330812/3750
    ("544416", "a114c4a1-7e95-42e0-93a2-2c61a9fa5142"),  # 2026-11-04 17:54, same ledgers
)
XBRL_GEN = HOME + "Msource/90D/CorpXbrlGen.aspx"
CALL_BUDGET = 40
_LINK = re.compile(r"""(?:href|src|action)\s*=\s*["']([^"'#][^"']*)["']""", re.I)
_DATE_FMT = re.compile(r"""["'](dd/MM/yyyy|yyyyMMdd|dd-MM-yyyy|yyyy-MM-dd|dd-MMM-yyyy|DD/MM/YYYY|YYYYMMDD)["']""")


class OverBudget(Exception):
    pass


def viewer_links(html: str, base: str) -> list[str]:
    """Links in an HTML answer that may lead to the XBRL itself (.xml / .html / .aspx / XBRL in the path)."""
    out = []
    for raw in _LINK.findall(html):
        u = urljoin(base, raw.strip())
        low = u.lower().split("?", 1)[0]
        if low.endswith((".js", ".css", ".png", ".gif", ".jpg", ".ico", ".svg")) or not u.startswith("http"):
            continue
        if low.endswith((".xml", ".html", ".htm", ".aspx", ".zip")) or "xbrl" in u.lower():
            out.append(u)
    return list(dict.fromkeys(out))


def xbrl_values(body: bytes) -> list[tuple[str, str]]:
    """(field, value) of every non-empty string field named like xbrl in the rows of a JSON answer."""
    try:
        rows = _rows(json.loads(body.decode("utf-8", "replace")))
    except ValueError:
        return []
    out = [(k, v.strip()) for r in rows for k, v in r.items() if re.search("xbrl", k, re.I) and isinstance(v, str)]
    return list(dict.fromkeys((k, v) for k, v in out if v))


def date_format(js: str) -> str:
    """The first Angular / moment date format the component names (BSE APIs use YYYYMMDD when none is found)."""
    m = _DATE_FMT.search(js)
    f = (m.group(1) if m else "yyyyMMdd").replace("DD", "dd").replace("YYYY", "yyyy")
    return f.replace("yyyy", "%Y").replace("MMM", "%b").replace("MM", "%m").replace("dd", "%d")


def fill_params(keys: list[str], code: str, a: date, b: date, fmt: str, category: str = "") -> dict[str, str]:
    """A value for each key: scrip-like -> code, from / to dates in `fmt`, category-like -> `category`, else ''."""
    out = {}
    for k in keys:
        low = k.lower()
        if re.search(r"cat", low):
            out[k] = category
        elif re.search(r"from|prev|start|fdt|frdt|fromdate|dtfrom", low):
            out[k] = a.strftime(fmt)
        elif re.search(r"to(date|dt)?$|^to|end|tdt|dtto", low):
            out[k] = b.strftime(fmt)
        elif re.search(r"page", low):
            out[k] = "1"
        else:
            out[k] = scrip_value(k, code)
    return out


def category_value(js: str, label: str = "Annual Report") -> tuple[str, list[str]]:
    """The option value next to `label` in a component (an object literal or <option value=..>), and the contexts."""
    ctx = _context(js, re.escape(label), 6, 200)
    for c in ctx:
        val = r"""(?:value|id|code|val|key)\s*[:=]\s*["']?([^"',}<>\s]+)"""
        m = re.search(val + r"""["']?[^{}]{0,120}""" + re.escape(label), c)
        m = m or re.search(re.escape(label) + r"[^{}]{0,120}?" + val, c)
        if m:
            return m.group(1), ctx
    return "", ctx


def xbrl4_probe(c: BseClient, scrips: list[tuple[str, str]]) -> None:
    codes = [code for code, _ in scrips]
    cache: dict[str, str | None] = {}

    def guard() -> None:
        if c.calls >= CALL_BUDGET:
            raise OverBudget(f"{c.calls} calls made (budget {CALL_BUDGET})")

    def text(url: str) -> str | None:
        if url in cache:
            return cache[url]
        guard()
        try:
            body = c.fetch_url(url, {}, "site_js" if url.endswith(".js") else "site_page", {}, file=True)
            cache[url] = body.decode("utf-8", "replace")
        except (Missing, BadRequest) as exc:
            print(f"SKIP  {url}: {type(exc).__name__}: {exc}")
            cache[url] = None
        return cache[url]

    def show_file(u: str, dataset: str, covers: dict) -> str | None:
        guard()
        try:
            body = c.xbrl_file(u, dataset, covers)
        except (Missing, BadRequest) as exc:
            print(f"SKIP  {dataset} {u}: {type(exc).__name__}: {exc}")
            return None
        t = body.decode("utf-8", errors="replace")
        ns = sorted(set(re.findall(r'xmlns:[\w-]+="(http[^"]+)"', t[:20000])))
        kind = "inline XBRL" if "ix:header" in t else "XBRL instance" if "xbrli:" in t[:20000] else "other"
        _show(f"{dataset} {u}", body, f"{kind}; namespaces={ns[:12]}")
        print(f"      head: {t[:300]!r}")
        return t

    # (a) AnnGetData/w, strCat=Result, once per scrip; then CorpXbrlGen.aspx for at most 3 NEWSIDs
    a, b = date(2026, 10, 20), date(2026, 11, 18)  # 500488 filed its Q2 results on 2026-11-05 (A18 run 3)
    fresh: list[tuple[str, str]] = []
    for code in codes:
        guard()
        params = {"pageno": "1", "strCat": "Result", "strPrevDate": ymd(a), "strScrip": code, "strSearch": "P",
                  "strToDate": ymd(b), "strType": "C"}  # fmt: skip
        try:
            covers = {"api": "AnnGetData", "scrip": code, "from": a.isoformat(), "to": b.isoformat()}
            body = c.get("AnnGetData/w", params, "announcements", covers)
        except (Missing, BadRequest) as exc:
            print(f"SKIP  AnnGetData {code}: {type(exc).__name__}: {exc}")
            continue
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            _show(f"AnnGetData {code} (not JSON)", body, f"head {body[:300]!r}")
            continue
        rows = payload.get("Table") if isinstance(payload, dict) else payload
        rows = rows if isinstance(rows, list) else []
        keys = sorted({k for r in rows if isinstance(r, dict) for k in r})
        _show(f"AnnGetData {code} Result {a}..{b}", body, f"{len(rows)} rows; tables "
              f"{sorted(payload) if isinstance(payload, dict) else '-'}; row keys {keys}")  # fmt: skip
        for r in rows[:6]:
            if isinstance(r, dict):
                print(f"      {r.get('NEWSID')} {r.get('NEWS_DT')} {r.get('CATEGORYNAME')} / {r.get('SUBCATNAME')} "
                      f"XML_NAME={r.get('XML_NAME')} QUARTER_ID={r.get('QUARTER_ID')} "
                      f"xbrl fields={ {k: v for k, v in r.items() if 'xbrl' in k.lower()} }")  # fmt: skip
        mine = [r for r in rows if isinstance(r, dict) and str(r.get("SCRIP_CD")) == code and r.get("NEWSID")]
        fresh += [(code, str(r["NEWSID"])) for r in mine[:1]]
    targets = list(dict.fromkeys([*fresh, *KNOWN_RESULT_NEWSIDS]))
    seen_ids: set[str] = set()
    fetched: set[str] = set()  # viewer links fetched (at most 2)
    for code, nid in targets:
        if nid.lower() in seen_ids or len(seen_ids) >= 3:
            continue
        seen_ids.add(nid.lower())
        guard()
        try:
            covers = {"scrip": code, "news_id": nid, "from": "CorpXbrlGen"}
            body = c.fetch_url(XBRL_GEN, {"Bsenewid": nid}, "results_xbrl", covers, file=True)
        except (Missing, BadRequest) as exc:
            print(f"SKIP  CorpXbrlGen {code} {nid}: {type(exc).__name__}: {exc}")
            continue
        t = body.decode("utf-8", errors="replace")
        ns = sorted(set(re.findall(r'xmlns:[\w-]+="(http[^"]+)"', t[:20000])))
        links = viewer_links(t, XBRL_GEN)
        kind = "inline XBRL" if "ix:header" in t else "XBRL instance" if "xbrli:" in t[:20000] else "HTML / other"
        _show(f"CorpXbrlGen {code} {nid}", body, f"{kind}; namespaces={ns[:10]}; {len(links)} links {links[:8]}")
        print(f"      head: {t[:300]!r}")
        links = [u for u in links if u not in fetched]
        if kind == "HTML / other" and links and len(fetched) < 2:
            pick = sorted(links, key=lambda u: (not u.lower().split("?")[0].endswith(".xml"), "xbrl" not in u.lower()))
            fetched.add(pick[0])
            show_file(pick[0], "results_xbrl", {"scrip": code, "news_id": nid, "from": "CorpXbrlGen viewer"})

    # (b) comp_resultsnew: the page, the component behind its route, its listing call, one Std and one Con file
    page = HOME + "corporates/comp_resultsnew"
    html = text(page) or ""
    mains = [urljoin(HOME, s) for s in _MAIN.findall(html)]
    print(f"OK    page {page}: {len(html)} chars, main bundle {mains[:1]}, links {viewer_links(html, page)[:6]}")
    main_js = text(mains[0]) if mains else ""
    lazy = lazy_routes(main_js or "")
    corp = _CORP_ROUTES.search(main_js or "")
    corp_chunk = corp.group(1) if corp else lazy.get("corporates", "")
    routes_js = text(JS_DIR + corp_chunk) if corp_chunk else None
    print(f"OK    lazy routes {lazy}; /corporates routes chunk {corp_chunk or '-'}")

    def component(word: str) -> tuple[str, str]:
        """(route path, component code) of the first route whose path contains `word` (case-insensitive)."""
        for src in (routes_js or "", main_js or ""):
            found = route_chunks(src, word)  # `word` lowercase: route_chunks lowercases the path
            for path, ch in found.items():
                if ch:
                    js = text(JS_DIR + ch)
                    if js:
                        return path, js
                code, imported = component_code(src, path)
                if code:
                    return path, code
                if imported:
                    js = text(JS_DIR + imported)
                    if js:
                        return path, js
        ctx = _context((routes_js or "") + (main_js or ""), word, 4)
        print(f"NONE  no route path containing {word!r}; contexts: {ctx}")
        return "", ""

    def url_maps(js: str) -> dict[str, str]:
        urls: dict[str, str] = {}
        for ch in url_map_chunks(js)[:2]:
            urls.update(url_map(text(JS_DIR + ch) or ""))
        return urls

    path, comp = component("resultsnew")
    named: dict[str, list[str]] = {"std": [], "con": []}
    if comp:
        urls = url_maps(comp)
        calls = calls_in(comp, urls)
        fmt = date_format(comp)
        fields = {f for _, f in _HREF_FIELD.findall(comp)}
        prefixes = _PREFIX_FIELD.findall(comp)
        listed = json.dumps(calls, sort_keys=True)
        print(f"OK    component {path}: {len(comp)} chars, date format {fmt!r}, calls {listed}; "
              f"XBRL link fields {sorted(fields)}; folder + field {prefixes}")  # fmt: skip
        for ctx in _context(comp, r"Std XBRL|Con XBRL|xbrl|/w`|/w\?|\.url\.", 16):
            print(f"      ...{ctx!r}")
        ranked = sorted(calls, key=lambda n: (not re.search("result", n, re.I), not re.search("xbrl", n, re.I)))
        for name in ranked[:2]:  # the listing, for one recent window of all companies
            guard()
            params = fill_params(calls[name], "", date(2026, 11, 12), date(2026, 11, 14), fmt)
            try:
                body = c.get(f"{name}/w", params, "xbrl_listing", {"api": name, "route": path})
            except (Missing, BadRequest) as exc:
                print(f"SKIP  {name} {params}: {type(exc).__name__}: {exc}")
                continue
            vals = xbrl_values(body)
            links = answer_links(body, prefixes, fields)
            _show(f"{name} {params}", body, f"xbrl fields {vals[:6]}; links {links[:4]}; head {body[:300]!r}")
            for f, v in vals:
                named["con" if re.search(r"con", f, re.I) else "std"].append(urljoin(HOME, v))
            for link in links:
                named["con" if re.search(r"con", link, re.I) else "std"].append(link)
            if vals or links:
                break
    else:  # a legacy page, not the Angular shell: its own Std / Con links
        for link in viewer_links(html, page):
            if "xbrl" in link.lower():
                named["con" if re.search(r"con", link, re.I) else "std"].append(link)
    for kind, links in named.items():
        ok = False
        for link in list(dict.fromkeys(links))[:2]:
            if show_file(link, "results_xbrl", {"from": f"comp_resultsnew {kind} XBRL"}) is not None:
                ok = True
                break
        if not ok:
            print(f"NONE  comp_resultsnew {kind} XBRL: none of {len(links)} named files could be fetched")

    # (c) xbrldetails, category Annual Reports, one scrip
    path, comp = component("xbrldetail")
    if comp:
        urls = url_maps(comp)
        calls = calls_in(comp, urls)
        fmt = date_format(comp)
        cat, ctx = category_value(comp)
        print(f"OK    component {path}: {len(comp)} chars, date format {fmt!r}, Annual Report option {cat!r}, "
              f"calls {json.dumps(calls, sort_keys=True)}")  # fmt: skip
        for x in ctx + _context(comp, r"/w`|/w\?|\.url\.", 8):
            print(f"      ...{x!r}")

        def rank(n: str) -> tuple[bool, bool]:
            return not re.search("xbrl", n, re.I), not any(re.search("cat", k, re.I) for k in calls[n])

        ranked = sorted(calls, key=rank)
        for name in ranked[:1]:
            guard()
            params = fill_params(
                calls[name], codes[0], date(2025, 4, 1), date(2026, 11, 18), fmt, cat or "Annual Report"
            )
            try:
                body = c.get(f"{name}/w", params, "xbrl_listing", {"api": name, "route": path, "scrip": codes[0]})
            except (Missing, BadRequest) as exc:
                print(f"SKIP  {name} {params}: {type(exc).__name__}: {exc}")
                continue
            _show(f"{name} {params}", body, f"xbrl fields {xbrl_values(body)[:6]}; head {body[:400]!r}")
    print(f"{c.calls} calls made (budget {CALL_BUDGET})")


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
    ap.add_argument("--mode", choices=("reach", "xbrl", "xbrl2", "xbrl3", "xbrl4"), default="reach")
    ap.add_argument("--scrips", default="500488:A,505036:B,530745:T", help="--mode xbrl: CODE or CODE:GROUP list")
    ap.add_argument("--max-js", type=int, default=30)
    ap.add_argument("--max-endpoints", type=int, default=4)
    a = ap.parse_args(argv)
    led = Ledger(a.out)
    c = BseClient(ledger=led)
    if a.mode in ("xbrl", "xbrl2", "xbrl3", "xbrl4"):
        try:
            if a.mode == "xbrl":
                xbrl_probe(c, _scrips(a.scrips), a.max_js, a.max_endpoints)
            elif a.mode == "xbrl2":
                xbrl2_probe(c, _scrips(a.scrips), 6, a.max_endpoints)
            elif a.mode == "xbrl3":
                xbrl3_probe(c, _scrips(a.scrips), 6, max(a.max_endpoints, 8))
            else:
                xbrl4_probe(c, _scrips(a.scrips))
        except (Blocked, Failed, OverBudget) as exc:
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
