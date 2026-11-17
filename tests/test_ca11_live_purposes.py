"""CA11: purpose texts seen in the live backfill (14 real 30-day corporate-action API windows, 2024-10 .. 2026-11)."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal

from conftest import FETCHED_AT

from _fixture_helpers import FIXTURES
from financials.admin import list_quarantine
from financials.parsers.nse_corp_actions import parse_nse_corp_actions_json, parse_purpose
from financials.promoter import promote
from financials.staging import stage_corp_actions

LIVE = sorted((FIXTURES / "corp_actions").glob("nse_corporateActions_equities_*-20*_*.json"))
D = Decimal


def _all():
    return [r for p in LIVE for r in parse_nse_corp_actions_json(p.read_bytes())]


def test_every_live_purpose_parses_except_six_genuinely_ambiguous_texts():
    rows = _all()
    assert len(LIVE) == 15  # 14 live windows + the original 2025 window
    left = sorted(r.subject for r in rows if r.parse_status == "UNPARSED")
    assert left == sorted([
        "Capital Reduction", "Interim Dividend - Rs Per 0.50 Share", "Rights - 7 Ccps And 7 Warrants:40",
        "Scheme Of Arrangement - Bonus Ncrps 3:1", "Scheme Of Arrangement - Bonus Ncrps 4:1",
        "Scheme Of Arrangement - Bonus Ncrps 46:1",
    ])  # fmt: skip
    kinds = Counter(c.action_type for r in rows for c in r.components)
    assert kinds["CONSOLIDATION"] == 1 and kinds["SPLIT"] >= 60 and kinds["DIVIDEND"] > 2000


def test_meeting_notices_and_combined_dividends():
    assert parse_purpose("Annual General Meeting", None)[0] == "IGNORED"
    assert parse_purpose("Extra Ordinary General Meeting", None)[0] == "IGNORED"
    st, _, comps = parse_purpose("Annual General Meeting/Dividend - Rs 8 Per Share", None)
    assert st == "PARSED" and [(c.action_type, c.cash_per_share) for c in comps] == [("DIVIDEND", D(8))]
    for text in ("Dividend - Rs 5 Per Share & Special Dividend Rs 2 Per Share",
                 "Interim Dividend - Rs 5 Per Share Special Dividend - Rs 2 Per Share",
                 "Dividend - Rs 5 Per Share/ Special Dividend - Rs 2",
                 "Dividend - Rs 5 Per Share And Special Dividend Rs 2 Per Share"):  # fmt: skip
        st, _, comps = parse_purpose(text, None)
        assert st == "PARSED" and [c.cash_per_share for c in comps] == [D(5), D(2)], text
    st, _, comps = parse_purpose("Dividend - Rs 35 Per Share & Special Dividend Of Rs 100 Per Share/ "
                                 "Special Dividend Of Rs 30", None)  # fmt: skip
    assert [c.cash_per_share for c in comps] == [D(35), D(100), D(30)]  # two different specials, as filed


def test_typos_rights_wordings_and_consolidation():
    for typo in (
        "Intereim Dividend - Rs 2 Per Share",
        "IntDividend - Rs 2 Per Share",
        "InterimDividend - Re 2 Per Share",
    ):
        assert parse_purpose(typo, None)[0] == "PARSED", typo
    for text in ("Rights 1:5 @ Premium Rs 90", "Rights 1:5 @ Premium 90", "Rights 1:5 @ Prm Rs 90/-"):
        st, _, (c,) = parse_purpose(text, D(10))
        assert st == "PARSED" and (c.ratio_num, c.ratio_den, c.issue_price) == (D(1), D(5), D(100)), text
    st, _, (c,) = parse_purpose("Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share", None)
    assert (st, c.action_type, c.ratio_num, c.ratio_den) == ("PARSED", "CONSOLIDATION", D(10), D(1))
    # the face-value split wording keeps its "/-" (not a separator)
    st, _, (c,) = parse_purpose("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", None)
    assert (st, c.ratio_num, c.ratio_den) == ("PARSED", D(2), D(10))


def test_a_record_stored_unparsed_is_upgraded_when_the_parser_reads_it(market):
    """The same real record promoted once with an unreadable purpose (in memory) and again as filed: one ledger
    row, upgraded to the parsed type, its UNPARSED_PURPOSE finding closed."""
    m = market
    promote(m.con, m.stage_day("20250922"))
    src = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
    rows = json.loads(src.read_bytes())
    pid = [r for r in rows if r["symbol"] == "PIDILITIND"]
    bad = [dict(pid[0], subject="Bonus 1:1")]
    unreadable = json.dumps([dict(bad[0], subject="Bonus one for one")]).encode()
    s1 = stage_corp_actions(m.vault, m.stage_root, data=unreadable, source_url="memory://unparsed",
                            fetched_at=FETCHED_AT)  # fmt: skip
    promote(m.con, s1)
    assert len(list_quarantine(m.con, reason_code="UNPARSED_PURPOSE")) == 1
    # NSE later re-sends the record under the same subject the parser now reads: same id only if subject equal,
    # so the upgrade path is exercised by re-promoting the same subject after a parser change, simulated here by
    # recording the UNKNOWN row under the parsed subject's id.
    from financials.ids import stable_id

    good_id = stable_id("ca", "NSE", bad[0]["isin"], __import__("datetime").date(2025, 9, 23), "Bonus 1:1", 0)
    m.con.execute("UPDATE corp_actions SET action_id = ? WHERE action_type = 'UNKNOWN'", [good_id])
    m.con.execute("UPDATE quarantine_queue SET details = json_merge_patch(details, ?) WHERE reason_code = "
                  "'UNPARSED_PURPOSE'", [json.dumps({"action_id": good_id})])  # fmt: skip
    s2 = stage_corp_actions(m.vault, m.stage_root, data=json.dumps(bad).encode(), source_url="memory://parsed",
                            fetched_at=FETCHED_AT)  # fmt: skip
    promote(m.con, s2)
    assert m.con.execute("SELECT action_type, status FROM corp_actions").fetchall() == [("BONUS", "PENDING")]
    assert list_quarantine(m.con, reason_code="UNPARSED_PURPOSE") == []
