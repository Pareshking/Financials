"""One results filing that declares the wrong LevelOfRounding [X201, rule LEVEL_OF_ROUNDING_SLIP].

India Motor Parts & Accessories (IMPAL) standalone Q1 FY27 (1705022) declares `Lakhs` and its Q2 (1748931) `Crores`;
Q1 files total income 24,396,000 (2.44 Cr) against Q2's 2,386,300,000 and an H1 of 4,825,900,000 (Q1 = 243.96 Cr).
Mamata Machinery standalone Q1 FY26 (1507427) declares `Millions` where its Q2 (1569007) declares `Lakhs`: Q1
revenue 2,757,900,000 is 10x the 275.79 Cr that the H1 identity needs. The three checks of level_slip.py (paid-up
capital vs the other filing, shareholding-pattern shares x face value, EPS x shares vs profit) all read the unit ratio
for the slipped filing; for the right filing of each pair the shareholding pattern reads 1 (GENUINE), so only the
slipped one is rescaled. Gandhar Oil standalone moved from `Millions` (Q2 FY26, 1572275) to `Crores` (Q3, 1609342)
for good: right values, every check GENUINE, nothing rescaled.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from _fixture_helpers import FIXTURES
from financials.admin import correct_from_pdf, find_level_slips, rescale_level_slips
from financials.fundamentals import load_factbook
from financials.level_slip import level_slip
from financials.promoter import promote
from financials.staging import stage_results_xbrl, stage_shareholding

DIR = FIXTURES / "level_slip"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
FILES = (  # (file, broadcast UTC)
    ("INTEGRATED_FILING_INDAS_1705022_30072026030857_WEB.xml", datetime(2026, 7, 30, 9, 38, 57)),
    ("INTEGRATED_FILING_INDAS_1748931_29102026045421_WEB.xml", datetime(2026, 10, 29, 11, 24, 21)),
    ("SHP_1697471_20072026072756_WEB.xml", datetime(2026, 7, 20, 13, 58, 2)),
    ("INTEGRATED_FILING_INDAS_1507427_08082025074055_WEB.xml", datetime(2025, 8, 8, 14, 10, 56)),
    ("INTEGRATED_FILING_INDAS_1569007_08112025020703_WEB.xml", datetime(2025, 11, 8, 8, 37, 3)),
    ("SHP_1583648_08122025123811_WEB.xml", datetime(2025, 12, 16, 11, 12, 7)),
    ("INTEGRATED_FILING_INDAS_1609342_23012026054425_WEB.xml", datetime(2026, 1, 23, 12, 14, 26)),
    ("INTEGRATED_FILING_INDAS_1572275_12112025050504_WEB.xml", datetime(2025, 11, 12, 11, 35, 5)),
    ("SHP_1605763_20012026045734_WEB.xml", datetime(2026, 1, 20, 11, 27, 40)),
)
FAR = datetime(2027, 1, 1)


@pytest.fixture
def slipped(market):
    assert promote(market.con, market.stage_day("20250919")).status == "PROMOTED"
    for name, ts in FILES:
        stage = stage_shareholding if name.startswith("SHP_") else stage_results_xbrl
        r = promote(market.con, stage(market.vault, market.stage_root, data=(DIR / name).read_bytes(),
                                      source_url=URL + name, fetched_at=datetime(2026, 11, 17, 6), broadcast_ts=ts,
                                      broadcast_ts_source="API_FIELD"))  # fmt: skip
        assert r.status == "PROMOTED", (name, r)
    return market


def _fid(con, name):
    return con.execute("SELECT filing_id FROM filings WHERE source_url = ?", [URL + name]).fetchone()[0]


def _ent(con, fid):
    return con.execute("SELECT entity_id, scope FROM filing_meta WHERE filing_id = ?", [fid]).fetchone()


def test_only_the_slipped_filings_are_found(slipped):
    con = slipped.con
    found = {x["filing_id"]: x["verdict"] for x in find_level_slips(con)}
    impal, mamata = _fid(con, FILES[0][0]), _fid(con, FILES[3][0])
    assert set(found) == {impal, mamata}
    assert found[impal].factor == Decimal(100) and (found[impal].declared, found[impal].usual) == ("Lakhs", "Crores")
    assert found[mamata].factor == Decimal("0.1") and found[mamata].usual == "Lakhs"
    for v in found.values():
        assert [c.verdict for c in v.checks] == ["SLIP", "SLIP", "SLIP"]


def test_rescale_restores_the_half_year_identity_and_closes_the_findings(slipped):
    con = slipped.con
    impal = _fid(con, FILES[0][0])
    ent, scope = _ent(con, impal)
    q1, q2 = (date(2026, 4, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 9, 30))
    h1 = (q1[0], q2[1])
    before = load_factbook(con, ent, scope, FAR)
    assert before.durations["total_income"][q1] == Decimal("24396000")
    assert before.ytd_breaks("total_income")
    opened = con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE reason_code = 'YTD_QUARTER_MISMATCH' AND entity_id = ? "
        "AND resolved_at IS NULL", [ent]).fetchone()[0]  # fmt: skip
    assert opened == 4  # revenue, total income, PBT, PAT
    out = rescale_level_slips(con)
    assert {x["filing_id"] for x in out} == {impal, _fid(con, FILES[3][0])}
    assert all(x["corrections"] > 20 for x in out), [x["corrections"] for x in out]
    book = load_factbook(con, ent, scope, FAR)
    ti = book.durations["total_income"]
    assert ti[q1] == Decimal("2439600000.00") and ti[q1] + ti[q2] == ti[h1] == Decimal("4825900000")
    for tag in ("revenue_from_operations", "total_income", "pat", "pbt_incl_jv"):
        assert not book.ytd_breaks(tag), tag
    assert book.durations["eps_basic"][q1] == before.durations["eps_basic"][q1]  # per-share values untouched
    left = con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE reason_code = 'YTD_QUARTER_MISMATCH' AND entity_id = ? "
        "AND resolved_at IS NULL", [ent]).fetchone()[0]  # fmt: skip
    assert left == 0
    raw = con.execute(
        "SELECT value_inr FROM fact_observations WHERE filing_id = ? AND canonical_tag = 'total_income' "
        "AND period_end = ?", [impal, q1[1]]).fetchone()[0]  # fmt: skip
    assert raw == Decimal("24396000")  # the filed fact is kept
    assert rescale_level_slips(con)  # idempotent: no new rows on a re-run
    n = con.execute("SELECT count(*) FROM fact_corrections").fetchone()[0]
    assert n == sum(x["corrections"] for x in out)


def test_a_pdf_correction_replaces_the_rule_value(slipped):
    con = slipped.con
    impal = _fid(con, FILES[0][0])
    ent, scope = _ent(con, impal)
    rescale_level_slips(con)
    q1 = (date(2026, 4, 1), date(2026, 6, 30))
    correct_from_pdf(con, impal, [{"canonical_tag": "pat", "period_start": q1[0], "period_end": q1[1],
                                   "value_inr": "216700000"}],
                     evidence_url="https://nsearchives.nseindia.com/corporate/IMPAL_example.pdf", evidence_page=1,
                     evidence_text="test", reads="TEXT+IMAGE", note="test")  # fmt: skip
    active = con.execute(
        "SELECT reads FROM fact_corrections WHERE filing_id = ? AND canonical_tag = 'pat' AND period_end = ? "
        "AND revoked_at IS NULL", [impal, q1[1]]).fetchall()  # fmt: skip
    assert active == [("TEXT+IMAGE",)]
    assert load_factbook(con, ent, scope, FAR).durations["pat"][q1] == Decimal("216700000")


def test_a_permanent_unit_change_is_genuine():
    """Gandhar standalone Q3 FY26 in crores after Q2 in millions: the shareholding pattern ties paid-up capital at the
    declared unit, so nothing is rescaled, and neighbours' paid-up alone (symmetric) never decides."""
    v = level_slip("Crores", ["Millions"], paid_up=Decimal("195800000"), neighbour_paid_ups=[Decimal("195800000")],
                   face_value=Decimal(2), shp_shares=97879530, eps_basic=Decimal("3.66"),
                   profit=Decimal("358000000"))  # fmt: skip
    assert v is None
    # one check alone is not enough
    assert level_slip("Lakhs", ["Crores"], paid_up=Decimal("1"), neighbour_paid_ups=[Decimal("100")],
                      face_value=None, shp_shares=None, eps_basic=None, profit=None) is None  # fmt: skip
