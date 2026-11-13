"""Fetch jobs: download → vault → staging. Each returns the stage directories it wrote.

URLs below are the ones verified in docs/references.md (P1, P10, A6, P12, CAL1, SHP6).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from financials.fetch.http import PoliteFetcher
from financials.parsers.shareholding import parse_shp_master
from financials.staging import (
    stage_corp_actions,
    stage_holidays,
    stage_index_snapshot,
    stage_market_day,
    stage_raw_only,
    stage_results_xbrl,
    stage_shareholding,
)
from financials.timeutil import utc_now
from financials.vault import Vault

ARCHIVE = "https://nsearchives.nseindia.com"
API = "https://www.nseindia.com/api"
JSON = "application/json"


def bhavcopy_url(d: date) -> str:
    return f"{ARCHIVE}/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def delivery_url(d: date) -> str:
    return f"{ARCHIVE}/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"


def corp_actions_url(start: date, end: date) -> str:
    return f"{API}/corporates-corporateActions?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"


def holidays_url() -> str:
    return f"{API}/holiday-master?type=trading"


def index_list_url(file_stub: str = "nifty500") -> str:
    return f"{ARCHIVE}/content/indices/ind_{file_stub}list.csv"


def shp_master_url(symbol: str) -> str:
    return f"{API}/corporate-share-holdings-master?index=equities&symbol={symbol}"


class Jobs:
    def __init__(self, fetcher: PoliteFetcher, vault: Vault, stage_root: Path) -> None:
        self.f, self.vault, self.stage_root = fetcher, vault, Path(stage_root)

    def market_day(self, d: date) -> list[Path] | None:
        """None when no bhavcopy exists (holiday/weekend): nothing is staged."""
        bhav = self.f.get(bhavcopy_url(d), allow_404=True)
        if bhav is None:
            return None
        deliv = self.f.get(delivery_url(d), allow_404=True)
        return [
            stage_market_day(
                self.vault, self.stage_root, bhavcopy=bhav, bhavcopy_url=bhavcopy_url(d), delivery=deliv,
                delivery_url=delivery_url(d) if deliv is not None else None, fetched_at=utc_now(),
            )
        ]  # fmt: skip

    def corp_actions(self, start: date, end: date) -> list[Path]:
        url = corp_actions_url(start, end)
        data = self.f.get(url, accept=JSON)
        return [stage_corp_actions(self.vault, self.stage_root, data=data, source_url=url, fetched_at=utc_now())]

    def holidays(self) -> list[Path]:
        data = self.f.get(holidays_url(), accept=JSON)
        return [stage_holidays(self.vault, self.stage_root, data=data, source_url=holidays_url(), fetched_at=utc_now())]

    def index_snapshot(self, snapshot_date: date, index_name: str = "NIFTY 500", file_stub: str = "nifty500"):
        url = index_list_url(file_stub)
        data = self.f.get(url)
        return [
            stage_index_snapshot(self.vault, self.stage_root, data=data, source_url=url, index_name=index_name,
                                 snapshot_date=snapshot_date, fetched_at=utc_now())
        ]  # fmt: skip

    def shareholding(self, symbol: str, *, latest_only: bool = True) -> list[Path]:
        """Master JSON gives each filing's XBRL URL and broadcast time [SHP6]."""
        url = shp_master_url(symbol)
        master = self.f.get(url, accept=JSON)
        out = [stage_raw_only(self.vault, self.stage_root, data=master, ext="json", media_type=JSON,
                              category="SHP_MASTER", source_url=url, fetched_at=utc_now())]  # fmt: skip
        entries = parse_shp_master(master)
        if latest_only:
            entries = entries[:1]
        for e in entries:
            xbrl = self.f.get(e.xbrl_url)
            out.append(
                stage_shareholding(
                    self.vault, self.stage_root, data=xbrl, source_url=e.xbrl_url, fetched_at=utc_now(),
                    broadcast_ts=e.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None),
                    broadcast_ts_source="API_FIELD",
                )
            )  # fmt: skip
        return out

    def results_xbrl(self, url: str, broadcast_ts: datetime | None = None, source: str = "UNKNOWN") -> list[Path]:
        """A results XBRL by URL (discovery API is UNVERIFIED [A7]; URLs come from the user or a list)."""
        data = self.f.get(url)
        return [
            stage_results_xbrl(self.vault, self.stage_root, data=data, source_url=url, fetched_at=utc_now(),
                               broadcast_ts=broadcast_ts, broadcast_ts_source=source)
        ]  # fmt: skip
