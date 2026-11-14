"""X77: a count / quantity filed under an INR unit with sub-paise digits is kept exactly, never as money."""

from __future__ import annotations

from conftest import FETCHED_AT

from _fixture_helpers import XBRL_DIR
from financials.parsers.reg34_annual import parse_reg34_annual
from financials.staging import read_manifest, stage_results_xbrl

SPARC = XBRL_DIR / "AR_XBRL_SPARC_08092026160440.xml"


def test_subpaise_inr_line_items_are_not_money_and_the_filing_stages(market):
    r = parse_reg34_annual(SPARC.read_bytes(), SPARC.name)
    sub = [f for f in r.facts if f.unit == "INR_SUBPAISE"]
    assert sub and all(f.value != f.value.quantize(1) or f.value % 1 for f in sub)
    assert any(f.source_element == "NumberOfShareholdersOfCompany" for f in sub)
    assert any(w["code"] == "INR_UNIT_SUBPAISE" for w in r.meta.get("warnings", []))
    s = stage_results_xbrl(market.vault, market.stage_root, data=SPARC.read_bytes(),
                           source_url="https://nsearchives.nseindia.com/corporate/xbrl/" + SPARC.name,
                           fetched_at=FETCHED_AT)  # fmt: skip
    assert read_manifest(s)["job"] == "results_xbrl"  # staged (it raised before the rule)
