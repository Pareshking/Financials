"""Content-addressable raw vault. Blobs are immutable; a filing is one publication of a blob."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from financials.ids import stable_id

# API_CREATION: listing creation_Date, used when it is later than broadcast_Date or that is null [X83]
BROADCAST_SOURCES = {"RSS_PUBDATE", "API_FIELD", "API_CREATION", "EOD_RULE", "UNKNOWN"}


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


GZIP_EXTS = ("xml", "json", "csv")  # text blobs are stored gzip-compressed (XBRL ~10x); zips are stored as sent


class Vault:
    """`storage_path` (in `blobs`, the URL index and staging) is the logical path `<sha[:2]>/<sha>.<ext>`; a text blob
    is physically `<storage_path>.gz`. Reads accept either form and always verify the sha256 of the original bytes."""

    _index_lock = threading.Lock()  # url_index.jsonl appends from parallel fetch workers

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @staticmethod
    def relative_path(sha256: str, ext: str) -> str:
        return f"{sha256[:2]}/{sha256}.{ext.lstrip('.')}"

    def put(self, data: bytes, *, ext: str, media_type: str, fetched_at: datetime) -> Blob:
        """Store bytes once; re-putting identical bytes is a no-op returning the same blob."""
        sha = hashlib.sha256(data).hexdigest()
        rel = self.relative_path(sha, ext)
        if self.exists(rel):
            if hashlib.sha256(self._read(rel)).hexdigest() != sha:
                raise RuntimeError(f"vault corruption at {rel}")
        else:
            compress = ext.lstrip(".").lower() in GZIP_EXTS
            path = self.root / (rel + ".gz" if compress else rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(gzip.compress(data, compresslevel=6, mtime=0) if compress else data)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            path.chmod(0o444)
        return Blob(sha, len(data), media_type, rel, fetched_at)

    def exists(self, storage_path: str) -> bool:
        return (self.root / storage_path).exists() or (self.root / (storage_path + ".gz")).exists()

    def _read(self, storage_path: str) -> bytes:
        plain = self.root / storage_path
        if plain.exists():
            return plain.read_bytes()
        return gzip.decompress((self.root / (storage_path + ".gz")).read_bytes())

    def read(self, blob: Blob) -> bytes:
        return self.read_path(blob.storage_path, blob.sha256)

    # ── fetch index: which URL gave which blob (or a 404), append-only JSON lines ──

    @property
    def index_path(self) -> Path:
        return self.root / "url_index.jsonl"

    def record_fetch(
        self, url: str, status: int, fetched_at: datetime, data: bytes | None = None, ext: str = ""
    ) -> None:
        entry = {"url": url, "status": status, "fetched_at": fetched_at.isoformat()}
        if data is not None:
            sha = hashlib.sha256(data).hexdigest()
            entry |= {"sha256": sha, "storage_path": self.relative_path(sha, ext)}
        self.root.mkdir(parents=True, exist_ok=True)
        with self._index_lock:
            with self.index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
            self._index = None

    def last_fetch(self, url: str) -> dict | None:
        with self._index_lock:
            return self._last_fetch(url)

    def _last_fetch(self, url: str) -> dict | None:
        if getattr(self, "_index", None) is None:
            self._index = {}
            if self.index_path.exists():
                for line in self.index_path.read_text(encoding="utf-8").splitlines():
                    e = json.loads(line)
                    self._index[e["url"]] = e
        return self._index.get(url)

    def read_path(self, storage_path: str, sha256: str) -> bytes:
        data = self._read(storage_path)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise RuntimeError(f"vault corruption: {storage_path}")
        return data
