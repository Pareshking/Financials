"""X140 rights entitlements, X141 reprocess without a staged batch, X142 ACCEPT with a payload on corporate-action
findings. Real fixture days and corporate-action windows; the misread purpose texts are in-memory modifications of the
real records (fixtures on disk are never changed)."""

from __future__ import annotations

import json
import re
import shutil
import zipfile

import pytest
from conftest import FETCHED_AT

from _fixture_helpers import BHAV_DIR, FIXTURES
from financials.admin import AdminError, list_quarantine, reprocess, resolve_quarantine
from financials.ids import stable_id
from financials.promoter import RIGHTS_ENTITLEMENT_NOTE, promote, resolve_rights_entitlement_gaps
from financials.staging import stage_corp_actions

CA_JSON = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
CA_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=15-09-2025&to_date=17-10-2025"
)


def _rows(name: str) -> list[list[str]]:
    with zipfile.ZipFile(BHAV_DIR / name) as zf:
        (inner,) = zf.namelist()
        lines = zf.read(inner).decode("utf-8-sig").splitlines()
    head = lines[0].split(",")
    return [dict(zip(head, ln.split(","), strict=False)) for ln in lines[1:]]


# ── X140 characterisation: what a rights entitlement looks like in the bhavcopy ──


def test_rights_entitlements_carry_type_code_20_and_a_parent_of_the_same_issuer():
    seen = 0
    for f in sorted(BHAV_DIR.glob("BhavCopy_NSE_CM_*.csv.zip")):
        rows = _rows(f.name)
        isins = {r["ISIN"] for r in rows}
        for r in rows:
            is_re_symbol = re.search(r"-RE[0-9]*$", r["TckrSymb"]) is not None
            is_re_isin = r["ISIN"].startswith("INE") and r["ISIN"][7:9] == "20"
            if r["SctySrs"] not in ("EQ", "BE", "BZ"):
                continue
            assert is_re_symbol == is_re_isin, (f.name, r["TckrSymb"], r["ISIN"])  # the two markers agree
            if is_re_symbol:
                seen += 1
                assert r["ISIN"][:7] + "01" in {i[:9] for i in isins}, (f.name, r["TckrSymb"])  # parent listed
    assert seen >= 15
    shivam = {r["TckrSymb"]: r for r in _rows("BhavCopy_NSE_CM_0_0_0_20261112_F_0000.csv.zip")}
    assert (shivam["SHIVAM-RE1"]["ISIN"], shivam["SHIVAM-RE1"]["SctySrs"]) == ("INE637H20024", "BE")
    assert shivam["SHIVAMAUTO"]["ISIN"] == "INE637H01024"


def test_a_rights_entitlement_gap_closes_by_rule_and_nothing_else_does(market):
    """CAPTRU-RE1 (Capital Trust's entitlement) opened 6.82 on 21 Oct 2025 after closing 8.87: -23%."""
    m = market
    for d in ("20251020", "20251021"):
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"  # promotion runs the rule itself
    sec = m.security_id("CAPTRU-RE1")
    (gap,) = list_quarantine(m.con, security_id=sec, include_resolved=True)
    assert gap["reason_code"] == "UNEXPLAINED_GAP" and json.loads(gap["details"])["trade_date"] == "2025-10-21"
    assert (gap["resolution"], gap["resolution_note"]) == ("FIXED_BY_RULE", RIGHTS_ENTITLEMENT_NOTE)
    others = m.con.execute(
        "SELECT DISTINCT h.symbol FROM quarantine_queue q JOIN security_identifier_history h USING (security_id) "
        "WHERE q.resolution_note = ?",
        [RIGHTS_ENTITLEMENT_NOTE],
    ).fetchall()
    assert others == [("CAPTRU-RE1",)]
    assert resolve_rights_entitlement_gaps(m.con) == 0  # idempotent


# ── X141: reprocess never claims a re-check it could not run ──


