"""The feed registry stays complete, consistent with its markdown, and backed by evidence."""

import re

from financials.sources import MD_PATH, ROOT, load, render


def test_registry_has_all_26_feeds_with_unique_ids():
    feeds = load()
    ids = [f["feed_id"] for f in feeds]
    assert ids == [f"F{n:02d}" for n in range(1, 27)]


def test_markdown_is_generated_from_yaml():
    assert MD_PATH.read_text(encoding="utf-8") == render(load()), "run: python -m financials.sources --write"


def test_verified_and_observed_entries_cite_existing_evidence():
    refs = (ROOT / "docs" / "references.md").read_text(encoding="utf-8")
    known = set(re.findall(r"^\| ([A-Z]+\d+) \|", refs, flags=re.M))
    for f in load():
        if f["verification_status"] in ("VERIFIED", "OBSERVED"):
            assert f["evidence"], f["feed_id"]
            assert set(f["evidence"]) <= known, (f["feed_id"], set(f["evidence"]) - known)
        else:
            assert f["evidence"] == [], f["feed_id"]


def test_unverified_feeds_do_not_claim_concrete_endpoints():
    for f in load():
        if f["verification_status"] in ("UNVERIFIED", "PLANNED"):
            assert "TBD" in f["url_or_endpoint_pattern"] or "per-AMC" in f["url_or_endpoint_pattern"], f["feed_id"]


def test_verified_feeds_have_a_parser_phase():
    assert {f["feed_id"] for f in load() if f["verification_status"] == "VERIFIED"} == {
        "F01", "F02", "F03", "F04", "F05", "F06", "F07", "F08", "F10", "F21",
    }  # fmt: skip
