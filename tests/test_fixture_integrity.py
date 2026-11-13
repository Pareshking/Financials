"""Fixtures are evidence: they must stay byte-identical to what was downloaded."""

import hashlib
import re

import pytest

from _fixture_helpers import FIXTURES

MANIFEST = FIXTURES / "MANIFEST.md"
ROW = re.compile(r"^\|\s*`(?P<path>(?:xbrl|bhavcopy)/[^`]+)`.*`(?P<sha>[0-9a-f]{64})`\s*\|\s*$")


def manifest_entries() -> list[tuple[str, str]]:
    entries = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            entries.append((m["path"], m["sha"]))
    return entries


def test_manifest_lists_every_fixture_file():
    listed = {p for p, _ in manifest_entries()}
    on_disk = {
        str(p.relative_to(FIXTURES)) for p in FIXTURES.rglob("*") if p.is_file() and p.parent != FIXTURES
    }
    assert listed == on_disk


@pytest.mark.parametrize(("rel_path", "sha"), manifest_entries())
def test_fixture_sha256_matches_manifest(rel_path, sha):
    assert hashlib.sha256((FIXTURES / rel_path).read_bytes()).hexdigest() == sha
