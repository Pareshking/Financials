"""BSE results XBRL [X247, X265]: the comp_resultsnew listing (`Corp_FinanceResult_ng_new`) and its Integrated Filing
(Finance) files, inline XBRL of the SEBI `in-capmkt` taxonomy, read by the NSE results parser (bse-reach mode xbrl6,
run 44271899335, 2026-11-18; fixtures under tests/fixtures/bse/, MANIFEST section QB7)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from decimal import Decimal

import pytest
from test_bse import Resp, client

from _fixture_helpers import FIXTURES
from financials.fetch import bse

BSE = FIXTURES / "bse"
ABBOTT = BSE / "Integrated_Finance_Ind_As_500488_511202619052_IFIndAs.html"
PARK = BSE / "Integrated_Finance_Ind_As_544111_18112026133342_IFIndAs.html"
PARK_NSE = BSE / "INTEGRATED_FILING_INDAS_1673679_27052026125706_WEB.xml"
LIST_500488 = BSE / "bse_Corp_FinanceResult_ng_new_500488_flagdur6_20261118.json"
LIST_TODAY = BSE / "bse_Corp_FinanceResult_ng_new_all_flagdur1_20261118.json"
ROW_KEYS = {"Consol_XMLName", "DT_TM", "Fld_CreateDate", "Fld_NatureOfReport", "Industry_name", "Qtr", "Resultpageurl",
            "Scrip_cd", "URL", "XMLName", "audited", "company_name", "quarter_code", "scrip_name"}  # fmt: skip


def _rows(path):
    return json.loads(path.read_bytes())["Table"]


def test_x247_dropdowns_and_results_listing():
    """FlagDur 1 Today .. 6 Last 1 year, 7 Beyond last 1 year; HFQ 3 Quarterly, 2 Yearly, 1 Half Yearly. One scrip over
    the last year: 7 rows, 4 files (a file serves the quarter and the half year / nine months / year rows)."""
    flags = {
        r["FlagDur"]: r["FlagDISPLAY"].strip() for r in _rows(BSE / "bse_Corp_GetFINANCE_DRDOWN_ng_flag1_20261118.json")
    }
    assert flags == {1: "Today", 2: "Last 1 Week", 3: "Last 15 Days", 4: "Last 1 month", 5: "Last 3 month",
                     6: "Last 1 year", 7: "Beyond last 1 year"}  # fmt: skip
    hfq = {r["HFQ"]: r["HFQDISPLAY"] for r in _rows(BSE / "bse_Corp_GetFINANCE_DRDOWN_ng_flag3_20261118.json")}
    assert hfq == {3: "Quarterly", 2: "Yearly", 1: "Half Yearly"}
    rows = _rows(LIST_500488)
    assert len(rows) == 7 and all(set(r) == ROW_KEYS for r in rows)
    assert [r["quarter_code"] for r in rows] == ["SQ2026-2027", "SH2026-2027", "JQ2026-2027", "MQ2025-2026",
                                                 "MC2025-2026", "DQ2025-2026", "DN2025-2026"]  # fmt: skip
    assert {r["XMLName"] for r in rows} == {
        f"IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_500488_{s}_IFIndAs.html"
        for s in ("511202619052", "1282026192354", "1152026225027", "1222026163853")
    }
    assert all(r["Consol_XMLName"] is None and r["Fld_NatureOfReport"] == "Standalone" for r in rows)
    today = _rows(LIST_TODAY)  # SCRIP_CD blank + FlagDur 1: every company's results of the day
    assert [(r["Scrip_cd"], r["quarter_code"], bool(r["Consol_XMLName"])) for r in today] == [
        (544111, "MQ2025-2026", True), (544111, "MC2025-2026", True), (544477, "SQ2026-2027", False),
        (544477, "SH2026-2027", True)]  # fmt: skip


def test_x265_quarter_codes_and_files_to_fetch():
    assert bse.quarter_period_end("SQ2026-2027") == date(2026, 9, 30)
    assert bse.quarter_period_end("DN2025-2026") == date(2025, 12, 31)
    assert bse.quarter_period_end("MC2025-2026") == date(2026, 3, 31)
    assert bse.quarter_period_end("MQ2024-2025") == date(2025, 3, 31)
    assert bse.quarter_period_end("JQ2026-2027") == date(2026, 6, 30)
    for bad in ("XQ2026-2027", "SQ2026-2028", "SQ2026", "", None):
        assert bse.quarter_period_end(bad) is None
    rows = _rows(LIST_500488)
    files, skipped = bse.results_files(rows, date(2025, 3, 31))
    assert skipped == 0 and len(files) == 4
    assert files[0] == (
        bse.XBRL_FILES + rows[0]["XMLName"],
        {"scrip": "500488", "quarter_code": "SQ2026-2027", "field": "XMLName", "scope": "standalone"},
    )
    files, skipped = bse.results_files(rows, date(2026, 6, 30))
    assert skipped == 4 and [c["quarter_code"] for _, c in files] == ["SQ2026-2027", "JQ2026-2027"]
    files, _ = bse.results_files(_rows(LIST_TODAY), date(2025, 3, 31))
    assert [u.rsplit("_", 2)[-2] for u, _ in files] == ["1811202613291", "18112026133342", "18112026122341",
                                                        "14112026175059"]  # fmt: skip
    # an unreadable quarter code is fetched (the promoter's scope gate decides)
    assert len(bse.results_files([{**rows[0], "quarter_code": "??"}], date(2030, 1, 1))[0]) == 1


def test_x265_file_name_stamps_and_visibility():
    """The file name's time parts are not zero-padded: every reading is listed; visibility takes the latest same-day
    one and the row's Fld_CreateDate (IST), never earlier."""

    def stamps(name):
        return bse.file_stamps(bse.XBRL_FILES + f"IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_{name}")

    assert stamps("500488_511202619052_IFIndAs.html") == [datetime(2026, 11, 5, 19, 0, 52),
                                                         datetime(2026, 11, 5, 19, 5, 2)]  # fmt: skip
    assert stamps("544111_18112026133342_IFIndAs.html") == [datetime(2026, 11, 18, 13, 33, 42)]
    assert stamps("544111_1811202613291_IFIndAs.html") == [datetime(2026, 11, 18, 13, 29, 1)]
    assert stamps("500488_1282026192354_IFIndAs.html") == [datetime(2026, 8, 12, 19, 23, 54)]
    assert stamps("x.html") == []


