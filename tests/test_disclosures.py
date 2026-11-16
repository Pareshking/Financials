"""disclosure_facts [X116] and the 18D feature columns (insider receivables X117, Reg. 31 declarations X118,
Schedule III subsidiary contribution X119). Every value is read straight from committed, unmodified fixtures."""

from __future__ import annotations

import hashlib
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials import features_disclosures as F
from financials import raw_xbrl
from financials.db import fetch_dicts
from financials.disclosures import STAGE_DIR, _stage_one, backfill_disclosures, pending_filings
from financials.dsl import ALIASES, compile_screen
from financials.parsers import disclosures as D
from financials.parsers.aoc1 import SCHEDULES, verbatim_elements
from financials.parsers.disclosures import DISCLOSURE_PARSER_VERSION, parse_disclosures, typed_value
from financials.parsers.reg23_rpt import ELEMENTS as REG23_ELEMENTS
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.parsers.rpt import TEXT_ELEMENTS as RPT_TEXT
from financials.parsers.segments import Windows
from financials.parsers.shareholding import HOLDER_ELEMENTS, shp_instance
from financials.parsers.xbrl import parse_instance
from financials.promoter import promote
from financials.scope import MIN_PERIOD_END_DATE
from financials.staging import (
    captured_elements,
    read_table,
    results_tables,
    shareholding_tables,
    stage_reg30_event,
    stage_results_xbrl,
    stage_shareholding,
)
from financials.timeutil import ist_to_utc

ARCHIVE = "https://nsearchives.nseindia.com/corporate/xbrl/"
ELECON, INOX = "AR_XBRL_ELECON_23072026161247.xml", "AR_XBRL_INOXINDIA_09082026015537.xml"
CUMMINS, ETERNAL, SRF = "AR_XBRL_CUMMINSIND_04092026113534.xml", "AR_XBRL_ETERNAL_23092026175418.xml", (
    "AR_XBRL_SRF_09082026022508.xml")  # fmt: skip
TCS, SPARC, ELIN = "AR_XBRL_TCS_09082026012216.xml", "AR_XBRL_SPARC_08092026160440.xml", (
    "AR_XBRL_ELIN_30092025131606.xml")  # fmt: skip
SAMMAAN, PSU_SHP, OLD_SHP = "SHP_1752549_04112026032917_WEB.xml", "SHP_1643664_30032026100841_WEB.xml", (
    "SHP_198754_1421266_21042025041033_WEB.xml")  # fmt: skip
FY25, FY26 = date(2025, 3, 31), date(2026, 3, 31)
FETCHED = datetime(2026, 11, 14, 6)


def _tables(name: str) -> dict:
    data = (XBRL_DIR / name).read_bytes()
    if name.startswith("SHP"):
        return shareholding_tables("fil_x", shp_instance(data)[0], data)
    return results_tables("fil_x", parse_instance(data), data, ARCHIVE + name)


def _cells(rows: list[dict], element: str, end: date) -> list[dict]:
    return [r for r in rows if r["element"] == element and r["period_end"] == end]


# ── parser [X116] ─────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "unit", "expected"),
    [("442100000", "INR", (Decimal("442100000"), None, None)), ("0.00", "INR", (Decimal(0), None, None)),
     ("1.005", "INR", (None, None, None)), ("0.9866", "PURE", (None, Decimal("0.9866"), None)),
     ("1234567", "SHARES", (None, Decimal(1234567), None)), ("n/a", "PURE", (None, None, None)),
     ("true", None, (None, None, True)), (" False ", None, (None, None, False)), ("Yes", None, (None, None, True)),
     ("******", None, (None, None, None)), ("Parent", None, (None, None, None))],
)  # fmt: skip
def test_typed_values_never_float_never_rescaled(text, unit, expected):
    assert typed_value(text, unit) == expected


def test_elecon_insider_elements_are_kept_with_their_dimensions():
    t = _tables(ELECON)
    rows = t["stg_disclosures"]
    (d,) = _cells(rows, F.DIRECTORS, FY26)
    assert F._axes(d["dimensions"]) == {
        "ClassificationBasedOnCurrentNoncurrentAxis": "CurrentMember",
        "ClassificationOfAssetsBasedOnSecurityAxis": "UnsecuredConsideredGoodMember",
    }
    assert all(":" in k and ":" in v for k, v in json.loads(d["dimensions"]).items())  # QNames as filed
    assert (d["value_inr"], d["value_text"], d["unit"], d["period_type"], d["in_window"], d["source_kind"]) == (
        Decimal("442100000"), "442100000", "INR", "INSTANT", True, "ANNUAL")  # fmt: skip
    others = _cells(rows, "TradeReceivablesDueByOthers", FY26)[0]["value_inr"]
    total = _cells(rows, "TradeReceivablesDueByDirectorsOtherOfficersOrOthers", FY26)[0]["value_inr"]
    assert total == d["value_inr"] + others == Decimal("6653800000")  # a subtotal that includes third parties
    assert {r["source_element"] for r in t["stg_xbrl_facts"]} & {F.DIRECTORS, F.FIRMS} == set()


