"""C22: the unmapped-element audit. Newly mapped elements parse to the filed values; the classifier is stable."""

from decimal import Decimal

import pytest

from _fixture_helpers import XBRL_DIR
from financials.parsers.integrated import parse_integrated_results
from financials.registry_audit import REASONS, classify

STAR = XBRL_DIR / "IF_INS_COM_IND_AS_19799_WebXMLFile_20261027_212749295.xml"
ITC = XBRL_DIR / "INTEGRATED_FILING_INDAS_1751354_02112026065539_WEB.xml"


def _instant(path, tag):
    r = parse_integrated_results(path.read_bytes())
    assert r.ok, r.issues
    return {f.value for f in r.facts if f.canonical_tag == tag}


def test_indas117_insurer_fixed_and_intangible_assets_now_mapped():
    assert _instant(STAR, "ppe_net") == {Decimal("2246195000")}
    assert _instant(STAR, "other_intangibles") == {Decimal("873830000")}
    assert _instant(STAR, "goodwill") == {Decimal("0")}


def test_corp_loans_and_noncurrent_payables_now_mapped():
    assert _instant(ITC, "loans_current") == {Decimal("67100000")}
    assert _instant(ITC, "loans_noncurrent") == {Decimal("25200000")}
    assert _instant(ITC, "trade_payables_noncurrent") == {Decimal("0")}
    assert _instant(ITC, "cash_cf_statement") == {Decimal("2988500000")}


@pytest.mark.parametrize(
    ("profile", "name", "reason"),
    [
        ("INDAS_CORP", "DilutedEarningsLossPerShareFromContinuingOperations", "PER_SHARE_DUPLICATE"),
        ("INDAS_CORP", "IncomeTaxRelatingToItemsThatWillNotBeReclassifiedToProfitOrLoss", "OCI_SUBLINE"),
        ("INDAS_CORP", "SegmentRevenue", "SEGMENT_DISCLOSURE"),
        ("INDAS_CORP", "DebtServiceCoverageRatio", "REGULATORY_MEMO"),
        ("REG31_SHP", "NumberOfFullyPaidUpEquityShares", "NON_FINANCIAL_COUNT"),
        ("INDAS_CORP", "ProceedsFromIssuingDebenturesNotesBondsEtc", "CASH_FLOW_DETAIL"),
        ("INDAS_CORP", "ProvisionsCurrent", "BALANCE_SHEET_DETAIL"),
        ("IRDAI_LIFE", "AllocationOfBonusToPolicyholders", "INSURANCE_SCHEDULE_DETAIL"),
        ("IRDAI_GENERAL", "Assets", "DERIVED_SUBTOTAL"),  # = ApplicationOfFunds, net of current liabilities
    ],
)
def test_classifier(profile, name, reason):
    assert classify(name, profile) == reason and reason in REASONS


def test_core_statement_lines_are_never_auto_excluded():
    """A canonical line must be mapped, not swept up by a rule: the classifier leaves these UNCLASSIFIED."""
    for name in ("Goodwill", "PropertyPlantAndEquipment", "RevenueFromOperations", "OtherExpenses", "Assets"):
        assert classify(name, "INDAS_CORP") is None