def test_reprocess_leaves_a_finding_open_when_its_batch_is_no_longer_staged(market):
    m = market
    promote(m.con, m.stage_day("20250919"))
    s = stage_corp_actions(m.vault, m.stage_root, data=CA_JSON.read_bytes(), source_url=CA_URL, fetched_at=FETCHED_AT)
    assert promote(m.con, s).status == "PROMOTED"
    stale = list_quarantine(m.con, reason_code="STALE_ISIN_OTHER_ISSUER")
    assert stale  # PREMIERPOL's dividend carries an ISIN of another issuer [CA7]
    shutil.rmtree(s)  # staging pruned after promotion
    r = reprocess(m.con, m.stage_root)
    assert r["batches"] == [] and r["cleared"] == []
    assert {q["quarantine_id"] for q in stale} <= set(r["batch_not_staged"])
    assert {q["quarantine_id"] for q in list_quarantine(m.con, reason_code="STALE_ISIN_OTHER_ISSUER")} == {
        q["quarantine_id"] for q in stale
    }


# ── X142: ACCEPT with a payload ──


def test_accepting_a_stale_isin_record_for_its_symbol_holder_records_the_action(market):
    m = market
    promote(m.con, m.stage_day("20250919"))
    s = stage_corp_actions(m.vault, m.stage_root, data=CA_JSON.read_bytes(), source_url=CA_URL, fetched_at=FETCHED_AT)
    promote(m.con, s)
    (q,) = [q for q in list_quarantine(m.con, reason_code="STALE_ISIN_OTHER_ISSUER")
            if json.loads(q["details"])["symbol"] == "PREMIERPOL"]  # fmt: skip
    d = json.loads(q["details"])
    assert (d["isin"], d["subject"]) == ("INE247401016", "Dividend - Re 0.15 Per Share")
    other = m.security_id("PIDILITIND")
    with pytest.raises(AdminError, match="never held"):
        resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note="x", payload={"security_id": other})
    sec = m.security_id("PREMIERPOL")
    r = resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note="NSE bc: PREMIERPOL DIV - RE 0.15",
                           payload={"security_id": sec})  # fmt: skip
    aid = stable_id("ca", "NSE", "INE247401016", d["ex_date"], d["subject"], 0)  # the id the promoter would give
    assert r["resolution"] == "ACCEPTED" and list(r["recorded_actions"]) == [aid]
    row = m.con.execute("SELECT security_id, action_type, cash_per_share FROM corp_actions WHERE action_id = ?",
                        [aid]).fetchone()  # fmt: skip
    assert row[:2] == (sec, "DIVIDEND") and str(row[2]) == "0.1500"


def test_accepting_a_meeting_notice_with_a_payload_is_refused(market):
    m = market
    promote(m.con, m.stage_day("20250919"))
    rows = json.loads(CA_JSON.read_bytes())
    for r in rows:
        if r["symbol"] == "PREMIERPOL":
            r["subject"] = "Extra Annual General Meeting"  # an unparsed text (GBGLOBAL's, live)
    s = stage_corp_actions(m.vault, m.stage_root, data=json.dumps(rows).encode(), source_url=CA_URL,
                           fetched_at=FETCHED_AT)  # fmt: skip
    promote(m.con, s)
    (q,) = [q for q in list_quarantine(m.con, reason_code="STALE_ISIN_OTHER_ISSUER")
            if json.loads(q["details"])["symbol"] == "PREMIERPOL"]  # fmt: skip
    with pytest.raises(AdminError, match="nothing to record"):
        resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note="x",
                           payload={"security_id": m.security_id("PREMIERPOL")})  # fmt: skip
    assert resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note="meeting notice")["resolution"] == (
        "ACCEPTED"
    )


