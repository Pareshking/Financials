"""Audit-opinion flags from the auditor's report text [X121-X124] (parsers/audit_report.py, audit_opinions,
features_audit, forensic_clean). Characterisation values are read from committed, unmodified fixtures (MANIFEST.md,
"Audit opinions"); the rule tests on short strings pin the negations and boilerplate the text rules must ignore."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from _fixture_helpers import AUDIT_OPINION_FIXTURES, FIXTURES, XBRL_DIR
from financials import features_audit as FA
from financials import features_gems as G
from financials.audit_opinions import STAGE_DIR, _stage_one, backfill_audit_opinions, pending_filings
from financials.dsl import ALIASES, compile_screen
from financials.parsers import audit_report as A
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.parsers.xbrl import parse_instance
from financials.promoter import promote
from financials.staging import results_tables, stage_results_xbrl
from financials.timeutil import ist_to_utc

ARCHIVE = "https://nsearchives.nseindia.com/corporate/xbrl/"
FETCHED = datetime(2026, 11, 14, 6)
FY25, FY26 = date(2025, 3, 31), date(2026, 3, 31)

# file -> (scope, audit_opinion, opinion_rule, going_concern_uncertainty, going_concern_component, emphasis_of_matter,
#          checkbox_qualified, opinion_conflict)
ANNUAL = {
    # UNMODIFIED (fixtures committed for earlier batches)
    "AR_XBRL_TCS_09082026012216.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", False, False, False, False,
                                       False),
    "AR_XBRL_ELECON_23072026161247.xml": ("STANDALONE", "UNMODIFIED", "OPINION_HEADING", False, False, False, False,
                                          False),
    "AR_XBRL_ETERNAL_23092026175418.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", False, False, True, False,
                                           False),
    # QUALIFIED
    "AR_XBRL_TITAGARH_13012026105336.xml": ("STANDALONE", "QUALIFIED", "OPINION_HEADING", False, False, False, True,
                                            False),
    "AR_XBRL_JPPOWER_13012026113224.xml": ("CONSOLIDATED", "QUALIFIED", "OPINION_HEADING", False, True, True, True,
                                           False),
    # QUALIFIED / DISCLAIMER in the text while the checkbox says false (the conflicts)
    "AR_XBRL_RKFORGE_24102025122553.xml": ("CONSOLIDATED", "QUALIFIED", "OPINION_HEADING", False, False, True, False,
                                           True),
    "AR_XBRL_VARROC_02092026142002.xml": ("CONSOLIDATED", "QUALIFIED", "OPINION_HEADING", False, False, True, False,
                                          True),
    "AR_XBRL_RELINFRA_18092026172005.xml": ("STANDALONE", "DISCLAIMER", "OPINION_HEADING", False, False, True, False,
                                            True),
    # DISCLAIMER
    "AR_XBRL_RELINFRA_06092025221939.xml": ("STANDALONE", "DISCLAIMER", "OPINION_HEADING", False, False, True, True,
                                            False),
    # going-concern material uncertainty about the group / company
    "AR_XBRL_MMTC_11022026110533.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", True, False, True, True,
                                        True),
    "AR_XBRL_IDEA_19092025180318.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", True, False, False, False,
                                        False),
    # ... about a component only (GOING_CONCERN_COMPONENT): another auditor's finding, an entity sub-heading
    "AR_XBRL_RPOWER_06092025221905.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", False, True, True, False,
                                          False),
    "AR_XBRL_CONCOR_11022026153323.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", False, True, True, False,
                                          False),
    # emphasis of matter (informational)
    "AR_XBRL_MFSL_17102025125715.xml": ("STANDALONE", "UNMODIFIED", "OPINION_HEADING", False, False, True, False,
                                        False),
    "AR_XBRL_BEML_13012026164812.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", False, False, True, True,
                                        True),
    # internal-financial-controls "Qualified Opinion" in the annexure only; the checkbox says true
    "AR_XBRL_VENTIVE_23092025192320.xml": ("STANDALONE", "UNMODIFIED", "OPINION_HEADING", False, False, False, True,
                                           True),
    # a component auditor's disclaimer / going-concern headings quoted in the consolidated report
    "AR_XBRL_OIL_17102025191837.xml": ("CONSOLIDATED", "UNMODIFIED", "OPINION_HEADING", False, False, True, False,
                                       False),
    # the report filed as one paragraph (no line breaks): OPINION_PARAGRAPH
    "AR_XBRL_SWANCORP_13012026103454.xml": ("STANDALONE", "UNMODIFIED", "OPINION_PARAGRAPH", False, False, False,
                                            False, False),
    # no report text: "As per Attachment"; a CARO / IFC annexure only
    "AR_XBRL_SUNTV_13012026154758.xml": ("CONSOLIDATED", None, "NO_REPORT", None, None, None, False, None),
    "AR_XBRL_MTARTECH_13012026142914.xml": ("CONSOLIDATED", None, "NO_REPORT", None, None, None, False, None),
}  # fmt: skip

# file -> (scope, period_end, declaration, audit_opinion, opinion_rule, qualification_count, repetitive)
RESULTS = {
    "INTEGRATED_FILING_INDAS_1672621_25052026073245_WEB.xml": ("CONSOLIDATED", FY26, "UNMODIFIED", "UNMODIFIED",
                                                               "DECLARATION", None, None),
    "INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml": ("STANDALONE", date(2026, 9, 30), "NOT_APPLICABLE", None,
                                                               "NO_OPINION", None, None),
    "INTEGRATED_FILING_INDAS_1707551_04082026041230_WEB.xml": ("CONSOLIDATED", date(2026, 6, 30), "STATEMENT",
                                                               "QUALIFIED", "OPINION_OF_AUDITORS", 1, False),
    "INTEGRATED_FILING_INDAS_1461904_01062025070430_WEB.xml": ("CONSOLIDATED", FY25, "STATEMENT", "QUALIFIED",
                                                               "OPINION_OF_AUDITORS", 1, False),
    "INTEGRATED_FILING_INDAS_1461165_30052025115826_WEB.xml": ("CONSOLIDATED", FY25, "STATEMENT", "QUALIFIED",
                                                               "OPINION_OF_AUDITORS", None, None),
    "INTEGRATED_FILING_INDAS_1758732_14112026091104_WEB.xml": ("CONSOLIDATED", date(2026, 9, 30), "STATEMENT",
                                                               "DISCLAIMER", "OPINION_OF_AUDITORS", 1, False),
    "INTEGRATED_FILING_INDAS_1449896_24052025124314_WEB.xml": ("CONSOLIDATED", FY25, "STATEMENT", "DISCLAIMER",
                                                               "OPINION_OF_AUDITORS", 2, True),
    "INTEGRATED_FILING_INDAS_1672152_23052026112720_WEB.xml": ("CONSOLIDATED", FY26, "STATEMENT", "DISCLAIMER",
                                                               "OPINION_OF_AUDITORS", 3, True),
}  # fmt: skip


def test_the_evidence_set_is_the_manifest_section():
    """Every new fixture is a characterisation case here and a MANIFEST.md row of the "Audit opinions" section."""
    section = (FIXTURES / "MANIFEST.md").read_text(encoding="utf-8").split("## Audit opinions")[1].split("\n## ")[0]
    listed = {line.split("`")[1].removeprefix("xbrl/") for line in section.splitlines() if line.startswith("| `")}
    assert listed == AUDIT_OPINION_FIXTURES
    assert (set(ANNUAL) | set(RESULTS)) >= AUDIT_OPINION_FIXTURES


def _row(name: str) -> dict:
    data = (XBRL_DIR / name).read_bytes()
    tables = results_tables("fil_x", parse_instance(data), data, ARCHIVE + name)
    assert not tables.get("stg_issues"), tables.get("stg_issues")
    (row,) = tables["stg_audit_opinions"]
    return row


# ── characterisation on real filings [X121-X123] ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(ANNUAL))
def test_annual_report_text_flags(name):
    r = _row(name)
    keys = ("scope", "audit_opinion", "opinion_rule", "going_concern_uncertainty", "going_concern_component",
            "emphasis_of_matter", "checkbox_qualified", "opinion_conflict")  # fmt: skip
    got = tuple(r[k] for k in keys)
    assert got == ANNUAL[name]
    assert r["source_kind"] == "ANNUAL" and r["parser_version"] == A.AUDIT_PARSER_VERSION
    # the checkbox recorded here is the value filing_meta.auditor_qualified holds (one rule, X75): reconciled
    assert parse_reg34_annual((XBRL_DIR / name).read_bytes(), name).meta["auditor_qualified"] == r["checkbox_qualified"]


@pytest.mark.parametrize("name", sorted(RESULTS))
def test_results_audit_fields(name):
    r = _row(name)
    got = (r["scope"], r["period_end"], r["declaration"], r["audit_opinion"], r["opinion_rule"],
           r["qualification_count"], r["qualification_repetitive"])  # fmt: skip
    assert got == RESULTS[name]
    assert r["going_concern_uncertainty"] is None and r["emphasis_of_matter"] is None and r["text_sha256"] is None
    assert r["checkbox_qualified"] is {"STATEMENT": True, "UNMODIFIED": False}.get(r["declaration"])
    assert r["opinion_conflict"] is (None if r["audit_opinion"] is None else False)


def test_mixed_qualification_types_take_the_most_severe():
    """RELINFRA Q4 FY26: two disclaimers and one qualified opinion on AuditQualificationAxis; OpinionOfAuditors
    "Disclaimer of opinion"; the type fallback gives the same answer."""
    inst = parse_instance((XBRL_DIR / "INTEGRATED_FILING_INDAS_1672152_23052026112720_WEB.xml").read_bytes())
    types = sorted(f.value_text for f in inst.facts if f.name == A.TYPE_ELEMENT)
    assert types == ["Disclaimer of opinion", "Disclaimer of opinion", "Qualified opinion"]
    r = A.classify_results("Statement on impact of audit qualification", None, types, [None] * 3)
    assert (r.audit_opinion, r.opinion_rule) == ("DISCLAIMER", "TYPE_OF_QUALIFICATION")


def test_report_text_is_read_whole_and_hashed():
    r = _row("AR_XBRL_RKFORGE_24102025122553.xml")
    inst = parse_instance((XBRL_DIR / "AR_XBRL_RKFORGE_24102025122553.xml").read_bytes())
    (text,) = [f.value_text for f in inst.facts if f.name == A.REPORT_ELEMENT]
    assert r["text_len"] == len(text) > 1000 and r["text_sha256"] == A.text_sha256(text)


# ── the rules on short strings: headings, negations, boilerplate ──────────────────────────────────────────────────

BOILERPLATE = (
    "<p>Basis for Opinion</p><p>We conducted our audit in accordance with the Standards on Auditing.</p>"
    "<p>Key Audit Matters</p><p>We do not provide a separate opinion on these matters.</p>"
    "<p>Our opinion is not modified in respect of this matter.</p>"
    "<p>Conclude on the appropriateness of management's use of the going concern basis of accounting and, based on "
    "the audit evidence obtained, whether a material uncertainty exists related to events or conditions that may cast "
    "significant doubt on the Company's ability to continue as a going concern.</p>"
    "<p>We have not identified any material uncertainty related to going concern.</p>"
    "<p>The Board of Directors is responsible for assessing the Company's ability to continue as a going concern.</p>"
)


def _report(*paragraphs: str, tail: str = BOILERPLATE) -> str:
    return "<p>Independent Auditor's Report</p>" + "".join(f"<p>{p}</p>" for p in paragraphs) + tail


@pytest.mark.parametrize(
    ("text", "opinion", "going", "emphasis"),
    [
        (_report("Opinion", "In our opinion ... give a true and fair view."), "UNMODIFIED", False, False),
        (_report("**Opinion**", "In our opinion ..."), "UNMODIFIED", False, False),
        (_report("1. Unmodified Opinion"), "UNMODIFIED", False, False),
        (_report("Qualified Opinion", "Except for the effects of ...", "Basis for Qualified Opinion"), "QUALIFIED",
         False, False),
        (_report("Opinion", "Basis for Qualified Opinion"), "QUALIFIED", False, False),
        (_report("Adverse Opinion", "Basis for Adverse Opinion"), "ADVERSE", False, False),
        (_report("Disclaimer of Opinion", "We were engaged to audit ...", "Basis for Disclaimer of Opinion"),
         "DISCLAIMER", False, False),
        (_report("Report on the Audit of the Standalone Financial Statements Qualified Opinion"), "QUALIFIED", False,
         False),
        (_report("Qualified Opinion We have audited the accompanying standalone financial statements of X."),
         "QUALIFIED", False, False),
        (_report("O pi n i on", "B a s i s f or O p i nion"), "UNMODIFIED", False, False),  # letter-spaced
        (_report("Opinion", "(a) Material Uncertainty Related to Going Concern", "We draw attention to Note 5 ..."),
         "UNMODIFIED", True, False),
        (_report("Opinion", "Material uncertainty relating to the going concern"), "UNMODIFIED", True, False),
        (_report("Opinion", "Emphasis of Matter – Scheme of Amalgamation", "We draw attention to Note 54."),
         "UNMODIFIED", False, True),
        (_report("Opinion", "Emphasisof Matters"), "UNMODIFIED", False, True),
        # a heading glued to the end of the preceding paragraph
        (_report("Opinion", "We believe that the audit evidence is sufficient to provide a basis for our opinion. "
                 "Emphasis of Matter", "We draw attention to Note 4."), "UNMODIFIED", False, True),
        # sentences are never headings
        (_report("Opinion", "The auditors of the subsidiary have included an Emphasis of Matter paragraph."),
         "UNMODIFIED", False, False),
    ],
)  # fmt: skip
def test_heading_rules(text, opinion, going, emphasis):
    f = A.classify_report(text)
    assert (f.audit_opinion, f.opinion_rule, f.going_concern_uncertainty, f.emphasis_of_matter) == (
        opinion, "OPINION_HEADING", going, emphasis)  # fmt: skip


def test_annexures_and_quotations_are_not_the_report():
    ifc = ("<p>Report on Other Legal and Regulatory Requirements</p><p>Annexure B to the Independent Auditor's Report"
           "</p><p>Qualified Opinion</p><p>Disclaimer of Opinion</p>"
           "<p>Material Uncertainty Related to Going Concern</p>")  # fmt: skip
    assert A.classify_report(_report("Opinion") + ifc).audit_opinion == "UNMODIFIED"
    quoted = _report(
        "Opinion",
        "The auditors of X BV have reported a Disclaimer of Opinion as under:",
        "“Disclaimer of Opinion”",
        "“Material Uncertainty relating to Going Concern”",
    )
    assert (A.classify_report(quoted).audit_opinion, A.classify_report(quoted).going_concern_uncertainty) == (
        "UNMODIFIED", False)  # fmt: skip
    # an exhibit label above the report is not an annexure heading; an annexure-only text has no report
    assert A.classify_report("<p>Annexure-X</p>" + _report("Opinion")).audit_opinion == "UNMODIFIED"
    annex = "<p>Annexure ‘1’ referred to in paragraph 2 of our report</p><p>Opinion</p><p>We have audited the IFC.</p>"
    assert A.classify_report(annex).opinion_rule == "NO_REPORT"
    assert A.heading_kind("Opinion on the Company’s internal financial controls with reference to financial "
                          "statements") is None  # fmt: skip


@pytest.mark.parametrize(
    ("text", "opinion"),
    [
        ("To the Members of X. In our opinion the statements give a true and fair view of the state of affairs.",
         "UNMODIFIED"),
        ("In our opinion, except for the effects of the matter described, the statements give a true and fair view.",
         "QUALIFIED"),
        ("Because of the significance of the matters, we do not express an opinion on the accompanying standalone "
         "financial statements.", "DISCLAIMER"),
        ("In our opinion, the statements do not give a true and fair view.", "ADVERSE"),
        ("As per Attachment", None),
        ("", None),
        ("<p>&nbsp;</p>", None),
    ],
)  # fmt: skip
def test_paragraph_rule_without_headings(text, opinion):
    f = A.classify_report(text)
    assert f.audit_opinion == opinion
    assert f.opinion_rule == ("NO_REPORT" if opinion is None else "OPINION_PARAGRAPH")
    assert f.going_concern_uncertainty is (None if opinion is None else False)


def test_going_concern_component_rule_applies_to_consolidated_reports_only():
    sub = _report(
        "Opinion",
        "(ii) In respect of HALBIT Avionics Private Ltd",
        "Material Uncertainty Related to Going Concern",
        "The Company has a net liability ...",
    )
    other = _report(
        "Opinion",
        "Material Uncertainty Related to Going Concern",
        "(a) The auditors of Jindal Steel & Power (Mauritius) Limited have drawn attention to ...",
        "Our opinion is not modified in respect of above matter.",
    )
    named = _report("Opinion", "Material Uncertainty related to the going concern - of Subsidiary Companies:")
    group = _report(
        "Opinion",
        "Material Uncertainty Related to Going Concern",
        "Statutory Auditors of certain subsidiaries have highlighted Emphasis of Matter paragraphs ...",
        "We draw attention to Note 38 regarding the Group’s ability to meet its obligations.",
    )
    for text, component in ((sub, True), (other, True), (named, True), (group, False)):
        f = A.classify_report(text, "CONSOLIDATED")
        assert (f.going_concern_uncertainty, f.going_concern_component) == (not component, component)
        assert A.classify_report(text, "STANDALONE").going_concern_uncertainty is True


def test_checkbox_results_and_conflict_rules():
    assert [A.checkbox(v) for v in ("true", " FALSE ", "True", "yes", "", None)] == [True, False, True, None, None,
                                                                                    None]  # fmt: skip
    assert A.conflict("QUALIFIED", False) is True and A.conflict("UNMODIFIED", True) is True
    assert A.conflict("DISCLAIMER", True) is False and A.conflict(None, True) is None
    na = A.classify_results("Not applicable", None, [], [])
    assert (na.declaration, na.audit_opinion, na.checkbox) == ("NOT_APPLICABLE", None, None)
    odd = A.classify_results("Something else", None, [], [])  # never observed: kept verbatim, no opinion
    assert (odd.declaration, odd.audit_opinion, odd.opinion_rule) == ("Something else", None, "NO_OPINION")
    bare = A.classify_results("Statement on impact of audit qualification", None, [], [])
    assert (bare.audit_opinion, bare.opinion_rule) == (None, "NO_OPINION")
    assert A.worst(["UNMODIFIED", None, "QUALIFIED"]) == "QUALIFIED" and A.worst([None]) is None


# ── promotion, backfill (vault), point-in-time features ───────────────────────────────────────────────────────────

FILED = (  # (file, broadcast IST): broadcasts after the market's first loaded day, so the filers resolve
    ("AR_XBRL_RKFORGE_24102025122553.xml", datetime(2025, 10, 24, 12, 25)),
    ("AR_XBRL_RELINFRA_18092026172005.xml", datetime(2026, 9, 18, 17, 20)),
    ("INTEGRATED_FILING_INDAS_1672152_23052026112720_WEB.xml", datetime(2026, 5, 23, 11, 27)),
    ("INTEGRATED_FILING_INDAS_1707551_04082026041230_WEB.xml", datetime(2026, 8, 4, 4, 12)),
)


@pytest.fixture
def filed(market):
    for day in ("20251023", "20261112"):
        promote(market.con, market.stage_day(day))
    for name, ist in FILED:
        stage = stage_results_xbrl(market.vault, market.stage_root, data=(XBRL_DIR / name).read_bytes(),
                                   source_url=ARCHIVE + name, fetched_at=FETCHED,
                                   broadcast_ts=ist_to_utc(ist.date(), ist.time()),
                                   broadcast_ts_source="API_FIELD")  # fmt: skip
        assert promote(market.con, stage).status in ("PROMOTED", "QUARANTINED")
    return market


def _rows(con):
    return con.execute("SELECT * FROM audit_opinions ORDER BY filing_id").fetchall()


def test_rows_are_promoted_with_their_filing_and_backfilled_from_the_vault(filed):
    con = filed.con
    assert con.execute("SELECT count(*) FROM audit_opinions").fetchone() == (len(FILED),)
    same = con.execute(
        """SELECT bool_and(a.visible_from_ts = m.visible_from_ts AND a.entity_id = m.entity_id AND a.scope = m.scope
                           AND a.audit_opinion_id = 'audit_' || left(sha256(a.filing_id || chr(31) || ?), 24))
           FROM audit_opinions a JOIN filing_meta m USING (filing_id)""",
        [A.AUDIT_PARSER_VERSION],
    ).fetchone()[0]
    assert same is True
    assert pending_filings(con) == []
    snapshot = _rows(con)
    con.execute("DELETE FROM audit_opinions")  # as if promoted before X121
    con.execute("DELETE FROM materialize_dirty")
    pending = pending_filings(con)
    assert len(pending) == len(FILED)
    annual = [p for p in pending if p[1] == "REG34_ANNUAL"]
    assert all(p[6] is not None for p in annual)  # the report rows are disclosure_facts pointers (X120)
    fid, profile, scope, end, path, sha, expected = pending[0]  # an interrupted run left one filing staged
    out = filed.stage_root / STAGE_DIR
    out.mkdir(parents=True)
    assert _stage_one((str(filed.vault.root), str(out), fid, profile, scope, end, path, sha, expected))[1] is None
    r = backfill_audit_opinions(con, filed.vault, filed.stage_root, workers=2)
    assert (r["filings"], r["parsed"], r["rows"], r["error_count"]) == (4, 3, 4, 0)
    assert _rows(con) == snapshot and list(out.iterdir()) == []
    assert con.execute("SELECT count(DISTINCT entity_id) FROM materialize_dirty WHERE reason = "
                       "'AUDIT_OPINION_BACKFILL'").fetchone() == (3,)  # fmt: skip
    assert backfill_audit_opinions(con, filed.vault, filed.stage_root, workers=1)["filings"] == 0  # idempotent
    # a vault text that does not match the pointer row's sha256 is reported, never written
    con.execute("DELETE FROM audit_opinions WHERE source_kind = 'ANNUAL'")
    con.execute(f"UPDATE disclosure_facts SET text_sha256 = repeat('0', 64) WHERE element = '{A.REPORT_ELEMENT}'")
    r = backfill_audit_opinions(con, filed.vault, filed.stage_root, workers=1)
    assert (r["rows"], r["error_count"]) == (0, 2) and "does not match" in r["errors"][0]


def _filer(con, file_name: str) -> str:
    """The entity the promoter resolved for that fixture's filing (a name match is ambiguous: two EMAMI entities)."""
    found = con.execute(
        "SELECT DISTINCT a.entity_id FROM audit_opinions a JOIN filings f USING (filing_id) WHERE f.source_url = ?",
        [ARCHIVE + file_name],
    ).fetchall()
    assert len(found) == 1, found
    return found[0][0]


