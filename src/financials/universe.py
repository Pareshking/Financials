"""Market-cap universe (owner 2026-11-17): every mainboard security with NSE market cap >= Rs 500 crore joins, members
never leave [X134].

Rule U1 (`RULE_VERSION`):
- On the last trading day W of each ISO week (Monday-Sunday; the next trading day falls in a later week), every row
  of W's PR-zip mcap file (raw_nse_mcap [X130-X133]) with series EQ / BE / BZ (never SME SM / ST / SZ; the zip's sme
  file is not read) and filed Market Cap >= THRESHOLD_INR joins on W, reason MCAP_GE_500CR, visible from the file's
  broadcast time. Each row stands on its own (owner: "ignore DVR", no share-class aggregation).
- Listed only (U1-L, coordinator 2026-11-17): only rows with Category `Listed` qualify (ELIGIBLE_CATEGORY).
  `Permitted` securities are listed on another exchange and only permitted to trade on NSE; the project's universe
  is NSE Mainboard listed companies and its filings pipeline is NSE-only (none of the 104 permitted rows >= Rs 500 Cr
  on 2026-11-13 has NSE financials). Their raw rows stay in raw_nse_mcap as sent.
- Seed, once (no SEED_EXISTING row yet): every security, in those series and with a bar, of an entity that already
  has financials (filing_meta) joins on its first bar date, reason SEED_EXISTING. The seed is a hindsight selection
  (the Nifty 500 set the project started with): survivorship bias as disclosed for the index backfill [L1].
- Sticky: a member never leaves; a backfill that finds an earlier qualifying week moves joined_date earlier.
- A qualifying row whose symbol / series resolves to no security on W (security_identifier_history) is quarantined
  (UNIVERSE / UNRESOLVED_SYMBOL, one finding per symbol and series), never guessed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from financials.db import fetch_dicts, insert_rows
from financials.identity import UNIVERSE_SERIES
from financials.ids import stable_id
from financials.timeutil import ist_to_utc, utc_now

UNIVERSE = "MCAP500"
RULE_VERSION = "U1-2026.11.17-L"  # -L: Listed rows only
ELIGIBLE_CATEGORY = "Listed"
THRESHOLD_INR = Decimal("5000000000")  # Rs 500 crore
SEED = "SEED_EXISTING"
JOIN = "MCAP_GE_500CR"


def week_end_trading_days(con, start: date, end: date, exchange: str = "NSE") -> tuple[list[date], list[date]]:
    """(last trading day of each ISO week in [start, end], trading days in range whose week end is not yet known).
    A trading day is a promoted bhavcopy day or a day with a promoted mcap file; D ends its week when every later
    day of that week is known not to trade: a holiday or inferred non-session row (CAL3), or a weekend of a year
    the holiday master covers (financials.calendar). Read in two queries, not per day."""
    days = {d for (d,) in con.execute(
        "SELECT cal_date FROM trading_calendar WHERE exchange = ? AND is_trading AND cal_date BETWEEN ? AND ? "
        "UNION SELECT DISTINCT trade_date FROM raw_nse_mcap WHERE exchange = ? AND trade_date BETWEEN ? AND ?",
        [exchange, start, end + timedelta(days=7), exchange, start, end + timedelta(days=7)]).fetchall()}  # fmt: skip
    closed = {d for (d,) in con.execute(
        "SELECT cal_date FROM trading_calendar WHERE exchange = ? AND NOT is_trading AND cal_date BETWEEN ? AND ?",
        [exchange, start, end + timedelta(days=7)]).fetchall()}  # fmt: skip
    covered = {y for (y,) in con.execute("SELECT cal_year FROM calendar_coverage WHERE exchange = ?",
                                          [exchange]).fetchall()}  # fmt: skip

    def trades(x: date) -> bool | None:
        if x in days:
            return True
        if x in closed:
            return False
        return x.weekday() < 5 if x.year in covered else None

    ends, unknown = [], []
    for d in sorted(x for x in days if start <= x <= end):
        rest = [trades(d + timedelta(days=k)) for k in range(1, 7 - d.weekday())]
        if any(rest):
            continue
        (unknown if None in rest else ends).append(d)
    return ends, unknown


def update_universe(con, start: date, end: date, *, now: datetime | None = None) -> dict:
    """Apply rule U1 to the week ends in [start, end] (and the seed, once). Batched: one query per step, not per week
    or security. Returns counts; audited in admin_log. The caller holds the write transaction."""
    now = now or utc_now()
    seeded = _seed(con, now)
    weeks, unknown = week_end_trading_days(con, start, end)
    have = {d for (d,) in con.execute(
        "SELECT DISTINCT trade_date FROM raw_nse_mcap WHERE trade_date IN (SELECT unnest(?))", [weeks]
    ).fetchall()}  # fmt: skip
    missing = [w for w in weeks if w not in have]
    # Latest filing per week-end date; qualifying rows; resolution on that date (security_identifier_history).
    rows = fetch_dicts(
        con,
        """WITH f AS (
             SELECT m.trade_date, any_value(m.filing_id ORDER BY fi.fetched_at DESC, m.filing_id DESC) AS filing_id
             FROM raw_nse_mcap m JOIN filings fi USING (filing_id)
             WHERE m.trade_date IN (SELECT unnest(?)) GROUP BY 1)
           SELECT m.trade_date, m.symbol, m.series, m.market_cap_inr, m.filing_id, fi.broadcast_ts,
                  h.security_id, s.entity_id
           FROM raw_nse_mcap m JOIN f USING (trade_date, filing_id) JOIN filings fi USING (filing_id)
           LEFT JOIN security_identifier_history h ON h.exchange = m.exchange AND h.symbol = m.symbol
                AND h.series = m.series AND h.valid_from <= m.trade_date
                AND (h.valid_to IS NULL OR h.valid_to > m.trade_date)
           LEFT JOIN securities s ON s.security_id = h.security_id
           WHERE m.series IN (SELECT unnest(?)) AND m.market_cap_inr >= ? AND m.category = ?
           ORDER BY m.trade_date, m.symbol, m.series""",
        [sorted(have), sorted(UNIVERSE_SERIES), THRESHOLD_INR, ELIGIBLE_CATEGORY],
    )
    first: dict[str, dict] = {}
    unresolved: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r["security_id"] is None:
            unresolved.setdefault((r["symbol"], r["series"]), r)
        elif r["security_id"] not in first:  # rows are in date order: the first qualifying week wins
            first[r["security_id"]] = r
    current = dict(con.execute(
        "SELECT security_id, joined_date FROM universe_membership WHERE universe = ?", [UNIVERSE]
    ).fetchall())  # fmt: skip
    new = [r for s, r in first.items() if s not in current]
    earlier = [r for s, r in first.items() if s in current and r["trade_date"] < current[s]]
    insert_rows(con, "universe_membership", [_member(r, now) for r in new])
    if earlier:  # UPDATE, not delete + insert (DuckDB checks the key eagerly inside one transaction)
        import pyarrow as pa

        con.register("_earlier", pa.Table.from_pylist([_member(r, now) for r in earlier]))
        try:
            con.execute(
                "UPDATE universe_membership u SET joined_date = e.joined_date, reason = e.reason, "
                "rule_version = e.rule_version, symbol = e.symbol, series = e.series, "
                "market_cap_inr = e.market_cap_inr, evidence_filing_id = e.evidence_filing_id, "
                "visible_from_ts = e.visible_from_ts, recorded_at = e.recorded_at FROM _earlier e "
                "WHERE u.universe = e.universe AND u.security_id = e.security_id"
            )
        finally:
            con.unregister("_earlier")
    findings = _quarantine_unresolved(con, unresolved.values(), now)
    closed = _close_resolved(con, now)
    total = con.execute("SELECT count(*) FROM universe_membership WHERE universe = ?", [UNIVERSE]).fetchone()[0]
    result = {"universe": UNIVERSE, "rule_version": RULE_VERSION, "seeded": seeded, "joined": len(new),
              "moved_earlier": len(earlier), "members": total, "week_ends": len(weeks),
              "week_ends_without_mcap_file": [str(w) for w in missing],
              "days_with_unknown_week_end": [str(d) for d in unknown], "unresolved": len(unresolved),
              "unresolved_findings": findings, "findings_closed": closed}  # fmt: skip
    con.execute(
        "INSERT OR IGNORE INTO admin_log VALUES (?, 'UPDATE_UNIVERSE', ?, ?, NULL, ?)",
        [stable_id("adm", "universe", start, end, now), json.dumps({"from": str(start), "to": str(end)}),
         json.dumps({k: v for k, v in result.items() if k != "unresolved_findings"}), now],
    )  # fmt: skip
    return result


def _member(r: dict, now: datetime) -> dict:
    return {"universe": UNIVERSE, "security_id": r["security_id"], "entity_id": r["entity_id"],
            "joined_date": r["trade_date"], "reason": JOIN, "rule_version": RULE_VERSION, "symbol": r["symbol"],
            "series": r["series"], "market_cap_inr": r["market_cap_inr"], "evidence_filing_id": r["filing_id"],
            "visible_from_ts": r["broadcast_ts"], "recorded_at": now}  # fmt: skip


def _seed(con, now: datetime) -> int:
    """SEED_EXISTING, once: securities (EQ / BE / BZ, with a bar) of entities with financials, on their first bar."""
    if con.execute("SELECT 1 FROM universe_membership WHERE universe = ? AND reason = ? LIMIT 1",
                   [UNIVERSE, SEED]).fetchone():  # fmt: skip
        return 0
    rows = fetch_dicts(
        con,
        """WITH first_bar AS (
             SELECT o.security_id, min(o.trade_date) AS d FROM ohlcv o JOIN securities s USING (security_id)
             WHERE o.series IN (SELECT unnest(?)) AND s.entity_id IN (SELECT entity_id FROM filing_meta)
             GROUP BY 1)
           SELECT b.security_id, s.entity_id, b.d AS trade_date,
                  any_value(h.symbol ORDER BY h.valid_from DESC) AS symbol,
                  any_value(h.series ORDER BY h.valid_from DESC) AS series
           FROM first_bar b JOIN securities s USING (security_id)
           JOIN security_identifier_history h ON h.security_id = b.security_id AND h.valid_from <= b.d
                AND (h.valid_to IS NULL OR h.valid_to > b.d)
           WHERE b.security_id NOT IN (SELECT security_id FROM universe_membership WHERE universe = ?)
           GROUP BY 1, 2, 3 ORDER BY 1""",
        [sorted(UNIVERSE_SERIES), UNIVERSE],
    )
    insert_rows(con, "universe_membership", [
        {"universe": UNIVERSE, "security_id": r["security_id"], "entity_id": r["entity_id"],
         "joined_date": r["trade_date"], "reason": SEED, "rule_version": RULE_VERSION, "symbol": r["symbol"],
         "series": r["series"], "market_cap_inr": None, "evidence_filing_id": None,
         "visible_from_ts": ist_to_utc(r["trade_date"], time(23, 59, 59)), "recorded_at": now}
        for r in rows
    ])  # fmt: skip
    return len(rows)


def _quarantine_unresolved(con, rows, now: datetime) -> list[str]:
    """One finding per symbol / series (deterministic id, so weekly re-runs do not add more)."""
    out = []
    for r in rows:
        details = json.dumps({"symbol": r["symbol"], "series": r["series"], "universe": UNIVERSE}, sort_keys=True)
        qid = stable_id("q", "UNIVERSE", "UNRESOLVED_SYMBOL", None, None, None, details)
        out.append({"quarantine_id": qid, "stage": "UNIVERSE", "reason_code": "UNRESOLVED_SYMBOL",
                    "entity_id": None, "security_id": None, "filing_id": r["filing_id"], "details": details,
                    "created_at": now})  # fmt: skip
    insert_rows(con, "quarantine_queue", out, or_ignore=True)
    return [r["quarantine_id"] for r in out]


def _close_resolved(con, now: datetime) -> int:
    """Close open UNRESOLVED_SYMBOL findings whose symbol / series has since joined (resolved in a later week)."""
    ids = [q for (q,) in con.execute(
        "SELECT q.quarantine_id FROM quarantine_queue q JOIN universe_membership u ON u.universe = ? "
        "AND u.symbol = json_extract_string(q.details, '$.symbol') AND u.series = json_extract_string(q.details, "
        "'$.series') WHERE q.stage = 'UNIVERSE' AND q.reason_code = 'UNRESOLVED_SYMBOL' AND q.resolved_at IS NULL",
        [UNIVERSE]).fetchall()]  # fmt: skip
    if ids:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = "
            "'resolved and joined in a later week (rule U1)' WHERE quarantine_id IN (SELECT unnest(?))",
            [now, ids],
        )
    return len(ids)


def members(con, as_of: date, *, new_only: bool = False) -> list[str]:
    """Current symbols (open identifier interval) of the members joined on or before `as_of`; `new_only` keeps
    members whose entity has no financials yet (the first discovery for the new joiners)."""
    extra = " AND u.entity_id NOT IN (SELECT entity_id FROM filing_meta)" if new_only else ""
    return [s for (s,) in con.execute(
        "SELECT DISTINCT h.symbol FROM universe_membership u JOIN security_identifier_history h "
        "ON h.security_id = u.security_id AND h.valid_to IS NULL WHERE u.universe = ? AND u.joined_date <= ?"
        + extra + " ORDER BY 1", [UNIVERSE, as_of]).fetchall()]  # fmt: skip


def weekly_growth(con) -> list[tuple[date, str, int]]:
    """(joined_date, reason, members joined that date) for reports."""
    return con.execute(
        "SELECT joined_date, reason, count(*) FROM universe_membership WHERE universe = ? GROUP BY 1, 2 ORDER BY 1, 2",
        [UNIVERSE],
    ).fetchall()


ISSUE_SIZE_MAX_STALENESS_DAYS = 7  # a quarter end on a holiday (31 Mar 2025) reads the previous trading day's file


def issue_size_check(con, as_of: date, *, include_agreeing: bool = False) -> dict:
    """Cross-check [X133]: NSE Issue Size (shares listed on NSE, mcap file of `as_of` or the latest within
    ISSUE_SIZE_MAX_STALENESS_DAYS before it) vs the Reg. 31 TOTAL shares of patterns as of `as_of` (latest version),
    per EQ / BE / BZ security. Not a share count for market cap: Reg. 31 stays primary (X133: 98.4% within 0.5%,
    below the 99% bar; Issue Size lags allotments until listing, keeps bought-back shares until extinguished on NSE,
    moves on the ex-date of a bonus / split, and excludes partly-paid shares)."""
    from financials.promoter import SHARE_CROSS_CHECK_TOLERANCE

    rows = fetch_dicts(
        con,
        """WITH f AS (
             SELECT m.trade_date, any_value(m.filing_id ORDER BY fi.fetched_at DESC, m.filing_id DESC) AS filing_id
             FROM raw_nse_mcap m JOIN filings fi USING (filing_id)
             WHERE m.trade_date = (SELECT max(trade_date) FROM raw_nse_mcap WHERE trade_date <= ? AND trade_date >= ?)
             GROUP BY 1),
           shp AS (
             SELECT o.entity_id, o.shares, m.has_partly_paid FROM shareholding_observations o
             JOIN shareholding_meta m USING (filing_id, parser_version)
             WHERE o.category = 'TOTAL' AND o.as_of_date = ?
             QUALIFY row_number() OVER (PARTITION BY o.entity_id
                                        ORDER BY o.visible_from_ts DESC, o.parser_version DESC) = 1)
           SELECT m.trade_date, m.symbol, m.series, m.issue_size, shp.shares AS reg31_total, shp.has_partly_paid,
                  s.entity_id, h.security_id
           FROM raw_nse_mcap m JOIN f USING (trade_date, filing_id)
           JOIN security_identifier_history h ON h.exchange = m.exchange AND h.symbol = m.symbol
                AND h.series = m.series AND h.valid_from <= m.trade_date
                AND (h.valid_to IS NULL OR h.valid_to > m.trade_date)
           JOIN securities s ON s.security_id = h.security_id
           JOIN shp ON shp.entity_id = s.entity_id
           WHERE m.series IN (SELECT unnest(?)) ORDER BY m.symbol, m.series""",
        [as_of, as_of - timedelta(days=ISSUE_SIZE_MAX_STALENESS_DAYS), as_of, sorted(UNIVERSE_SERIES)],
    )
    out, agree, exact = [], 0, 0
    for r in rows:
        reg31, issue = Decimal(r["reg31_total"]), Decimal(r["issue_size"])
        rel = (issue - reg31) / reg31 if reg31 else None
        ok = rel is not None and abs(rel) <= SHARE_CROSS_CHECK_TOLERANCE
        agree += ok
        exact += issue == reg31
        if include_agreeing or not ok:
            out.append({**r, "relative_diff": None if rel is None else float(rel), "agrees": ok,
                        "direction": None if ok else "ISSUE_SIZE_BELOW_REG31" if issue < reg31
                        else "ISSUE_SIZE_ABOVE_REG31"})  # fmt: skip
    return {"as_of": as_of, "mcap_file_date": rows[0]["trade_date"] if rows else None, "pairs": len(rows),
            "exact": exact, "within_tolerance": agree, "tolerance": float(SHARE_CROSS_CHECK_TOLERANCE),
            "agreement_rate": agree / len(rows) if rows else None, "rows": out}  # fmt: skip