def test_text_is_stored_as_filed_or_as_a_pointer_and_pre_cutoff_facts_are_not():
    data = (XBRL_DIR / ELIN).read_bytes()
    inst = parse_instance(data)
    m = parse_reg34_annual(data, ELIN).meta
    report = parse_disclosures(inst, frozenset(), Windows.from_meta(m), min_period_end=MIN_PERIOD_END_DATE,
                               source_kind="ANNUAL")  # fmt: skip
    assert report.skipped_pre_cutoff > 0  # FY24 comparatives (C9)
    assert all(f.period_end is None or f.period_end >= FY25 for f in report.facts)
    by_seq = {f.seq: f for f in inst.facts}
    short = [r for r in report.facts if r.value_text is not None]
    assert all(r.value_text == by_seq[r.seq].value_text for r in short)  # exactly as filed, not stripped
    assert all(len(r.value_text) <= D.TEXT_POINTER_CHARS and r.text_sha256 is None for r in short)
    pointers = [r for r in report.facts if r.value_text is None]
    assert len(pointers) == report.pointers > 0
    for r in pointers:  # TEXT_POINTER [X120]: length, sha256 of the text as filed, a plain-text snippet
        text = by_seq[r.seq].value_text
        assert (r.text_len, r.text_sha256) == (len(text), hashlib.sha256(text.encode()).hexdigest())
        assert 0 < len(r.text_snippet) <= D.SNIPPET_CHARS and "<" not in r.text_snippet and "  " not in r.text_snippet
    assert max(r.text_len for r in pointers) > 50_000  # notes text blocks: whole in the vault, a pointer here


def test_named_rules_of_disc_2():
    """X120: EXCLUDED_ELEMENT (per source kind), MASKED_VALUE and TEXT_POINTER, never on an element a reader reads."""
    data = (XBRL_DIR / ELIN).read_bytes()
    inst = parse_instance(data)
    m = parse_reg34_annual(data, ELIN).meta
    w = Windows.from_meta(m)
    annual = parse_disclosures(inst, frozenset(), w, min_period_end=None, source_kind="ANNUAL")
    results = parse_disclosures(inst, frozenset(), w, min_period_end=None, source_kind="RESULTS")
    excluded = {e for k, e in D.excluded_elements() if k == "ANNUAL"}
    filed = {f.name for f in inst.facts}
    assert annual.skipped_excluded == sum(f.name in excluded for f in inst.facts) > 0
    assert not {r.element for r in annual.facts} & excluded
    assert {r.element for r in results.facts} & excluded  # the list is per source kind
    masked = [f for f in inst.facts if D.is_masked(f.value_text) and f.name not in excluded]
    assert annual.skipped_masked == len(masked)
    assert not any(r.value_text and D.is_masked(r.value_text) for r in annual.facts)
    assert filed & D.READ_ELEMENTS  # ELIN files insider receivables and the Schedule III table
    kept = {r.seq: r for r in annual.facts}
    for f in inst.facts:  # every fact of an element a reader selects is stored exactly as under disc-1
        if f.name in D.READ_ELEMENTS:
            assert kept[f.seq].value_text == f.value_text and kept[f.seq].text_sha256 is None


@pytest.mark.parametrize(
    ("text", "masked"), [("******", True), ("*", True), (" ****** ", False), ("**12**", False), ("", False)]
)
def test_masked_values_are_asterisks_only(text, masked):
    assert D.is_masked(text) is masked


def test_snippet_strips_tags_entities_and_whitespace():
    assert D.snippet("<span /><p>47. INVESTMENTS</p>\n<p>A&amp;B\xa0 Ltd</p>") == "47. INVESTMENTS A&B Ltd"
    assert D.snippet("&lt;p&gt;Escaped &lt;b&gt;tags&lt;/b&gt;&lt;/p&gt;") == "Escaped tags"
    assert len(D.snippet("word " * 500)) == D.SNIPPET_CHARS


def test_exclusion_list_is_curated_pinned_and_never_names_an_element_a_reader_selects():
    """reference/disclosure_exclusions.csv (owner decision M): 783 (source_kind, element) pairs with a reason, pinned
    by EXCLUSIONS_SHA256; READ_ELEMENTS is derived here from the readers' own code, so a reader that starts selecting
    an element fails this test until the element is protected."""
    import csv
    import re

    from financials import filing_checks, related_parties

    with D.EXCLUSIONS_FILE.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == ["source_kind", "element", "reason"] and len(rows) == 783
    assert len({(r["source_kind"], r["element"]) for r in rows}) == 783 and all(r["reason"].strip() for r in rows)
    assert {r["source_kind"] for r in rows} <= {"RESULTS", "ANNUAL", "SHAREHOLDING", "EVENT"}
    assert D.exclusions_sha256(D.excluded_elements()) == D.EXCLUSIONS_SHA256
    read = {*F.INSIDER_ELEMENTS, F.ENTITY_NAME, F.ENTITY_TYPE, F.ENTITY_PROFIT}
    read |= {e + v for e in F.SHP_DECLARATIONS.values() for v in ("", *F.SHP_VARIANTS)}
    for mod in (filing_checks, related_parties):
        read |= set(re.findall(r"element = '(\w+)'", Path(mod.__file__).read_text(encoding="utf-8")))
    assert {"ScripCode", "NameOfCounterParty"} <= read <= D.READ_ELEMENTS
    assert not {e for _, e in D.excluded_elements()} & read


def test_shp16_entity_contexts_are_period_none():
    rows = _tables(OLD_SHP)["stg_disclosures"]
    flags = [r for r in rows if r["element"] == "WhetherTheListedEntityHasAnySignificantBeneficialOwner"]
    assert [(r["period_type"], r["period_end"], r["in_window"], r["value_bool"]) for r in flags] == [
        ("NONE", None, False, True)]  # fmt: skip


# ── coverage: every element of every parsed fixture reaches a clean table ─────────────────────────────────────────


def _blob_facts(data: bytes, kind: str) -> list[tuple[str, object]]:
    """[(element, context end or None)] of every fact of the file, read by the parser from the blob (decision J: the
    raw facts are the blob's, not a table's); SHP files through shp_instance, as staging reads them."""
    inst = shp_instance(data)[0] if kind == "SHP" else parse_instance(data)
    return [(f.name, inst.contexts[f.context_id].instant or inst.contexts[f.context_id].end) for f in inst.facts]


