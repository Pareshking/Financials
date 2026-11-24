"""X313: BSE serves NBFC results as plain XML instances (`IFNBFCDuplicateUploadDocument/..._IFNBFC.xml`), NSE's NBFC
Integrated Filing XML in form and taxonomy. `import_ledger` stages them through the NSE results path, as the inline
`.html` of X265; filings vaulted raw only before this keep their raw-only category and are parsed by a re-import
(fixtures under tests/fixtures/bse/, MANIFEST section QB9)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import FIXTURES, XBRL_DIR
from financials.fetch import bse

BSE = FIXTURES / "bse"
STD = BSE / "Integrated_Finance_NBFC_530245_1482026171926_IFNBFC.xml"
CON = BSE / "Integrated_Finance_NBFC_530245_1482026172036_IFNBFC.xml"
LISTING = BSE / "bse_Corp_FinanceResult_ng_new_530245_flagdur6_20261118.json"
NSE_NBFC = XBRL_DIR / "INTEGRATED_FILING_NBFC_INDAS_1748226_28102026075925_WEB.xml"  # PNB Housing Q2 FY27
LISTING_URL = bse.API + "Corp_FinanceResult_ng_new/w?SCRIP_CD=530245&FlagDur=6&HFQ=&ISUBGROUP_CODE=&segment=C"


def _url(p) -> str:
    return bse.XBRL_FILES + "IFNBFCDuplicateUploadDocument/" + p.name


def test_x313_bse_nbfc_xml_is_the_nse_nbfc_taxonomy():
    """Same header comment, the same in-capmkt / IntegratedFinance_NBFC 2026-01-31 namespaces as an NSE NBFC fixture;
    plain XML (not inline), so plain_results_profile reads its profile from the entity namespace."""
    from financials.parsers.ixbrl import is_inline
    from financials.parsers.xbrl import parse_instance

    nse = parse_instance(NSE_NBFC.read_bytes())
    for p in (STD, CON):
        data = p.read_bytes()
        assert data.startswith(b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\r\n<!--IFNBFC V2.1 (26-06-2026)-->')
        assert b"<!--IFNBFC V2.1 (26-06-2026)-->" in NSE_NBFC.read_bytes()[:400]
        assert not is_inline(data)
        inst = parse_instance(data)
        assert (
            inst.entity_namespace
            == nse.entity_namespace
            == ("http://www.sebi.gov.in/xbrl/IntegratedFinance_NBFC/2026-01-31/in-capmkt/in-capmkt-ent")
        )
        assert (
            inst.namespaces["in-capmkt"]
            == nse.namespaces["in-capmkt"]
            == "http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt"
        )
        assert bse.plain_results_profile(data) == "INDAS_NBFC"
    assert bse.plain_results_profile(b"<?xml version='1.0'?><x/>") is None  # no entity namespace
    assert bse.plain_results_profile(b"not xml") is None
    inline = (BSE / "Integrated_Finance_Ind_As_500488_511202619052_IFIndAs.html").read_bytes()
    assert bse.plain_results_profile(inline) is None


def test_x313_bse_nbfc_xml_parses_with_the_nse_parser():
    """Aryaman Financial Services Q1 FY27: INDAS_NBFC, scope from NatureOfReportStandaloneConsolidated, LevelOfRounding
    Lakhs; amounts are absolute rupees (EPS 1.63 x 12,247,000 shares = PAT 1.995 Cr, standalone)."""
    from financials.parsers.integrated import parse_integrated_results

    q1 = (date(2026, 4, 1), date(2026, 6, 30))
    std = parse_integrated_results(STD.read_bytes(), STD.name)
    con = parse_integrated_results(CON.read_bytes(), CON.name)
    for p, scope in ((std, "STANDALONE"), (con, "CONSOLIDATED")):
        assert p.ok and p.profile == "INDAS_NBFC", p.issues
        assert p.meta["scope"] == scope and p.meta["level_of_rounding"] == "Lakhs"
        assert p.meta["period_end"] == date(2026, 6, 30) and p.meta["fy_start"] == date(2026, 4, 1)
        assert p.meta["stated_isin"] == "INE032E01017" and p.meta["stated_symbol"] == "NOTLISTED"
    assert std.value("revenue_from_operations", *q1) == Decimal("57373000")
    assert std.value("total_income", *q1) == Decimal("61121000")
    assert std.value("pat", *q1) == Decimal("19950000")
    assert std.value("eps_basic", *q1) == Decimal("1.63")
    paid_up = next(f.value for f in std.facts if f.canonical_tag == "paid_up_equity_capital")
    face = next(f.value for f in std.facts if f.canonical_tag == "face_value_per_share")
    assert paid_up == Decimal("122470000") and face == Decimal("10")
    assert abs(std.value("pat", *q1) / (paid_up / face) - Decimal("1.63")) < Decimal("0.005")
    assert con.value("revenue_from_operations", *q1) == Decimal("199318000")
    assert con.value("pat", *q1) == Decimal("140919000")
    assert con.value("pat_owners", *q1) == Decimal("101343000")
    for p in (std, con):  # Lakhs at 2 decimals: every rupee amount is a whole thousand
        assert all(f.value % 1000 == 0 for f in p.facts if f.unit == "INR"), p.meta["scope"]


def _ledger(root):
    led = bse.Ledger(root)
    led.put(dataset="xbrl_listing", url=LISTING_URL, status=200, body=LISTING.read_bytes(),
            content_type="application/json; charset=utf-8", via="requests",
            fetched_at=datetime.fromisoformat("2026-11-18T20:18:46+00:00"))  # fmt: skip
    for p, field, scope in ((STD, "XMLName", "standalone"), (CON, "Consol_XMLName", "consolidated")):
        led.put(dataset="results_xbrl", url=_url(p), status=200, body=p.read_bytes(), content_type="text/xml",
                via="requests", covers={"scrip": "530245", "quarter_code": "JQ2026-2027", "field": field,
                                        "scope": scope},
                fetched_at=datetime.fromisoformat("2026-11-18T20:19:03+00:00"))  # fmt: skip
    return led


def _market(tmp_path):
    from conftest import Market

    from financials.promoter import promote

    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"
    # a stand-in security carrying the member's BSE code (rule BSE1): the filed ISIN has no NSE identifier row
    m.con.execute("UPDATE security_identifier_history SET bse_scrip_code = '530245' WHERE symbol = 'ABBOTINDIA'")
    return m


def test_x313_import_ledger_stages_plain_nbfc_xml_through_the_results_path(tmp_path):
    """Both files promote, vaulted as XML, visible from the later of Fld_CreateDate (17:19:26.623 IST) and the file
    name's same-day time (consolidated `1482026172036` = 17:20:36 IST)."""
    from financials.promoter import promote

    m = _market(tmp_path)
    _ledger(tmp_path / "led")
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == [] and [p.parent.name for p in staged] == ["raw_only", "results_xbrl", "results_xbrl"]
    assert [promote(m.con, s).status for s in staged] == ["PROMOTED"] * 3
    rows = m.con.execute(
        "SELECT f.category, f.broadcast_ts, f.broadcast_ts_source, b.storage_path FROM filings f "
        "JOIN blobs b USING (sha256) WHERE f.source_url LIKE '%IFNBFC.xml' ORDER BY f.source_url"
    ).fetchall()
    assert [r[:3] for r in rows] == [
        ("RESULTS_XBRL", datetime(2026, 8, 14, 11, 49, 26, 623000), "API_CREATION"),
        ("RESULTS_XBRL", datetime(2026, 8, 14, 11, 50, 36), "API_CREATION"),
    ]
    assert all(r[3].endswith(".xml") for r in rows)
    got = m.con.execute(
        "SELECT o.scope, o.value_inr, o.visible_from_ts FROM fact_observations o WHERE o.canonical_tag = "
        "'revenue_from_operations' AND o.period_start = DATE '2026-04-01' AND o.period_months = 3 ORDER BY 1"
    ).fetchall()
    assert got == [("CONSOLIDATED", Decimal("199318000.00"), datetime(2026, 8, 14, 11, 50, 36)),
                   ("STANDALONE", Decimal("57373000.00"), datetime(2026, 8, 14, 11, 49, 26, 623000))]  # fmt: skip
    m.con.close()