def test_x265_inline_results_parse_with_the_nse_parser():
    from financials.parsers.integrated import parse_integrated_results
    from financials.parsers.ixbrl import inline_to_instance, is_inline
    from financials.parsers.xbrl import parse_instance

    data = ABBOTT.read_bytes()
    assert is_inline(data) and b"http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt" in data[:600]
    inst = parse_instance(data)
    assert (
        inst.entity_namespace
        == "http://www.sebi.gov.in/xbrl/IntegratedFinance_IndAS/2026-01-31/in-capmkt/in-capmkt-ent"
    )
    assert len(inst.facts) == 402 + 297 and inst.units == {"INR": "INR", "INRPerShare": "INR_PER_SHARE"}
    assert parse_instance(inline_to_instance(data)).facts == inst.facts
    p = parse_integrated_results(data, ABBOTT.name)
    assert (p.profile, p.issues, p.findings) == ("INDAS_CORP", [], [])
    m = p.meta
    keys = ("scope", "period_end", "level_of_rounding", "stated_isin", "stated_symbol", "audited")
    assert tuple(m[k] for k in keys) == ("STANDALONE", date(2026, 9, 30), "Crores", "INE358A01014", "NOTLISTED", False)
    got = {(f.canonical_tag, f.period_start): f.value for f in p.facts}
    # scale 7 = crores; ixt3:numdotdecimalin = Indian grouping: 1,951.01 -> 19,510,100,000 rupees
    assert got[("revenue_from_operations", date(2026, 7, 1))] == Decimal("19510100000")
    assert got[("revenue_from_operations", date(2026, 4, 1))] == Decimal("37646900000")
    assert got[("other_income", date(2026, 7, 1))] == Decimal("680600000")
    assert len(p.facts) == 239


def test_x265_numdotdecimalin_is_checked():
    from financials.parsers import ParseError
    from financials.parsers.ixbrl import inline_to_instance

    data = ABBOTT.read_bytes()
    assert b">1,951.01<" in data
    with pytest.raises(ParseError, match="Indian-grouped"):
        inline_to_instance(data.replace(b">1,951.01<", b">1,9510.1<", 1))