def _blob_values(data: bytes, kind: str) -> list[tuple[str, object, str]]:
    """[(element, context end or None, value_text)] of every fact of the file."""
    inst = shp_instance(data)[0] if kind == "SHP" else parse_instance(data)
    return [(f.name, inst.contexts[f.context_id].instant or inst.contexts[f.context_id].end, f.value_text)
            for f in inst.facts]  # fmt: skip


def _seq_texts(data: bytes, kind: str) -> list[tuple[int, str]]:
    inst = shp_instance(data)[0] if kind == "SHP" else parse_instance(data)
    return [(f.seq, f.value_text) for f in inst.facts]


def _staged_coverage(stage_dir, con, data: bytes, kind: str) -> tuple[set, set, set]:
    """(raw elements in scope, elements in the clean staged tables or left in the vault by a named disc-2 rule, raw
    elements only in pre-cutoff contexts). A vault-only element is one of the exclusion list for the filing's source
    kind, or one whose every in-scope value is masked (X120)."""
    raw = _blob_facts(data, kind)
    t = {n: read_table(con, stage_dir, n) for n in ("stg_xbrl_facts", "stg_segments", "stg_related_parties",
                                                     "stg_reg23_rpt", "stg_group_structure", "stg_shp_line_items",
                                                     "stg_shp_holders", "stg_events", "stg_disclosures")}  # fmt: skip
    clean = {r["source_element"] for r in t["stg_xbrl_facts"]} | {r["element"] for r in t["stg_segments"]}
    clean |= {r["source_element"] for r in t["stg_related_parties"]} | {r["element"] for r in t["stg_shp_line_items"]}
    clean |= {r["element"] for r in t["stg_disclosures"]}
    clean |= set(RPT_TEXT) if t["stg_related_parties"] else set()
    clean |= REG23_ELEMENTS if t["stg_reg23_rpt"] else set()
    clean |= HOLDER_ELEMENTS if t["stg_shp_holders"] else set()
    for rel in {r["relation"] for r in t["stg_group_structure"]}:
        clean |= verbatim_elements(rel)
    for e in t["stg_events"]:
        clean |= set(json.loads(e["details"]).get("numeric", {}))
    kept = {e for e, end in raw if t["stg_events"] or end is None or end >= MIN_PERIOD_END_DATE}
    pre = {e for e, _ in raw} - kept
    source_kind = {r["source_kind"] for r in t["stg_disclosures"]}
    assert len(source_kind) <= 1
    clean |= {e for k, e in D.excluded_elements() if k in source_kind}
    values = defaultdict(list)
    for e, end, v in _blob_values(data, kind):
        if t["stg_events"] or end is None or end >= MIN_PERIOD_END_DATE:
            values[e].append(v)
    clean |= {e for e, vs in values.items() if e not in D.READ_ELEMENTS and all(D.is_masked(v) for v in vs)}
    return kept, clean, pre


PROFILES = ("INDAS_CORP", "INDAS_NBFC", "IGAAP_BANK", "IRDAI_LIFE", "IRDAI_GENERAL", "INDAS_INSURANCE", "REG34_ANNUAL",
            "REG31_SHP", "REG23_RPT", "REG30_EVENT")  # fmt: skip


def test_every_element_of_every_parsed_fixture_reaches_a_clean_table(market):
    """X116, the decision J proof after the drop: for each committed XBRL fixture that parses, the staged batch the
    promoter loads holds every in-scope element of the file (parsed from the blob, not read from any table) in at
    least one clean table, or leaves it in the vault by a named disc-2 rule (X120: the exclusion list, masked values;
    a pointer row keeps its element); checked per accounting profile and file type, each with at least one real
    fixture (a results filing carrying the Reg. 23(9) section counts for REG23_RPT too). Every staged pointer row
    matches its fact in the blob."""
    checked, pointers = defaultdict(list), 0
    for path in sorted(XBRL_DIR.glob("*.xml")) + sorted((FIXTURES / "events").glob("*WebXMLFile*.xml")):
        data, url = path.read_bytes(), ARCHIVE + path.name
        if path.parent.name == "events":
            stage = stage_reg30_event(market.vault, market.stage_root, data=data, source_url=url, fetched_at=FETCHED)
        elif path.name.startswith("SHP"):
            stage = stage_shareholding(market.vault, market.stage_root, data=data, source_url=url, fetched_at=FETCHED)
        else:
            stage = stage_results_xbrl(market.vault, market.stage_root, data=data, source_url=url, fetched_at=FETCHED)
        if read_table(market.con, stage, "stg_issues") or not read_table(market.con, stage, "stg_disclosures"):
            continue  # not parsed (routed profile, quarantine, raw-only event family): nothing clean is promoted
        kind = "EVENT" if path.parent.name == "events" else "SHP" if path.name.startswith("SHP") else "RESULTS"
        kept, clean, _ = _staged_coverage(stage, market.con, data, kind)
        assert not (stage / "raw_xbrl_facts.parquet").exists()  # no raw copy is staged (decision J)
        assert kept - clean == set(), path.name
        texts = {seq: v for seq, v in _seq_texts(data, kind)}
        for r in read_table(market.con, stage, "stg_disclosures"):
            if r["value_text"] is None:
                assert r["text_sha256"] == hashlib.sha256(texts[r["seq"]].encode()).hexdigest(), path.name
                pointers += 1
            else:
                assert r["value_text"] == texts[r["seq"]], path.name
        meta = read_table(market.con, stage, "stg_xbrl_filing")
        profile = meta[0]["accounting_profile"] if meta else "REG30_EVENT" if path.parent.name == "events" else (
            "REG31_SHP")  # fmt: skip
        checked[profile].append(path.name)
        if read_table(market.con, stage, "stg_reg23_rpt"):
            checked["REG23_RPT"].append(path.name)
    assert [p for p in PROFILES if not checked[p]] == [], {p: len(v) for p, v in checked.items()}
    assert set(checked) <= set(PROFILES), set(checked)
    assert sum(len(v) for p, v in checked.items() if p != "REG23_RPT") >= 135
    assert pointers > 100


