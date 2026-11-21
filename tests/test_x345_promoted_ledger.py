"""X345 PROMOTED_LEDGER: discovery treats a promoted filing as done even when its staging directory is gone.

The 2026-11-19 sweep re-staged 1,086 already-promoted results (76 symbols, two hours, nothing new) because
`Jobs.is_done` only looked for the staging directory. Promote now writes the promoted filing ids next to staging;
filings with an open PARSE / IDENTITY / PERIOD finding stay off the list so a parser fix is still retried.
"""

from datetime import datetime

from financials import promoted_ledger
from financials.db import apply_schema, connect, insert_rows
from financials.fetch.http import PoliteFetcher
from financials.fetch.jobs import Jobs
from financials.ids import stable_id
from financials.vault import Vault

URL = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1623305_11022026044628_WEB.xml"
BODY = b"<xbrl/>"
T = datetime(2026, 11, 14, 3, 20)


class NoNetwork:
    def get(self, url, headers, timeout):  # pragma: no cover - must never be called
        raise AssertionError("no request expected")


def _jobs(tmp_path) -> Jobs:
    vault = Vault(tmp_path / "vault")
    blob = vault.put(BODY, ext="xml", media_type="application/xml", fetched_at=T)
    vault.record_fetch(URL, 200, T, BODY, "xml")
    assert vault.exists(blob.storage_path)
    return Jobs(PoliteFetcher(NoNetwork(), sleep=lambda s: None), vault, tmp_path / "staging")


def _filing_id() -> str:
    import hashlib

    return stable_id("fil", "NSE", URL, hashlib.sha256(BODY).hexdigest())


def _db(fid: str, *, open_parse_finding: bool):
    con = connect()
    apply_schema(con)
    insert_rows(con, "blobs", [{"sha256": "x", "byte_size": 7, "media_type": "application/xml",
                                "storage_path": "x.xml", "first_fetched_at": T}])  # fmt: skip
    insert_rows(con, "filings", [{
        "filing_id": fid, "sha256": "x", "exchange": "NSE", "category": "RESULTS_XBRL", "source_url": URL,
        "exchange_ref": None, "stated_symbol": None, "stated_isin": None, "broadcast_ts": T,
        "broadcast_ts_source": "API_FIELD", "fetched_at": T, "supersedes_filing_id": None,
    }])  # fmt: skip
    if open_parse_finding:
        insert_rows(con, "quarantine_queue", [{
            "quarantine_id": "q1", "stage": "PARSE", "reason_code": "UNKNOWN_TAXONOMY", "entity_id": None,
            "security_id": None, "filing_id": fid, "details": "{}", "created_at": T, "resolved_at": None,
            "resolution": None, "resolution_note": None,
        }])  # fmt: skip
    return con


def test_without_staging_dir_or_ledger_the_file_is_not_done(tmp_path):
    jobs = _jobs(tmp_path)
    assert not jobs.is_done(URL, "results_xbrl")  # the old behaviour: re-staged from the vault


def test_promoted_filing_is_done_without_its_staging_dir(tmp_path):
    jobs = _jobs(tmp_path)
    fid = _filing_id()
    assert promoted_ledger.write(_db(fid, open_parse_finding=False), tmp_path / "staging") == 1
    assert promoted_ledger.read(tmp_path / "staging") == {fid}
    assert jobs.is_done(URL, "results_xbrl")


def test_filing_with_open_parse_finding_is_retried(tmp_path):
    jobs = _jobs(tmp_path)
    assert promoted_ledger.write(_db(_filing_id(), open_parse_finding=True), tmp_path / "staging") == 0
    assert not jobs.is_done(URL, "results_xbrl")


def test_staging_dir_still_counts(tmp_path):
    jobs = _jobs(tmp_path)
    (tmp_path / "staging" / "results_xbrl" / _filing_id()).mkdir(parents=True)
    assert jobs.is_done(URL, "results_xbrl")
