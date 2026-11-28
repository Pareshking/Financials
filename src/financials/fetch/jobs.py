"""Fetch jobs: download → vault → staging. Each returns the stage directories it wrote.

URLs below are the ones verified in docs/references.md (P1, P10, A6, A7, P12, CAL1, SHP6, X130).

Never re-download a vaulted blob (CLAUDE.md): every fetch is recorded in the vault's URL index; an archive file
(bhavcopy, delivery, filing XBRL) that is already vaulted is read back from the vault, and a 404 that was observed
at least two days after the date it was asked for is not asked again. Listings, RSS and API answers change, so
they are always fetched afresh.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from financials.fetch.http import FetchError, PoliteFetcher
from financials.parsers import ParseError
from financials.parsers.discovery import listing_progress, parse_integrated_filing_listing, symbols_with_results_today
from financials.parsers.reg30_events import parse_announcements_rss
from financials.parsers.reg34_annual import parse_annual_listing
from financials.parsers.shareholding import parse_shp_master
from financials.scope import MIN_PERIOD_END_DATE
from financials.staging import (
    read_manifest,
    stage_classification,
    stage_corp_actions,
    stage_equity_master,
    stage_holidays,
    stage_index_closes,
    stage_index_snapshot,
    stage_market_day,
    stage_mcap_day,
    stage_raw_only,
    stage_reg30_event,
    stage_results_listing,
    stage_results_xbrl,
    stage_shareholding,
)
from financials.timeutil import ist_to_utc, utc_now
from financials.vault import Vault

ARCHIVE = "https://nsearchives.nseindia.com"
# NSE moved its site to nseindia.in (A19, nse-reach run 44357423381, 2026-11-18): www.nseindia.com answers 301 to the
# same path on www.nseindia.in, API included; calling .in directly avoids the redirect and keeps cookies on one host.
API = "https://www.nseindia.in/api"
JSON = "application/json"
WARMUP = {"www.nseindia.in": "https://www.nseindia.in/"}  # session cookies for the API host [A1]
CORP_ACTION_CHUNK_DAYS = 30  # the API answer was verified on a one-month window [P12]
# X365: annual report PDFs, kept at the URL the listing gives (the .in host; the .com alias is UNVERIFIED for them)
ANNUAL_REPORTS_ARCHIVE = "https://nsearchives.nseindia.in/annual_reports/"
IMMUTABLE_PREFIXES = (f"{ARCHIVE}/content/cm/BhavCopy_", f"{ARCHIVE}/products/content/sec_bhavdata_full_",
                      f"{ARCHIVE}/corporate/xbrl/", f"{ARCHIVE}/content/indices/ind_close_all_",
                      f"{ARCHIVE}/archives/equities/bhavcopy/pr/", ANNUAL_REPORTS_ARCHIVE)  # fmt: skip
ANNUAL_REPORT_MEDIA = {"pdf": "application/pdf", "zip": "application/zip"}
EQUITY_MASTER_URL = f"{ARCHIVE}/content/equities/EQUITY_L.csv"  # [IDX10]
NOT_FOUND_SETTLE_DAYS = 2  # a 404 counts as final only when observed this long after the requested date [P11]


def bhavcopy_url(d: date) -> str:
    return f"{ARCHIVE}/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def delivery_url(d: date) -> str:
    return f"{ARCHIVE}/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"


def index_close_url(d: date) -> str:
    return f"{ARCHIVE}/content/indices/ind_close_all_{d:%d%m%Y}.csv"  # [IDX9]


def pr_zip_url(d: date) -> str:
    """NSE's daily PRddmmyy.zip; its mcapddmmyyyy.csv is the market-cap file [X130]."""
    return f"{ARCHIVE}/archives/equities/bhavcopy/pr/PR{d:%d%m%y}.zip"


def corp_actions_url(start: date, end: date) -> str:
    return f"{API}/corporates-corporateActions?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"


def holidays_url() -> str:
    return f"{API}/holiday-master?type=trading"


def index_list_url(file_stub: str = "nifty500") -> str:
    return f"{ARCHIVE}/content/indices/ind_{file_stub}list.csv"


