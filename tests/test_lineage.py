"""Corporate lineage (G37, G51, G56-G58; architecture §11.7, references CA14).

Pure position conversion and COA-split checks on hand-made edges, the manifest pinned to committed fixtures, and the
audited admin path on real fixture days (TATAMOTORS demerger ex 2025-10-14, TMCV listed in the 2026-11-12 bhavcopy).
"""

import io
import json
import re
import zipfile
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from conftest import FETCHED_AT, Market

from _fixture_helpers import BHAV_DIR, FIXTURES
from financials.admin import (
    AdminError,
    add_lineage,
    amend_lineage,
    load_lineage_manifest,
    retire_lineage,
    set_demerger_coa,
)
from financials.cli import main
from financials.lineage import (
    Holding,
    LineageEdge,
    LineageError,
    coa_split,
    convert_position,
    current_edges,
    load_edges,
    parse_ratio,
    read_manifest,
)
from financials.promoter import adjusted_closes, promote
from financials.staging import stage_corp_actions

MANIFEST = Path(__file__).parents[1] / "reference" / "entity_lineage.csv"
CA_FILE = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
EX = date(2025, 10, 14)


def edge(lid, parent, child, relation, eff, ratio=None, coa=None, pcoa=None, state="ACTIVE", sup=None):
    num, den = parse_ratio(ratio)
    return LineageEdge(lid, parent, child, relation, eff, num, den, coa, pcoa, state, sup)


# ── pure ───────────────────────────────────────────────────────────────────


def test_edge_validation():
    with pytest.raises(LineageError, match="relation"):
        edge("x", "A", "B", "SPUN_OFF", EX)
    with pytest.raises(LineageError, match="differ"):
        edge("x", "A", "A", "MERGED_INTO", EX)
    with pytest.raises(LineageError, match="demerger only"):
        edge("x", "A", "B", "MERGED_INTO", EX, coa=D(10))
    with pytest.raises(LineageError, match="positive"):
        parse_ratio("0:1")
    with pytest.raises(LineageError, match="A:B"):
        parse_ratio("3")
    assert parse_ratio("3:2") == (D(3), D(2)) and parse_ratio("") == (None, None)


def test_current_edges_follow_supersession_and_retirement():
    a = edge("a", "P", "T", "MERGED_INTO", EX)
    b = edge("b", "P", "T", "MERGED_INTO", EX, ratio="1:2", sup="a")
    assert current_edges([a, b]) == [b]
    c = edge("c", "P", "T", "MERGED_INTO", EX, ratio="1:2", state="RETIRED", sup="b")
    assert current_edges([a, b, c]) == []


def test_merger_converts_target_shares_by_swap_ratio():
    e = [edge("m", "ACQ", "TGT", "MERGED_INTO", date(2025, 6, 2), ratio="3:2")]
    assert convert_position(e, "TGT", 100, date(2025, 6, 2)) == [Holding("ACQ", D(150), D(1))]
    assert convert_position(e, "TGT", 100, date(2025, 6, 1)) == [Holding("TGT", D(100), D(1))]  # not yet effective
    assert convert_position(e, "TGT", 100, date(2026, 1, 1), held_since=date(2025, 6, 2)) == [
        Holding("TGT", D(100), D(1))
    ]  # bought on/after the effective date: nothing to convert
    assert convert_position(e, "ACQ", 10, date(2026, 1, 1)) == [Holding("ACQ", D(10), D(1))]  # acquirer unchanged
    assert convert_position(e, "TGT", 3, date(2026, 1, 1)) == [Holding("ACQ", D("4.5"), D(1))]  # fraction kept
    with pytest.raises(LineageError, match="no verified swap"):
        convert_position([edge("m", "ACQ", "TGT", "AMALGAMATED", EX)], "TGT", 100, EX)


