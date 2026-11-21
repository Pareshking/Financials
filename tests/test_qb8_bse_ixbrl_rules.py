"""QB8 [X280-X283]: BSE results inline XBRL of Jun-2025 .. Feb-2026 that batch 1 of the BSE results fetch quarantined
(INVALID_XBRL 280, NO_DECLARED_PERIOD 10 of 574 filings). Fixtures: real BSE files from the vault, MANIFEST QB8."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

import pytest

from _fixture_helpers import FIXTURES
from financials.parsers import ParseError, ixbrl
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.xbrl import parse_instance

BSE = FIXTURES / "bse"
BOOL_TRUE = "Integrated_Finance_Ind_As_523862_1411202516851_IFIndAs.html"  # Q2 FY26 consolidated
BOOL_FALSE = "Integrated_Finance_Ind_As_539607_132202620589_IFIndAs.html"  # Q3 FY26 consolidated
VOID_BR = "Integrated_Finance_Ind_As_513536_128202520028_IFIndAs.html"  # Q1 FY26 consolidated
THEAD = "Integrated_Finance_Ind_As_539607_25112025201023_IFIndAs.html"  # Q2 FY26 standalone
UNTAGGED_PERIOD = "Integrated_Finance_Ind_As_504731_88202519641_IFIndAs.html"  # Q1 FY26 consolidated
_IX_TAGS = re.compile(rb"<ix:(?:nonFraction|nonNumeric)\b")


def _read(name: str) -> bytes:
    return (BSE / name).read_bytes()


def _values(data: bytes, element: str) -> dict[str, str]:
    return {f.context_id: f.value_text for f in parse_instance(data).facts if f.name == element}


def _money(result, tag: str) -> dict[tuple[date, date], Decimal]:
    return {(f.period_start, f.period_end): f.value for f in result.facts if f.canonical_tag == tag}


def test_x280_boolean_lexical_text_reads_as_itself():
    """BSE's pages of Nov-2025 .. Feb-2026 display 'true' / 'false' (always under ixt2:booleantrue): read as itself,
    the value NSE's XML of the same form carries; 'Yes' / 'No' still read as before (X170)."""
    data = _read(BOOL_TRUE)
    assert b"format='ixt2:booleantrue'>true</ix:nonNumeric>" in data
    assert _values(data, "WhetherCashFlowStatementIsApplicableOnCompany") == {"OneD": "true"}
    r = parse_integrated_results(data, BOOL_TRUE)
    assert r.issues == [] and r.profile == "INDAS_CORP" and r.meta["scope"] == "CONSOLIDATED"
    assert r.meta["quarter_period"] == (date(2025, 7, 1), date(2025, 9, 30))
    assert _money(r, "pat")[(date(2025, 7, 1), date(2025, 9, 30))] == Decimal("48599000")

    data = _read(BOOL_FALSE)
    assert b"format='ixt2:booleantrue'>false</ix:nonNumeric>" in data
    element = "DeclarationPursuantToClauseDOfSubRegulation3OfRegulation33OfSEBILODRRegulation2015"
    assert _values(data, element) == {"OneD": "false"}
    assert _values(data, "WhetherTheFirmHoldsAValidPeerReviewCertificateIssuedByPeerReviewBoardOfICAI") == {
        "D_Auditor1": "true"
    }
    r = parse_integrated_results(data, BOOL_FALSE)
    assert r.issues == [] and r.meta["quarter_period"] == (date(2025, 10, 1), date(2025, 12, 31))
    assert _money(r, "revenue_from_operations")[(date(2025, 10, 1), date(2025, 12, 31))] == Decimal("2654108000")
    for other in (b"True", b"TRUE", b"yes", b"1"):  # any other text still fails
        bad = data.replace(b"format='ixt2:booleantrue'>false<", b"format='ixt2:booleantrue'>" + other + b"<", 1)
        with pytest.raises(ParseError, match="neither Yes nor No"):
            ixbrl.inline_to_instance(bad)