def test_columns_are_point_in_time_and_feed_the_forensic_gate(filed):
    con = filed.con
    rk, ri, em = (_filer(con, FILED[i][0]) for i in (0, 1, 3))  # RKFORGE annual, RELINFRA annual, EMAMI Q1 FY27
    rows = [{"entity_id": e} for e in (rk, ri, em)]
    FA.add_columns(con, rows, ist_to_utc(date(2025, 10, 24), datetime.min.time()))
    assert all(r[c] is None for r in rows for c in FA.COLUMNS)  # nothing visible yet
    FA.add_columns(con, rows, ist_to_utc(date(2025, 10, 25), datetime.min.time()))
    assert (rows[0]["audit_opinion"], rows[0]["audit_opinion_fy_end"], rows[0]["audit_opinion_conflict"],
            rows[0]["emphasis_of_matter"], rows[0]["going_concern_uncertainty"]) == (
        "QUALIFIED", FY25, True, True, False)  # fmt: skip
    as_of = ist_to_utc(date(2026, 11, 13), datetime.min.time())
    FA.add_columns(con, rows, as_of)
    assert (rows[1]["audit_opinion"], rows[1]["audit_opinion_quarterly"], rows[1]["audit_opinion_quarter_end"]) == (
        "DISCLAIMER", "DISCLAIMER", FY26)  # fmt: skip
    assert (rows[2]["audit_opinion"], rows[2]["audit_opinion_quarterly"]) == (None, "QUALIFIED")  # no annual filed
    for r in rows:
        assert FA.modified_opinion(r) is True
        assert G.forensic_clean({"fundamentals_end": FY26, **r}) is False
    before = [{"entity_id": em}]
    FA.add_columns(con, before, ist_to_utc(date(2026, 8, 4), datetime.min.time()) - timedelta(days=1))
    assert before[0]["audit_opinion_quarterly"] is None


