"""Persistent point-in-time segment and geography rows [X95-X97]: parser characterisation on real filings (quarterly
multi-segment, single-segment, Reg. 34 annual with geography), promotion with the filing, the non-blocking sum
check, and the point-in-time reader."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import XBRL_DIR
from financials import PARSER_VERSION
from financials.db import fetch_dicts, insert_rows
from financials.fundamentals import load_factbook, load_segments
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.segments import Windows, parse_segments
from financials.promoter import promote
from financials.staging import read_table, stage_results_xbrl

D = Decimal
CUMMINS = XBRL_DIR / "INTEGRATED_FILING_INDAS_1753292_04112026105837_WEB.xml"
APL = XBRL_DIR / "INTEGRATED_FILING_INDAS_1746046_26102026055540_WEB.xml"
SRF26 = XBRL_DIR / "AR_XBRL_SRF_09082026022508.xml"
TCS26 = XBRL_DIR / "AR_XBRL_TCS_09082026012216.xml"
TCS25 = XBRL_DIR / "AR_XBRL_TCS_14082025184751.xml"
ETERNAL26 = XBRL_DIR / "AR_XBRL_ETERNAL_23092026175418.xml"
Q, H1, END = (date(2026, 7, 1), date(2026, 9, 30)), (date(2026, 4, 1), date(2026, 9, 30)), date(2026, 9, 30)
FY26, MAR26, MAR25 = (date(2025, 4, 1), date(2026, 3, 31)), date(2026, 3, 31), date(2025, 3, 31)
ARCHIVE = "https://nsearchives.nseindia.com/corporate/xbrl/"
LUBES_Q = b'<in-capmkt:SegmentRevenue contextRef="OneReportable2D" decimals="-5" unitRef="INR">10145600000<'


def segments(path, data: bytes | None = None):
    data = data if data is not None else path.read_bytes()
    parsed = parse_integrated_results(data, path.name)
    assert not parsed.issues, parsed.issues
    m = parsed.meta
    return parse_segments(data, Windows.from_meta(m), level_of_rounding=m["level_of_rounding"])


def by(report, metric, period, kind="BUSINESS"):
    start, end = (None, period) if isinstance(period, date) else period
    return {
        (f.member.split(":")[-1], f.label): f.value
        for f in report.facts
        if f.canonical_metric == metric and f.axis_kind == kind and (f.period_start, f.period_end) == (start, end)
    }


# ── parser characterisation ──────────────────────────────────────────────────────────────────────────────────


def test_quarterly_multi_segment_cummins():
    """[X95] Cummins Q2 FY27 consolidated: two labelled members on four per-element axes, quarter and H1 durations,
    period-end instants. Every row keeps axis, member and label as filed."""
    r = segments(CUMMINS)
    assert r.issues == [] and r.warnings == [] and r.unmapped == [] and len(r.facts) == 12
    assert by(r, "REVENUE", Q) == {("ReportableSegments1Member", "Engines"): D("32474700000"),
                                   ("ReportableSegments2Member", "Lubes"): D("10145600000")}  # fmt: skip
    assert by(r, "REVENUE", H1) == {("ReportableSegments1Member", "Engines"): D("66224000000"),
                                    ("ReportableSegments2Member", "Lubes"): D("20179300000")}  # fmt: skip
    assert by(r, "RESULT", Q) == {("ReportableSegments1Member", "Engines"): D("6213600000"),
                                  ("ReportableSegments2Member", "Lubes"): D("198700000")}  # fmt: skip
    assert by(r, "ASSETS", END) == {("ReportableSegments1Member", "Engines"): D("113864300000"),
                                    ("ReportableSegments2Member", "Lubes"): D(0)}  # fmt: skip
    assert by(r, "LIABILITIES", END)[("ReportableSegments1Member", "Engines")] == D("30870700000")
    axes = {f.canonical_metric: f.axis for f in r.facts}
    assert axes == {"REVENUE": "in-capmkt:ReportableSegmentsAxis",
                    "RESULT": "in-capmkt:ReportableSegmentsFinanceCostsAxis",
                    "ASSETS": "in-capmkt:ReportableSegmentAssetsAxis",
                    "LIABILITIES": "in-capmkt:ReportableSegmentLiabilitiesAxis"}  # fmt: skip
    assert {(f.period_type, f.period_months) for f in r.facts} == {("DURATION", 3), ("DURATION", 6), ("INSTANT", None)}
    assert {f.member_role for f in r.facts} == {"SEGMENT"}
    # not a P&L substitute [X49]: the segment revenue sum is before inter-segment elimination
    pnl = parse_integrated_results(CUMMINS.read_bytes())
    assert sum(by(r, "REVENUE", Q).values()) == D("42620300000") != pnl.value("revenue_from_operations", *Q)


def test_single_segment_filer_has_no_rows(market):
    """[X49] APL Apollo files no segment axis: no rows, nothing staged."""
    assert segments(APL).facts == []
    stage = stage_results_xbrl(market.vault, market.stage_root, data=APL.read_bytes(), source_url=ARCHIVE + APL.name,
                               fetched_at=FETCHED_AT)  # fmt: skip
    assert read_table(market.con, stage, "stg_segments") == []


def test_annual_business_segments_srf_roles_from_member_names():
    """[X96] SRF FY26 consolidated (Reg. 34): one EntitySReportableSegmentsAxis for every element, labels from
    NatureOfReportableSegment. Unallocated, elimination and reconciling members are kept as filed and flagged by
    member name; MaterialReconcilingItemsMember = unallocated + eliminations."""
    r = segments(SRF26)
    assert r.issues == [] and r.warnings == [] and r.unmapped == []
    rev = by(r, "REVENUE", FY26)
    assert rev == {
        ("ReportableSegments1Member", "Technical Textiles Business (TTB)"): D("18770000000"),
        ("ReportableSegments2Member", "Chemicals business (CB)"): D("77789700000"),
        ("ReportableSegments3Member", "Performance Films & Foil Business (PFB)"): D("57642300000"),
        ("ReportableSegments4Member", "Others"): D("3663800000"),
        ("UnallocatedAmountsMember", "Unallocable"): D("1070600000"),
        ("EliminationOfIntersegmentAmountsMember", "Inter Segment"): D("-700000"),
        ("MaterialReconcilingItemsMember", "Refer to child member"): D("1069900000"),
    }
    roles = {f.member.split(":")[-1]: f.member_role for f in r.facts if f.axis_kind == "BUSINESS"}
    assert roles == {"ReportableSegments1Member": "SEGMENT", "ReportableSegments2Member": "SEGMENT",
                     "ReportableSegments3Member": "SEGMENT", "ReportableSegments4Member": "SEGMENT",
                     "UnallocatedAmountsMember": "UNALLOCATED", "EliminationOfIntersegmentAmountsMember": "ELIMINATION",
                     "MaterialReconcilingItemsMember": "RECONCILING"}  # fmt: skip
    assert by(r, "RESULT", FY26)[("ReportableSegments2Member", "Chemicals business (CB)")] == D("22628700000")
    assert by(r, "ASSETS", MAR26)[("ReportableSegments2Member", "Chemicals business (CB)")] == D("118862600000")
    assert {f.canonical_metric for f in r.facts if f.axis_kind == "BUSINESS"} == {
        "REVENUE", "EXTERNAL_REVENUE", "INTERSEGMENT_REVENUE", "RESULT", "ASSETS", "LIABILITIES",
        "DEPRECIATION_AMORTISATION"}  # fmt: skip
    # Observed, not used by any code: segments + eliminations = P&L revenue from operations for FY26.
    pnl = parse_integrated_results(SRF26.read_bytes(), SRF26.name)
    seg_elim = sum(v for (m, _), v in rev.items() if m.startswith(("ReportableSegments", "Elimination")))
    assert seg_elim == pnl.value("revenue_from_operations", *FY26) == D("157865100000")
    # FY25 comparative is in scope (period end 2025-03-31 >= cutoff) and kept
    assert by(r, "REVENUE", (date(2024, 4, 1), MAR25))[("ReportableSegments2Member", "Chemicals business (CB)")] == (
        D("66907500000"))  # fmt: skip


def test_annual_geography_srf_labels_and_foreign_total():
    """[X97] SRF FY26 geography: domicile + ForeignCountriesMember (= sum of the ten ForeignCountryN members) equals
    P&L revenue; country names are the filer's labels."""
    r = segments(SRF26)
    geo = by(r, "EXTERNAL_REVENUE", FY26, "GEOGRAPHY")
    assert geo[("CountryOfDomicileMember", "INDIA")] == D("78604200000")
    assert geo[("ForeignCountriesMember", "Refer to child member")] == D("79260900000")
    assert geo[("ForeignCountry1Member", "UNITED STATES")] == D("13018000000")
    assert geo[("ForeignCountry10Member", "HUNGARY")] == D("36006500000")
    foreign = [v for (m, _), v in geo.items() if m.startswith("ForeignCountry") and m != "ForeignCountriesMember"]
    assert len(foreign) == 10 and sum(foreign) == D("79260900000")
    roles = {f.member.split(":")[-1]: f.member_role for f in r.facts if f.axis_kind == "GEOGRAPHY"}
    assert roles["CountryOfDomicileMember"] == "DOMICILE" and roles["ForeignCountriesMember"] == "FOREIGN_TOTAL"
    assert {v for k, v in roles.items() if k.startswith("ForeignCountry") and k != "ForeignCountriesMember"} == {
        "FOREIGN"
    }
    pnl = parse_integrated_results(SRF26.read_bytes(), SRF26.name)
    assert D("78604200000") + D("79260900000") == pnl.value("revenue_from_operations", *FY26)
    nca = by(r, "NON_CURRENT_ASSETS", MAR26, "GEOGRAPHY")
    assert nca[("CountryOfDomicileMember", "INDIA")] == D("133354900000")
    assert all(f.axis == "ind-as:GeographicalAreasAxis" for f in r.facts if f.axis_kind == "GEOGRAPHY")


