"""BSE client, ported as-is from the owner's production collector (owner 2026-11-17: "I need exact same way our BSE
working"; source `Pareshking/NSE-BSE-Insider-Tracker`, `collectors/bse/client.py`, endpoints confirmed there with real
answers on 12-13 Oct 2026 [A17]). It runs on GitHub-hosted runners only: this container's IP is refused by BSE [A16].

Method (unchanged from the source):
- Plain HTTP first with BSE's own headers (`HEADERS`: the `bse` package's User-Agent, Accept, Origin and Referer
  https://www.bseindia.com, Sec-Fetch-Site same-site), 4-6 s between calls (`PACE_SECONDS`), 3 retries on network
  errors and 5xx, a hard stop on 401 / 403 / 429 (`Blocked`).
- If BSE refuses a plain request, the rest of the run goes through `InPage`: an XMLHttpRequest made from inside a
  bseindia.com page in headless Chrome (selenium), the way BSE's own pages call the API (`fetch` with credentials
  fails BSE's CORS rule; a plain XHR passes). Its raw copy is the page's response text in UTF-8, marked
  `via: in_page_xhr`.
- Every answer is stored byte for byte before it is read: here in a `Ledger` (blobs named by sha256 + one JSON line per
  fetch), which `import_ledger` vaults and stages on the owner's machine; the promoter (single writer) then promotes it.
  The runner never sees the database.

Endpoints (UNVERIFIED in this project until a run of `scripts/probe_bse_reach.py` returns them; the source repo's
fixtures are committed under tests/fixtures/bse/ [A17]):
- announcements `AnnSubCategoryGetData/w` (50 rows a page, newest first, Table1 ROWCNT); attachment at
  `www.bseindia.com/xml-data/corpfiling/AttachLive/<ATTACHMENTNAME>`;
- shareholding filings `Corp_Shareholding_ng/w?scripcode=&flag=&indtype=` (`flag` = period back from today), each row
  linking inline XBRL under `www.bseindia.com/XBRLFILES/SHPXBRLDataXML/`;
- list of securities `ListofScripData/w` (`bse` package `listSecurities`: per group, `SCRIP_CD`, `ISIN_NUMBER`,
  `Mktcap` in Rs crore), the scrip-code / ISIN map and BSE's own market cap.
- results XBRL [X247, X265, VERIFIED]: per scrip `Corp_FinanceResult_ng_new/w?SCRIP_CD=&FlagDur=&HFQ=&ISUBGROUP_CODE=
  &segment=C` (`FlagDur` 1 Today .. 6 Last 1 year, 7 Beyond last 1 year), rows with `quarter_code`, `Fld_CreateDate`
  (IST), `XMLName` (standalone) and `Consol_XMLName` (consolidated) under `www.bseindia.com/XBRLFILES/`: the
  Integrated Filing (Finance) as inline XBRL (`IFIndasDuplicateUploadDocument/..._IFIndAs.html`), the SEBI `in-capmkt`
  taxonomy of NSE's XML instances. `import_ledger` stages these `.html` files through `stage_results_xbrl`, the NSE
  path (`parse_instance` reads inline XBRL as the instance it denotes, parsers.ixbrl). NBFCs file plain XML instances
  instead (`IFNBFCDuplicateUploadDocument/Integrated_Finance_NBFC_<code>_<stamp>_IFNBFC.xml`), NSE's NBFC
  Integrated Filing XML byte for byte in form [X313]: they take the same path. A plain `.xml` of any other profile and
  annual XBRL (`annual_xbrl`, X241) stay raw only: no real file of either has been seen. The RSS feed
  `www.bseindia.com/Data/XML/FinancialResultsFeed.aspx` [X240, X242] is kept as a raw-only dataset.

`requests` and `selenium` are needed only here (`pip install -e ".[bse]"`), imported lazily.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

API = "https://api.bseindia.com/BseIndiaAPI/api/"
HOME = "https://www.bseindia.com/"
ATTACHMENT = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
RESULTS_FEED = "https://www.bseindia.com/Data/XML/FinancialResultsFeed.aspx"  # X240, UNVERIFIED
XBRL_FILES = "https://www.bseindia.com/XBRLFILES/"  # + a results row's XMLName / Consol_XMLName [X247, X265]
# X265: BSE results inline XBRL (`.html`, dataset results_xbrl) is parsed with the NSE results parser (fixtures
# tests/fixtures/bse/Integrated_Finance_Ind_As_*.html, tests/test_bse_results_ixbrl.py). Plain `.xml` copies and
# annual XBRL stay raw only (never seen), except the profiles below.
RESULTS_XBRL_VERIFIED = True
# X313: BSE's plain XML results instances of these profiles are NSE's Integrated Filing XML of the same taxonomy
# (IFNBFC V2.1, in-capmkt 2025-01-31 / 2026-01-31; fixtures tests/fixtures/bse/Integrated_Finance_NBFC_*_IFNBFC.xml,
# tests/test_x313_bse_nbfc_xml.py) and take the NSE path unchanged. Any other profile stays raw only until seen.
PLAIN_RESULTS_PROFILES = ("INDAS_NBFC",)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.5",
           "Origin": "https://www.bseindia.com", "Referer": HOME, "Connection": "keep-alive",
           "Sec-Fetch-Site": "same-site"}  # fmt: skip
PACE_SECONDS = (4.0, 6.0)
RETRIES = 3
STOP_STATUSES = (401, 403, 429)


class Blocked(RuntimeError):
    """BSE refused us (401/403/429) or sent something that is not data. Stop."""


class Failed(RuntimeError):
    """Still failing after the retries (network error or 5xx)."""


class Missing(Failed):
    """A filing's file answered 404: that file only, not a refusal."""


