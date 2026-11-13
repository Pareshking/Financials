"""Content-addressable raw vault. Blobs are immutable; a filing is one publication of a blob."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from financials.ids import stable_id

BROADCAST_SOURCES = {"RSS_PUBDATE", "API_FIELD", "EOD_RULE", "UNKNOWN"}


@dataclass(frozen=True)
class Blob:
    sha256: str
    byte_size: int
    media_type: str
    storage_path: str  # relative to vault root
    first_fetched_at: datetime


@dataclass(frozen=True)
class Filing:
    filing_id: str
    sha256: str
    exchange: str
    category: str
    source_url: str
    exchange_ref: str | None
    stated_symbol: str | None
    stated_isin: str | None
    broadcast_ts: datetime | None
    broadcast_ts_source: str
    fetched_at: datetime
    supersedes_filing_id: str | None = None


def make_filing(
    blob: Blob,
    *,
    exchange: str,
    category: str,
    source_url: str,
    fetched_at: datetime,
    broadcast_ts: datetime | None = None,
    broadcast_ts_source: str = "UNKNOWN",
    exchange_ref: str | None = None,
    stated_symbol: str | None = None,
    stated_isin: str | None = None,
    supersedes_filing_id: str | None = None,
) -> Filing:
    if broadcast_ts_source not in BROADCAST_SOURCES:
        raise ValueError(f"unknown broadcast_ts_source {broadcast_ts_source!r}")
    if (broadcast_ts is None) != (broadcast_ts_source == "UNKNOWN"):
        raise ValueError("broadcast_ts must be set iff broadcast_ts_source != UNKNOWN")
    return Filing(
        filing_id=stable_id("fil", exchange, source_url, blob.sha256),
        sha256=blob.sha256,
        exchange=exchange,
        category=category,
        source_url=source_url,
        exchange_ref=exchange_ref,
        stated_symbol=stated_symbol,
        stated_isin=stated_isin,
        broadcast_ts=broadcast_ts,
        broadcast_ts_source=broadcast_ts_source,
        fetched_at=fetched_at,
        supersedes_filing_id=supersedes_filing_id,
    )


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @staticmethod
    def relative_path(sha256: str, ext: str) -> str:
        return f"{sha256[:2]}/{sha256}.{ext.lstrip('.')}"

    def put(self, data: bytes, *, ext: str, media_type: str, fetched_at: datetime) -> Blob:
        """Store bytes once; re-putting identical bytes is a no-op returning the same blob."""
        sha = hashlib.sha256(data).hexdigest()
        rel = self.relative_path(sha, ext)
        path = self.root / rel
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise RuntimeError(f"vault corruption at {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            path.chmod(0o444)
        return Blob(sha, len(data), media_type, rel, fetched_at)

    def read(self, blob: Blob) -> bytes:
        data = (self.root / blob.storage_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != blob.sha256:
            raise RuntimeError(f"vault corruption: {blob.storage_path}")
        return data