def test_annual_geography_tcs_regions_and_pre_cutoff_comparatives():
    """[X97] TCS FY26: India + Americas / Europe / Others; the FY25 filing's FY24 comparatives are pre-cutoff (C9) and
    never emitted."""
    r = segments(TCS26)
    geo = by(r, "EXTERNAL_REVENUE", FY26, "GEOGRAPHY")
    assert geo == {("CountryOfDomicileMember", "India"): D("157750000000"),
                   ("ForeignCountriesMember", "Refer Child Member"): D("2512460000000"),
                   ("ForeignCountry1Member", "Americas"): D("1349980000000"),
                   ("ForeignCountry2Member", "Europe"): D("874670000000"),
                   ("ForeignCountry3Member", "Others"): D("287810000000")}  # fmt: skip
    assert sum(by(r, "REVENUE", FY26).values()) == D("157750000000") + D("2512460000000")
    old = segments(TCS25)
    assert old.facts and min(f.period_end for f in old.facts) == MAR25 and old.ignored == 46


def test_annual_external_plus_intersegment_is_segment_revenue_eternal():
    """[X96] Eternal FY26: RevenuePrimaryReportableSegment (EXTERNAL_REVENUE) + inter-segment = segment revenue for
    every member; its geography has no labels (label NULL, never invented)."""
    r = segments(ETERNAL26)
    rows: dict = {}
    for f in r.facts:
        if f.axis_kind == "BUSINESS":
            rows.setdefault((f.member, f.period_start), {})[f.canonical_metric] = f.value
    pairs = [m for m in rows.values() if "INTERSEGMENT_REVENUE" in m]
    assert len(pairs) == 8
    assert all(m["EXTERNAL_REVENUE"] + m["INTERSEGMENT_REVENUE"] == m["REVENUE"] for m in pairs)
    geo = [f for f in r.facts if f.axis_kind == "GEOGRAPHY"]
    assert geo and all(f.label is None for f in geo)


