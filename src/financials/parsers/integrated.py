"""Route an Integrated Filing (financials) XBRL to the parser for its accounting profile."""

from __future__ import annotations

from financials.parsers.indas_corp import ParsedResults, detect_profile, parse_indas_corp_results
from financials.parsers.indas_nbfc import parse_indas_nbfc_results
from financials.parsers.xbrl import parse_instance

PARSERS = {"INDAS_NBFC": parse_indas_nbfc_results}


def parse_integrated_results(data: bytes) -> ParsedResults:
    """INDAS_NBFC -> Division III parser; everything else -> INDAS_CORP path (which routes, without parsing,
    profiles that are not implemented and reports unknown taxonomies)."""
    profile = detect_profile(parse_instance(data).entity_namespace)
    return PARSERS.get(profile, parse_indas_corp_results)(data)
