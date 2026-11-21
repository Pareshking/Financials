"""QP4 [X285-X287]: the last BSE results inline XBRL files still INVALID_XBRL after QB8 (6 of the Permitted cohort's
files: 3 'not well-formed (invalid token)', 3 'mismatched tag'). Fixtures: real BSE files of the bse-fetch runner
ledgers, MANIFEST QP4. Each repair stays under the X281 gate (one fact per raw ix start tag)."""

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
BARE_LT = "Integrated_Finance_Ind_As_539469_1422026194048_IFIndAs.html"  # 539469 Q3 FY26 consolidated
TR_END = "IFOtherthan_538668_1482025163259_IFOtherthan.html"  # 538668 Q1 FY26, OtherThanBank template
TABLE_END = "Integrated_Finance_Ind_As_538668_141120252067_IFIndAs.html"  # 538668 Q2 FY26 consolidated
_IX_TAGS = re.compile(rb"<ix:(?:nonFraction|nonNumeric)\b")


def _read(name: str) -> bytes:
    return (BSE / name).read_bytes()


def _money(result, tag: str) -> dict[tuple[date, date], Decimal]:
    return {(f.period_start, f.period_end): f.value for f in result.facts if f.canonical_tag == tag}


def test_x285_bare_lt_in_a_text_block_is_the_character():
    """OCR'd notes carry 're<lassified': inside an ix:nonNumeric, a '<' with no '>' before the next '<' is text."""
    data = _read(BARE_LT)
    with pytest.raises(ET.ParseError, match="not well-formed"):
        ET.fromstring(data)
    assert data.count(b"<lassified") == 1
    inst = parse_instance(data)
    assert len(inst.facts) == len(_IX_TAGS.findall(data)) == 126
    element = "DisclosureOfNotesOnFinancialResultsExplanatoryTextBlock"
    notes = {f.context_id: f.value_text for f in inst.facts if f.name == element}
    assert "are re<lassified / re armanged" in notes["OneD"]
    r = parse_integrated_results(data, BARE_LT)
    assert r.issues == [] and r.profile == "INDAS_CORP" and r.meta["scope"] == "CONSOLIDATED"
    assert r.meta["quarter_period"] == (date(2025, 10, 1), date(2025, 12, 31))
    assert _money(r, "revenue_from_operations") == {
        (date(2025, 10, 1), date(2025, 12, 31)): Decimal("294682000"),
        (date(2025, 4, 1), date(2025, 12, 31)): Decimal("2436727000"),
    }
    assert _money(r, "pat")[(date(2025, 4, 1), date(2025, 12, 31))] == Decimal("28226000")
    # a '<' outside every text block is not repaired: the original ParseError stands
    bad = data.replace(b"</body>", b"<p>a <b c</p></body>", 1)
    with pytest.raises(ParseError, match="invalid XHTML: not well-formed"):
        ixbrl.inline_to_instance(bad)


def test_x285_a_real_tag_in_a_text_block_is_kept():
    """A '<' that does start a tag (a '>' before the next '<') is left alone: BSE's own <br/> stay elements."""
    assert ixbrl._BARE_LT.sub(b"&lt;", b"a<br/>b re<lassified c") == b"a<br/>b re&lt;lassified c"


def test_x286_tr_end_omitted_before_the_next_row():
    data = _read(TR_END)
    with pytest.raises(ET.ParseError, match="mismatched tag"):
        ET.fromstring(data)
    assert data.count(b"</td><tr") == 2
    inst = parse_instance(data)
    # every raw ix fact, plus the two displayed reporting-period facts of X283 (OneD only)
    assert len(_IX_TAGS.findall(data)) == 96 and len(inst.facts) == 98
    r = parse_integrated_results(data, TR_END)
    # parses now; the OtherThanBank template is a known unsupported profile (X89), as NSE's copies are
    assert [i.reason_code for i in r.issues] == ["UNKNOWN_TAXONOMY"]
    assert "IntegratedFinance_OtherThanBank" in r.issues[0].details["entity_namespace"]


def test_x287_empty_audit_qualification_table_ends_before_the_next_heading():
    data = _read(TABLE_END)
    with pytest.raises(ET.ParseError, match="mismatched tag"):
        ET.fromstring(data)
    m = ixbrl._TABLE_OPEN.search(data)
    assert m is not None and b"Auditors Comments on (i) or (ii) above" in m[0] and b"<ix:" not in m[0]
    inst = parse_instance(data)
    assert len(inst.facts) == len(_IX_TAGS.findall(data)) == 337
    r = parse_integrated_results(data, TABLE_END)
    assert r.issues == [] and r.meta["scope"] == "CONSOLIDATED"
    assert r.meta["quarter_period"] == (date(2025, 7, 1), date(2025, 9, 30))
    assert _money(r, "revenue_from_operations") == {
        (date(2025, 7, 1), date(2025, 9, 30)): Decimal("87839000"),
        (date(2025, 4, 1), date(2025, 9, 30)): Decimal("192553000"),
    }
    assert _money(r, "pat")[(date(2025, 4, 1), date(2025, 9, 30))] == Decimal("27307000")


def test_x285_x287_repairs_keep_the_fact_count_gate():
    data = _read(TABLE_END)
    hidden = data.replace(b"</body>", b"<!-- <ix:nonNumeric name='in-capmkt:X' contextRef='OneD'>x -->\n</body>", 1)
    with pytest.raises(ParseError, match="repair lost facts"):
        ixbrl.inline_to_instance(hidden)


def test_qp4_well_formed_files_are_untouched():
    """The repairs run only on a file that does not parse; the earlier BSE fixtures read exactly as before."""
    for name in ("Integrated_Finance_Ind_As_544477_14112026175059_IFIndAs.html",
                 "Integrated_Finance_Ind_As_523862_1411202516851_IFIndAs.html"):  # fmt: skip
        data = _read(name)
        ET.fromstring(data)
        assert len(parse_instance(data).facts) >= len(_IX_TAGS.findall(data))
