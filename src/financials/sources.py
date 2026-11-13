"""Data-source registry: config/data_sources.yaml -> docs/data_sources.md.

python -m financials.sources --write     # regenerate the markdown
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = ROOT / "config" / "data_sources.yaml"
MD_PATH = ROOT / "docs" / "data_sources.md"

FIELDS = (
    "feed_id", "name", "exchange_or_agency", "url_or_endpoint_pattern", "format", "cadence", "fetch_runtime",
    "join_keys", "target_tables", "unlocked_metrics", "phase", "verification_status", "evidence", "notes",
)  # fmt: skip
STATUSES = ("VERIFIED", "OBSERVED", "UNVERIFIED", "PLANNED")
RUNTIMES = ("CONTAINER_DIRECT", "SESSION_WARMED", "UNKNOWN")


def load(path: Path = YAML_PATH) -> list[dict]:
    feeds = yaml.safe_load(path.read_text(encoding="utf-8"))["feeds"]
    for f in feeds:
        missing = [k for k in FIELDS if k not in f]
        if missing:
            raise ValueError(f"{f.get('feed_id')}: missing {missing}")
        if f["verification_status"] not in STATUSES or f["fetch_runtime"] not in RUNTIMES:
            raise ValueError(f"{f['feed_id']}: bad status/runtime")
    return feeds


def _cell(v) -> str:
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v) if v else "—"
    return str(v if v not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def render(feeds: list[dict]) -> str:
    counts = {s: sum(f["verification_status"] == s for f in feeds) for s in STATUSES}
    out = [
        "# Data sources",
        "",
        "<!-- GENERATED from config/data_sources.yaml by `python -m financials.sources --write`. Do not edit. -->",
        "",
        f"{len(feeds)} feeds: " + ", ".join(f"{counts[s]} {s}" for s in STATUSES) + ". Status meanings and runtime "
        "labels are defined in `config/data_sources.yaml`; evidence IDs point to `docs/references.md`.",
        "",
        "| ID | Feed | Phase | Status | Runtime | Evidence |",
        "|---|---|---|---|---|---|",
    ]
    out += [
        f"| {f['feed_id']} | {_cell(f['name'])} | {f['phase']} | {f['verification_status']} | {f['fetch_runtime']} | "
        f"{_cell(f['evidence'])} |"
        for f in feeds
    ]
    for f in feeds:
        out += ["", f"## {f['feed_id']} — {f['name']}", "", "| Field | Value |", "|---|---|"]
        out += [f"| {k} | {_cell(f[k])} |" for k in FIELDS if k not in ("feed_id", "name")]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="financials.sources")
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    text = render(load())
    if args.write:
        MD_PATH.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
