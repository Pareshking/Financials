"""Share cross-check and attribution rules of work QC2 (universe expansion, NEW entities) [X211-X214].

- X211 (X187 amended): BLS E-Services re-sent its Q4 FY25 consolidated results on 21-Oct-2026 (1743401), after the
  1:2 split went ex on 6-Oct-2026; the re-send states the period's own face value Rs 10 and paid-up 90.8565 Cr =
  90,856,500 shares = the Reg. 31 total of 31-Mar-2025 (90,856,485). X187 alone expected 2 x that total.
- X212 ALLOTMENT_BEFORE_RESULTS: Selan Q1 FY26 (1510694, board meeting 12-Aug-2025) tags paid-up 35.16 Cr =
  35,162,358 shares after the 19,962,358 shares allotted at that meeting under its scheme of arrangement (results PDF
  page 1); the Reg. 31 of 30-Jun-2025 has 15,200,000 and the event-dated Reg. 31 of 12-Aug-2025 35,162,358. Davangere
  Sugar Q2 FY27 (1757893, 13-Nov-2026) states 1,695,896,000 shares of Re 1; NSE's PR-zip of 13-Nov-2026 lists
  1,695,895,798 (Reg. 31 of 30-Sep-2026: 1,429,990,798).
- X213 TRUST_HOLDERS_OUTSIDE_EMPLOYEE_TRUSTS: Digispice Q4 FY25 standalone (1449578) paid-up 62.2665 Cr / Rs 3 =
  207,555,000 shares; Reg. 31 of 31-Mar-2025 totals 233,623,106 and names 'Independent Non Promoter Trust'
  15,912,776 and 'Independent Non Promoter (Spice Employee Benefit)Trust' 10,155,067 under non-institutions "Others";
  results PDF note 6: paid-up 7,008.69 lakhs presented net of the two trusts' shares under Ind AS 32.
- X214 ATTRIBUTION_BY_EPS: Ajmera Q2 FY26 consolidated (1567276) owners 0, NCI 87 lakh, PAT 3,124 lakh; EPS 7.72 x
  39,360,000 = 3,038.6 lakh; PDF 'Profit/(Loss) after Tax and Non Controlling Interests' 3,037 lakh (Q2) / 6,865
  (H1). Bajaj Indef H1 FY26 re-filing (1598932) NCI +3.5 lakh with owners 0; the PDF prints 'Share of Non
  controlling Interest' (3.50) and owners 625.95 (Q2) / 1,191.16 (H1) lakh; EPS 1.96 / 3.72 picks PAT + 3.5 lakh.
  Nilkamal FY25 (1439263): owners 1,064.27 Mn agree with EPS 71.32 x 14,922,500, but the PAT line (1,832 Mn, tax as a
  credit) is not; owners are kept and the NCI is dropped, not derived.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from _fixture_helpers import FIXTURES
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.shareholding import parse_shareholding
from financials.promoter import close_resolved_share_findings, promote, share_disagreement
from financials.staging import stage_corp_actions, stage_mcap_day, stage_results_xbrl, stage_shareholding

QC2 = FIXTURES / "xbrl_qc2"
URL = "https://nsearchives.nseindia.com/corporate/xbrl/"
KW = dict(fetched_at=datetime(2026, 11, 17, 6), broadcast_ts_source="API_FIELD")


def _promote(market, name, broadcast_ts):
    stage = stage_shareholding if name.startswith("SHP_") else stage_results_xbrl
    r = promote(market.con, stage(market.vault, market.stage_root, data=(QC2 / name).read_bytes(),
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


def test_x211_resend_after_a_split_states_the_period_end_count(market):
    promote(market.con, market.stage_day("20261112"))
    ca = FIXTURES / "corp_actions" / "nse_corporateActions_equities_21-09-2026_20-10-2026.json"
    promote(market.con, stage_corp_actions(market.vault, market.stage_root, data=ca.read_bytes(), source_url="nse-ca",
                                           fetched_at=datetime(2026, 11, 17, 6)))  # fmt: skip
    _promote(market, "SHP_197284_1415020_15042025053836_WEB.xml", datetime(2025, 4, 15, 5, 38))
    r = _promote(market, "INTEGRATED_FILING_INDAS_1743401_21102026064421_WEB.xml", datetime(2026, 10, 21, 6, 44))
    ent = _entity(market, r.message)
    split = market.con.execute(
        "SELECT ca.ex_date, ca.ratio_num, ca.ratio_den FROM corp_actions ca JOIN securities s USING (security_id) "
        "WHERE s.entity_id = ? AND ca.action_type = 'SPLIT'",
        [ent],
    ).fetchall()
    assert split == [(date(2026, 10, 6), 5, 10)]  # ex-date after 31-Mar-2025, before the re-send
    paid = market.con.execute(
        "SELECT DISTINCT value_other FROM fact_observations WHERE entity_id = ? AND canonical_tag = "
        "'shares_from_paid_up' AND period_end = DATE '2025-03-31'",
        [ent],
    ).fetchall()
    assert paid == [(Decimal(90856500),)]  # face value Rs 10 of the period, not the post-split Rs 5
    assert share_disagreement(market.con, ent, date(2025, 3, 31)) is None and _open(market, ent) == 0


def test_x212_allotment_at_the_results_meeting_agrees_with_the_next_reg31(market):
    promote(market.con, market.stage_day("20261112"))
    _promote(market, "SHP_1485504_17072025045200_WEB.xml", datetime(2025, 7, 17, 4, 52))
    r = _promote(market, "INTEGRATED_FILING_INDAS_1510694_13082025021504_WEB.xml", datetime(2025, 8, 12, 20, 45))
    ent, as_of = _entity(market, r.message), date(2025, 6, 30)
    details = share_disagreement(market.con, ent, as_of)
    assert details["reg31_total"] == 15200000 and details["paid_up_over_face_value"] == 35160000
    assert _open(market, ent) == 1
    s = _promote(market, "SHP_1515913_21082025073534_WEB.xml", datetime(2025, 8, 21, 7, 35))
    assert market.con.execute(
        "SELECT as_of_date, shares FROM shareholding_observations WHERE filing_id = ? AND category = 'TOTAL'",
        [s.message],
    ).fetchall() == [(date(2025, 8, 12), 35162358)]  # event-dated pattern of the allotment (SHP17)
    assert share_disagreement(market.con, ent, as_of) is None
    assert close_resolved_share_findings(market.con) == 1 and _open(market, ent) == 0


def test_x212_paid_up_agrees_with_nse_issue_size_on_the_results_date(market):
    promote(market.con, market.stage_day("20261112"))
    _promote(market, "SHP_1742915_21102026035238_WEB.xml", datetime(2026, 10, 21, 3, 52))
    r = _promote(market, "INTEGRATED_FILING_INDAS_1757893_13112026081803_WEB.xml", datetime(2026, 11, 13, 8, 18))
    ent, as_of = _entity(market, r.message), date(2026, 9, 30)
    details = share_disagreement(market.con, ent, as_of)
    assert details["reg31_total"] == 1429990798 and details["paid_up_over_face_value"] == 1695896000
    pr = (FIXTURES / "pr_zip" / "PR131126.zip").read_bytes()
    url = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR131126.zip"
    staged = stage_mcap_day(market.vault, market.stage_root, data=pr, source_url=url, fetched_at=KW["fetched_at"])
    promote(market.con, staged)
    issue = market.con.execute(
        "SELECT trade_date, issue_size FROM raw_nse_mcap WHERE symbol = 'DAVANGERE' AND series = 'EQ'"
    ).fetchall()
    assert issue == [(date(2026, 11, 13), 1695895798)]
    assert share_disagreement(market.con, ent, as_of) is None
    close_resolved_share_findings(market.con)
    assert _open(market, ent) == 0


def test_x213_trust_holders_named_under_others_are_treasury_shares(market):
    shp = parse_shareholding((QC2 / "SHP_198927_1422138_21042025100818_WEB.xml").read_bytes())
    others = {(h["holder_name"], h["shares"]) for h in shp.major_holders
              if h["holder_category"] == "OTHER_NON_INSTITUTIONS"}  # fmt: skip
    # the sub-category row 'Trusts' (no 'Category' flag) is not a holder; the word 'trust' alone selects the two
    assert {("Trusts", 26067843), ("Independent Non Promoter Trust", 15912776),
            ("Independent Non Promoter (Spice Employee Benefit)Trust", 10155067)} <= others  # fmt: skip
    assert {n for n, _ in others if re.search(r"(?i)\btrust\b", n)} == {
        "Independent Non Promoter Trust", "Independent Non Promoter (Spice Employee Benefit)Trust"}  # fmt: skip
    promote(market.con, market.stage_day("20261112"))
    _promote(market, "SHP_198927_1422138_21042025100818_WEB.xml", datetime(2025, 4, 21, 10, 8))
    r = _promote(market, "INTEGRATED_FILING_INDAS_1449578_23052025092633_WEB.xml", datetime(2025, 5, 23, 9, 26))
    ent = _entity(market, r.message)
    total = market.con.execute(
        "SELECT shares FROM shareholding_observations WHERE entity_id = ? AND category = 'TOTAL'", [ent]
    ).fetchone()[0]
    assert total == 233623106 and total - 15912776 - 10155067 == 207555263  # paid-up / Rs 3 = 207,555,000
    assert share_disagreement(market.con, ent, date(2025, 3, 31)) is None and _open(market, ent) == 0


def _attr(name, period):
    r = parse_integrated_results((QC2 / name).read_bytes(), name)
    assert r.ok
    got = {f.canonical_tag: (f.value, f.source_element) for f in r.facts
           if f.canonical_tag in ("pat", "pat_owners", "pat_nci", "attribution_withheld")
           and (str(f.period_start), str(f.period_end)) == period}  # fmt: skip
    return got, r


def test_x214_owners_zero_placeholder_recovered_as_pat_less_nci():
    name = "INTEGRATED_FILING_INDAS_1567276_06112025071457_WEB.xml"
    for period, pat, nci, owners in ((("2025-07-01", "2025-09-30"), 312400000, 8700000, 303700000),
                                     (("2025-04-01", "2025-09-30"), 706800000, 20300000, 686500000)):  # fmt: skip
        got, r = _attr(name, period)
        assert got["pat"][0] == pat and "attribution_withheld" not in got
        assert got["pat_owners"] == (Decimal(owners), "RULE:ATTRIBUTION_BY_EPS")
        assert got["pat_nci"] == (Decimal(nci), "RULE:ATTRIBUTION_BY_EPS")
    filed = {f.value for f in r.facts if f.canonical_tag == "asfiled_profit_or_loss_attributable_to_owners_of_parent"}
    assert filed == {Decimal(0)}  # as filed, kept (C24)
    assert not [i for i in r.findings if i.reason_code == "ATTRIBUTION_WITHHELD"]


def test_x214_eps_flips_the_nci_sign():
    name = "INTEGRATED_FILING_INDAS_1598932_12012026052921_WEB.xml"
    for period, owners in ((("2025-07-01", "2025-09-30"), 62595000), (("2025-04-01", "2025-09-30"), 119116000)):
        got, _ = _attr(name, period)
        assert got["pat_owners"] == (Decimal(owners), "RULE:ATTRIBUTION_BY_EPS")  # 625.95 / 1,191.16 lakh (PDF)
        assert got["pat_nci"] == (Decimal(-350000), "RULE:ATTRIBUTION_BY_EPS")  # filed +3.5 lakh


def test_x214_owners_agreeing_with_eps_keep_no_derived_nci():
    got, r = _attr("INTEGRATED_FILING_INDAS_1439263_14052025102806_WEB.xml", ("2024-04-01", "2025-03-31"))
    assert got["pat_owners"] == (Decimal(1064266000), "RULE:ATTRIBUTION_BY_EPS")
    assert "pat_nci" not in got and "attribution_withheld" not in got
    eps = next(f.value for f in r.facts if f.canonical_tag == "eps_basic"
               and (str(f.period_start), str(f.period_end)) == ("2024-04-01", "2025-03-31"))  # fmt: skip
    assert abs(eps * 14922500 - 1064266000) < Decimal("0.005") * 1064266000