def _sym(symbol: str) -> str:
    """URL-encode an NSE symbol: "M&M", "J&KBANK", "ARE&M" otherwise split the query string at "&" and the API
    answers for symbol "M" (M&M, M&M Financial, Amara Raja, GE Vernova T&D and J&K Bank had no results, 2026-11-15)."""
    return quote(symbol, safe="")


def results_listing_url(symbol: str, page: int = 1) -> str:
    """Newest 20 rows; `page=N` gives rows 20(N-1)+1.. (A7: TCS page 2 = rows 21-22 of totalCount 22)."""
    base = f"{API}/integrated-filing-results?index=equities&symbol={_sym(symbol)}"
    return base if page == 1 else f"{base}&page={page}"


ANNOUNCEMENTS_RSS = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
# XBRL file-name prefixes of the parsed Reg. 30 families [E2]
EVENT_PREFIXES = (
    "REG30_PARA_B_",
    "CIM_",
    "ALTERATION_OF_CAPITAL_AND_FUND_RAISING_",
    "ANN_FRAUD_",
    "AIATOP_",
    "REG30_Restructuring_",
)  # X360
RSS_ATTEMPTS = 3  # X350: a cut-short announcements RSS is asked again (3 answers in all)
RSS_RETRY_WAIT = 10.0  # seconds before asking again (on top of the host's spacing)


def annual_listing_url(symbol: str) -> str:
    return f"{API}/annual-reports-xbrl?index=equities&symbol={_sym(symbol)}"


def annual_report_listing_url(symbol: str) -> str:
    """X365: the annual report PDFs of one symbol [A8]."""
    return f"{API}/annual-reports?index=equities&symbol={_sym(symbol)}"


def quote_url(symbol: str, series: str = "EQ") -> str:
    """NSE quote answer carrying the 4-level industry classification in `secInfo` [IC1]. `/api/quote-equity`
    answered 403 from the container on 2026-11-15; this endpoint answered 200 (A1-style, no warm-up needed)."""
    return (f"{API}/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series={quote(series)}"
            f"&symbol={_sym(symbol)}")  # fmt: skip


def shp_master_url(symbol: str) -> str:
    return f"{API}/corporate-share-holdings-master?index=equities&symbol={_sym(symbol)}"


def chunks(start: date, end: date, days: int = CORP_ACTION_CHUNK_DAYS) -> list[tuple[date, date]]:
    out, d = [], start
    while d <= end:
        e = min(d + timedelta(days=days - 1), end)
        out.append((d, e))
        d = e + timedelta(days=1)
    return out


