"""CA13: ETF unit splits (re-ISIN at ~1/k of the previous close) and re-ISINs without price effect, on real days."""

from __future__ import annotations

from financials.promoter import promote, resolve_isin_changes


def _open(con, reason):
    return con.execute(
        "SELECT count(*) FROM quarantine_queue WHERE reason_code = ? AND resolved_at IS NULL", [reason]
    ).fetchone()[0]


def test_etf_unit_splits_are_recorded_and_verified(market):
    m = market
    for d in ("20260226", "20260227"):
        assert promote(m.con, m.stage_day(d)).status == "PROMOTED"  # promotion runs the rule itself
    splits = m.con.execute(
        "SELECT h.symbol, a.ratio_num, a.ratio_den, a.status FROM corp_actions a JOIN security_identifier_history h "
        "ON h.security_id = a.security_id AND h.valid_to IS NULL WHERE a.ex_date = DATE '2026-02-27' ORDER BY 1"
    ).fetchall()
    names = {s for s, *_ in splits}
    assert {"BANKNIFTY1", "CONS", "MIDCAP", "NV20", "SILVER1"} <= names
    assert all((n, d, st) == (1, 10, "VERIFIED") for _, n, d, st in splits)
    for sym in ("BANKNIFTY1", "NV20"):
        sec = m.security_id(sym)
        assert m.con.execute("SELECT count(*) FROM quarantine_queue WHERE security_id = ? AND resolved_at IS NULL",
                             [sec]).fetchone()[0] == 0  # fmt: skip


def test_reisin_without_price_effect_closes_and_equities_are_never_split_by_the_rule(market):
    m = market
    for d in ("20250227", "20250228"):
        promote(m.con, m.stage_day(d))
    sec = m.security_id("HDFCLIQUID")
    note = m.con.execute("SELECT resolution_note FROM quarantine_queue WHERE security_id = ? "
                         "AND reason_code = 'ISIN_CHANGE_WITHOUT_ACTION'", [sec]).fetchone()[0]  # fmt: skip
    assert note == "ISIN change without price effect [CA13]"
    assert m.con.execute("SELECT count(*) FROM corp_actions WHERE security_id IN (SELECT security_id FROM "
                         "security_identifier_history WHERE isin LIKE 'INE%') AND ex_date = DATE '2025-02-28' "
                         "AND action_type = 'SPLIT'").fetchone()[0] == 0  # fmt: skip
    assert resolve_isin_changes(m.con) == 0  # idempotent
