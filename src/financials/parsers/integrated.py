"""Route an Integrated Filing (financials) XBRL to the parser for its accounting profile."""

from __future__ import annotations

from financials.parsers.igaap_bank import parse_igaap_bank_results
from financials.parsers.indas_corp import ParsedResults, detect_profile, parse_indas_corp_results
from financials.parsers.indas_nbfc import parse_indas_nbfc_results
from financials.parsers.irdai_insurance import SPECS as INSURER_SPECS
from financials.parsers.irdai_insurance import parse_insurer_results
from financials.parsers.xbrl import parse_instance

PARSERS = {
    "INDAS_NBFC": parse_indas_nbfc_results,
    "IGAAP_BANK": parse_igaap_bank_results,
    **{p: (lambda data, p=p: parse_insurer_results(data, p)) for p in INSURER_SPECS},
}


def parse_integrated_results(data: bytes) -> ParsedResults:
    """INDAS_NBFC -> Division III parser; IGAAP_BANK -> RBI-format parser; everything else -> the INDAS_CORP
    path, which routes (without parsing) profiles that are not implemented and reports unknown taxonomies."""
    profile = detect_profile(parse_instance(data).entity_namespace)
    return PARSERS.get(profile, parse_indas_corp_results)(data)