def _facts(inst, factor=Decimal(1)):
    out = Counter()
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if f.is_numeric:
            unit = inst.unit_kind(f.unit_ref)
            v = Decimal(f.value_text.strip()) * (factor if unit == "INR" else 1)
            val = ("N", unit, v.normalize())
        else:
            val = ("T", f.value_text.strip())
        out[(f.ns, f.name, c.start, c.end, c.instant, c.dimensions, val)] += 1
    return out


def test_r20_bse_copy_of_an_nse_filing_reads_to_the_same_facts():
    """R20 [X265]: PARKHOTELS Q4 FY26 consolidated, NSE XML (filed 26-May-2026, LevelOfRounding 'Lakhs', the X201 slip:
    figures in crores, corrected x 100 in fact_corrections) against BSE's inline copy (re-uploaded 18-Nov-2026,
    'Crores'). Element, period, dimensions and unit read identically; every value agrees after NSE's x 100 except the
    lines the filer revised in the re-upload: 20 balance-sheet amounts at 31-Mar-2026 (PPE -11.11 Cr, deferred tax
    assets 204.00 -> 21.80 Cr, ...), Reserves excluding revaluation reserves (NSE 0), lease-liability splits and the
    notes' text. P&L, OCI and cash-flow amounts both copies carry are all identical."""
    from financials.parsers.integrated import parse_integrated_results
    from financials.parsers.xbrl import parse_instance

    b, n = parse_instance(PARK.read_bytes()), parse_instance(PARK_NSE.read_bytes())
    assert b.entity_namespace == n.entity_namespace
    fb, fn = _facts(b), _facts(n, Decimal(100))
    assert (sum(fb.values()), sum(fn.values())) == (334, 332)
    assert sum((fb & fn).values()) == 293
    durations_b = {k for k in fb - fn if k[-1][0] == "N" and k[4] is None}
    assert {k[1] for k in durations_b} == {"ProfitBeforeTax", "ReserveExcludingRevaluationReserves"}
    assert {k[1] for k in fn - fb if k[-1][0] == "N" and k[4] is None} == {
        "OtherComprehensiveIncome",
        "ReserveExcludingRevaluationReserves",
    }
    # the inline file shows 5 facts twice (same name, context, value: display copies), the NSE XML each once; the
    # second copy of the FY ProfitBeforeTax is the one duration amount left over
    assert fb[next(k for k in fb if k[1] == "ProfitBeforeTax" and k[2] == date(2025, 4, 1))] == 2
    assert sum(v - 1 for v in fb.values() if v > 1) == 5 and all(v == 1 for v in fn.values())
    pb = parse_integrated_results(PARK.read_bytes(), PARK.name)
    pn = parse_integrated_results(PARK_NSE.read_bytes(), PARK_NSE.name)
    assert (pb.meta["level_of_rounding"], pn.meta["level_of_rounding"]) == ("Crores", "Lakhs")
    kb = {(f.canonical_tag, f.period_start, f.period_end): f for f in pb.facts}
    kn = {(f.canonical_tag, f.period_start, f.period_end): f for f in pn.facts}
    common = set(kb) & set(kn)
    differ = {k for k in common if kb[k].value != kn[k].value * (100 if kn[k].unit in ("INR", "SHARES") else 1)}
    assert len(common) == 264 and len(differ) == 21
    assert {k[0] for k in differ if k[1] != k[2]} == {"li_reserve_excluding_revaluation_reserves"}
    assert all(k[2] == date(2026, 3, 31) for k in differ)
    assert kb[("revenue_from_operations", date(2026, 1, 1), date(2026, 3, 31))].value == Decimal("1837000000")
    assert kn[("revenue_from_operations", date(2026, 1, 1), date(2026, 3, 31))].value == Decimal("18370000")


def _ledger(tmp_path, *files):
    answers = [Resp(200, LIST_500488.read_bytes(), "application/json; charset=utf-8")]
    answers += [Resp(200, p.read_bytes(), "text/html") for p in files]
    c, _ = client(answers, tmp_path)
    rows = c.finance_results("500488", 6)
    url, params = c.session.calls[0]
    assert url == bse.API + "Corp_FinanceResult_ng_new/w"
    assert params == {"SCRIP_CD": "500488", "FlagDur": "6", "HFQ": "", "ISUBGROUP_CODE": "", "segment": "C"}
    for p in files:
        name = next(r["XMLName"] for r in rows if r["XMLName"].endswith(p.name))
        c.xbrl_file(bse.XBRL_FILES + name, "results_xbrl", {"scrip": "500488"})
    return c


