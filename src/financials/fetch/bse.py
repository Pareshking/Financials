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

`requests` and `selenium` are needed only here (`pip install -e ".[bse]"`), imported lazily.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

API = "https://api.bseindia.com/BseIndiaAPI/api/"
HOME = "https://www.bseindia.com/"
ATTACHMENT = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
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

    def _wait(self) -> None:
        if self.calls:
            self.sleep(self.rng.uniform(*self.pace))
        self.calls += 1

    def _fetch(self, url: str, params: dict) -> tuple[int, str, bytes]:
        if self.via == "in_page_xhr":
            return self.in_page.get(f"{url}?{urlencode(params)}" if params else url)
        r = self.session.get(url, params=params, timeout=45)
        return r.status_code, r.headers.get("Content-Type", ""), r.content

    def get(self, path: str, params: dict, dataset: str, covers: dict | None = None) -> bytes:
        return self.fetch_url(API + path, params, dataset, covers)

    def fetch_url(self, url: str, params: dict, dataset: str, covers: dict | None = None,
                  file: bool = False) -> bytes:  # fmt: skip
        """`file`: one filing's file (a 404 is Missing, not a refusal). The raw copy is written before return."""
        last = None
        errors = _net_errors()
        for _ in range(RETRIES + 1):
            self._wait()
            try:
                status, ctype, body = self._fetch(url, params)
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

    def close(self) -> None:
        if self.in_page is not None:
            self.in_page.close()


# ── import on the owner's machine: ledger -> vault + staging (the promoter promotes) ──

CATEGORY = {"announcements": "BSE_ANNOUNCEMENTS", "attachment": "BSE_ATTACHMENT",
            "shareholding_filings": "BSE_SHP_LISTING", "shareholding_xbrl": "BSE_SHP_XBRL",
            "list_securities": "BSE_LIST_SECURITIES"}  # fmt: skip


def _ext(rec: dict) -> tuple[str, str]:
    name = rec["url"].split("?", 1)[0].rsplit("/", 1)[-1].lower()
    ctype = (rec.get("content_type") or "").split(";")[0].strip().lower()
    if rec["dataset"] in ("announcements", "shareholding_filings", "list_securities") or "json" in ctype:
        return "json", "application/json"
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
    from financials.staging import stage_raw_only
    from financials.timeutil import utc_now

    led = Ledger(ledger_dir)
    staged, errors = [], []
    shp_broadcast = _shp_broadcast_times(led)
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
        staged.append(stage_raw_only(vault, stage_root, data=data, ext=ext, media_type=media,
                                     category=CATEGORY[rec["dataset"]], source_url=rec["url"], fetched_at=fetched,
                                     exchange="BSE"))  # fmt: skip
    return staged, errors


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
