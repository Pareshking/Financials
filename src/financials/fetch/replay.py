"""Sharded discovery on GitHub runners and `import-vault` (owner 2026-11-17: "We used to download using 8 runners").

A runner runs `discover-filings --symbols-file F --shard K/N --record-responses` against a fresh, empty data dir (no
market database: discovery needs none). Its vault is the hand-back: blobs, `url_index.jsonl` (the archive files, as
on every machine) and `responses.jsonl` (one line per listing / API answer, which the URL index does not keep because
listings change). `import-vault` then, on the owner's machine:

1. verifies every blob a ledger line names against that line's sha256 and refuses the whole import on any mismatch
   or missing blob (nothing is written);
2. puts the blobs into the local vault (an already vaulted blob is left as it is) and appends the runner's URL index
   lines the local ledger does not have yet (by URL + status + sha256), so those files are never downloaded again;
3. stages by running the very same discovery jobs offline, with a transport that answers only from the recorded
   responses: listings are parsed and staged as they would have been locally, archive files come from the vault.
   A file the runner did not fetch is skipped (counted), never asked from the network.

Every step is idempotent: stage ids derive from content, ledger lines are de-duplicated.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from financials.fetch.http import PoliteFetcher, Response
from financials.timeutil import utc_now
from financials.vault import Vault

RESPONSES = "responses.jsonl"
KIND_PATHS = {"/api/integrated-filing-results": "results", "/api/annual-reports-xbrl": "annual",
              "/api/corporate-share-holdings-master": "shareholding"}  # fmt: skip


class ImportRefused(RuntimeError):
    """A runner vault failed verification; nothing was imported."""


def read_symbols_file(path: Path) -> list[str]:
    """One NSE symbol per line; blank lines and `#` comments ignored; order kept, duplicates dropped."""
    out: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if s and s not in out:
            out.append(s)
    return out


def shard(symbols: list[str], k: int, n: int) -> list[str]:
    """Shard k (0-based) of n: symbols ordered by sha256 of the symbol, cut into n contiguous near-equal ranges.
    Deterministic for a given list, and independent of the list's order."""
    if not 0 <= k < n:
        raise ValueError(f"shard {k} out of range for {n} shards")
    ordered = sorted(set(symbols), key=lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())
    size, extra = divmod(len(ordered), n)
    start = k * size + min(k, extra)
    return ordered[start : start + size + (1 if k < extra else 0)]


def parse_shard(text: str) -> tuple[int, int]:
    k, n = (int(x) for x in text.split("/", 1))
    if n < 1 or not 0 <= k < n:
        raise ValueError(f"--shard {text!r}: want K/N with 0 <= K < N")
    return k, n


_lock = threading.Lock()