def test_demerger_adds_children_and_splits_cost():
    eff = date(2025, 10, 14)
    e = [
        edge("d1", "PAR", "CH1", "DEMERGED_FROM", eff, ratio="1:1", coa=D("30"), pcoa=D("60")),
        edge("d2", "PAR", "CH2", "DEMERGED_FROM", eff, ratio="1:5", coa=D("10"), pcoa=D("60")),
    ]
    assert coa_split(e, "PAR", eff).complete
    assert convert_position(e, "PAR", 100, eff) == [
        Holding("CH1", D(100), D("0.3")),
        Holding("CH2", D(20), D("0.1")),
        Holding("PAR", D(100), D("0.6")),
    ]
    # Incomplete split (one child without COA): shares still convert, cost is unknown.
    partial = [e[0], edge("d2", "PAR", "CH2", "DEMERGED_FROM", eff, ratio="1:5")]
    assert not coa_split(partial, "PAR", eff).complete
    assert {h.cost_fraction for h in convert_position(partial, "PAR", 100, eff)} == {None}


def test_coa_split_must_not_exceed_or_miss_100():
    eff = date(2025, 10, 14)
    over = [edge("d1", "P", "C", "DEMERGED_FROM", eff, coa=D(50), pcoa=D(60))]
    with pytest.raises(LineageError, match="sums to"):
        coa_split(over, "P", eff)
    short = [edge("d1", "P", "C", "DEMERGED_FROM", eff, coa=D(30), pcoa=D(60))]
    with pytest.raises(LineageError, match="not 100"):
        coa_split(short, "P", eff)
    disagree = [edge("d1", "P", "C1", "DEMERGED_FROM", eff, coa=D(20), pcoa=D(60)),
                edge("d2", "P", "C2", "DEMERGED_FROM", eff, coa=D(20), pcoa=D(70))]  # fmt: skip
    with pytest.raises(LineageError, match="disagree"):
        coa_split(disagree, "P", eff)


def test_chained_merger_then_demerger():
    e = [
        edge("m", "A", "T", "MERGED_INTO", date(2025, 3, 3), ratio="1:2"),
        edge("d", "A", "B", "DEMERGED_FROM", date(2025, 9, 1), ratio="1:1", coa=D(25), pcoa=D(75)),
    ]
    assert convert_position(e, "T", 200, date(2025, 12, 31)) == [
        Holding("A", D(100), D("0.75")),
        Holding("B", D(100), D("0.25")),
    ]


# ── manifest evidence [CA14] ──────────────────────────────────────────────


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_manifest_rows_are_pinned_to_committed_fixtures():
    rows = read_manifest(MANIFEST.read_text(encoding="utf-8"))
    assert len(rows) == 1
    (r,) = rows
    notice = _norm((FIXTURES / r["evidence_fixture"]).read_text(encoding="utf-8"))
    assert _norm(r["evidence_quote"]) in notice
    assert "Tata Motors Ltd. (TMCV) was listed on November 12, 2025" in notice
    assert r["evidence_url"] in (FIXTURES / "MANIFEST.md").read_text(encoding="utf-8")
    # Parent: the DEMERGER record (symbol TMPV, CA1) on the ISIN that kept trading on the ex-date (P7).
    ca = json.loads(CA_FILE.read_text(encoding="utf-8"))
    ca = ca if isinstance(ca, list) else ca["data"]
    assert [(x["symbol"], x["exDate"]) for x in ca if x["isin"] == r["parent"] and x["subject"] == "Demerger"] == [
        ("TMPV", "14-Oct-2025")
    ]
    assert date.fromisoformat(r["effective_date"]) == EX
    # Child: the ISIN the 2026-11-12 bhavcopy lists for symbol TMCV.
    with zipfile.ZipFile(BHAV_DIR / "BhavCopy_NSE_CM_0_0_0_20261112_F_0000.csv.zip") as z:
        text = z.read(z.namelist()[0]).decode()
    assert f",{r['child']},TMCV,EQ," in text
    # Nothing unverified: no ratio or COA in the manifest (R7 is UNVERIFIED).
    assert not any(r[k] for k in ("ratio_num", "ratio_den", "coa_pct", "parent_coa_pct"))