class BadRequest(RuntimeError):
    """HTTP 400: BSE rejected this call's parameters (probe run 2, A18). That call only, not a refusal: the run goes
    on (a deviation from the source client, which stops on any status other than 200 / 404 / 5xx)."""


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _net_errors() -> tuple[type[BaseException], ...]:
    try:
        import requests

        return (requests.RequestException, OSError)
    except ImportError:  # tests inject a session; a missing package fails at session creation instead
        return (OSError,)


class InPage:
    """api.bseindia.com called by an XHR from inside a bseindia.com page (as the source's InPage class)."""

    SCRIPT = ("const cb = arguments[arguments.length - 1]; const x = new XMLHttpRequest();"
              "x.open('GET', arguments[0]); x.timeout = 90000;"
              "x.onload = () => cb([x.status, x.getResponseHeader('content-type') || '', x.responseText]);"
              "x.onerror = x.ontimeout = () => cb([0, '', '']); x.send();")  # fmt: skip

    def __init__(self, driver_factory: Callable[[], Any] | None = None) -> None:
        self._factory = driver_factory or self._chrome
        self._driver = None

    @staticmethod
    def _chrome():
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        o = Options()
        for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-blink-features=AutomationControlled", f"--user-agent={UA}"):  # fmt: skip
            o.add_argument(a)
        d = webdriver.Chrome(options=o)
        d.set_script_timeout(120)
        return d

    def get(self, url: str) -> tuple[int, str, bytes]:
        if self._driver is None:
            self._driver = self._factory()
            self._driver.get(HOME)
        status, ctype, text = self._driver.execute_async_script(self.SCRIPT, url)
        return int(status or 0), ctype, (text or "").encode("utf-8")

    def close(self) -> None:
        if self._driver is not None:
            self._driver.quit()
            self._driver = None