def record_response(vault: Vault, url: str, data: bytes, ext: str, fetched_at) -> None:
    """Runner side: vault a listing / API answer and note URL -> sha256 in responses.jsonl."""
    blob = vault.put(data, ext=ext, media_type="application/octet-stream", fetched_at=fetched_at)
    entry = {"url": url, "status": 200, "fetched_at": fetched_at.isoformat(), "sha256": blob.sha256,
             "storage_path": blob.storage_path}  # fmt: skip
    with _lock, (vault.root / RESPONSES).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ReplayTransport:
    """Answers recorded URLs with their verified bytes; anything else is a 404 (never the network)."""

    def __init__(self, answers: dict[str, bytes]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def get(self, url: str, headers: dict[str, str], timeout: float) -> Response:
        self.asked.append(url)
        body = self.answers.get(url)
        return Response(404, b"") if body is None else Response(200, body)


def _verify(src: Path) -> tuple[list[dict], list[dict], dict[str, tuple[bytes, str]]]:
    """(url index lines, response lines, sha -> (bytes, ext)); raises ImportRefused on any bad or missing blob."""
    if not src.is_dir():
        raise ImportRefused(f"{src}: not a directory")
    runner = Vault(src)
    index, responses = _lines(src / "url_index.jsonl"), _lines(src / RESPONSES)
    if not index and not responses:
        raise ImportRefused(f"{src}: no url_index.jsonl or {RESPONSES}")
    blobs: dict[str, tuple[bytes, str]] = {}
    for e in index + responses:
        if "sha256" not in e:
            continue
        sha, rel = e["sha256"], e["storage_path"]
        if rel != Vault.relative_path(sha, rel.split(".", 1)[1] if "." in rel else "bin"):
            raise ImportRefused(f"{src}: storage path {rel} does not belong to sha256 {sha}")
        if sha in blobs:
            continue
        try:
            data = runner.read_path(rel, sha)
        except FileNotFoundError as exc:
            raise ImportRefused(f"{src}: blob {rel} missing ({e['url']})") from exc
        except (RuntimeError, OSError, EOFError) as exc:  # sha mismatch, bad gzip
            raise ImportRefused(f"{src}: blob {rel} fails its sha256 ({e['url']}): {exc}") from exc
        blobs[sha] = (data, rel.split(".", 1)[1])
    return index, responses, blobs


def import_vault(vault: Vault, stage_root: Path, dirs: list[Path]) -> tuple[list[Path], list[str], dict[str, int]]:
    """Merge runner vaults into `vault`, then stage their filings for `promote`. Returns (staged, errors, stats)."""
    checked = [(Path(d), *_verify(Path(d))) for d in dirs]  # all verified before anything is written
    stats = {"blobs_new": 0, "blobs_present": 0, "ledger_lines_added": 0, "files_not_on_runner": 0}
    answers: dict[str, bytes] = {}
    local_index = _lines(vault.index_path)
    have = {(e["url"], e["status"], e.get("sha256")) for e in local_index}
    have_url = {e["url"] for e in local_index}
    new_lines: list[dict] = []
    for _src, index, responses, blobs in checked:
        for sha, (data, ext) in blobs.items():
            if vault.exists(Vault.relative_path(sha, ext)):
                stats["blobs_present"] += 1
            else:
                stats["blobs_new"] += 1
            vault.put(data, ext=ext, media_type="application/octet-stream", fetched_at=utc_now())
        for e in index:
            key = (e["url"], e["status"], e.get("sha256"))
            # a runner 404 never shadows what this machine already knows about the URL
            if key in have or (e["status"] != 200 and e["url"] in have_url):
                continue
            have.add(key)
            have_url.add(e["url"])
            new_lines.append(e)
        for e in responses:  # later lines win (the newest answer), as in the URL index
            answers[e["url"]] = blobs[e["sha256"]][0]
    if new_lines:
        vault.root.mkdir(parents=True, exist_ok=True)
        with Vault._index_lock:
            with vault.index_path.open("a", encoding="utf-8") as fh:
                for e in new_lines:
                    fh.write(json.dumps(e, sort_keys=True) + "\n")
            vault._index = None
    stats["ledger_lines_added"] = len(new_lines)
    staged, errors = _stage(vault, stage_root, answers, stats)
    return staged, errors, stats


def _symbol_kinds(urls) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for url in urls:
        parts = urlsplit(url)
        kind = KIND_PATHS.get(parts.path)
        q = parse_qs(parts.query)
        if kind is None or "page" in q or not q.get("symbol"):
            continue
        kinds = out.setdefault(q["symbol"][0], [])
        if kind not in kinds:
            kinds.append(kind)
    return out


def _stage(vault: Vault, stage_root: Path, answers: dict[str, bytes], stats: dict[str, int]):
    from financials.fetch.jobs import Jobs

    transport = ReplayTransport(answers)

    class ReplayJobs(Jobs):
        def _file(self, url: str) -> bytes | None:
            if not self.is_vaulted(url) and url not in answers:  # not fetched on the runner: skip, no network
                stats["files_not_on_runner"] += 1
                return None
            return super()._file(url)

    fetcher = PoliteFetcher(transport, min_interval=0.0, max_attempts=1, sleep=lambda s: None)
    jobs = ReplayJobs(fetcher, vault, stage_root)
    jobs.shp_min_as_of = date.min  # every quarter the runner fetched (its --shp-from already chose them)
    staged: list[Path] = []
    errors: list[str] = []
    for sym, kinds in sorted(_symbol_kinds(answers).items()):
        got, errs = jobs.discover([sym], kinds, events=False)
        staged += got
        errors += errs
    return staged, errors
