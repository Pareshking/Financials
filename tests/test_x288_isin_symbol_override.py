"""[X288] An ISIN_SYMBOL_CONFLICT that no named rule settles (X101 needs the symbol's entity to carry the filed name)
is decided by hand: `quarantine resolve --action OVERRIDE --payload-json '{"field": "security_id", ...}'`, as for an
unknown ISIN. Live case (QP4): Vadilal Enterprises Q3 FY26 (BSE 519152) files ISIN INE593D01018 (its own is
INE693D01018) and Symbol VADILALIND (Vadilal Industries', a group company); ScripCode 519152 and the company name are
Vadilal Enterprises'. Here: an in-memory copy of the ELIN fixture with another company's symbol."""

from __future__ import annotations

import io

from conftest import FETCHED_AT, Market

from _fixture_helpers import CORP
from financials.admin import list_quarantine, resolve_quarantine
from financials.cli import promote_pending
from financials.promoter import promote
from financials.staging import stage_results_xbrl


def test_override_security_id_settles_an_isin_symbol_conflict(tmp_path):
    from datetime import datetime

    m = Market(tmp_path)
    promote(m.con, m.stage_day("20251014"))
    data = CORP.read_bytes()
    assert data.count(b">ELIN<") >= 1
    data = data.replace(b">ELIN<", b">PIDILITIND<")  # in memory: the stated symbol names another entity
    stage_results_xbrl(m.vault, m.stage_root, data=data, source_url="memory://elin-other-symbol", fetched_at=FETCHED_AT,
                       broadcast_ts=datetime(2026, 11, 5, 12, 36), broadcast_ts_source="API_FIELD")  # fmt: skip
    promote_pending(m.con, m.stage_root, io.StringIO())
    (q,) = list_quarantine(m.con, reason_code="ISIN_SYMBOL_CONFLICT")
    elin = m.security_id("ELIN")
    r = resolve_quarantine(m.con, q["quarantine_id"], action="OVERRIDE", note="ELIN filing: ISIN and name are ELIN's",
                           payload={"field": "security_id", "value": elin}, stage_root=m.stage_root)  # fmt: skip
    assert r["repromoted"]["status"] == "PROMOTED"
    ent = m.con.execute("SELECT entity_id FROM securities WHERE security_id = ?", [elin]).fetchone()[0]
    assert m.con.execute("SELECT entity_id FROM filing_meta").fetchone()[0] == ent
    assert m.con.execute("SELECT resolution FROM quarantine_queue WHERE quarantine_id = ?",
                         [q["quarantine_id"]]).fetchone() == ("OVERRIDDEN",)  # fmt: skip