def test_x265_bse_results_promote_for_the_nse_security(tmp_path):
    """A Permitted member's BSE results file is vaulted as HTML, staged through the NSE results path and promoted
    for the security NSE trades (by ISIN), visible from the row's Fld_CreateDate / file name time (IST)."""
    from conftest import Market

    from financials.promoter import promote

    assert bse.RESULTS_XBRL_VERIFIED
    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"
    _ledger(tmp_path, ABBOTT)
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == [] and [p.parent.name for p in staged] == ["raw_only", "results_xbrl"]
    results = [promote(m.con, s) for s in staged]
    assert [r.status for r in results] == ["PROMOTED", "PROMOTED"], results
    f = m.con.execute(
        "SELECT f.exchange, f.category, f.broadcast_ts, f.broadcast_ts_source, b.storage_path FROM filings f "
        "JOIN blobs b USING (sha256) WHERE f.category = 'RESULTS_XBRL'"
    ).fetchall()
    # 19:05:02 IST (the later reading of 511202619052; Fld_CreateDate 19:00:52.8) = 13:35:02 UTC
    assert [r[:4] for r in f] == [("BSE", "RESULTS_XBRL", datetime(2026, 11, 5, 13, 35, 2), "API_CREATION")]
    assert f[0][4].endswith(".html")
    got = m.con.execute(
        "SELECT h.symbol, o.scope, o.value_inr, o.visible_from_ts FROM fact_observations o "
        "JOIN securities s ON s.entity_id = o.entity_id JOIN security_identifier_history h USING (security_id) "
        "WHERE o.canonical_tag = 'revenue_from_operations' AND o.period_start = DATE '2026-07-01'"
    ).fetchall()
    assert got == [("ABBOTINDIA", "STANDALONE", Decimal("19510100000.00"), datetime(2026, 11, 5, 13, 35, 2))]
    m.con.close()


def test_x265_identity_by_scrip_code_and_code_conflict(tmp_path):
    """No NSE row with the filed ISIN: the filed ScripCode finds the entity through `bse_scrip_code` (rule BSE1
    codes). A different stored code for the filed ISIN is an IDENTIFIER finding, not a silent overwrite."""
    from conftest import Market

    from financials.promoter import promote
    from financials.staging import stage_results_xbrl

    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    assert promote(m.con, m.stage_day("20261112")).status == "PROMOTED"
    data = ABBOTT.read_bytes()
    url = bse.XBRL_FILES + "IFIndasDuplicateUploadDocument/" + ABBOTT.name
    kw = dict(source_url=url, fetched_at=datetime(2026, 11, 18), broadcast_ts=datetime(2026, 11, 5, 13, 35, 2),
              broadcast_ts_source="API_CREATION", exchange="BSE")  # fmt: skip
    m.con.execute("UPDATE security_identifier_history SET bse_scrip_code = '500488' WHERE symbol = 'ABBOTINDIA'")
    other_isin = data.replace(b">INE358A01014<", b">INE000Z01019<")
    r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=other_isin, **kw))
    assert r.status == "PROMOTED", r
    m.con.execute("UPDATE security_identifier_history SET bse_scrip_code = '999999' WHERE symbol = 'ABBOTINDIA'")
    r = promote(m.con, stage_results_xbrl(m.vault, m.stage_root, data=data, **kw))
    assert r.status == "PROMOTED", r
    q = m.con.execute(
        "SELECT stage, reason_code, json_extract_string(details, '$.stored'), json_extract_string(details, '$.filed') "
        "FROM quarantine_queue WHERE stage = 'IDENTIFIER'"
    ).fetchall()
    assert q == [("IDENTIFIER", "BSE_SCRIP_CODE_CONFLICT", "999999", "500488")]
    m.con.close()


def test_x265_plain_xml_and_annual_stay_raw_only(tmp_path):
    """Only the inline `.html` form is parsed; anything else of results_xbrl / annual_xbrl is vaulted raw."""
    from conftest import Market

    c, _ = client([Resp(200, b"<?xml version='1.0'?><x/>", "text/xml")] * 2, tmp_path)
    c.xbrl_file("/XBRLFILES/IFIndasDuplicateUploadDocument/a.xml", "results_xbrl")
    c.xbrl_file("/XBRLFILES/x/b.html", "annual_xbrl")
    (tmp_path / "m").mkdir()
    m = Market(tmp_path / "m")
    staged, errors = bse.import_ledger(m.vault, m.stage_root, tmp_path / "led")
    assert errors == [] and [p.parent.name for p in staged] == ["raw_only", "raw_only"]
    m.con.close()