def test_columns_combine_the_scopes_of_the_latest_period():
    a = lambda end, op, conflict=False, gc=False, eom=False: (end, op, conflict, gc, eom)  # noqa: E731
    out = FA.columns({"ANNUAL": [a(FY26, "UNMODIFIED", eom=True), a(FY26, "QUALIFIED", conflict=None)],
                      "RESULTS": [a(FY26, "UNMODIFIED")]})  # fmt: skip
    assert (out["audit_opinion"], out["audit_opinion_conflict"], out["emphasis_of_matter"],
            out["going_concern_uncertainty"], out["audit_opinion_quarterly"]) == (
        "QUALIFIED", False, True, False, "UNMODIFIED")  # fmt: skip
    none = FA.columns({"ANNUAL": [(FY26, None, None, None, None)]})  # "As per attachment"
    assert (none["audit_opinion"], none["audit_opinion_fy_end"]) == (None, FY26)
    assert none["going_concern_uncertainty"] is None
    assert FA.columns(None) == dict.fromkeys(FA.COLUMNS)


@pytest.mark.parametrize(
    ("change", "clean"),
    [({}, True), ({"audit_opinion": "QUALIFIED"}, False), ({"audit_opinion": "ADVERSE"}, False),
     ({"audit_opinion_quarterly": "DISCLAIMER"}, False), ({"going_concern_uncertainty": True}, False),
     ({"emphasis_of_matter": True}, True), ({"audit_opinion_conflict": True}, True),
     ({"audit_opinion": None, "going_concern_uncertainty": None}, True)],
)  # fmt: skip
def test_forensic_gate_on_audit_opinions(change, clean):
    base = {"fundamentals_end": FY26, "audit_opinion": "UNMODIFIED", "audit_opinion_quarterly": "UNMODIFIED",
            "going_concern_uncertainty": False, "emphasis_of_matter": False}  # fmt: skip
    assert G.forensic_clean(base | change) is clean
    assert G.forensic_clean(change) is None  # NULL without fundamentals, as before


def test_columns_are_event_columns_with_dsl_aliases():
    from financials.db import declared_columns
    from financials.features_store import EVENT_COLUMNS

    names = [c for c, _ in declared_columns()["screener_features"]]
    assert names[-len(FA.COLUMNS) - 1 : -1] == list(FA.COLUMNS)  # then roe_screener (X227, QF3)
    assert set(FA.COLUMNS) <= set(EVENT_COLUMNS)
    for name in ("audit opinion modified", "quarterly audit opinion modified", "audit opinion conflict",
                 "going concern uncertainty", "emphasis of matter"):  # fmt: skip
        assert name in ALIASES
        assert compile_screen(f"{name} = 1").where_sql