def test_captured_set_comes_from_the_rows_and_the_row_parsers_vocabularies():
    t = _tables(CUMMINS)
    cap = captured_elements(t)
    assert {r["source_element"] for r in t["stg_xbrl_facts"]} <= cap
    assert {r["element"] for r in t["stg_segments"]} <= cap and set(RPT_TEXT) <= cap
    assert verbatim_elements("SUBSIDIARY") <= cap or "SUBSIDIARY" not in {
        r["relation"] for r in t["stg_group_structure"]
    }
    # stored only as a sum (net worth) or as a fallback: kept as filed in disclosure_facts
    assert SCHEDULES["SUBSIDIARY"][1]["share_capital"] not in verbatim_elements("SUBSIDIARY")
    assert not cap & {r["element"] for r in t["stg_disclosures"]}


# ── features: pure functions on fixture rows ──────────────────────────────────────────────────────────────────────


def _insider(name: str, end: date) -> Decimal | None:
    by = defaultdict(list)
    for r in _tables(name)["stg_disclosures"]:
        if r["element"] in F.INSIDER_ELEMENTS and r["period_end"] == end and r["value_inr"] is not None:
            by[r["element"]].append((F._axes(r["dimensions"]), r["value_inr"]))
    return F.insider_total(by)


def test_insider_receivables_sum_without_double_counting():
    assert _insider(ELECON, FY26) == Decimal("442100000")  # directors only; ...OrOthers (third parties) is not added
    assert _insider(INOX, FY25) == Decimal("528618000")  # firms / companies subtotal = its one filed part, once
    assert _insider(INOX, FY26) == Decimal(0)
    assert _insider(CUMMINS, FY26) == Decimal(0)  # filed nil (0 in every class)
    assert F.insider_total({}) is None  # not filed


def test_element_total_uses_the_most_detailed_dimension_set_only():
    cur, non = {"A": "Current", "S": "Good"}, {"A": "Noncurrent", "S": "Good"}
    assert F.element_total([({"S": "Good"}, Decimal(5)), (cur, Decimal(2)), (non, Decimal(3))]) == Decimal(5)
    assert F.element_total([({"S": "Good"}, Decimal(5)), ({"S": "Doubtful"}, Decimal(1))]) == Decimal(6)


def _shp_values(name: str) -> dict:
    return {r["element"]: r["value_bool"] for r in _tables(name)["stg_disclosures"] if r["dimensions"] is None}


def test_shareholding_declarations():
    assert F.shp_columns(_shp_values(SAMMAAN)) == {
        "has_warrants": True, "has_convertibles": True, "has_partly_paid": True, "has_locked_in": True,
        "has_dvr_shares": True, "has_sbo": False, "is_psu": False}  # fmt: skip
    psu = F.shp_columns(_shp_values(PSU_SHP))
    assert (psu["is_psu"], psu["has_locked_in"], psu["has_warrants"]) == (True, True, False)
    assert F.shp_columns(_shp_values(OLD_SHP))["has_sbo"] is True  # 2022-09-30 taxonomy, SHP16 contexts
    assert F.shp_columns(None) == dict.fromkeys(F.SHP_DECLARATION_COLUMNS)


def test_declaration_falls_back_to_the_category_variants():
    e = F.SHP_DECLARATIONS["has_warrants"]
    assert F.declaration({e + "ForPromoterAndPromoterGroup": False, e + "ForPublicShareholder": True}, e) is True
    assert F.declaration({e + v: False for v in F.SHP_VARIANTS}, e) is False
    assert F.declaration({e: False, e + "ForPublicShareholder": True}, e) is False  # the entity-level value wins
    assert F.declaration({}, e) is None


def _subsidiary(name: str) -> dict:
    t = _tables(name)
    fy_end = t["stg_xbrl_filing"][0]["fy_end"]
    rows = defaultdict(dict)
    for r in t["stg_disclosures"]:
        axes = F._axes(r["dimensions"])
        if set(axes) == {F.ENTITY_AXIS} and r["period_end"] == fy_end and r["element"] in (
                F.ENTITY_NAME, F.ENTITY_TYPE, F.ENTITY_PROFIT):  # fmt: skip
            rows[axes[F.ENTITY_AXIS]][r["element"]] = r["value_inr"] if r["element"] == F.ENTITY_PROFIT else r[
                "value_text"]  # fmt: skip
    pat = next(r["value_inr"] for r in t["stg_xbrl_facts"] if r["canonical_tag"] == "pat"
               and r["period_end"] == fy_end and r["period_months"] == 12)  # fmt: skip
    return F.subsidiary_columns({"fy_end": fy_end, "rows": list(rows.values()), "pat": pat})


