"""Share cross-check and attribution rules from the universe expansion audit (work QC) [X187-X189].

- X187 SHARE_EVENT_AFTER_PERIOD_END: BLSE (BLS E-Services) Q2 FY27. The Reg. 31 pattern of 30-Sep-2026 (1743042)
  totals 90,856,485 shares of Rs 10; the 1:2 split went ex on 6-Oct-2026 (NSE corporate-actions fixture), before the
  results (1751399, 2-Nov-2026) were published, which state face value Rs 5 and paid-up 90.8565 Cr: 181,713,000 =
  2 x 90,856,485 (+30 shares of rounding). 14 open findings of 14 companies had this shape (live snapshot 2026-11-17).
- X188 PAID_UP_WHOLE_UNITS: Kewal Kiran (KKCL) Q2 FY27 states every rupee figure in whole crores; paid-up capital
  62 Cr / Rs 10 = 62,000,000 vs Reg. 31 61,625,185 (0.61% apart, 3.75 lakh rupees of capital: inside half a crore).
- X188 (zero): Atlanta Electricals Q1 FY27 tags paid-up capital 0 (Rs 2 face value): 0 / 2 is not a share count.
- X189 OWNERS_BEFORE_JV_SHARE: India Power (DPSCLTD) Q4 FY25 consolidated (1454124) tags owners -17,748,000 = PAT
  -18,661,000 less the JV share -913,000; NCI 0. The results PDF (consolidated statement, page 19) has no NCI line
  and prints "Profit/(loss) for the period (186.61)" lakhs (FY 702.98) after "Share of Profit/(Loss) of Joint
  Venture (9.13)". Gokul Agro FY26 (1667760): owners 3,700,655,000 = 37,006.55 lakhs before associates; the Q2 FY27
  PDF (page 6) prints the FY26 column "Share of Profit / (Loss) of Associates (68.97)", "Minority Interest 0.00".
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import FIXTURES
from financials.parsers.integrated import parse_integrated_results
from financials.promoter import close_resolved_share_findings, promote, share_disagreement
from financials.staging import stage_corp_actions, stage_results_xbrl, stage_shareholding

QC_DIR = FIXTURES / "xbrl_qc"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
KW = dict(fetched_at=datetime(2026, 11, 17, 6), broadcast_ts_source="API_FIELD")


def _promote(market, name, broadcast_ts):
    stage = stage_shareholding if name.startswith("SHP_") else stage_results_xbrl
    r = promote(market.con, stage(market.vault, market.stage_root, data=(QC_DIR / name).read_bytes(),
                                  source_url=URL + name, broadcast_ts=broadcast_ts, **KW))  # fmt: skip
    assert r.status == "PROMOTED", r
    return r


def _entity(market, filing_id):
    return market.con.execute("SELECT entity_id FROM filing_meta WHERE filing_id = ?", [filing_id]).fetchone()[0]


def _open(market, entity_id):
    return market.con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE reason_code = 'CROSS_CHECK_FAILED' AND entity_id = ? "
        "AND resolved_at IS NULL",
        [entity_id],
    ).fetchone()[0]


def test_split_after_the_period_end_explains_paid_up_over_face_value(market):
    promote(market.con, market.stage_day("20261112"))
    _promote(market, "SHP_1743042_21102026043910_WEB.xml", datetime(2026, 10, 21, 4, 39))
    r = _promote(market, "INTEGRATED_FILING_INDAS_1751399_02112026072220_WEB.xml", datetime(2026, 11, 2, 7, 22))
    ent, as_of = _entity(market, r.message), date(2026, 9, 30)
    details = share_disagreement(market.con, ent, as_of)  # no split in the ledger yet: 2x apart
    assert details["reg31_total"] == 90856485 and details["paid_up_over_face_value"] == 181713000
    assert _open(market, ent) == 1
    ca = FIXTURES / "corp_actions" / "nse_corporateActions_equities_21-09-2026_20-10-2026.json"
    promote(market.con, stage_corp_actions(market.vault, market.stage_root, data=ca.read_bytes(), source_url="nse-ca",
                                           fetched_at=datetime(2026, 11, 17, 6)))  # fmt: skip
    split = market.con.execute(
        "SELECT ca.ex_date, ca.ratio_num, ca.ratio_den, ca.status FROM corp_actions ca "
        "JOIN securities s USING (security_id) "
        "WHERE s.entity_id = ? AND ca.action_type = 'SPLIT'",
        [ent],
    ).fetchall()
    assert split == [(date(2026, 10, 6), 5, 10, "PENDING")]  # face value 10 -> 5; no bars to verify it
    assert share_disagreement(market.con, ent, as_of) is None
    assert close_resolved_share_findings(market.con) == 1 and _open(market, ent) == 0


def test_paid_up_capital_in_whole_crores_agrees_within_half_a_crore(market):
    promote(market.con, market.stage_day("20261112"))
    _promote(market, "SHP_1740781_17102026035440_WEB.xml", datetime(2026, 10, 17, 3, 54))
    _promote(market, "INTEGRATED_FILING_INDAS_1751446_02112026075601_WEB.xml", datetime(2026, 11, 2, 7, 56))
    r = _promote(market, "INTEGRATED_FILING_INDAS_1751447_02112026075620_WEB.xml", datetime(2026, 11, 2, 7, 56, 20))
    ent = _entity(market, r.message)
    paid = market.con.execute(
        "SELECT DISTINCT value_other FROM fact_observations WHERE entity_id = ? "
        "AND canonical_tag = 'shares_from_paid_up'",
        [ent],
    ).fetchall()
    assert paid == [(Decimal(62000000),)]
    reg31 = market.con.execute(
        "SELECT shares FROM shareholding_observations WHERE entity_id = ? AND category = 'TOTAL'", [ent]
    ).fetchone()[0]
    assert reg31 == 61625185 and abs(62000000 - reg31) / reg31 > Decimal("0.005")  # outside the 0.5% test
    # the finding raised when the first (consolidated) filing arrived closes on re-check: both filings now agree
    assert share_disagreement(market.con, ent, date(2026, 9, 30)) is None
    close_resolved_share_findings(market.con)
    assert _open(market, ent) == 0


def test_zero_paid_up_capital_is_not_a_share_count(market):
    promote(market.con, market.stage_day("20261112"))
    _promote(market, "SHP_1702639_28072026113716_WEB.xml", datetime(2026, 7, 28, 11, 37))
    r = _promote(market, "INTEGRATED_FILING_INDAS_1697896_21072026124625_WEB.xml", datetime(2026, 7, 21, 12, 46))
    ent = _entity(market, r.message)
    assert share_disagreement(market.con, ent, date(2026, 6, 30)) is None and _open(market, ent) == 0


def _split(name, period):
    r = parse_integrated_results((QC_DIR / name).read_bytes(), name)
    assert r.ok
    return {
        f.canonical_tag: (f.value, f.source_element)
        for f in r.facts
        if f.canonical_tag in ("pat", "pat_owners", "pat_nci", "share_of_associates_jv", "attribution_withheld")
        and (str(f.period_start), str(f.period_end)) == period
    }, r


def test_owners_before_the_jv_share_with_zero_nci_recover_as_pat():
    name = "INTEGRATED_FILING_INDAS_1454124_28052025104806_WEB.xml"
    for period, pat, jv in ((("2025-01-01", "2025-03-31"), -18661000, -913000),
                            (("2024-04-01", "2025-03-31"), 70298000, -913000)):  # fmt: skip
        s, r = _split(name, period)
        assert s["pat"][0] == pat and s["share_of_associates_jv"][0] == jv and s["pat_nci"][0] == 0
        assert s["pat_owners"] == (Decimal(pat), "RULE:OWNERS_BEFORE_JV_SHARE") and "attribution_withheld" not in s
    assert not [i for i in r.findings if i.reason_code == "ATTRIBUTION_WITHHELD"]
    filed = {f.value for f in r.facts if f.canonical_tag == "asfiled_profit_or_loss_attributable_to_owners_of_parent"}
    assert filed == {Decimal(-17748000), Decimal(71211000)}  # as filed, kept (C24)
    s, _ = _split("INTEGRATED_FILING_INDAS_1667760_15052026050235_WEB.xml", ("2025-04-01", "2026-03-31"))
    assert s["pat_owners"] == (Decimal(3693757000), "RULE:OWNERS_BEFORE_JV_SHARE")
    # the filed owners figure is PAT less the associates' share to one lakh (lakh rounding of each line)
    assert abs(s["pat"][0] - s["share_of_associates_jv"][0] - Decimal(3700655000)) <= 100000
