"""Sharded NSE discovery on GitHub runners and `import-vault` (fetch.replay, owner 2026-11-17)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
import yaml
from test_fetch_and_e2e import FakeTransport

from _fixture_helpers import FIXTURES
from financials.cli import build_parser, main
from financials.fetch.http import Response
from financials.fetch.jobs import results_listing_url
from financials.fetch.replay import read_symbols_file, shard
from financials.sources import ROOT

A7 = FIXTURES / "discovery" / "nse_integrated-filing-results_equities_TCS_20261113.json"
A7_PAGE2 = FIXTURES / "discovery" / "nse_integrated-filing-results_equities_TCS_page2_20261114.json"
XBRL = "https://nsearchives.nseindia.com/corporate/xbrl/"
Q2 = XBRL + "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
Q4 = XBRL + "INTEGRATED_FILING_INDAS_1648408_09042026114218_WEB.xml"


def routes():
    return {results_listing_url("TCS"): Response(200, A7.read_bytes()),
            results_listing_url("TCS", 2): Response(200, A7_PAGE2.read_bytes()),
            Q2: Response(200, (FIXTURES / "xbrl" / Q2.rsplit("/", 1)[-1]).read_bytes()),
            Q4: Response(200, (FIXTURES / "xbrl" / Q4.rsplit("/", 1)[-1]).read_bytes())}  # fmt: skip


def run(argv, transport=None) -> tuple[int, str]:
    import financials.cli as cli_mod

    out, orig = io.StringIO(), cli_mod.PoliteFetcher
    cli_mod.PoliteFetcher = lambda transport, **kw: orig(transport, sleep=lambda s: None, **kw)
    try:
        rc = main(argv, transport=transport, out=out)
    finally:
        cli_mod.PoliteFetcher = orig
    return rc, out.getvalue()


def staged_set(stage_root: Path) -> set[str]:
    return {p.parent.relative_to(stage_root).as_posix() for p in stage_root.glob("*/*/manifest.json")}


def test_shards_partition_the_list_deterministically_whatever_its_order():
    syms = [f"S{i}" for i in range(1337)]
    parts = [shard(syms, k, 8) for k in range(8)]
    assert sorted(s for p in parts for s in p) == sorted(syms)
    assert {len(p) for p in parts} <= {167, 168}
    assert parts == [shard(list(reversed(syms)), k, 8) for k in range(8)]
    with pytest.raises(ValueError):
        shard(syms, 8, 8)


def test_symbols_file_ignores_blanks_comments_and_duplicates(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("# list\nTCS\n\nM&M  # ampersand\nTCS\n", encoding="utf-8")
    assert read_symbols_file(f) == ["TCS", "M&M"]


def runner_fetch(tmp_path) -> Path:
    """A runner: fresh data dir, no market database, one shard of a symbols file."""
    f = tmp_path / "list.txt"
    f.write_text("TCS\n", encoding="utf-8")
    runner = tmp_path / "runner"
    rc, text = run(["--data-dir", str(runner), "--archive-rps", "8", "discover-filings", "--symbols-file", str(f),
                    "--shard", "0/1", "--kinds", "results", "--no-events", "--record-responses"],
                   FakeTransport(routes()))  # fmt: skip
    assert "shard 0/1: 1 symbol(s)" in text
    assert rc == 1  # the 12 unserved in-scope files are reported, the rest goes on
    assert not (runner / "market.duckdb").exists()
    return runner / "vault"


def test_import_vault_stages_what_a_local_discovery_would_and_is_idempotent(tmp_path):
    nse_fetch = runner_fetch(tmp_path)
    responses = [json.loads(x) for x in (nse_fetch / "responses.jsonl").read_text().splitlines()]
    assert {r["url"] for r in responses} == {results_listing_url("TCS"), results_listing_url("TCS", 2)}

    direct = tmp_path / "direct"  # the same discovery run locally, for comparison
    run(["--data-dir", str(direct), "discover-filings", "--symbols", "TCS", "--kinds", "results", "--no-events"],
        FakeTransport(routes()))  # fmt: skip

    local = tmp_path / "local"
    rc, text = run(["--data-dir", str(local), "import-vault", str(nse_fetch)])
    assert rc == 0, text
    assert "blobs_new=4" in text and "ledger_lines_added=2" in text and "files_not_on_runner=12" in text
    assert staged_set(local / "staging") == staged_set(direct / "staging")
    ledger = (local / "vault" / "url_index.jsonl").read_text().splitlines()
    assert {json.loads(x)["url"] for x in ledger} == {Q2, Q4}

    # a second import (or the same artifact twice) adds nothing
    rc, text = run(["--data-dir", str(local), "import-vault", str(nse_fetch), str(nse_fetch)])
    assert rc == 0 and "blobs_new=0" in text and "ledger_lines_added=0" in text, text
    assert (local / "vault" / "url_index.jsonl").read_text().splitlines() == ledger

    # the archive files are vaulted locally now: a local discovery never downloads them again
    t = FakeTransport(routes())
    run(["--data-dir", str(local), "discover-filings", "--symbols", "TCS", "--kinds", "results", "--no-events"], t)
    assert not {Q2, Q4} & {u for u, _ in t.calls}

    assert run(["--data-dir", str(local), "init-db"])[0] == 0
    rc, text = run(["--data-dir", str(local), "promote"])
    assert "results_xbrl" in text and "PROMOTED" in text, text


def test_import_vault_refuses_a_tampered_blob_and_writes_nothing(tmp_path):
    nse_fetch = runner_fetch(tmp_path)
    q2 = next(json.loads(x) for x in (nse_fetch / "url_index.jsonl").read_text().splitlines() if x and Q2 in x)
    blob = next(nse_fetch.glob(q2["storage_path"] + "*"))
    os.chmod(blob, 0o644)
    import gzip

    blob.write_bytes(gzip.compress(b"<xbrl>tampered</xbrl>"))
    local = tmp_path / "local"
    rc, text = run(["--data-dir", str(local), "import-vault", str(nse_fetch)])
    assert rc == 1 and "refused" in text and "sha256" in text, text
    assert not (local / "vault").exists() and not (local / "staging").exists()


def test_nse_fetch_workflow_fans_out_shards_and_hands_back_only_the_vault():
    path = ROOT / ".github" / "workflows" / "nse-fetch.yml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    on = doc.pop(True, doc.get("on"))
    assert on["workflow_dispatch"]["inputs"]["shards"]["default"] == "8"
    lst = on["workflow_dispatch"]["inputs"]["list"]["default"]
    assert set(on["push"]["paths"]) == {".github/workflows/nse-fetch.yml", lst}
    assert len(read_symbols_file(ROOT / lst)) > 1000
    fetch = doc["jobs"]["fetch"]
    assert fetch["strategy"]["fail-fast"] is False
    assert "needs.plan.outputs" in str(fetch["strategy"]["max-parallel"])
    run_text = "\n".join(s.get("run", "") for s in fetch["steps"])
    assert "--shard" in run_text and "--record-responses" in run_text and "--archive-rps 8" in run_text
    upload = next(s for s in fetch["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert upload["with"]["path"] == "nse_fetch/" and upload["with"]["retention-days"] == 1
    assert upload["with"]["name"] == "nse-fetch-${{ matrix.shard }}"
    args = build_parser().parse_args(
        ["discover-filings", "--symbols-file", lst, "--shard", "0/8", "--record-responses"]
    )
    assert args.shard == "0/8" and args.record_responses