class Jobs:
    def __init__(self, fetcher: PoliteFetcher, vault: Vault, stage_root: Path) -> None:
        self.f, self.vault, self.stage_root = fetcher, vault, Path(stage_root)
        self.warnings: list[str] = []
        self.errors: list[str] = []  # per-file failures inside a listing (the rest of the listing goes on)
        self.shp_min_as_of: date | None = None  # discovery: shareholding quarters from this date (None = latest)
        self.workers = 1  # fetch-days threads (useful only with a host limit above one connection)
        self.record_responses = False  # runner hand-back: also note listing / API answers (fetch.replay)
        self.since: date | None = None  # X346: discovery fetches only filings broadcast on or after this date

    def _has_listing_page(self, url: str) -> bool:
        """A later listing page may be asked for (live: always; a runner replay overrides it)."""
        return True

    def _before_since(self, ts) -> bool:
        """X346: a listed filing broadcast before `since` is skipped (no download). Unknown time: never skipped."""
        return self.since is not None and ts is not None and ts.date() < self.since

    def _file(self, url: str) -> bytes | None:
        try:
            return self._get(url)
        except FetchError as exc:
            self.errors.append(f"{url.rsplit('/', 1)[-1]}: {exc}")
            return None

    # ── fetch with the vault's URL index ──

    def _ext(self, url: str) -> str:
        name = url.rsplit("/", 1)[-1]
        return "csv.zip" if name.endswith(".csv.zip") else name.rsplit(".", 1)[-1] if "." in name else "bin"

    def _get(
        self, url: str, *, accept: str = "*/*", allow_404: bool = False, asked_for: date | None = None,
        refetch: bool = False,
    ):  # fmt: skip
        """Bytes, or None for an allowed 404. Archive files already vaulted are not downloaded again, except on an
        explicit `refetch` (rule X322, `fetch-results URL --refetch`): the archive served a file that was empty or cut
        short when it was first fetched. The old blob and its ledger line stay; the new answer is ledgered after it,
        and different bytes are a new blob and so a new filing (invariant 2)."""
        immutable = url.startswith(IMMUTABLE_PREFIXES)
        last = self.vault.last_fetch(url) if immutable and not refetch else None
        if refetch and immutable and self.vault.last_fetch(url):
            self.warnings.append(f"refetch (X322): {url} downloaded again on request; the vaulted blob is kept")
        if last and last["status"] == 200 and self.vault.exists(last["storage_path"]):
            return self.vault.read_path(last["storage_path"], last["sha256"])
        if last and last["status"] == 404 and allow_404 and asked_for is not None:
            seen = datetime.fromisoformat(last["fetched_at"]).date()
            if seen >= asked_for + timedelta(days=NOT_FOUND_SETTLE_DAYS):
                return None
        data = self.f.get(url, accept=accept, allow_404=allow_404)
        if immutable:
            if data is not None:  # the blob is in the vault before the ledger says so (a killed run leaves no lie)
                self.vault.put(data, ext=self._ext(url), media_type="application/octet-stream", fetched_at=utc_now())
            self.vault.record_fetch(url, 404 if data is None else 200, utc_now(), data, self._ext(url))
        elif self.record_responses and data is not None:
            from financials.fetch.replay import record_response

            record_response(self.vault, url, data, "json" if accept == JSON else self._ext(url), utc_now())
        return data

    def is_done(self, url: str, job: str) -> bool:
        """Vaulted and staged. A file vaulted whose staging failed (e.g. a parser fixed since) is staged again from the
        vault, never downloaded again."""
        last = self.vault.last_fetch(url)
        if not (last and last["status"] == 200 and self.vault.exists(last["storage_path"])):
            return False
        from financials.ids import stable_id

        fid = stable_id("fil", "NSE", url, last["sha256"])
        if (self.stage_root / job / fid).exists():
            return True
        return fid in self._promoted_ids()  # X345: promoted filings whose staging directory is gone

    def _promoted_ids(self) -> frozenset[str]:
        if getattr(self, "_promoted", None) is None:
            from financials import promoted_ledger

            self._promoted = promoted_ledger.read(self.stage_root)
        return self._promoted

    def _promoted_answer(self, url: str, data: bytes) -> bool:
        """X349 PROMOTED_ANSWER_SKIP: a listing / master / RSS answer byte-identical to one already promoted (same
        URL and sha256, so the same filing id) is not staged again; it is still read. import-vault re-staged every
        listing of a runner vault each time (2,143 listings of one 8-runner sweep)."""
        import hashlib

        from financials.ids import stable_id

        return stable_id("fil", "NSE", url, hashlib.sha256(data).hexdigest()) in self._promoted_ids()

    def is_vaulted(self, url: str) -> bool:
        last = self.vault.last_fetch(url)
        return bool(last and last["status"] == 200 and self.vault.exists(last["storage_path"]))

    # ── market data ──

    def market_day(self, d: date) -> list[Path] | None:
        """None when no bhavcopy exists (holiday/weekend): nothing is staged. A bhavcopy staged without delivery
        is staged again once the delivery file appears [P0-2]; a fully fetched day is not fetched again."""
        b_url, d_url = bhavcopy_url(d), delivery_url(d)
        closes = self._index_closes(d) + self.mcap_day(d) if self.is_vaulted(b_url) else []
        if self.is_vaulted(b_url) and self.is_vaulted(d_url):
            return closes
        bhav = self._get(b_url, allow_404=True, asked_for=d)
        if bhav is None:
            return None
        if not closes:
            closes = self._index_closes(d) + self.mcap_day(d)
        deliv = self._get(d_url, allow_404=True, asked_for=d)
        stage = stage_market_day(
            self.vault, self.stage_root, bhavcopy=bhav, bhavcopy_url=b_url, delivery=deliv,
            delivery_url=d_url if deliv is not None else None, fetched_at=utc_now(),
        )  # fmt: skip
        traded = read_manifest(stage)["trade_date"]
        if traded != d.isoformat():
            # NSE can answer a non-trading date with another day's file; the batch is filed under its own TradDt.
            self.warnings.append(f"{d}: file holds TradDt {traded}; staged under {traded}")
        return [stage, *closes]

    def _index_closes(self, d: date) -> list[Path]:
        """The day's ind_close_all [IDX9], fetched only for a date with a bhavcopy; vaulted files are not refetched."""
        url = index_close_url(d)
        if self.is_vaulted(url):
            return []
        data = self._get(url, allow_404=True, asked_for=d)
        if data is None:
            return []
        return [stage_index_closes(self.vault, self.stage_root, data=data, source_url=url, fetched_at=utc_now())]

    def mcap_day(self, d: date) -> list[Path]:
        """The day's PRddmmyy.zip mcap file [X130], for a date with a bhavcopy. A vaulted zip is not downloaded again;
        one vaulted but not staged (a parse failure since fixed) is staged again from the vault."""
        url = pr_zip_url(d)
        last = self.vault.last_fetch(url)
        vaulted = bool(last and last["status"] == 200 and self.vault.exists(last["storage_path"]))
        if vaulted and any((self.stage_root / "mcap_day").glob(f"*-{last['sha256'][:12]}")):
            return []
        data = self._get(url, allow_404=True, asked_for=d)
        if data is None:
            return []
        return [stage_mcap_day(self.vault, self.stage_root, data=data, source_url=url, fetched_at=utc_now())]

    def mcap_days(self, days: Iterable[date]) -> tuple[list[Path], list[str]]:
        """fetch-mcap: the PR zips of the given trading days (e.g. the week ends of a backfill); a failure on one
        day is reported and the rest continues."""
        staged, errors = [], []
        for d in days:
            try:
                staged += self.mcap_day(d)
            except (FetchError, ParseError) as exc:
                errors.append(f"{d} mcap: {exc}")
        return staged, errors

    def equity_master(self) -> list[Path]:
        data = self._get(EQUITY_MASTER_URL)
        return [stage_equity_master(self.vault, self.stage_root, data=data, source_url=EQUITY_MASTER_URL,
                                    fetched_at=utc_now())]  # fmt: skip

    def market_days(self, start: date, end: date) -> tuple[list[Path], list[str]]:
        """Every date in [start, end] (weekends included: special sessions exist, e.g. Saturday 1 Feb 2025 [CAL2]).
        A failure on one day is reported and the range continues; re-running resumes where it failed."""
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

        def one(d: date) -> tuple[list[Path], list[str]]:
            try:
                return self.market_day(d) or [], []
            except (FetchError, ParseError) as exc:
                return [], [f"{d}: {exc}"]

        if self.workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                results = list(pool.map(one, days))
        else:
            results = [one(d) for d in days]
        staged = [p for got, _ in results for p in got]
        return staged, [e for _, errs in results for e in errs]

    def corp_actions(self, start: date, end: date) -> list[Path]:
        """One request per 30-day window [P12]; each answer is its own vaulted, staged batch."""
        out = []
        for a, b in chunks(start, end):
            url = corp_actions_url(a, b)
            data = self._get(url, accept=JSON)
            out.append(stage_corp_actions(self.vault, self.stage_root, data=data, source_url=url, fetched_at=utc_now()))
        return out

    def holidays(self) -> list[Path]:
        data = self._get(holidays_url(), accept=JSON)
        return [stage_holidays(self.vault, self.stage_root, data=data, source_url=holidays_url(), fetched_at=utc_now())]

    def index_snapshot(self, snapshot_date: date, index_name: str = "NIFTY 500", file_stub: str = "nifty500"):
        url = index_list_url(file_stub)
        data = self._get(url)
        return [
            stage_index_snapshot(self.vault, self.stage_root, data=data, source_url=url, index_name=index_name,
                                 snapshot_date=snapshot_date, fetched_at=utc_now())
        ]  # fmt: skip

    def classification(
        self, symbols: Iterable[str], series: dict[str, str] | None = None
    ) -> tuple[list[Path], list[str]]:
        """fetch-classification: one quote answer per symbol (API host, 1 request/s), vaulted and staged [IC1].
        Answers change daily (prices), so they are always fetched; a failure on one symbol is reported and the rest
        continues."""
        staged, errors = [], []
        for sym in symbols:
            url = quote_url(sym, (series or {}).get(sym, "EQ"))
            try:
                data = self._get(url, accept=JSON)
                staged.append(stage_classification(self.vault, self.stage_root, data=data, source_url=url,
                                                   fetched_at=utc_now()))  # fmt: skip
            except (FetchError, ParseError) as exc:
                errors.append(f"{sym} classification: {exc}")
        return staged, errors

    # ── filings ──

    def shareholding(self, symbol: str, *, latest_only: bool = True, min_as_of: date | None = None) -> list[Path]:
        """Master JSON gives each filing's XBRL URL and broadcast time [SHP6]. `min_as_of` keeps the quarters from
        that date on (2024-12-31 gives the first in-scope quarter, 2025-03-31, its QoQ comparison)."""
        url = shp_master_url(symbol)
        master = self._get(url, accept=JSON)
        out = [] if self._promoted_answer(url, master) else [
            stage_raw_only(self.vault, self.stage_root, data=master, ext="json", media_type=JSON,
                           category="SHP_MASTER", source_url=url, fetched_at=utc_now())]  # fmt: skip
        entries = parse_shp_master(master)
        if min_as_of is not None:
            entries = [e for e in entries if e.as_of_date >= min_as_of]
        elif latest_only:
            entries = entries[:1]
        for e in entries:
            if self._before_since(e.broadcast_ts_ist):
                continue
            if self.is_done(e.xbrl_url, "shareholding") or (xbrl := self._file(e.xbrl_url)) is None:
                continue
            out.append(
                stage_shareholding(
                    self.vault, self.stage_root, data=xbrl, source_url=e.xbrl_url, fetched_at=utc_now(),
                    broadcast_ts=e.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None),
                    broadcast_ts_source="API_FIELD",
                )
            )  # fmt: skip
        return out

    def annual_reports(self, symbol: str, *, min_to_year: int = 2025) -> list[Path]:
        """Reg. 34 annual XBRL [A8, X69]: listing JSON (vaulted) gives each file's URL and broadcast time.
        Only fiscal years ending in or after `min_to_year` are downloaded (C9); one file per request."""
        url = annual_listing_url(symbol)
        listing = self._get(url, accept=JSON)
        out = [] if self._promoted_answer(url, listing) else [
            stage_raw_only(self.vault, self.stage_root, data=listing, ext="json", media_type=JSON,
                           category="ANNUAL_LISTING", source_url=url, fetched_at=utc_now())]  # fmt: skip
        for e in parse_annual_listing(listing):
            if e.to_year < min_to_year or self._before_since(e.broadcast_ts_ist):
                continue
            if self.is_done(e.xbrl_url, "results_xbrl"):
                continue
            if (xbrl := self._file(e.xbrl_url)) is None:
                continue
            out.append(
                stage_results_xbrl(
                    self.vault, self.stage_root, data=xbrl, source_url=e.xbrl_url, fetched_at=utc_now(),
                    broadcast_ts=e.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None),
                    broadcast_ts_source="API_FIELD",
                )
            )  # fmt: skip
        return out

    def annual_report_pdfs(self, symbol: str, *, min_to_year: int = 2025) -> list[Path]:
        """X365 `fetch-annual-reports`: the `annual-reports` listing [A8] (vaulted, category
        ANNUAL_REPORT_PDF_LISTING), then every listed file of a fiscal year ending in or after `min_to_year` (C9),
        vaulted and staged raw only (category ANNUAL_REPORT_PDF, the listed broadcast time, the asked symbol). Nothing
        is parsed into canonical tables. A vaulted file is never downloaded again; one request at a time."""
        from financials.parsers.annual_report_pdf import parse_annual_report_listing

        url = annual_report_listing_url(symbol)
        listing = self._get(url, accept=JSON)
        entries = parse_annual_report_listing(listing)  # before vaulting: an answer that is not a listing is not kept
        out = [] if self._promoted_answer(url, listing) else [
            stage_raw_only(self.vault, self.stage_root, data=listing, ext="json", media_type=JSON,
                           category="ANNUAL_REPORT_PDF_LISTING", source_url=url, fetched_at=utc_now())]  # fmt: skip
        for e in entries:
            if e.to_year < min_to_year or self._before_since(e.broadcast_ts_ist):
                continue
            if self.is_done(e.file_url, "raw_only") or (data := self._file(e.file_url)) is None:
                continue
            out.append(stage_raw_only(
                self.vault, self.stage_root, data=data, ext=e.ext,
                media_type=ANNUAL_REPORT_MEDIA.get(e.ext, "application/octet-stream"), category="ANNUAL_REPORT_PDF",
                source_url=e.file_url, fetched_at=utc_now(),
                broadcast_ts=e.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None), broadcast_ts_source="API_FIELD",
                stated_symbol=symbol,
            ))  # fmt: skip
        return out

    def annual_report_pdfs_many(self, symbols: Iterable[str], *, min_to_year: int = 2025):
        """X365: `annual_report_pdfs` per symbol; a failure on one symbol is reported and the rest continues."""
        staged, errors = [], []
        for sym in symbols:
            try:
                staged += self.annual_report_pdfs(sym, min_to_year=min_to_year)
            except (FetchError, ParseError) as exc:
                errors.append(f"{sym} annual report PDFs: {exc}")
        return staged, errors + self.errors

    def results(self, symbol: str) -> list[Path]:
        """Integrated Filing results [A7]: listing JSON (vaulted), then every Financials row with a period end in
        scope (C9) whose XBRL is not vaulted yet; broadcast time from the listing (IST)."""
        out, entries, page = [], [], 1
        while True:  # every page until totalCount rows are listed [A7]
            url = results_listing_url(symbol, page)
            if page > 1 and not self._has_listing_page(url):  # replay: the runner stopped paging here (X346)
                break
            listing = self._get(url, accept=JSON)
            if not self._promoted_answer(url, listing):
                out.append(stage_results_listing(self.vault, self.stage_root, data=listing, source_url=url,
                                                 fetched_at=utc_now()))  # fmt: skip
            rows = parse_integrated_filing_listing(listing)
            entries += rows
            seen, total = listing_progress(listing)
            if not seen or page * 20 >= total or page >= 10:
                break
            if rows and all(self._before_since(e.visible_ts_ist) for e in rows):  # X346: a page wholly before since
                break
            page += 1
        for e in entries:
            if e.period_end < MIN_PERIOD_END_DATE or self._before_since(e.visible_ts_ist):
                continue
            if self.is_done(e.xbrl_url, "results_xbrl"):
                continue
            if (xbrl := self._file(e.xbrl_url)) is None:
                continue
            # Visibility = later of broadcast_Date and creation_Date (a revised row has no broadcast) [X83].
            v = e.visible_ts_ist
            ts = None if v is None else ist_to_utc(v.date(), v.time())
            src = "UNKNOWN" if ts is None else "API_FIELD" if v == e.broadcast_ts_ist else "API_CREATION"
            out.append(
                stage_results_xbrl(
                    self.vault,
                    self.stage_root,
                    data=xbrl,
                    source_url=e.xbrl_url,
                    fetched_at=utc_now(),
                    broadcast_ts=ts,
                    broadcast_ts_source=src,
                )
            )
        return out  # fmt: skip

    def reg30_events(self, *, limit: int | None = None, rss: bytes | None = None) -> list[Path]:
        """Announcements RSS (vaulted) -> structured event XBRL of the parsed families, one file per request [E1, E2].
        The RSS pubDate (IST) is the broadcast time."""
        rss = rss if rss is not None else self.announcements_rss()
        parsed = parse_announcements_rss(rss)  # before vaulting: a cut-short answer is never kept as the day's RSS
        out = [] if self._promoted_answer(ANNOUNCEMENTS_RSS, rss) else [stage_raw_only(
            self.vault, self.stage_root, data=rss, ext="xml", media_type="application/rss+xml",
            category="ANNOUNCEMENTS_RSS", source_url=ANNOUNCEMENTS_RSS, fetched_at=utc_now(),
        )]  # fmt: skip
        items = [i for i in parsed
                 if i.xbrl_url and i.xbrl_url.rsplit("/", 1)[-1].startswith(EVENT_PREFIXES)
                 and not self.is_vaulted(i.xbrl_url)]  # fmt: skip
        for item in items[:limit]:
            if (data := self._file(item.xbrl_url)) is None:
                continue
            ts = None if item.pub_ts_ist is None else ist_to_utc(item.pub_ts_ist.date(), item.pub_ts_ist.time())
            out.append(
                stage_reg30_event(self.vault, self.stage_root, data=data, source_url=item.xbrl_url,
                                  fetched_at=utc_now(), broadcast_ts=ts, broadcast_ts_source="RSS_PUBDATE")
            )  # fmt: skip
        return out

    def results_xbrl(
        self, url: str, broadcast_ts: datetime | None = None, source: str = "UNKNOWN", *, refetch: bool = False
    ) -> list[Path]:
        """A results XBRL by URL (when the URL is known from elsewhere); `refetch`: see `_get` (X322)."""
        data = self._get(url, refetch=refetch)
        return [
            stage_results_xbrl(self.vault, self.stage_root, data=data, source_url=url, fetched_at=utc_now(),
                               broadcast_ts=broadcast_ts, broadcast_ts_source=source)
        ]  # fmt: skip

    def discover(
        self, symbols: Iterable[str], kinds: Iterable[str] = ("results", "annual", "shareholding"), *,
        events: bool = True, workers: int = 1,
    ) -> tuple[list[Path], list[str]]:  # fmt: skip
        """discover-filings: per-symbol listings (results [A7], annual [A8], shareholding [SHP6]) plus the Reg. 30
        events of the announcements RSS. Per-symbol failures are reported and the rest continues.

        `workers` > 1 runs symbols on a thread pool. The fetcher still sends at most one request per host at a time,
        >= 1 s apart, so workers only overlap the API host (listings) with the archive host (files)."""
        staged: list[Path] = []
        errors: list[str] = []
        self.errors = []
        if events:
            try:
                staged += self.reg30_events()
            except (FetchError, ParseError) as exc:
                errors.append(f"events: {exc}")
        jobs = {"results": self.results, "annual": self.annual_reports,
                "shareholding": lambda s: self.shareholding(s, min_as_of=self.shp_min_as_of)}  # fmt: skip
        kinds = list(kinds)

        def one(sym: str) -> tuple[list[Path], list[str]]:
            got, errs = [], []
            for k in kinds:
                try:
                    got += jobs[k](sym)
                except (FetchError, ParseError) as exc:
                    errs.append(f"{sym} {k}: {exc}")
            return got, errs

        symbols = list(symbols)
        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(one, symbols))
        else:
            results = [one(s) for s in symbols]
        for got, errs in results:  # input order, whatever the completion order
            staged += got
            errors += errs
        return staged, errors + self.errors

    def symbols_from_rss(self) -> list[str]:
        """Daily hint: symbols whose 'financial results' announcements are in the RSS (attachment file name)."""
        return symbols_with_results_today(self.announcements_rss())

    def announcements_rss(self) -> bytes:
        """X350 RSS_PARSE_RETRY: the announcements RSS, fetched once per job set (run-day reads it for the symbols
        hint and for the Reg. 30 events) and accepted only when it parses as XML. NSE served a cut-short file on
        2026-11-20 ("unclosed token: line 1, column 430594") and the day's discovery failed: an answer that does not
        parse is asked again after RSS_RETRY_WAIT seconds (the host's own spacing still applies), up to
        RSS_ATTEMPTS times in all; then the ParseError is raised. A rejected answer is never vaulted or recorded."""
        if getattr(self, "_rss", None) is not None:
            return self._rss
        for attempt in range(1, RSS_ATTEMPTS + 1):
            data = self.f.get(ANNOUNCEMENTS_RSS)
            try:
                parse_announcements_rss(data)
            except ParseError as exc:
                if attempt == RSS_ATTEMPTS:
                    raise ParseError(f"{exc} ({attempt} attempts)") from exc
                self.warnings.append(f"announcements RSS did not parse ({exc}); asked again ({attempt + 1}/"
                                     f"{RSS_ATTEMPTS}) [X350]")  # fmt: skip
                self.f.sleep(RSS_RETRY_WAIT)
                continue
            if self.record_responses:
                from financials.fetch.replay import record_response

                record_response(self.vault, ANNOUNCEMENTS_RSS, data, "xml", utc_now())
            self._rss = data
            return data
        raise AssertionError("unreachable")