@pytest.fixture
def misread_bonus(market):
    """PIDILITIND's real 1:1 bonus (ex 23 Sep 2025) recorded as 1:4: factor 0.8 against an observed ~0.5."""
    m = market
    promote(m.con, m.stage_day("20250922"))
    rows = json.loads(CA_JSON.read_bytes())
    for r in rows:
        if r["symbol"] == "PIDILITIND":
            r["subject"] = "Bonus 1:4"
    s = stage_corp_actions(m.vault, m.stage_root, data=json.dumps(rows).encode(), source_url=CA_URL,
                           fetched_at=FETCHED_AT)  # fmt: skip
    promote(m.con, s)
    promote(m.con, m.stage_day("20250923"))
    m.pid = m.security_id("PIDILITIND")
    return m


def test_accepting_a_failed_verification_applies_the_recorded_factor_and_reaudits_the_day(misread_bonus):
    m = misread_bonus
    (vf,) = list_quarantine(m.con, reason_code="VERIFY_FAILED", security_id=m.pid)
    (gap,) = list_quarantine(m.con, reason_code="UNEXPLAINED_GAP", security_id=m.pid)
    with pytest.raises(AdminError, match="accept_recorded_factor"):
        resolve_quarantine(m.con, vf["quarantine_id"], action="ACCEPT", note="x", payload={"other": 1})
    r = resolve_quarantine(m.con, vf["quarantine_id"], action="ACCEPT", note="ratio proven by Issue Size",
                           payload={"accept_recorded_factor": True})  # fmt: skip
    aid = json.loads(vf["details"])["action_id"]
    assert r["accepted_action"] == aid and r["gap_finding"] == gap["quarantine_id"]  # same deterministic finding
    assert -0.45 < float(r["residual_gap"]) < -0.30  # ~0.5 / 0.8 - 1: still a gap, left for its own decision
    status, pf = m.con.execute("SELECT status, price_factor FROM corp_actions WHERE action_id = ?", [aid]).fetchone()
    assert status == "VERIFIED_MANUAL" and pf == pytest.approx(0.8)
    assert list_quarantine(m.con, reason_code="UNEXPLAINED_GAP", security_id=m.pid)[0]["resolved_at"] is None
    with pytest.raises(AdminError, match="already resolved"):
        resolve_quarantine(m.con, vf["quarantine_id"], action="ACCEPT", note="x",
                           payload={"accept_recorded_factor": True})  # fmt: skip


def test_accepting_an_unparsed_record_with_its_parse_verifies_it(market):
    m = market
    promote(m.con, m.stage_day("20250922"))
    rows = json.loads(CA_JSON.read_bytes())
    for r in rows:
        if r["symbol"] == "PIDILITIND":
            r["subject"] = "Bonus issue one for one"
    s = stage_corp_actions(m.vault, m.stage_root, data=json.dumps(rows).encode(), source_url=CA_URL,
                           fetched_at=FETCHED_AT)  # fmt: skip
    promote(m.con, s)
    promote(m.con, m.stage_day("20250923"))
    pid = m.security_id("PIDILITIND")
    (q,) = list_quarantine(m.con, reason_code="UNPARSED_PURPOSE", security_id=pid)
    r = resolve_quarantine(m.con, q["quarantine_id"], action="ACCEPT", note="NSE bc: BONUS 1:1",
                           payload={"action_type": "BONUS", "ratio_num": 1, "ratio_den": 1})  # fmt: skip
    assert r["status"] == "VERIFIED"
    assert list_quarantine(m.con, reason_code="UNEXPLAINED_GAP", security_id=pid) == []  # explained on verification


def test_reprocess_reruns_the_named_market_rules(market):
    m = market
    for d in ("20251020", "20251021"):
        promote(m.con, m.stage_day(d))
    m.con.execute(  # an older finding, closed by nothing before the rule existed
        "UPDATE quarantine_queue SET resolved_at = NULL, resolution = NULL, resolution_note = NULL "
        "WHERE resolution_note = ?",
        [RIGHTS_ENTITLEMENT_NOTE],
    )
    r = reprocess(m.con, m.stage_root)
    assert r["market_rules"]["X140"] == 1
