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
    missing = sorted(
        c for c in cited if c not in KNOWN and re.fullmatch(r"(X|S|C|P|CA|A|I|R|L|FD|SHP|IDX|CAL|E)\d+", c)
    )
    assert missing == []


def test_every_registry_quirk_cites_existing_evidence():
    for name, q in REGISTRY["quirks"].items():
        for ref in str(q["refs"]).split(","):
            assert ref.strip() in KNOWN, (name, ref)


INTEGRATED = sorted([*XBRL_DIR.glob("INTEGRATED_FILING_*.xml"), *XBRL_DIR.glob("IF_INS_COM_IND_AS_*.xml")])


@pytest.mark.parametrize("path", INTEGRATED, ids=lambda p: p.name[:40])
def test_registry_covers_every_element_of_committed_filings(path):
    inst = parse_instance(path.read_bytes())
    profile = detect_profile(inst.entity_namespace)
    assert profile in IMPLEMENTED_PROFILES, (path.name, profile)  # since Batch 6 every committed filing is parsed
    elements = {f.name for f in inst.facts if not inst.contexts[f.context_id].dimensions}
    registered = set(REGISTRY["profiles"].get(profile, {}))
    assert elements - registered == set(), path.name
    assert path.name in REGISTRY["files"]


SHP_FILES = sorted(XBRL_DIR.glob("SHP_*.xml"))


@pytest.mark.parametrize("path", SHP_FILES, ids=lambda p: p.stem)
def test_registry_covers_every_reg31_element_axis_and_category(path):
    """Reg. 31 is dimensional: every element (any context), axis and CategoryOfShareholders member is registered."""
    from financials.parsers.shareholding import shp_instance

    inst = shp_instance(path.read_bytes())[0]  # SHP16: the 2022-09-30 taxonomy's undeclared entity contexts
    elements = {f.name for f in inst.facts}
    axes = {a.split(":")[-1] for c in inst.contexts.values() for a, _ in c.dimensions}
    members = {
        m.split(":")[-1]
        for c in inst.contexts.values()
        for a, m in c.dimensions
        if a.split(":")[-1] == "CategoryOfShareholdersAxis"
    }
    assert elements - set(REGISTRY["profiles"]["REG31_SHP"]) == set()
    assert axes - set(REGISTRY["axes"]["REG31_SHP"]) == set()
    assert members - set(REGISTRY["members"]["REG31_SHP"]["CategoryOfShareholdersAxis"]) == set()
    assert path.name in REGISTRY["files"]


def test_every_seen_numeric_element_is_mapped():
    """C24 zero-drop: every numeric element in the registry has a canonical key and a category; none is excluded.
    Structural duplicates are still mapped and name the key they duplicate."""
    from financials.line_items import STRUCTURAL_DUPLICATES

    problems = []
    for profile, entries in REGISTRY["profiles"].items():
        for name, e in entries.items():
            if not e["numeric"]:
                continue
            if not e.get("mapped_to") or e.get("line_item_category") in (None, "UNCLASSIFIED") or "status" in e:
                problems.append((profile, name, e.get("mapped_to"), e.get("line_item_category")))
            if (profile, name) in STRUCTURAL_DUPLICATES and e.get("duplicate_of") != STRUCTURAL_DUPLICATES[
                (profile, name)
            ]:
                problems.append((profile, name, "duplicate_of"))
    assert problems == []
    assert "UNKNOWN" not in REGISTRY["profiles"]


ALL_RESULTS = sorted([*INTEGRATED, *XBRL_DIR.glob("AR_XBRL_*.xml")])


@pytest.mark.parametrize("path", ALL_RESULTS, ids=lambda p: p.name[:40])
def test_zero_drop_every_numeric_element_of_a_committed_filing_becomes_a_fact(path):
    """C24: every numeric non-dimensional element in a period the parser validated yields a fact (curated tag,
    li_ key, or asfiled_ when a named rule withheld the value). Pre-cutoff and undeclared contexts stay raw."""
    from financials.parsers.integrated import parse_integrated_results

    data = path.read_bytes()
    r = parse_integrated_results(data, path.name)
    inst = parse_instance(data)
    if r.profile == "REG34_ANNUAL":
        durs, insts = set(r.meta["in_scope_periods"]), set(r.meta["in_scope_instants"])
    else:
        durs, insts = {r.meta["quarter_period"], r.meta["ytd_period"]}, {r.meta["period_end"]}
    elements = set()
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        inside = (c.instant in insts) if c.instant is not None else ((c.start, c.end) in durs)
        if f.is_numeric and not c.dimensions and inside:
            elements.add(f.name)
    assert elements - {f.source_element for f in r.facts} == set()
    assert all(
        f.line_item_category for f in r.facts if not f.source_element.startswith(("DERIVED:", "PPE_", "INTANG", "GEO"))
    )


ANNUAL_FILES = sorted(XBRL_DIR.glob("AR_XBRL_*.xml"))


@pytest.mark.parametrize("path", ANNUAL_FILES, ids=lambda p: p.stem)
def test_registry_covers_every_element_of_committed_annual_filings(path):
    """Reg. 34 annual XBRL [X69, X76]: every non-dimensional element is registered under REG34_ANNUAL."""
    inst = parse_instance(path.read_bytes())
    elements = {f.name for f in inst.facts if not inst.contexts[f.context_id].dimensions}
    assert elements - set(REGISTRY["profiles"]["REG34_ANNUAL"]) == set()
    assert path.name in REGISTRY["files"]


EVENT_FILES = sorted((XBRL_DIR.parent / "events").glob("*_WebXMLFile_*.xml"))


@pytest.mark.parametrize("path", EVENT_FILES, ids=lambda p: p.stem[:40])
def test_registry_covers_every_element_of_committed_event_filings(path):
    """Reg. 30 events [E2]: every element (any context) and axis is registered under REG30_EVENT."""
    inst = parse_instance(path.read_bytes())
    assert {f.name for f in inst.facts} - set(REGISTRY["profiles"]["REG30_EVENT"]) == set()
    axes = {a.split(":")[-1] for c in inst.contexts.values() for a, _ in c.dimensions}
    assert axes - set(REGISTRY["axes"]["REG30_EVENT"]) == set()
    assert path.name in REGISTRY["files"]


def test_evidence_ids_are_unique():
    ids = re.findall(r"^\| ([A-Z]+\d+) \|", REFS, flags=re.M)
    assert sorted({i for i in ids if ids.count(i) > 1}) == []
