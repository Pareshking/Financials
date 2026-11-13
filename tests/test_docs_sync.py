"""Docs stay in sync with code and fixtures: cited evidence exists; the tag registry covers every committed filing."""

import re

import pytest
import yaml

from _fixture_helpers import XBRL_DIR
from financials.parsers.indas_corp import IMPLEMENTED_PROFILES, detect_profile
from financials.parsers.xbrl import parse_instance
from financials.sources import ROOT

REFS = (ROOT / "docs" / "references.md").read_text(encoding="utf-8")
KNOWN = set(re.findall(r"^\| ([A-Z]+\d+) \|", REFS, flags=re.M)) | set(
    re.findall(r"^- \*\*([A-Z]+\d+) ", REFS, flags=re.M)
)
REGISTRY = yaml.safe_load((ROOT / "docs" / "tag_registry.yaml").read_text(encoding="utf-8"))
CITE = re.compile(r"\[((?:[A-Z]{1,3}\d+)(?:\s*,\s*[A-Z]{1,3}\d+)*)\]")


def _cited(text: str) -> set[str]:
    return {i.strip() for m in CITE.findall(text) for i in m.split(",")}


def test_every_evidence_id_cited_in_code_exists():
    cited: set[str] = set()
    for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        cited |= _cited(p.read_text(encoding="utf-8"))
    missing = sorted(c for c in cited if c not in KNOWN and re.fullmatch(r"(X|S|C|P|CA|A|I|R|L|FD|SHP|IDX|CAL)\d+", c))
    assert missing == []


def test_every_registry_quirk_cites_existing_evidence():
    for name, q in REGISTRY["quirks"].items():
        for ref in str(q["refs"]).split(","):
            assert ref.strip() in KNOWN, (name, ref)


INTEGRATED = sorted(XBRL_DIR.glob("INTEGRATED_FILING_*.xml"))


@pytest.mark.parametrize("path", INTEGRATED, ids=lambda p: p.name[18:40])
def test_registry_covers_every_element_of_committed_filings(path):
    inst = parse_instance(path.read_bytes())
    profile = detect_profile(inst.entity_namespace)
    if profile not in IMPLEMENTED_PROFILES:
        pytest.skip(f"{profile}: inspected with its batch")
    elements = {f.name for f in inst.facts if not inst.contexts[f.context_id].dimensions}
    registered = set(REGISTRY["profiles"].get(profile, {}))
    assert elements - registered == set(), path.name
    assert path.name in REGISTRY["files"]