def test_subsidiary_contribution():
    c = _subsidiary(CUMMINS)  # Parent + an associate + a JV, no subsidiary
    assert c["parent_profit_share"] == pytest.approx(23301800000 / 23617500000)  # filed 0.9866
    assert (c["largest_subsidiary_profit_share"], c["consolidated_entities_count"]) == (None, 2)
    e = _subsidiary(ETERNAL)  # "Consolidation Adjustments" typed Parent; an NCI row
    assert e["parent_profit_share"] == pytest.approx(26550000000 / 3660000000)  # filed 7.25
    assert (e["largest_subsidiary_name"], e["consolidated_entities_count"]) == ("Zomato Payments Private Limited", 23)
    assert e["largest_subsidiary_profit_share"] == pytest.approx(80000000 / 3660000000)
    s = _subsidiary(SRF)  # "Adjustments arising out of consolidation" typed Indian Subsidiary
    assert s["parent_profit_share"] == pytest.approx(17246300000 / 18351800000)  # filed 0.9397
    assert (s["largest_subsidiary_name"], s["consolidated_entities_count"]) == ("SRF Global BV (Consolidated)", 4)
    t = _subsidiary(TCS)  # TCS files % of the pre-elimination sum (0.8548); the column uses the filing's PAT
    assert t["parent_profit_share"] == pytest.approx(490960000000 / 494540000000)
    assert t["largest_subsidiary_name"] == "Tata America International Corporation"
    # TCS files the NCI share of 7 subsidiaries as second rows typed "Subsidiary" with the subsidiary's name: 6 repeat
    # the name exactly, one does not ("... (South Africa) (PTY) Ltd." vs "(Proprietary) Limited"): 68 entities count 69
    assert t["consolidated_entities_count"] == 69
    p = _subsidiary(SPARC)  # subsidiaries only, no Parent row
    assert (p["parent_profit_share"], p["largest_subsidiary_name"]) == (None, "SPARCLIFE Inc.")


@pytest.mark.parametrize(
    ("name", "kind", "role"),
    [("Consolidation Adjustments", "Parent", "ADJUSTMENT"), ("Eternal Limited ", "Parent", "PARENT"),
     ("Non Controlling Interest in all Subsidiaries", "Non Controlling Interests In All Subsidiaries", "NCI"),
     ("Minority interest in all subsidiaries", "Indian Subsidiary", "NCI"), ("X Ltd", "Foreign Joint Venture",
     "JOINT_VENTURE"), ("Y Ltd", "Indian Associate", "ASSOCIATE"), ("Z Inc", "Foreign Subsidiary", "SUBSIDIARY")],
)  # fmt: skip
def test_entity_roles(name, kind, role):
    assert F.entity_role(name, kind) == role


# ── promotion, backfill, point-in-time features ───────────────────────────────────────────────────────────────────


@pytest.fixture
def filed(market):
    for day in ("20251023", "20261112"):  # the filers must be known on their broadcast dates
        promote(market.con, market.stage_day(day))
    for name, ts in ((ELECON, datetime(2026, 7, 23, 10, 42)), (CUMMINS, datetime(2026, 9, 4, 6, 5))):
        stage = stage_results_xbrl(market.vault, market.stage_root, data=(XBRL_DIR / name).read_bytes(),
                                   source_url=ARCHIVE + name, fetched_at=FETCHED, broadcast_ts=ts,
                                   broadcast_ts_source="API_FIELD")  # fmt: skip
        assert promote(market.con, stage).status == "PROMOTED"
        assert promote(market.con, stage).status == "ALREADY_PROMOTED"
    stage = stage_shareholding(market.vault, market.stage_root, data=(XBRL_DIR / SAMMAAN).read_bytes(),
                               source_url=ARCHIVE + SAMMAAN, fetched_at=FETCHED,
                               broadcast_ts=datetime(2026, 11, 4, 9, 59), broadcast_ts_source="API_FIELD")  # fmt: skip
    assert promote(market.con, stage).status == "PROMOTED"
    return market


def _counts(con):
    return con.execute("SELECT source_kind, count(*) FROM disclosure_facts GROUP BY 1 ORDER BY 1").fetchall()


def test_rows_are_promoted_with_their_filing_and_backfilled_idempotently(filed):
    con = filed.con
    staged = len(_tables(ELECON)["stg_disclosures"]) + len(_tables(CUMMINS)["stg_disclosures"])
    counts = dict(_counts(con))
    assert counts["ANNUAL"] == staged and counts["SHAREHOLDING"] == len(_tables(SAMMAAN)["stg_disclosures"])
    same = con.execute(
        """SELECT bool_and(d.visible_from_ts = m.visible_from_ts AND d.entity_id = m.entity_id AND d.scope = m.scope
                           AND d.parser_version = ?)
           FROM disclosure_facts d JOIN filing_meta m USING (filing_id)""", [DISCLOSURE_PARSER_VERSION]
    ).fetchone()[0]  # fmt: skip
    assert same is True
    assert pending_filings(con) == []
    before = _counts(con)
    assert not raw_xbrl.table_exists(con)  # decision J: no raw table
    snapshot = con.execute("SELECT * FROM disclosure_facts ORDER BY filing_id, seq").fetchall()
    con.execute("DELETE FROM disclosure_facts")  # as if promoted before X116
    con.execute("DELETE FROM materialize_dirty")
    # an interrupted run left one filing staged: it is reused, not re-parsed
    kind, fid, _, _, _, url, path, sha = pending_filings(con)[0]
    out = filed.stage_root / STAGE_DIR
    out.mkdir(parents=True)
    assert _stage_one((str(filed.vault.root), str(out), kind, fid, url, path, sha))[1] is None
    r = backfill_disclosures(con, filed.vault, filed.stage_root, workers=2)  # process pool, one insert
    assert (r["filings"], r["parsed"], r["rows"], r["error_count"]) == (3, 2, sum(n for _, n in before), 0)
    assert con.execute("SELECT * FROM disclosure_facts ORDER BY filing_id, seq").fetchall() == snapshot
    assert list(out.iterdir()) == []  # staged files removed after the commit
    assert {d for (d,) in con.execute("SELECT from_date FROM materialize_dirty WHERE reason = 'DISCLOSURE_BACKFILL'")
            .fetchall()} == {date(2026, 7, 23), date(2026, 9, 4), date(2026, 11, 4)}  # fmt: skip
    assert backfill_disclosures(con, filed.vault, filed.stage_root, workers=1)["filings"] == 0  # idempotent
    assert not raw_xbrl.table_exists(con)  # the backfill reads blobs, writes no raw copy
    assert con.execute("SELECT count(DISTINCT parser_version) FROM filing_meta").fetchone() == (1,)