def test_no_committed_corp_action_carries_a_merger_purpose():
    """[CA14] (b): merger parsing stays BLOCKED; the only scheme texts are NCRPS bonus schemes."""
    subjects = []
    for f in sorted((FIXTURES / "corp_actions").glob("nse_corporateActions_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        subjects += [r["subject"] for r in (data if isinstance(data, list) else data["data"])]
    assert len(subjects) > 1000
    assert [x for x in subjects if re.search(r"merg|amalg", x, re.I) and x != "Demerger"] == []
    assert {x for x in subjects if re.search("scheme", x, re.I)} == {
        "Scheme Of Arrangement - Bonus Ncrps 46:1",
        "Scheme Of Arrangement - Bonus Ncrps 4:1",
        "Scheme Of Arrangement - Bonus Ncrps 3:1",
    }
    rss = (FIXTURES / "corp_actions" / "RSS_Corporate_action_20261113.xml").read_text(encoding="utf-8")
    assert not re.search(r"merg|amalg", rss, re.I)


# ── admin path on real fixture days ───────────────────────────────────────


@pytest.fixture(scope="module")
def days(tmp_path_factory):
    m = Market(tmp_path_factory.mktemp("lineage"))
    assert promote(m.con, m.stage_day("20251013")).status == "PROMOTED"
    stage = stage_corp_actions(m.vault, m.stage_root, data=CA_FILE.read_bytes(), source_url="nse-ca",
                               fetched_at=FETCHED_AT)  # fmt: skip
    promote(m.con, stage)
    for d in ("20251014", "20261112"):
        promote(m.con, m.stage_day(d))
    yield m
    m.con.close()


@pytest.fixture
def mkt(days, tmp_path):
    """A fresh copy of the promoted days per test (admin writes must not leak between tests)."""
    import shutil

    from financials.db import connect

    days.con.execute("CHECKPOINT")
    shutil.copy(days.con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()")
                .fetchone()[0], tmp_path / "m.duckdb")  # fmt: skip
    con = connect(tmp_path / "m.duckdb")
    yield con
    con.close()


def entity(con, symbol):
    rows = con.execute("SELECT DISTINCT s.entity_id FROM security_identifier_history h JOIN securities s "
                       "USING (security_id) WHERE h.symbol = ?", [symbol]).fetchall()  # fmt: skip
    assert len(rows) == 1, (symbol, rows)
    return rows[0][0]


def security(con, symbol):
    return con.execute("SELECT DISTINCT security_id FROM security_identifier_history WHERE symbol = ?",
                       [symbol]).fetchone()[0]  # fmt: skip


def test_manifest_loads_the_tata_motors_demerger(mkt):
    tmpv_closes = adjusted_closes(mkt, security(mkt, "TMPV"))
    r = load_lineage_manifest(mkt, read_manifest(MANIFEST.read_text(encoding="utf-8")))
    assert len(r["inserted"]) == 1 and r["skipped"] == []
    (e,) = load_edges(mkt)
    assert (e.parent_entity_id, e.child_entity_id, e.relation, e.effective_date) == (
        entity(mkt, "TMPV"), entity(mkt, "TMCV"), "DEMERGED_FROM", EX)  # fmt: skip
    assert e.ratio is None and e.coa_pct is None  # R7 unverified: not stored
    ev = mkt.execute("SELECT evidence_filing_id, source FROM entity_lineage").fetchone()
    action_filing = mkt.execute(
        "SELECT source_filing_id FROM corp_actions WHERE action_type = 'DEMERGER' AND ex_date = ? AND security_id = ?",
        [EX, security(mkt, "TMPV")],
    ).fetchone()[0]
    assert ev == (action_filing, "MANIFEST")
    assert load_lineage_manifest(mkt, read_manifest(MANIFEST.read_text(encoding="utf-8")))["inserted"] == []
    assert adjusted_closes(mkt, security(mkt, "TMPV")) == tmpv_closes  # lineage never touches prices
    # A demerged child stays ACTIVE; no ratio yet, so a backtest cannot convert the position.
    assert mkt.execute("SELECT status FROM entity_master WHERE entity_id = ?", [e.child_entity_id]).fetchone() == (
        "ACTIVE",)  # fmt: skip
    with pytest.raises(LineageError, match="no verified"):
        convert_position(load_edges(mkt), e.parent_entity_id, 100, EX)

    # G51 / G58 by admin entry (synthetic figures and URL: the real ones are UNVERIFIED, R7).
    amend_lineage(mkt, e.lineage_id, ratio_num=D(1), ratio_den=D(1), evidence_url="test://ratio", note="test")
    with pytest.raises(AdminError, match="not 100"):
        set_demerger_coa(mkt, parent="TMPV", effective_date=EX, parent_pct=D(60), children={"TMCV": D(30)},
                         evidence_url="test://coa", note="test")  # fmt: skip
    with pytest.raises(AdminError, match="children are"):
        set_demerger_coa(mkt, parent="TMPV", effective_date=EX, parent_pct=D(60), children={"RELIANCE": D(40)},
                         evidence_url="test://coa", note="test")  # fmt: skip
    set_demerger_coa(mkt, parent="TMPV", effective_date=EX, parent_pct=D(60), children={"TMCV": D(40)},
                     evidence_url="test://coa", note="test")  # fmt: skip
    assert convert_position(load_edges(mkt), e.parent_entity_id, 100, EX) == sorted(
        [Holding(e.parent_entity_id, D(100), D("0.6")), Holding(e.child_entity_id, D(100), D("0.4"))],
        key=lambda h: h.entity_id,
    )
    assert mkt.execute("SELECT count(*) FROM entity_lineage").fetchone()[0] == 3  # append-only: 1 + amend + coa
    assert mkt.execute("SELECT count(*) FROM admin_log WHERE action LIKE 'LINEAGE_%'").fetchone()[0] == 3
    # A re-load after the amendment leaves the amended edge current.
    assert load_lineage_manifest(mkt, read_manifest(MANIFEST.read_text(encoding="utf-8")))["inserted"] == []
    assert load_edges(mkt)[0].coa_pct == D(40)
    retire_lineage(mkt, load_edges(mkt)[0].lineage_id, note="withdrawn")  # a retired scheme needs no COA check
    assert load_edges(mkt) == []


def test_demerger_edge_needs_the_parents_accepted_action(mkt):
    with pytest.raises(AdminError, match="no accepted DEMERGER"):
        add_lineage(mkt, parent="RELIANCE", child="TMCV", relation="DEMERGED_FROM", effective_date=EX,
                    evidence_url="test://x", note="test")  # fmt: skip


def test_merger_marks_target_and_never_adjusts_prices(mkt):
    """G56 / G57: target MERGED with merged_into; neither series is back-adjusted (factor 1.0)."""
    acq, tgt = security(mkt, "RELIANCE"), security(mkt, "INFY")
    before = {s: adjusted_closes(mkt, s) for s in (acq, tgt)}
    raw_tgt = sorted(mkt.execute("SELECT trade_date, close FROM ohlcv WHERE security_id = ?", [tgt]).fetchall())
    actions_before = mkt.execute("SELECT count(*) FROM corp_actions").fetchone()[0]
    r = add_lineage(mkt, parent="RELIANCE", child="INFY", relation="MERGED_INTO", effective_date=EX,
                    ratio_num=D(1), ratio_den=D(4), evidence_url="test://merger", note="synthetic")  # fmt: skip
    assert r["inserted"]
    status = mkt.execute("SELECT status, merged_into, inactive_date FROM entity_master WHERE entity_id = ?",
                         [entity(mkt, "INFY")]).fetchone()  # fmt: skip
    assert status == ("MERGED", entity(mkt, "RELIANCE"), EX)
    assert {s: adjusted_closes(mkt, s) for s in (acq, tgt)} == before
    # The target's own history stays as traded (to the day-gap freeze the fixture's year-long hole causes, C4).
    assert len(before[tgt]) >= 2 and before[tgt] == raw_tgt[: len(before[tgt])]
    assert mkt.execute("SELECT count(*) FROM corp_actions").fetchone()[0] == actions_before
    assert convert_position(load_edges(mkt), entity(mkt, "INFY"), 400, EX) == [
        Holding(entity(mkt, "RELIANCE"), D(100), D(1))
    ]
    with pytest.raises(AdminError, match="edge exists"):
        add_lineage(mkt, parent="RELIANCE", child="INFY", relation="MERGED_INTO", effective_date=EX,
                    evidence_url="test://merger", note="again")  # fmt: skip
    with pytest.raises(AdminError, match="already MERGED"):
        add_lineage(mkt, parent="TCS", child="INFY", relation="MERGED_INTO", effective_date=EX,
                    evidence_url="test://merger", note="other acquirer")  # fmt: skip
    assert mkt.execute("SELECT count(*) FROM company_overrides WHERE field = 'lineage'").fetchone()[0] == 1

    retire_lineage(mkt, r["lineage_id"], note="entered by mistake")
    assert load_edges(mkt) == []
    assert mkt.execute("SELECT status, merged_into FROM entity_master WHERE entity_id = ?",
                       [entity(mkt, "INFY")]).fetchone() == ("ACTIVE", None)  # fmt: skip
    with pytest.raises(AdminError, match="superseded or retired"):
        retire_lineage(mkt, r["lineage_id"], note="twice")
    again = add_lineage(mkt, parent="RELIANCE", child="INFY", relation="MERGED_INTO", effective_date=EX,
                        ratio_num=D(1), ratio_den=D(4), evidence_url="test://merger", note="re-entered")  # fmt: skip
    assert again["inserted"] and again["lineage_id"] != r["lineage_id"]
    assert [e.lineage_id for e in load_edges(mkt)] == [again["lineage_id"]]
    assert mkt.execute("SELECT count(*) FROM entity_lineage").fetchone()[0] == 3


def test_cli_lineage(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    m = Market(data)
    for d in ("20251013", "20261112"):
        promote(m.con, m.stage_day(d))
    m.con.close()
    out = io.StringIO()
    code = main(["--data-dir", str(data), "lineage", "load", "--manifest", str(MANIFEST)], out=out)
    assert code == 0  # no corporate-action file promoted: the demerger row waits for its action
    assert "no accepted DEMERGER" in json.loads(out.getvalue())["skipped"][0]["reason"]
    out = io.StringIO()
    code = main(["--data-dir", str(data), "lineage", "add", "--parent", "RELIANCE", "--child", "INFY", "--relation",
                 "MERGED_INTO", "--effective", "2025-10-14", "--ratio", "1:4", "--evidence-url", "test://m",
                 "--note", "synthetic"], out=out)  # fmt: skip
    assert code == 0 and json.loads(out.getvalue())["inserted"]
    out = io.StringIO()
    assert main(["--data-dir", str(data), "lineage", "list"], out=out) == 0
    (row,) = json.loads(out.getvalue())
    assert row["relation"] == "MERGED_INTO" and row["swap_ratio_den"] == "4.000000"
    out = io.StringIO()
    code = main(["--data-dir", str(data), "lineage", "add", "--parent", "NOPE", "--child", "INFY", "--relation",
                 "MERGED_INTO", "--effective", "2025-10-14", "--evidence-url", "u", "--note", "n"],
                out=out)  # fmt: skip
    assert code == 1 and "names 0 entities" in out.getvalue()