# ── staging + promotion ──────────────────────────────────────────────────────────────────────────────────────


def _stage(m, data: bytes, name: str, ts: datetime):
    return stage_results_xbrl(m.vault, m.stage_root, data=data, source_url=ARCHIVE + name, fetched_at=FETCHED_AT,
                              broadcast_ts=ts, broadcast_ts_source="API_FIELD")  # fmt: skip


SEEN = datetime(2026, 11, 4, 6, 0)


@pytest.fixture
def cummins_market(market):
    promote(market.con, market.stage_day("20261112"))
    return market


def test_segments_promote_with_the_filing_point_in_time(cummins_market):
    m = cummins_market
    s = _stage(m, CUMMINS.read_bytes(), CUMMINS.name, SEEN)
    assert promote(m.con, s).status == "PROMOTED"
    ent, fid, visible = m.con.execute("SELECT entity_id, filing_id, visible_from_ts FROM filing_meta").fetchone()
    rows = m.con.execute(
        "SELECT DISTINCT entity_id, filing_id, scope, parser_version, visible_from_ts FROM segment_observations"
    ).fetchall()
    assert rows == [(ent, fid, "CONSOLIDATED", PARSER_VERSION, visible)]
    assert load_segments(m.con, ent, "CONSOLIDATED", visible.replace(minute=59, hour=visible.hour - 1)) == []
    got = load_segments(m.con, ent, "CONSOLIDATED", visible)
    assert len(got) == 12 and load_segments(m.con, ent, "STANDALONE", visible) == []
    rev = {(r.label, r.period_months): r.value_inr for r in got if r.canonical_metric == "REVENUE"}
    assert rev == {("Engines", 3): D("32474700000.00"), ("Engines", 6): D("66224000000.00"),
                   ("Lubes", 3): D("10145600000.00"), ("Lubes", 6): D("20179300000.00")}  # fmt: skip
    assert load_segments(m.con, ent, "CONSOLIDATED", visible, axis_kind="GEOGRAPHY") == []
    # segments never feed fact_observations: what was promoted there is exactly the parser's facts
    assert m.con.execute("SELECT count(*) FROM fact_observations").fetchone()[0] == len(
        read_table(m.con, s, "stg_xbrl_facts")
    )
    assert promote(m.con, s).status == "ALREADY_PROMOTED"
    assert m.con.execute("SELECT count(*) FROM segment_observations").fetchone()[0] == 12