def test_x313_raw_only_filing_is_parsed_by_a_re_import_and_restaged_later(tmp_path):
    """The live state before X313: the file was vaulted and promoted raw only (BSE_RESULTS_XBRL, no broadcast_ts).
    Re-importing the ledger parses it (same filing id; the raw-only row stays as it was, append-only), visible from
    the ledger's time. `restage` then selects it with that time; the visibility check does not flag it."""
    from financials.cli import restage_rows
    from financials.promoter import filings_with_later_visibility, promote
    from financials.staging import stage_raw_only

    m = _market(tmp_path)
    r = promote(m.con, stage_raw_only(m.vault, m.stage_root, data=STD.read_bytes(), ext="xml",
                                      media_type="application/xml", category="BSE_RESULTS_XBRL", source_url=_url(STD),
                                      fetched_at=datetime(2026, 11, 18, 11, 40), exchange="BSE"))  # fmt: skip
    assert r.status == "PROMOTED"
    assert m.con.execute("SELECT count(*) FROM filing_meta").fetchone()[0] == 0
    _ledger(tmp_path / "led")
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == [] and [promote(m.con, s).status for s in staged] == ["PROMOTED"] * 3
    fid, cat, bts = m.con.execute(
        "SELECT filing_id, category, broadcast_ts FROM filings WHERE source_url = ?", [_url(STD)]
    ).fetchone()
    assert (cat, bts) == ("BSE_RESULTS_XBRL", None)
    meta = m.con.execute(
        "SELECT entity_id IS NOT NULL, visible_from_ts, visible_from_source FROM filing_meta WHERE filing_id = ?", [fid]
    ).fetchall()
    assert meta == [(True, datetime(2026, 8, 14, 11, 49, 26, 623000), "BROADCAST")]
    every = {row[0]: row[4:6] for row in restage_rows(m.con, "RESULTS_XBRL", "ALL")}
    assert every[_url(STD)] == (datetime(2026, 8, 14, 11, 49, 26, 623000), "API_CREATION")
    assert every[_url(CON)] == (datetime(2026, 8, 14, 11, 50, 36), "API_CREATION")
    assert filings_with_later_visibility(m.con) == []
    # a re-parse at another parser version keeps the visibility
    from financials.staging import stage_results_xbrl

    url, fetched, _, _, b, src, exch = next(r for r in restage_rows(m.con, "RESULTS_XBRL", "ALL") if r[0] == _url(STD))
    s = stage_results_xbrl(m.vault, m.stage_root, data=STD.read_bytes(), source_url=url, fetched_at=fetched,
                           broadcast_ts=b, broadcast_ts_source=src, exchange=exch, run_suffix="t")  # fmt: skip
    assert promote(m.con, s).status == "ALREADY_PROMOTED"  # same parser version: nothing new
    m.con.close()