def test_x281_unclosed_br_in_text_blocks_is_a_void_element():
    data = _read(VOID_BR)
    with pytest.raises(ET.ParseError, match="mismatched tag"):
        ET.fromstring(data)
    assert data.count(b"<BR>") == 6 and b"</BR>" not in data
    inst = parse_instance(data)
    # every ix fact of the raw text, plus the two displayed reporting-period facts of X283 (OneD only: no FourD)
    assert len(_IX_TAGS.findall(data)) == 73 and len(inst.facts) == 75
    notes = _values(data, "DisclosureOfNotesOnFinancialResultsExplanatoryTextBlock")["OneD"]
    assert notes.startswith("1) The above consolidated  financial results have been reviewed") and "<BR>" not in notes
    r = parse_integrated_results(data, VOID_BR)
    assert r.issues == [] and r.meta["scope"] == "CONSOLIDATED"
    assert _money(r, "revenue_from_operations") == {(date(2025, 4, 1), date(2025, 6, 30)): Decimal("33549000")}
    # a <BR> outside every ix:nonNumeric is not repaired: the original ParseError stands
    with pytest.raises(ParseError, match="invalid XHTML: mismatched tag"):
        ixbrl.inline_to_instance(data.replace(b"</body>", b"<BR></body>", 1))
    assert ixbrl.repair_xhtml(data.replace(b"</body>", b"<BR></body>", 1)) is None


def test_x282_thead_closed_by_tbody_in_the_empty_rpt_table():
    data = _read(THEAD)
    with pytest.raises(ET.ParseError, match="mismatched tag"):
        ET.fromstring(data)
    assert data.count(b"<thead") == 1 and b"</thead>" not in data
    seg = data[data.index(b"<thead") : data.index(b"</tbody>", data.index(b"<thead"))]
    assert b"<ix:" not in seg and b"No records available" in seg
    inst = parse_instance(data)
    assert len(inst.facts) == len(_IX_TAGS.findall(data)) == 281
    r = parse_integrated_results(data, THEAD)
    assert r.issues == [] and r.meta["scope"] == "STANDALONE"
    assert _money(r, "revenue_from_operations") == {
        (date(2025, 7, 1), date(2025, 9, 30)): Decimal("1676640000"),
        (date(2025, 4, 1), date(2025, 9, 30)): Decimal("3220431000"),
    }


def test_x281_x282_repair_counts_facts():
    """A repaired document must yield one fact per raw ix start tag: a start tag the parser does not see as a fact
    (here inside a comment, invisible to ElementTree) refuses the repair."""
    data = _read(THEAD)
    hidden = data.replace(b"</body>", b"<!-- <ix:nonNumeric name='in-capmkt:X' contextRef='OneD'>x -->\n</body>", 1)
    with pytest.raises(ParseError, match="repair lost facts"):
        ixbrl.inline_to_instance(hidden)


def test_x283_untagged_reporting_period_from_the_displayed_rows():
    data = _read(UNTAGGED_PERIOD)
    assert b"DateOfStartOfReportingPeriod" not in data and b"DateOfEndOfReportingPeriod" not in data
    assert b">Date of start of reporting period</td>" in data
    assert _values(data, "DateOfStartOfReportingPeriod") == {"OneD": "2025-04-01"}
    assert _values(data, "DateOfEndOfReportingPeriod") == {"OneD": "2025-06-30"}
    r = parse_integrated_results(data, UNTAGGED_PERIOD)
    assert r.issues == [] and r.meta["quarter_period"] == (date(2025, 4, 1), date(2025, 6, 30))
    assert r.meta["ytd_period"] == (date(2025, 4, 1), date(2025, 6, 30))
    assert _money(r, "pat") == {(date(2025, 4, 1), date(2025, 6, 30)): Decimal("739000")}
    # a displayed date that disagrees with the OneD context adds nothing: NO_DECLARED_PERIOD stands
    m = re.search(rb">Date of start of reporting period</td><td[^>]*>01-04-2025</td>", data)
    assert m is not None
    shifted = data[: m.start()] + m[0].replace(b">01-04-2025</td>", b">02-04-2025</td>") + data[m.end() :]
    r = parse_integrated_results(shifted, UNTAGGED_PERIOD)
    assert [i.reason_code for i in r.issues] == ["NO_DECLARED_PERIOD"]


def test_x283_tagged_files_are_untouched():
    """The later template tags the same cells (OneD, and FourD when the file has it): nothing is added."""
    for name in (BOOL_TRUE, THEAD):
        data = _read(name)
        assert b"name='in-capmkt:DateOfStartOfReportingPeriod' contextRef='OneD'" in data
        assert _values(data, "DateOfStartOfReportingPeriod") == {"OneD": "2025-07-01", "FourD": "2025-04-01"}