def test_quarantined_filing_promotes_no_segment_rows(market):
    """No identity (no bhavcopy loaded): the filing quarantines and its staged segment rows stay in staging."""
    s = _stage(market, CUMMINS.read_bytes(), CUMMINS.name, SEEN)
    assert len(read_table(market.con, s, "stg_segments")) == 12
    assert promote(market.con, s).status == "QUARANTINED"
    assert market.con.execute("SELECT count(*) FROM segment_observations").fetchone()[0] == 0


def test_segment_sum_mismatch_is_a_non_blocking_finding(cummins_market):
    """[X95] A member that no longer sums to the filed SegmentRevenue total beyond the LevelOfRounding tolerance
    (Crores: 0.5 Cr per term; an in-memory copy, the fixture is never edited) is promoted with an open SEGMENT_SUM
    finding; the filing's P&L facts are unchanged."""
    m = cummins_market
    data = CUMMINS.read_bytes()
    assert data.count(LUBES_Q) == 1
    broken = data.replace(LUBES_Q, LUBES_Q.replace(b">10145600000<", b">10165600000<"))
    r = segments(CUMMINS, broken)
    assert [c for c, _ in r.issues] == ["SEGMENT_SUM"]
    assert r.issues[0][1] == {"element": "SegmentRevenue", "period": ["2026-07-01", "2026-09-30"],
                              "sum": "42640300000", "filed": "42620300000"}  # fmt: skip
    res = promote(m.con, _stage(m, broken, CUMMINS.name, SEEN))
    assert res.status == "PROMOTED" and len(res.quarantined) == 1
    q = m.con.execute("SELECT stage, reason_code, resolved_at FROM quarantine_queue").fetchall()
    assert q == [("SEGMENT", "SEGMENT_SUM", None)]
    ent = m.con.execute("SELECT entity_id FROM filing_meta").fetchone()[0]
    book = load_factbook(m.con, ent, "CONSOLIDATED", SEEN)
    pnl = parse_integrated_results(data)
    for tag in ("revenue_from_operations", "total_income", "pbt", "pat"):
        assert book.durations[tag][Q] == pnl.value(tag, *Q)
    lubes = [x for x in load_segments(m.con, ent, "CONSOLIDATED", SEEN) if x.label == "Lubes" and x.period_months == 3
             and x.canonical_metric == "REVENUE"]  # fmt: skip
    assert [x.value_inr for x in lubes] == [D("10165600000.00")]  # stored as filed, never corrected