def _row_for(con, symbol: str) -> dict:
    ent = con.execute("SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s "
                      "USING (security_id) WHERE h.symbol = ?", [symbol]).fetchone()[0]  # fmt: skip
    return {"entity_id": ent, "scope_used": None}


def test_columns_are_point_in_time(filed):
    con = filed.con
    rows = [_row_for(con, s) for s in ("ELECON", "CUMMINSIND", "SAMMAANCAP")]
    before = ist_to_utc(date(2026, 7, 23), datetime.min.time())
    F.add_columns(con, rows, before)
    assert all(r[c] is None for r in rows for c in F.COLUMNS)
    F.add_columns(con, rows, ist_to_utc(date(2026, 11, 5), datetime.min.time()))
    elecon, cummins, sammaan = rows
    recv = fetch_dicts(
        con,
        "SELECT canonical_tag, value_inr FROM fact_observations WHERE entity_id = ? AND "
        "canonical_tag LIKE 'trade_receivables_%' AND period_end = ?",
        [elecon["entity_id"], FY26],
    )
    den = sum(r["value_inr"] for r in recv)
    assert (elecon["insider_receivables"], elecon["insider_receivables_as_of"], elecon["has_insider_receivables"]) == (
        Decimal("442100000"), FY26, True)  # fmt: skip
    assert elecon["insider_receivables_to_receivables"] == pytest.approx(442100000 / float(den))
    assert (cummins["insider_receivables"], cummins["has_insider_receivables"]) == (Decimal(0), False)
    assert cummins["parent_profit_share"] == pytest.approx(23301800000 / 23617500000)
    assert cummins["consolidated_entities_count"] == 2 and elecon["subsidiary_fy_end"] is None  # standalone only
    assert (sammaan["has_warrants"], sammaan["has_dvr_shares"], sammaan["is_psu"]) == (True, True, False)
    assert elecon["has_warrants"] is None  # no shareholding filing loaded for ELECON
    later = [_row_for(con, "ELECON")]
    F.add_columns(con, later, ist_to_utc(date(2026, 7, 23), datetime.min.time()) + timedelta(days=1))
    assert later[0]["insider_receivables"] == Decimal("442100000")  # visible from the broadcast day


def test_full_text_reads_a_pointer_row_from_the_vault_and_verifies_it(filed):
    """X120: a pointer row's text comes back whole from the filing's vault blob, checked against its sha256."""
    from financials.disclosures import TextMismatch, full_text

    con = filed.con
    fid, seq, length, digest, snip = con.execute(
        "SELECT filing_id, seq, text_len, text_sha256, text_snippet FROM disclosure_facts WHERE value_text IS NULL "
        "ORDER BY text_len DESC, filing_id LIMIT 1").fetchone()  # fmt: skip
    text = full_text(con, filed.vault, fid, seq)
    assert len(text) == length > 50_000 and hashlib.sha256(text.encode()).hexdigest() == digest
    assert D.snippet(text) == snip
    sfid, sseq, short = con.execute("SELECT filing_id, seq, value_text FROM disclosure_facts WHERE value_text IS NOT "
                                    "NULL ORDER BY filing_id, seq LIMIT 1").fetchone()  # fmt: skip
    assert full_text(con, filed.vault, sfid, sseq) == short
    assert full_text(con, filed.vault, fid, -1) is None
    assert full_text(con, filed.vault, fid, seq, parser_version="disc-0") is None
    con.execute("UPDATE disclosure_facts SET text_sha256 = repeat('0', 64) WHERE filing_id = ? AND seq = ?", [fid, seq])
    with pytest.raises(TextMismatch):
        full_text(con, filed.vault, fid, seq)


def test_reparse_to_a_new_version_keeps_every_reader_answer_and_prunes_the_old_one(filed, tmp_path):
    """Owner decision M: `backfill-disclosures` re-parses filings whose rows are of an earlier version (disc-1 here:
    the rows relabelled, with the read values corrupted so a reader of the wrong version would show), the readers
    select the current version, nothing is marked dirty, and `prune-versions` archives and removes the old rows."""
    from financials import storage
    from financials.filing_checks import filed_scrip_code

    con = filed.con
    syms = ("ELECON", "CUMMINSIND", "SAMMAANCAP")
    as_of = ist_to_utc(date(2026, 11, 5), datetime.min.time())
    before = [_row_for(con, s) for s in syms]
    F.add_columns(con, before, as_of)
    fids = [f for (f,) in con.execute("SELECT DISTINCT filing_id FROM disclosure_facts ORDER BY 1").fetchall()]
    codes = {f: filed_scrip_code(con, f) for f in fids}
    current = con.execute("SELECT count(*) FROM disclosure_facts").fetchone()[0]
    con.execute("UPDATE disclosure_facts SET parser_version = 'disc-1'")
    con.execute("UPDATE disclosure_facts SET value_inr = value_inr + 1 WHERE value_inr IS NOT NULL")
    con.execute("UPDATE disclosure_facts SET value_bool = NOT value_bool, value_text = value_text || '9'")
    assert len(pending_filings(con)) == 3
    con.execute("DELETE FROM materialize_dirty")
    r = backfill_disclosures(con, filed.vault, filed.stage_root, workers=1)
    assert (r["filings"], r["rows"], r["error_count"]) == (3, current, 0)
    assert con.execute("SELECT count(*) FROM materialize_dirty").fetchone()[0] == 0  # a re-parse marks nothing
    after = [_row_for(con, s) for s in syms]
    F.add_columns(con, after, as_of)
    assert after == before and {f: filed_scrip_code(con, f) for f in fids} == codes
    res = storage.prune_versions(con, tmp_path / "archive")
    assert (res.status, res.removed) == ("PRUNED", current)
    assert con.execute("SELECT DISTINCT parser_version FROM disclosure_facts").fetchall() == [("disc-2",)]
    again = [_row_for(con, s) for s in syms]
    F.add_columns(con, again, as_of)
    assert again == before


