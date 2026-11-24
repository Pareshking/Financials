"""Batch K: GitHub Actions nightly workflows (docs/architecture.md §13, ops/README.md) and the
`fetch-classification --missing-only` selection the self-hosted pipeline uses."""

from __future__ import annotations

import io
import re
from datetime import datetime

import yaml
from conftest import Market

from _fixture_helpers import FIXTURES
from financials.cli import build_parser, classified_symbols, main
from financials.fetch.http import Response
from financials.promoter import promote
from financials.sources import ROOT
from financials.staging import stage_classification

WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> dict:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))  # YAML 1.1 reads the bare key `on` as true
    return doc


def _run_lines(doc: dict) -> list[str]:
    return [line for job in doc["jobs"].values() for s in job["steps"] for line in s.get("run", "").splitlines()]


def _cli_commands(text: str) -> list[str]:
    return re.findall(r"-m financials (?:--data-dir \S+ )?([a-z][a-z-]+)", text)


def test_nightly_workflows_parse_and_run_only_on_manual_dispatch():
    for name in ("nightly-tests.yml", "nightly-pipeline.yml"):
        doc = _load(name)
        assert list(doc["on"]) == ["workflow_dispatch"], name  # owner 2026-11-23: no schedule (manual only)
        assert doc["permissions"] == {"contents": "read"}, name  # nothing can be pushed back
        for job in doc["jobs"].values():
            assert job["timeout-minutes"] > 0


def test_nightly_tests_run_the_same_offline_checks_as_ci():
    ci, nightly = _load("ci.yml"), _load("nightly-tests.yml")
    assert nightly["jobs"]["test"]["runs-on"] == "ubuntu-latest"
    assert _run_lines(nightly) == _run_lines(ci)
    lines = {line.strip() for line in _run_lines(nightly)}
    assert {"ruff check src tests", "ruff format --check src tests", "python -m pytest"} <= lines


def test_nightly_pipeline_runs_only_on_the_owners_runner_with_existing_commands():
    doc = _load("nightly-pipeline.yml")
    job = doc["jobs"]["pipeline"]
    assert job["runs-on"] == ["self-hosted", "financials"]
    assert doc["concurrency"] == {"group": "financials-nightly-pipeline", "cancel-in-progress": False}
    text = (WORKFLOWS / "nightly-pipeline.yml").read_text(encoding="utf-8")
    used = _cli_commands(text)
    assert used == ["run-day", "fetch-classification", "promote", "materialize"]
    assert set(used) <= set(build_parser()._subparsers._group_actions[0].choices)
    assert all('--data-dir "$FINANCIALS_DATA_DIR"' in line for line in _run_lines(doc) if "-m financials" in line)
    assert "materialize --incremental" in text and "--missing-only" in text
    args = build_parser().parse_args(["fetch-classification", "--universe", "nifty500", "--missing-only"])
    assert args.missing_only and args.universe == "nifty500"


def test_no_workflow_commits_pushes_or_uploads_data():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc, text = _load(path.name), path.read_text(encoding="utf-8")
        for bad in ("git commit", "git push", "git add", "contents: write", "market.duckdb", ".parquet"):
            assert bad not in text, (path.name, bad)
        for job in doc["jobs"].values():
            for step in job["steps"]:
                if str(step.get("uses", "")).startswith("actions/upload-artifact"):
                    target = step["with"]["path"]
                    # Owner decision P (2026-11-17): exchange files fetched by a probe may be uploaded as artifacts;
                    # the database, Parquet and data/ never are (checked above and below).
                    assert target in (
                        "${{ runner.temp }}/nightly-log/nightly-pipeline.log",
                        "bse_probe/",
                        "bse_fetch/",
                        "nse_fetch/",
                    ), target  # bse_fetch/: the BSE runner ledger (A17); nse_fetch/: an NSE runner vault (import-vault)
                    assert "data" not in target.replace("nightly", ""), target
        code = re.sub(r"(^|\s)#.*$", "", text, flags=re.M)  # comments may explain; code never names data/
        assert not re.search(r"(^|[\s\"'=/])data/", code, re.M), path.name


def test_missing_only_fetches_classification_just_for_unclassified_symbols(tmp_path):
    m = Market(tmp_path)
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"
    tcs = (FIXTURES / "classification" / "GetQuoteApi_getSymbolData_TCS.json").read_bytes()
    r = promote(m.con, stage_classification(m.vault, m.stage_root, data=tcs, source_url="https://www.nseindia.com/q",
                                            fetched_at=datetime(2026, 11, 13, 9)))  # fmt: skip
    assert r.status == "PROMOTED", r
    m.con.close()
    assert "TCS" in classified_symbols(tmp_path / "market.duckdb")
    assert "HDFCBANK" not in classified_symbols(tmp_path / "market.duckdb")
    assert classified_symbols(tmp_path / "absent.duckdb") == set()

    class Offline:
        def __init__(self):
            self.urls = []

        def get(self, url, headers, timeout):
            self.urls.append(url)
            return Response(404, b"")

    import financials.cli as cli_mod

    t, out, orig = Offline(), io.StringIO(), cli_mod.PoliteFetcher
    cli_mod.PoliteFetcher = lambda transport, **kw: orig(transport, sleep=lambda s: None, **kw)
    try:
        main(["--data-dir", str(tmp_path), "fetch-classification", "TCS", "HDFCBANK", "--missing-only"],
             transport=t, out=out)  # fmt: skip
    finally:
        cli_mod.PoliteFetcher = orig
    assert "1 symbol(s) without a classification" in out.getvalue()
    quotes = [u for u in t.urls if "GetQuoteApi" in u]
    assert quotes and all("symbol=HDFCBANK" in u for u in quotes)