class Ledger:
    """Raw store of one runner job: `blobs/<sha256>` (bytes as received) and `ledger.jsonl` (one line per fetch,
    written after its blob). This directory is the job's artifact and the import contract (`import_ledger`)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)

    def put(self, *, dataset: str, url: str, status: int, body: bytes, content_type: str, via: str,
            covers: dict | None = None, fetched_at: datetime | None = None) -> str:  # fmt: skip
        sha = hashlib.sha256(body).hexdigest()
        p = self.root / "blobs" / sha
        if not p.exists():
            p.write_bytes(body)
        rec = {"dataset": dataset, "url": url, "status": status, "sha256": sha, "bytes": len(body),
               "content_type": content_type or None, "via": via, "covers": covers or {},
               "fetched_at": (fetched_at or datetime.now().astimezone()).isoformat()}  # fmt: skip
        with (self.root / "ledger.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return sha

    def records(self) -> list[dict]:
        p = self.root / "ledger.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    def read(self, sha: str) -> bytes:
        data = (self.root / "blobs" / sha).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError(f"ledger blob {sha} does not match its sha256")
        return data


class BseClient:
    def __init__(self, session=None, sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None,
                 pace: tuple[float, float] = PACE_SECONDS, ledger: Ledger | None = None,
                 in_page: InPage | None = None, allow_in_page: bool = True) -> None:  # fmt: skip
        if session is None:
            import requests

            session = requests.Session()
        self.ledger = ledger
        self.session = session
        self.session.headers.update(HEADERS)
        self.sleep, self.rng, self.pace = sleep, rng or random.Random(), pace
        self.in_page, self.allow_in_page = in_page, allow_in_page
        self.via = "in_page_xhr" if in_page is not None else "requests"
        self.calls = 0
        self.last: dict = {}  # the last answer's final URL (after redirects) and redirect statuses

    def _wait(self) -> None:
        if self.calls:
            self.sleep(self.rng.uniform(*self.pace))
        self.calls += 1

    def _fetch(self, url: str, params: dict, form: dict | None = None,
               headers: dict | None = None) -> tuple[int, str, bytes]:  # fmt: skip
        if self.via == "in_page_xhr":
            if form is not None:
                raise Failed("a form postback is sent with plain requests only (in-page mode is GET only)")
            full = f"{url}?{urlencode(params)}" if params else url
            status, ctype, body = self.in_page.get(full)
            self.last = {"url": full, "redirects": [], "status": status, "content_type": ctype}
            return status, ctype, body
        if form is not None:  # a browser's form postback: the page's own fields, sent to the page's own URL
            r = self.session.post(url, data=form, timeout=45, headers=headers)
        else:
            r = self.session.get(url, params=params, timeout=45)
        ctype = r.headers.get("Content-Type", "")
        hops = [getattr(h, "status_code", 0) for h in getattr(r, "history", None) or []]
        self.last = {"url": str(getattr(r, "url", "") or url), "status": r.status_code, "content_type": ctype,
                     "redirects": hops}  # fmt: skip
        return r.status_code, ctype, r.content

    def get(self, path: str, params: dict, dataset: str, covers: dict | None = None) -> bytes:
        return self.fetch_url(API + path, params, dataset, covers)

    def fetch_url(self, url: str, params: dict, dataset: str, covers: dict | None = None,
                  file: bool = False, form: dict | None = None, headers: dict | None = None) -> bytes:  # fmt: skip
        """`file`: one filing's file (a 404 is Missing, not a refusal). `form`: POST these fields to `url` (an ASP.NET
        page's own postback, as a browser submits it; plain requests only). The raw copy is written before return;
        `self.last` holds the final URL after redirects. A redirect to BSE's `showinterest` page is a refusal
        (`Blocked`), never data."""
        last = None
        errors = _net_errors()
        for _ in range(RETRIES + 1):
            self._wait()
            try:
                status, ctype, body = self._fetch(url, params, form, headers)
            except errors as e:
                last = f"{type(e).__name__}: {e}"
                continue
            if status in STOP_STATUSES and self.via == "requests" and self.allow_in_page:
                # BSE refused a plain request: the rest of the run goes through the page.
                self.in_page = self.in_page or InPage()
                self.via = "in_page_xhr"
                try:
                    status, ctype, body = self._fetch(url, params)
                except Exception as e:  # no browser: report the refusal itself
                    raise Blocked(f"HTTP {status} from {url}; in-page fetch failed ({type(e).__name__}: {e})") from e
            if status in STOP_STATUSES:
                raise Blocked(f"HTTP {status} from {url} ({self.via})")
            if "showinterest" in self.last.get("url", "").lower():
                raise Blocked(f"redirected to {self.last['url']} from {url} ({self.via})")
            if status == 0 or status >= 500:
                last = f"HTTP {status} from {url} ({self.via})"
                continue
            if status == 404 and file:
                raise Missing(f"HTTP 404 from {url}")
            if status == 400:
                raise BadRequest(f"HTTP 400 from {url} ({self.via}) params {params}")
            if status != 200:
                raise Blocked(f"HTTP {status} from {url} ({self.via})")
            if self.ledger is not None:
                full = f"{url}?{urlencode(params)}" if params else url
                try:  # exact bytes first, before any parsing
                    self.ledger.put(dataset=dataset, url=full, status=status, body=body, content_type=ctype,
                                    via=self.via, covers=covers)  # fmt: skip
                except Exception as e:  # never continue without the raw copy
                    raise Failed(f"raw store write failed: {type(e).__name__}: {e}") from e
            return body
        raise Failed(f"{last} (after {RETRIES} retries)")

    def _payload(self, path: str, params: dict, dataset: str, covers: dict | None) -> Any:
        body = self.get(path, params, dataset, covers)
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except ValueError:
            raise Blocked(f"not JSON from {path} ({body[:60]!r})") from None

    def _rows(self, path: str, params: dict, dataset: str, covers: dict | None) -> list[dict]:
        payload = self._payload(path, params, dataset, covers)
        rows = payload.get("Table") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise Blocked(f"JSON without a row list from {path}")
        return rows

    # ── endpoints (parameters as in the source repo and the `bse` package) ──

    def announcements(self, a: date, b: date, page: int = 1, scrip: str = "", category: str = "-1"
                      ) -> tuple[list[dict], int | None]:  # fmt: skip
        """One page (50 rows, newest first) of the filings BSE disseminated in [a, b], and BSE's count (Table1
        ROWCNT). `scrip` narrows to one BSE scrip code (`strScrip`, as the `bse` package's announcements)."""
        payload = self._payload("AnnSubCategoryGetData/w",
                                {"pageno": page, "strCat": category, "strPrevDate": ymd(a), "strScrip": scrip,
                                 "strSearch": "P", "strToDate": ymd(b), "strType": "C", "subcategory": "-1"},
                                "announcements", {"from": a.isoformat(), "to": b.isoformat(), "page": page,
                                                  "scrip": scrip})  # fmt: skip
        rows = payload.get("Table") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise Blocked("JSON without a row list from AnnSubCategoryGetData")
        total = (payload.get("Table1") or [{}])[0].get("ROWCNT")
        return rows, int(total) if isinstance(total, int | float) else None

    def attachment(self, name: str, covers: dict | None = None) -> bytes:
        return self.fetch_url(ATTACHMENT + name, {}, "attachment", covers, file=True)

    def shareholding_filings(self, flag: int, scrip: str = "") -> list[dict]:
        return self._rows("Corp_Shareholding_ng/w", {"scripcode": scrip, "flag": str(flag), "indtype": ""},
                          "shareholding_filings", {"flag": flag, "scrip": scrip})  # fmt: skip

    def shareholding_xbrl(self, url: str, covers: dict | None = None) -> bytes:
        """One filing's inline XBRL, as sent."""
        if url.startswith("/"):
            url = HOME.rstrip("/") + url
        return self.fetch_url(url, {}, "shareholding_xbrl", covers, file=True)

    def list_securities(self, group: str, scrip: str = "") -> list[dict]:
        """`bse` package `listSecurities`: active equity securities of one BSE group (SCRIP_CD, ISIN_NUMBER, Mktcap)."""
        return self._rows("ListofScripData/w", {"scripcode": scrip, "Group": group, "industry": "",
                                                "segment": "Equity", "status": "Active"},
                          "list_securities", {"group": group, "scrip": scrip})  # fmt: skip

    def finance_results(self, scrip: str, flag_dur: int, segment: str = "C") -> list[dict]:
        """BSE's results listing of one scrip (comp_resultsnew page) [X247, X265]: `flag_dur` 6 = last 1 year,
        7 = beyond last 1 year (`Corp_GetFINANCE_DRDOWN_ng` flag 1); `segment` C = Equity."""
        return self._rows("Corp_FinanceResult_ng_new/w",
                          {"SCRIP_CD": scrip, "FlagDur": str(flag_dur), "HFQ": "", "ISUBGROUP_CODE": "",
                           "segment": segment},
                          "xbrl_listing", {"api": "Corp_FinanceResult_ng_new", "scrip": scrip,
                                           "flag_dur": flag_dur})  # fmt: skip

    def results_feed(self) -> bytes:
        """BSE's financial results RSS feed, as sent [X240, UNVERIFIED]."""
        return self.fetch_url(RESULTS_FEED, {}, "results_feed", {}, file=True)

    def xbrl_file(self, url: str, dataset: str, covers: dict | None = None) -> bytes:
        """One results (`results_xbrl`) or annual (`annual_xbrl`) XBRL file under www.bseindia.com, as sent."""
        if dataset not in ("results_xbrl", "annual_xbrl"):
            raise ValueError(f"not an XBRL dataset: {dataset}")
        if url.startswith("/"):
            url = HOME.rstrip("/") + url
        return self.fetch_url(url, {}, dataset, covers, file=True)

    def close(self) -> None:
        if self.in_page is not None:
            self.in_page.close()


# ── import on the owner's machine: ledger -> vault + staging (the promoter promotes) ──

CATEGORY = {"announcements": "BSE_ANNOUNCEMENTS", "attachment": "BSE_ATTACHMENT",
            "shareholding_filings": "BSE_SHP_LISTING", "shareholding_xbrl": "BSE_SHP_XBRL",
            "list_securities": "BSE_LIST_SECURITIES", "results_feed": "BSE_RESULTS_FEED",
            "xbrl_listing": "BSE_XBRL_LISTING", "results_xbrl": "BSE_RESULTS_XBRL",
            "annual_xbrl": "BSE_ANNUAL_XBRL"}  # fmt: skip  # raw only but results .html (X265) and NBFC .xml (X313)


def _ext(rec: dict) -> tuple[str, str]:
    name = rec["url"].split("?", 1)[0].rsplit("/", 1)[-1].lower()
    ctype = (rec.get("content_type") or "").split(";")[0].strip().lower()
    if (
        rec["dataset"] in ("announcements", "shareholding_filings", "list_securities", "xbrl_listing")
        or "json" in ctype
    ):
        return "json", "application/json"
    if rec["dataset"] == "results_feed":
        return "xml", "application/rss+xml"
    for ext, media in (("pdf", "application/pdf"), ("xml", "application/xml"), ("html", "text/html"),
                       ("zip", "application/zip"), ("csv", "text/csv")):  # fmt: skip
        if name.endswith("." + ext):
            return ext, media
    return "bin", ctype or "application/octet-stream"


def import_ledger(vault, stage_root: Path, ledger_dir: Path) -> tuple[list[Path], list[str]]:
    """Vault every 200 answer of a runner's ledger as a BSE filing (exchange BSE, the URL as asked, fetched_at as
    recorded) and stage it: the list of securities is parsed (raw_bse_securities, rule BSE1 [X169]); everything else
    raw only, until a parser is proven on a real file of that kind [A17]. Each blob's sha256 is checked against the
    ledger; a re-import adds nothing (idempotent ids)."""
    from financials.parsers.ixbrl import is_inline
    from financials.staging import stage_raw_only
    from financials.timeutil import utc_now

    led = Ledger(ledger_dir)
    staged, errors = [], []
    shp_broadcast = _shp_broadcast_times(led)
    results_broadcast = _results_broadcast_times(led)
    for rec in led.records():
        if rec["status"] != 200 or rec["dataset"] not in CATEGORY:
            continue
        try:
            data = led.read(rec["sha256"])
        except (OSError, ValueError) as exc:
            errors.append(f"{rec['url']}: {exc}")
            continue
        ext, media = _ext(rec)
        fetched = datetime.fromisoformat(rec["fetched_at"]) if rec.get("fetched_at") else utc_now()
        if fetched.tzinfo is not None:  # timestamps are naive UTC in the database (invariant 11)
            from datetime import UTC

            fetched = fetched.astimezone(UTC).replace(tzinfo=None)
        if rec["dataset"] == "list_securities":  # parsed: the ISIN -> scrip code map of rule BSE1 [X169]
            from financials.parsers import ParseError
            from financials.staging import stage_bse_securities

            try:
                staged.append(stage_bse_securities(vault, stage_root, data=data, source_url=rec["url"],
                                                   fetched_at=fetched))  # fmt: skip
            except ParseError as exc:
                errors.append(f"{rec['url']}: {exc}")
            continue
        if rec["dataset"] == "shareholding_xbrl":  # parsed: inline XBRL -> the shareholding tables [X170]
            from financials.staging import stage_shareholding

            ts = shp_broadcast.get(rec["url"].split("?", 1)[0])
            staged.append(stage_shareholding(vault, stage_root, data=data, source_url=rec["url"], fetched_at=fetched,
                                             broadcast_ts=ts, broadcast_ts_source="API_FIELD" if ts else "UNKNOWN",
                                             exchange="BSE"))  # fmt: skip
            continue
        if (
            rec["dataset"] == "results_xbrl"
            and RESULTS_XBRL_VERIFIED
            and (is_inline(data) or plain_results_profile(data) in PLAIN_RESULTS_PROFILES)
        ):
            # X265: BSE's inline XBRL of the SEBI in-capmkt results taxonomy takes the NSE path unchanged
            # (parse_instance reads it as the instance it denotes; parse_integrated_results dispatches on the profile).
            # X313: so does a plain XML instance of a profile seen in that form (NBFC).
            from financials.staging import stage_results_xbrl

            ts = results_broadcast.get(rec["url"].split("?", 1)[0])
            staged.append(stage_results_xbrl(vault, stage_root, data=data, source_url=rec["url"], fetched_at=fetched,
                                             broadcast_ts=ts, broadcast_ts_source="API_CREATION" if ts else "UNKNOWN",
                                             exchange="BSE"))  # fmt: skip
            continue
        staged.append(stage_raw_only(vault, stage_root, data=data, ext=ext, media_type=media,
                                     category=CATEGORY[rec["dataset"]], source_url=rec["url"], fetched_at=fetched,
                                     exchange="BSE"))  # fmt: skip
    return staged, errors


def plain_results_profile(data: bytes) -> str | None:
    """Accounting profile of a plain (not inline) XBRL instance from its entity namespace [X313], None for inline
    XBRL, anything that does not read as an XBRL instance, or an unknown namespace."""
    from financials.parsers import ParseError
    from financials.parsers.indas_corp import detect_profile
    from financials.parsers.ixbrl import is_inline
    from financials.parsers.xbrl import parse_instance

    if is_inline(data):
        return None
    try:
        return detect_profile(parse_instance(data).entity_namespace)
    except ParseError:
        return None


_QUARTER_CODE = re.compile(r"^([JSDM])([QHNC])(\d{4})-(\d{4})$")
_MONTH_END = {"J": (6, 30), "S": (9, 30), "D": (12, 31), "M": (3, 31)}


def quarter_period_end(code: str | None) -> date | None:
    """Period end of a BSE results row's `quarter_code` [X265]: month letter J / S / D / M (June, September, December
    of the first year; March of the second) + Q quarter / H half year / N nine months / C cumulative (year), then the
    financial year: `SQ2026-2027` -> 2026-09-30, `MC2025-2026` -> 2026-03-31. Anything else -> None."""
    m = _QUARTER_CODE.match((code or "").strip())
    if not m or int(m[4]) != int(m[3]) + 1:
        return None
    month, day = _MONTH_END[m[1]]
    return date(int(m[4]) if m[1] == "M" else int(m[3]), month, day)


def results_files(rows: list[dict], min_period_end: date) -> tuple[list[tuple[str, dict]], int]:
    """(file URL, covers) of every distinct `XMLName` / `Consol_XMLName` in a scrip's results rows whose quarter ends
    on or after `min_period_end` (a row with an unreadable `quarter_code` is kept: the promoter's scope gate decides),
    and the number of rows skipped as earlier. One file serves several rows (quarter + half year, quarter + year)."""
    out: dict[str, dict] = {}
    skipped = 0
    for r in rows:
        end = quarter_period_end(r.get("quarter_code"))
        if end is not None and end < min_period_end:
            skipped += 1
            continue
        for field, scope in (("XMLName", "standalone"), ("Consol_XMLName", "consolidated")):
            name = (r.get(field) or "").strip()
            if name:
                out.setdefault(XBRL_FILES + name.lstrip("/"),
                               {"scrip": str(r.get("Scrip_cd", "")), "quarter_code": r.get("quarter_code"),
                                "field": field, "scope": scope})  # fmt: skip
    return list(out.items()), skipped


def created_since(rows: list[dict], since: date | None, field: str = "Fld_CreateDate") -> tuple[list[dict], int]:
    """X353 BSE_SINCE_WINDOW: the rows whose `field` (IST: a results row's `Fld_CreateDate` [X265], a shareholding
    row's `D` [A18]) falls on or after `since`, and how many were left out. A row whose time does not read is kept;
    `since` None keeps every row."""
    if since is None:
        return rows, 0
    kept = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(str(r.get(field) or ""))
        except ValueError:
            kept.append(r)
            continue
        if ts.date() >= since:
            kept.append(r)
    return kept, len(rows) - len(kept)


_FILE_STAMP = re.compile(r"_(\d{11,16})_(?:IFIndAs\.html|IFNBFC\.xml)$", re.IGNORECASE)


def file_stamps(url: str) -> list[datetime]:
    """Every IST time a BSE results file name `..._<D><M><YYYY><H><MM><SS>_IFIndAs.html` (or `_IFNBFC.xml`, X313) can
    encode: the parts are not zero-padded (X240), so `511202619052` reads as 5-11-2026 19:05:02 or 19:00:52 (its row's
    Fld_CreateDate is 19:00:52.8). Only valid dates and times, years 20xx."""
    m = _FILE_STAMP.search(url.split("?", 1)[0])
    if not m:
        return []
    s, out = m[1], set()
    for d in (1, 2):
        for mo in (1, 2):
            year, rest = s[d + mo : d + mo + 4], s[d + mo + 4 :]
            if not year.startswith("20"):
                continue
            for h in (1, 2):
                for mi in (1, 2):
                    if len(rest) - h - mi not in (1, 2):
                        continue
                    try:
                        out.add(datetime(int(year), int(s[d : d + mo]), int(s[:d]), int(rest[:h]),
                                         int(rest[h : h + mi]), int(rest[h + mi :])))  # fmt: skip
                    except ValueError:
                        continue
    return sorted(out)


def _results_broadcast_times(led: Ledger) -> dict[str, datetime]:
    """Results file URL -> the earliest time it is taken as public (UTC) [X265]: the latest of its listing rows'
    `Fld_CreateDate` (IST, the XBRL row's creation, minutes after the announcement: 500488 Q2 FY27 announced 18:55:13,
    Fld_CreateDate 19:00:52.8) and every same-day time its file name can encode, since a consolidated file can be
    named after its row's Fld_CreateDate (544111: 13:33:42 against 13:33:28.4). Later, never earlier."""
    from financials.timeutil import ist_to_utc

    created: dict[str, datetime] = {}
    for rec in led.records():
        if rec["dataset"] != "xbrl_listing" or rec["status"] != 200 or "Corp_FinanceResult_ng_new" not in rec["url"]:
            continue
        try:
            rows = json.loads(led.read(rec["sha256"]).decode("utf-8")).get("Table") or []
        except (OSError, ValueError, AttributeError):
            continue
        for r in rows:
            try:
                ts = datetime.fromisoformat(str(r.get("Fld_CreateDate") or ""))
            except ValueError:
                continue
            for field in ("XMLName", "Consol_XMLName"):
                name = (r.get(field) or "").strip()
                if name:
                    url = XBRL_FILES + name.lstrip("/")
                    created[url] = max(created.get(url, ts), ts)
    out = {}
    for url, ts in created.items():
        ist = max([ts, *(t for t in file_stamps(url) if t.date() == ts.date())])
        out[url] = ist_to_utc(ist.date(), ist.time())
    return out


def _shp_broadcast_times(led: Ledger) -> dict[str, datetime]:
    """XBRL file URL -> broadcast time (UTC) from the shareholding filings answers in the same ledger: `D` is the
    broadcast time in IST to the minute (`broadcastTime` "Oct 14 2026  4:19PM" = `D` 2026-10-14T16:19:00, A18)."""
    from financials.timeutil import ist_to_utc

    out: dict[str, datetime] = {}
    for rec in led.records():
        if rec["dataset"] != "shareholding_filings" or rec["status"] != 200:
            continue
        try:
            rows = json.loads(led.read(rec["sha256"]).decode("utf-8")).get("Table") or []
        except (OSError, ValueError, AttributeError):
            continue
        for r in rows:
            path, d = r.get("XBRLAttachment"), r.get("D")
            if path and d:
                ts = datetime.fromisoformat(d)
                out[HOME.rstrip("/") + path] = ist_to_utc(ts.date(), ts.time())
    return out