def test_x265_bse_fetch_results_pass(tmp_path):
    """`bse_fetch.py --only results`: FlagDur 6 for every scrip, then FlagDur 7; each in-scope file once; a missing
    file is skipped, a 400 listing is skipped, the run goes on."""
    import importlib.util

    from test_bse import RoutedSession, _resp

    from financials.sources import ROOT

    spec = importlib.util.spec_from_file_location("bse_fetch", ROOT / "scripts" / "bse_fetch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    listing = LIST_500488.read_bytes()
    s = RoutedSession([
        ("SCRIP_CD=500488&FlagDur=6", _resp(200, listing, "application/json")),
        ("SCRIP_CD=500488&FlagDur=7", _resp(200, listing, "application/json")),  # repeats: nothing new to fetch
        ("SCRIP_CD=505036&FlagDur=6", _resp(400, b"")),
        ("SCRIP_CD=505036&FlagDur=7", _resp(200, b'{"Table": []}', "application/json")),
        ("_1222026163853_", _resp(404, b"")),
        ("XBRLFILES/IFIndasDuplicateUploadDocument/", _resp(200, ABBOTT.read_bytes(), "text/html")),
    ])  # fmt: skip
    c = bse.BseClient(s, sleep=lambda _: None, ledger=bse.Ledger(tmp_path / "led"), allow_in_page=False)
    lines: list[str] = []
    skipped = m.run(c, ["500488", "505036@2026-11-05"], date(2025, 4, 1), date(2026, 11, 18), lines.append, "results")
    order = [(p.get("SCRIP_CD"), p.get("FlagDur")) for _, u, p, _ in s.calls if "FinanceResult" in u]
    assert order == [("500488", "6"), ("505036", "6"), ("500488", "7"), ("505036", "7")]
    files = [u for _, u, _, _ in s.calls if "XBRLFILES" in u]
    assert len(files) == 4 and len(set(files)) == 4 and skipped == 2  # the 404 file and the 400 listing
    recs = bse.Ledger(tmp_path / "led").records()
    assert [r["dataset"] for r in recs].count("results_xbrl") == 3
    assert recs[1]["covers"] == {"scrip": "500488", "quarter_code": "SQ2026-2027", "field": "XMLName",
                                 "scope": "standalone"}  # fmt: skip
    assert "500488 FlagDur 6: 7 results rows, 0 before Q4 FY25, 4 new files" in lines
    assert "500488 FlagDur 7: 7 results rows, 0 before Q4 FY25, 0 new files" in lines


def test_r20_identical_upload_on_bse_and_nse_reads_to_the_same_canonical_facts():
    """R20 [X266]: HILINFRA 544477 Q2 FY27 consolidated, the same upload on BSE (inline XBRL, 17:50:59 IST) and NSE
    (XML, 17:51:50 IST). Every canonical fact the parser produces is identical (tag, period, scope, value). The raw
    instances differ only by BSE's display duplicates and NSE's extra `OtherComprehensiveIncome` element, whose line-
    item row `li_other_comprehensive_income` equals the mapped `oci_net` both carry."""
    from financials.parsers.integrated import parse_integrated_results

    def canon(name):
        data = (BSE / name).read_bytes()
        r = parse_integrated_results(data, name)
        assert r.ok, r.issues
        return Counter((f.canonical_tag, str(f.period_start), str(f.period_end), f.value) for f in r.facts)

    nse = canon("INTEGRATED_FILING_INDAS_1758435_14112026055150_WEB.xml")
    bse_ = canon("Integrated_Finance_Ind_As_544477_14112026175059_IFIndAs.html")
    assert len(nse) > 40
    only_nse, only_bse = set(nse) - set(bse_), set(bse_) - set(nse)
    assert only_bse == set()
    assert only_nse == {("li_other_comprehensive_income", "2026-04-01", "2026-09-30", Decimal("-181000"))}
    assert ("oci_net", "2026-04-01", "2026-09-30", Decimal("-181000")) in bse_