def test_reader_latest_filing_per_axis_period_and_current_parser_version(cummins_market):
    """A revision (new blob, later broadcast) replaces the breakdown only from its visibility; rows of an older
    parser version of the same filing are never read (versions compare numerically: 0.10.0 > 0.9.0)."""
    m = cummins_market
    data = CUMMINS.read_bytes()
    assert promote(m.con, _stage(m, data, CUMMINS.name, SEEN)).status == "PROMOTED"
    revised = data.replace(LUBES_Q, LUBES_Q.replace(b">10145600000<", b">10145700000<"))
    later = datetime(2026, 11, 10, 6, 0)
    assert promote(m.con, _stage(m, revised, CUMMINS.name, later)).status == "PROMOTED"
    ent = m.con.execute("SELECT DISTINCT entity_id FROM filing_meta").fetchone()[0]

    def lubes_q(as_of):
        return [(x.value_inr, x.filing_id) for x in load_segments(m.con, ent, "CONSOLIDATED", as_of)
                if x.label == "Lubes" and x.period_months == 3 and x.canonical_metric == "REVENUE"]  # fmt: skip

    ((v1, f1),) = lubes_q(datetime(2026, 11, 5))
    ((v2, f2),) = lubes_q(later)
    assert (v1, v2) == (D("10145600000.00"), D("10145700000.00")) and f1 != f2
    engines = [x for x in load_segments(m.con, ent, "CONSOLIDATED", later) if x.label == "Engines"]
    assert {x.filing_id for x in engines} == {f2}  # whole breakdown from the latest filing, never mixed

    # An older parser version's rows for the revised filing (as a pre-0.10 parse would have left them).
    assert "0.9.0" > "0.10.0"  # why a string sort is wrong
    meta = fetch_dicts(m.con, "SELECT * FROM filing_meta WHERE filing_id = ?", [f2])[0]
    insert_rows(m.con, "filing_meta", [{**meta, "parser_version": "0.9.0"}])
    old = fetch_dicts(m.con, "SELECT * FROM segment_observations WHERE filing_id = ?", [f2])
    insert_rows(m.con, "segment_observations", [{**r, "parser_version": "0.9.0", "value_inr": D("1.00")} for r in old])
    assert lubes_q(later) == [(D("10145700000.00"), f2)]


def test_stale_context_dates_rule_re_dates_segment_rows_siemens():
    """[X87] Siemens Q3 FY26 standalone: every context (segment ones too) carries the previous filing's dates. The
    rule the filing's parser applied re-dates segment rows to the declared quarter and 15-month period; without it
    all 36 rows would fall outside the declared periods."""
    path = XBRL_DIR / "INTEGRATED_FILING_INDAS_1620148_06022026044508_WEB.xml"
    r = segments(path)
    assert r.issues == [] and len(r.facts) == 36
    assert {(f.period_start, f.period_end, f.period_months) for f in r.facts} == {
        (date(2025, 10, 1), date(2025, 12, 31), 3), (date(2024, 10, 1), date(2025, 12, 31), 15),
        (None, date(2025, 12, 31), None)}  # fmt: skip
    q = by(r, "REVENUE", (date(2025, 10, 1), date(2025, 12, 31)))
    assert q[("ReportableSegments1Member", "Smart Infrastructure")] == D("17238000000")
    assert q[("ReportableSegments5Member", "Low Voltage Motors - Discontinued operations")] == D("2509000000")
    plain = parse_segments(
        path.read_bytes(),
        Windows(
            frozenset(Windows.from_meta(parse_integrated_results(path.read_bytes()).meta).durations),
            frozenset({date(2025, 12, 31)}),
        ),
    )
    assert plain.facts == [] or all(f.period_start is None for f in plain.facts)
    assert plain.issues[0][0] == "SEGMENT_CONTEXT_OUTSIDE_DECLARED" and plain.issues[0][1]["count"] == 24
