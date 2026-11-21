"""X322: an archive file vaulted empty or cut short is downloaded again only on an explicit request.

SOFTTECH's INTEGRATED_FILING_INDAS_1753180 was vaulted as 0 bytes: the archive host itself answers 200 with
content-length 0 (checked 2026-11-19, references X322), so PoliteFetcher had nothing to retry. Once the archive
serves the full file, `fetch-results URL --refetch` downloads it again; the old blob and ledger line stay.
"""

from financials.fetch.http import PoliteFetcher, Response
from financials.fetch.jobs import Jobs
from financials.vault import Vault

URL = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1753180_04112026084409_WEB.xml"
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class Seq:
    def __init__(self, *bodies: bytes) -> None:
        self.bodies, self.calls = list(bodies), 0

    def get(self, url, headers, timeout):
        self.calls += 1
        return Response(200, self.bodies.pop(0), {"content-length": "0"})


def test_vaulted_file_is_not_downloaded_again_unless_refetch_is_asked(tmp_path):
    t = Seq(b"", b"<xbrl/>")
    jobs = Jobs(PoliteFetcher(t, sleep=lambda s: None), Vault(tmp_path / "vault"), tmp_path / "staging")
    assert jobs._get(URL) == b""
    assert jobs.vault.last_fetch(URL)["sha256"] == EMPTY_SHA
    assert jobs._get(URL) == b"" and t.calls == 1  # the ledger is the checkpoint: no silent re-download
    assert jobs.warnings == []

    assert jobs._get(URL, refetch=True) == b"<xbrl/>" and t.calls == 2
    assert jobs.warnings and "X322" in jobs.warnings[0]
    last = jobs.vault.last_fetch(URL)
    assert last["sha256"] != EMPTY_SHA
    lines = (tmp_path / "vault" / "url_index.jsonl").read_text().splitlines()
    assert len(lines) == 2  # both answers ledgered, in order
    assert jobs.vault.exists(f"e3/{EMPTY_SHA}.xml")  # the empty blob stays (append-only)
    assert jobs._get(URL) == b"<xbrl/>" and t.calls == 2  # the new blob is now the checkpoint