def test_dsl_aliases_compile():
    for name in ("insider receivables pct", "parent profit share", "largest subsidiary profit share",
                 "consolidated entities", "insider receivables"):  # fmt: skip
        assert name in ALIASES
        compile_screen(f"{name} > 1")


def test_columns_are_appended_and_split_event_daily():
    from financials.db import declared_columns
    from financials.features_store import DAILY_COLUMNS, EVENT_COLUMNS

    names = [c for c, _ in declared_columns()["screener_features"]]
    assert names[-len(F.COLUMNS) :] == list(F.COLUMNS)
    assert {*F.INSIDER_COLUMNS, *F.SUBSIDIARY_COLUMNS} <= set(EVENT_COLUMNS)  # annual filings: in the cache key
    assert set(F.SHP_DECLARATION_COLUMNS) <= set(DAILY_COLUMNS)  # shareholding is outside the key


# ── decision J: the coverage gate and the one-shot drop of raw_xbrl_facts ─────────────────────────────────────────

# The table as schema.sql declared it before decision J; a pre-J database still holds it.
LEGACY_RAW_DDL = """CREATE TABLE raw_xbrl_facts (
    filing_id VARCHAR NOT NULL REFERENCES filings(filing_id), parser_version VARCHAR NOT NULL, seq INTEGER NOT NULL,
    element_ns VARCHAR NOT NULL, element_name VARCHAR NOT NULL, context_id VARCHAR NOT NULL, ctx_start DATE,
    ctx_end DATE, ctx_instant DATE, dimensions JSON, unit_ref VARCHAR, decimals VARCHAR, value_text VARCHAR,
    PRIMARY KEY (filing_id, parser_version, seq))"""


def _legacy_raw_table(market) -> int:
    """Recreate raw_xbrl_facts as the pre-J promoter filled it (every fact of every vaulted XBRL filing, verbatim),
    from the vault blobs. Returns its row count."""
    import pyarrow as pa

    from financials import PARSER_VERSION

    con = market.con
    con.execute(LEGACY_RAW_DDL)
    rows = []
    for fid, cat, path, sha in con.execute(
        "SELECT f.filing_id, f.category, b.storage_path, b.sha256 FROM filings f JOIN blobs b USING (sha256) "
        "WHERE f.category IN ('RESULTS_XBRL', 'SHP_XBRL', 'REG30_EVENT')"
    ).fetchall():
        data = market.vault.read_path(path, sha)
        inst = shp_instance(data)[0] if cat == "SHP_XBRL" else parse_instance(data)
        for f in inst.facts:
            c = inst.contexts[f.context_id]
            dims = json.dumps(dict(c.dimensions)) if c.dimensions else None
            rows.append({"filing_id": fid, "parser_version": PARSER_VERSION, "seq": f.seq, "element_ns": f.ns,
                         "element_name": f.name, "context_id": f.context_id, "ctx_start": c.start, "ctx_end": c.end,
                         "ctx_instant": c.instant, "dimensions": dims,
                         "unit_ref": f.unit_ref, "decimals": f.decimals, "value_text": f.value_text})  # fmt: skip
    con.register("_raw", pa.Table.from_pylist(rows))
    con.execute("INSERT INTO raw_xbrl_facts BY NAME SELECT * FROM _raw")
    con.unregister("_raw")
    return len(rows)


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("disclosure_coverage", FIXTURES.parents[1] / "scripts" /
                                                  "disclosure_coverage.py")  # fmt: skip
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_coverage_script_finds_every_element_in_a_clean_table(filed):
    """scripts/disclosure_coverage.py (financials.raw_xbrl.coverage, the gate of drop-raw-xbrl) on promoted real
    filings of a database that still holds raw_xbrl_facts."""
    assert raw_xbrl.coverage(filed.con) is None  # no raw table: nothing to measure
    assert _legacy_raw_table(filed) > 0
    rows = {r["profile"]: r for r in raw_xbrl.coverage(filed.con)}
    assert set(rows) >= {"REG34_ANNUAL", "REG31_SHP"} and all(r["uncaptured"] == 0 for r in rows.values()), rows
    assert _script().coverage is raw_xbrl.coverage
    filed.con.execute("DELETE FROM disclosure_facts")
    assert raw_xbrl.coverage(filed.con)[0]["uncaptured"] > 0  # the check fails without disclosure_facts


