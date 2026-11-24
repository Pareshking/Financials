"""docs/data_catalogue.md is generated from tests/fixtures/ by scripts/data_catalogue.py: a new fixture forces a
catalogue update, every fixture file lands in exactly one family, and the INGESTED claims hold against the code."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("data_catalogue", ROOT / "scripts" / "data_catalogue.py")
cat = importlib.util.module_from_spec(_spec)
sys.modules["data_catalogue"] = cat  # dataclasses resolve their module by name
_spec.loader.exec_module(cat)


@pytest.fixture(scope="module")
def entries():
    return cat.walk()


def test_committed_catalogue_matches_generator(entries):
    assert cat.MD_PATH.read_text(encoding="utf-8") == cat.render(entries), (
        "run: python scripts/data_catalogue.py --write"
    )


def test_every_fixture_file_is_in_exactly_one_family(entries):
    groups = cat.classify(entries)  # raises on a file in no family or in several
    assert sum(len(v) for v in groups.values()) == len(entries)
    on_disk = {p.relative_to(cat.FIXTURES).as_posix() for p in cat.FIXTURES.rglob("*") if p.is_file()}
    assert {e.path.split("!", 1)[0] for e in entries} == on_disk
    assert [name for name, es in groups.items() if not es] == [], "a family matches no fixture: drop or fix it"


def test_every_zip_member_is_listed(entries):
    import zipfile

    for z in sorted(cat.FIXTURES.rglob("*.zip")):
        rel = z.relative_to(cat.FIXTURES).as_posix()
        with zipfile.ZipFile(z) as zf:
            members = {n for n in zf.namelist() if not n.endswith("/")}
        assert {e.path.split("!", 1)[1] for e in entries if e.path.startswith(rel + "!")} == members


def test_family_claims_hold_against_the_code():
    assert cat.verify() == []


def test_unclassified_file_fails_the_run(entries):
    with pytest.raises(ValueError, match="unclassified"):
        cat.classify([*entries, cat.Entry("new_dir/unknown_feed.csv", b"a,b\n1,2\n")])


def test_pr_zip_members_quote_nse_readme(entries):
    readme = cat.pr_readme_sentences(entries)
    assert readme["bh"].startswith("bhddmmyyyy.csv file contains a list of securities which have hit their price bands")
    assert {"an", "bc", "bh", "bm", "corpbond", "etf", "gl", "hl", "mcap", "pd", "pr", "sme", "tt", "readme"} <= set(
        readme
    )
    md = cat.MD_PATH.read_text(encoding="utf-8")
    assert re.search(r"^\| \[NSE PR zip: bh price-band hits\].* \| NOT_INGESTED \| .*G207", md, flags=re.M)