def test_drop_raw_xbrl_is_gated_audited_idempotent_and_compacts(filed, monkeypatch):
    from financials import storage
    from financials.cli import main
    from financials.db import apply_schema, connect

    con = filed.con
    n = _legacy_raw_table(filed)
    pre = con.execute("SELECT count(*) FROM raw_xbrl_facts WHERE coalesce(ctx_instant, ctx_end) < ?",
                      [MIN_PERIOD_END_DATE]).fetchone()[0]  # fmt: skip
    assert pre > 0  # the annual reports' FY24 comparatives: vault only after the drop (C9)
    # the gate: an element no clean table holds refuses the drop and changes nothing
    con.execute("CREATE TEMP TABLE keep AS SELECT * FROM disclosure_facts")
    con.execute("DELETE FROM disclosure_facts")
    r = raw_xbrl.drop_raw_xbrl(con)
    assert r.status == "REFUSED" and "uncaptured" in r.message and raw_xbrl.table_exists(con)
    assert con.execute("SELECT count(*) FROM admin_log WHERE action = 'DROP_RAW_XBRL'").fetchone()[0] == 0
    con.execute("INSERT INTO disclosure_facts SELECT * FROM keep")
    # a pre-J database refuses compaction until the table is dropped (never dropped silently)
    con.close()
    path = filed.vault.root.parent / "market.duckdb"
    for res in (storage.compact(path), storage.compact_via_spill(path, path.parent / "spill")):
        assert res.status == "REFUSED" and "drop-raw-xbrl" in res.message
    monkeypatch.setattr(storage, "AUTO_COMPACT_MIN_BYTES", 0)
    monkeypatch.setattr(storage, "AUTO_COMPACT_MIN_DEAD", 0)
    out = io.StringIO()
    assert main(["--data-dir", str(path.parent), "drop-raw-xbrl"], out=out) == 0, out.getvalue()
    text = out.getvalue()
    assert "drop-raw-xbrl: DROPPED" in text and "compact: COMPACTED" in text, text
    con = filed.con = connect(path)
    assert not raw_xbrl.table_exists(con)
    (params, result, note) = con.execute(
        "SELECT params, result, note FROM admin_log WHERE action = 'DROP_RAW_XBRL'").fetchone()  # fmt: skip
    result = json.loads(result)
    assert json.loads(params)["decision"] == "J" and "decision J" in note
    assert (result["rows"], result["pre_cutoff_values"]) == (n, pre) and result["unpromoted_values"] == 0
    assert all(c["uncaptured"] == 0 for c in result["coverage"])
    assert apply_schema(con) == [] and not raw_xbrl.table_exists(con)  # never recreated
    assert raw_xbrl.drop_raw_xbrl(con).status == "ALREADY_DROPPED"
    con.close()
    out = io.StringIO()
    assert main(["--data-dir", str(path.parent), "drop-raw-xbrl", "--spill", str(path.parent / "spill")],
                out=out) == 0  # fmt: skip
    assert "ALREADY_DROPPED" in out.getvalue() and "compact: COMPACTED" in out.getvalue()  # spill mode, no raw table
    assert main(["--data-dir", str(path.parent), "compact"], out=io.StringIO()) == 0
    filed.con = connect(path)
    assert filed.con.execute("SELECT count(*) FROM admin_log WHERE action = 'DROP_RAW_XBRL'").fetchone()[0] == 1


def test_clean_rows_answer_what_the_raw_table_answered():
    """Decision J: the two readers that queried raw_xbrl_facts by element get the same answer from the clean rows,
    on every results / annual fixture that parses: the non-dimensional ScripCode (G79, filing_checks.filed_scrip_code:
    disclosure_facts, never a fact_observations line item) and whether the filing carries a Reg. 23(9) counterparty
    (related_parties.pending_results_filings: reg23 rows or NameOfCounterParty in disclosure_facts)."""
    checked = 0
    for path in sorted(XBRL_DIR.glob("*.xml")):
        if path.name.startswith("SHP"):
            continue
        data = path.read_bytes()
        inst = parse_instance(data)
        t = results_tables("fil_x", inst, data, ARCHIVE + path.name)
        if t.get("stg_issues"):
            continue
        raw_code = {f.value_text.strip() for f in inst.facts
                    if f.name == "ScripCode" and not inst.contexts[f.context_id].dimensions}  # fmt: skip
        clean_code = {r["value_text"].strip() for r in t["stg_disclosures"]
                      if r["element"] == "ScripCode" and r["dimensions"] is None}  # fmt: skip
        assert raw_code == clean_code, path.name
        assert not any(r["source_element"] == "ScripCode" for r in t.get("stg_xbrl_facts", [])), path.name
        if t["stg_xbrl_filing"][0]["accounting_profile"] != "REG34_ANNUAL":
            raw_cp = any(f.name == "NameOfCounterParty" for f in inst.facts)
            clean_cp = bool(t.get("stg_reg23_rpt")) or any(r["element"] == "NameOfCounterParty"
                                                            for r in t["stg_disclosures"])  # fmt: skip
            assert raw_cp == clean_cp, path.name
        checked += 1
    assert checked >= 100


def test_scope_gate_reads_the_declared_period_end_from_the_manifest_or_a_pre_j_stage(market, tmp_path):
    """The promoter's C9 gate needs the file's DateOfEndOfReportingPeriod: new stages carry it in the manifest (no raw
    Parquet is staged since decision J); a batch staged before J still carries raw_xbrl_facts.parquet and is read."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from financials.promoter import _declared_period_end
    from financials.staging import read_manifest

    stage = stage_results_xbrl(market.vault, market.stage_root, data=(XBRL_DIR / ELECON).read_bytes(),
                               source_url=ARCHIVE + ELECON, fetched_at=FETCHED)  # fmt: skip
    m = read_manifest(stage)
    assert m["declared_period_ends"] and _declared_period_end(market.con, stage, m) == FY26
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    pq.write_table(pa.table({"element_name": ["DateOfEndOfReportingPeriod", "ScripCode"],
                             "value_text": [" 2025-12-31 ", "500180"]}), legacy / "raw_xbrl_facts.parquet")  # fmt: skip
    assert _declared_period_end(market.con, legacy, {"job": "results_xbrl"}) == date(2025, 12, 31)
    assert _declared_period_end(market.con, tmp_path, {"job": "results_xbrl"}) is None  # nothing staged: no gate
