"""Market-cap universe (owner 2026-11-17): every mainboard security with NSE market cap >= Rs 500 crore joins, members
never leave [X134].

Rule U1 (`RULE_VERSION`):
- On the last trading day W of each ISO week (Monday-Sunday; the next trading day falls in a later week), every row
  of W's PR-zip mcap file (raw_nse_mcap [X130-X133]) with series EQ / BE / BZ (never SME SM / ST / SZ; the zip's sme
  file is not read) and filed Market Cap >= THRESHOLD_INR joins on W, reason MCAP_GE_500CR, visible from the file's
  broadcast time. Each row stands on its own (owner: "ignore DVR", no share-class aggregation).
- Listed and Permitted (U1-P, owner 2026-11-17, superseding U1-L): rows with Category `Listed` or `Permitted`
  qualify (ELIGIBLE_CATEGORIES). `Permitted` securities are listed on another exchange (mostly BSE) and permitted to
  trade on NSE; they file their results on that exchange, not on NSE [X166], so the membership row records the
  qualifying row's category (`listing_category`) and `bse_members` lists the members that need BSE filings.
- Seed, once (no SEED_EXISTING row yet): every security, in those series and with a bar, of an entity that already
  has financials (filing_meta) joins on its first bar date, reason SEED_EXISTING. The seed is a hindsight selection
  (the Nifty 500 set the project started with): survivorship bias as disclosed for the index backfill [L1].
- No rights entitlements (rule X311, U1-R): a qualifying row whose security is a rights entitlement (named rule
  X140's markers, `identity.rights_entitlement_sql`: ISIN type code 20, symbol -RE[n], a type-01 equity ISIN of the
  same issuer) never joins. An RE is a short-lived right to subscribe a rights issue, not an equity share of a
  company: no financials of its own, and its "market cap" (RE count x RE price) measures nothing; the parent equity
  is the member. NSE lists REs in series BE, Category Permitted (UPL-RE, Rs 1,782 Cr, 6 Dec 2024).
- Sticky: a member never leaves; a backfill that finds an earlier qualifying week moves joined_date earlier. The one
  exception is X311 for members admitted before it: an RE was never a valid member, so it is deleted, its row logged
  in full in admin_log (UNIVERSE_REMOVE_RIGHTS_ENTITLEMENT; reversible) and counted as `rights_entitlements_removed`.
- A qualifying row whose symbol / series resolves to no security on W (security_identifier_history) is quarantined
  (UNIVERSE / UNRESOLVED_SYMBOL, one finding per symbol and series), never guessed. One named exception, rule
  X323: the mcap file lists a symbol in its new series a few sessions before the bhavcopy switches it; the row is
  the security whose own identifier history makes that switch within 5 sessions (`_resolve_series_switch_ahead`).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from financials.db import fetch_dicts, insert_rows
from financials.identity import UNIVERSE_SERIES, rights_entitlement_sql
from financials.ids import stable_id
from financials.timeutil import ist_to_utc, utc_now

UNIVERSE = "MCAP500"
RULE_VERSION = "U1-2026.11.18-R"  # -R: no rights entitlements [X311] (-P: Listed and Permitted; -L: Listed only)
ELIGIBLE_CATEGORIES = ("Listed", "Permitted")
PERMITTED = "Permitted"
THRESHOLD_INR = Decimal("5000000000")  # Rs 500 crore
SEED = "SEED_EXISTING"
JOIN = "MCAP_GE_500CR"
REMOVE_RE = "UNIVERSE_REMOVE_RIGHTS_ENTITLEMENT"


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
    removed = _remove_rights_entitlements(con, now)
    categorised = _fill_listing_category(con)
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
           SELECT m.trade_date, m.symbol, m.series, m.market_cap_inr, m.category, m.filing_id, fi.broadcast_ts,
                  h.security_id, s.entity_id,
                  coalesce(h.security_id IS NOT NULL AND """
        + rights_entitlement_sql("h")
        + """, false) AS rights_entitlement
           FROM raw_nse_mcap m JOIN f USING (trade_date, filing_id) JOIN filings fi USING (filing_id)
           LEFT JOIN security_identifier_history h ON h.exchange = m.exchange AND h.symbol = m.symbol
                AND h.series = m.series AND h.valid_from <= m.trade_date
                AND (h.valid_to IS NULL OR h.valid_to > m.trade_date)
           LEFT JOIN securities s ON s.security_id = h.security_id
           WHERE m.series IN (SELECT unnest(?)) AND m.market_cap_inr >= ?
             AND m.category IN (SELECT unnest(?))
           ORDER BY m.trade_date, m.symbol, m.series""",
        [sorted(have), sorted(UNIVERSE_SERIES), THRESHOLD_INR, list(ELIGIBLE_CATEGORIES)],
    )
    switched = _resolve_series_switch_ahead(con, [r for r in rows if r["security_id"] is None])
    first: dict[str, dict] = {}
    unresolved: dict[tuple[str, str], dict] = {}
    skipped_re = {r["security_id"] for r in rows if r["rights_entitlement"]}
    for r in rows:
        if r["rights_entitlement"]:  # X311: a right to subscribe, not an equity share of a company
            continue
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
                "market_cap_inr = e.market_cap_inr, listing_category = e.listing_category, "
                "evidence_filing_id = e.evidence_filing_id, "
                "visible_from_ts = e.visible_from_ts, recorded_at = e.recorded_at FROM _earlier e "
                "WHERE u.universe = e.universe AND u.security_id = e.security_id"
            )
        finally:
            con.unregister("_earlier")
    findings = _quarantine_unresolved(con, unresolved.values(), now)
    closed = _close_series_switched(con, switched - set(unresolved), now) + _close_resolved(con, now)
    total = con.execute("SELECT count(*) FROM universe_membership WHERE universe = ?", [UNIVERSE]).fetchone()[0]
    result = {"universe": UNIVERSE, "rule_version": RULE_VERSION, "seeded": seeded, "joined": len(new),
              "moved_earlier": len(earlier), "rights_entitlements_skipped": len(skipped_re),
              "rights_entitlements_removed": removed, "members": total,
              "permitted_members": con.execute(
                  "SELECT count(*) FROM universe_membership WHERE universe = ? AND listing_category = ?",
                  [UNIVERSE, PERMITTED]).fetchone()[0], "listing_category_filled": categorised, "week_ends": len(weeks),
              "week_ends_without_mcap_file": [str(w) for w in missing],
              "days_with_unknown_week_end": [str(d) for d in unknown], "unresolved": len(unresolved),
              "series_switch_resolved": len(switched),
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
            "series": r["series"], "market_cap_inr": r["market_cap_inr"], "listing_category": r["category"],
            "evidence_filing_id": r["filing_id"],
            "visible_from_ts": r["broadcast_ts"], "recorded_at": now}  # fmt: skip


def _remove_rights_entitlements(con, now: datetime) -> int:
    """Rule X311 for members admitted before it (U1-L / U1-P): membership is sticky, but a rights entitlement was
    never a valid member, so a member whose security is an RE (X140 markers on any of its identifier intervals) is
    deleted. The deleted rows are first written in full to admin_log (UNIVERSE_REMOVE_RIGHTS_ENTITLEMENT), so the
    removal is audited and reversible (re-insert the logged rows, or re-run rule U1-2026.11.17-P). Idempotent."""
    rows = fetch_dicts(
        con,
        """SELECT u.* FROM universe_membership u
           WHERE u.universe = ? AND EXISTS (SELECT 1 FROM security_identifier_history h
                                            WHERE h.security_id = u.security_id AND """
        + rights_entitlement_sql("h")
        + """)
           ORDER BY u.security_id""",
        [UNIVERSE],
    )
    if not rows:
        return 0
    ids = [r["security_id"] for r in rows]
    con.execute(
        "INSERT OR IGNORE INTO admin_log VALUES (?, ?, ?, ?, ?, ?)",
        [stable_id("adm", "universe", REMOVE_RE, *ids, now), REMOVE_RE,
         json.dumps({"universe": UNIVERSE, "rule": "X311", "rule_version": RULE_VERSION}),
         json.dumps({"removed": rows}, default=str),
         "rights entitlements are not equity shares of a company; never valid members [X311]", now],
    )  # fmt: skip
    con.execute(
        "DELETE FROM universe_membership WHERE universe = ? AND security_id IN (SELECT unnest(?))", [UNIVERSE, ids]
    )
    return len(rows)


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
         "series": r["series"], "market_cap_inr": None, "listing_category": None, "evidence_filing_id": None,
         "visible_from_ts": ist_to_utc(r["trade_date"], time(23, 59, 59)), "recorded_at": now}
        for r in rows
    ])  # fmt: skip
    return len(rows)


def _fill_listing_category(con) -> int:
    """Rows joined before the column existed (rule U1-L): the category of their own evidence row, as filed. Batched,
    idempotent (only NULLs of MCAP_GE_500CR rows are filled; SEED_EXISTING rows have no evidence row)."""
    n = con.execute(
        "SELECT count(*) FROM universe_membership WHERE universe = ? AND listing_category IS NULL "
        "AND evidence_filing_id IS NOT NULL", [UNIVERSE]).fetchone()[0]  # fmt: skip
    if n:
        con.execute(
            "UPDATE universe_membership u SET listing_category = m.category FROM raw_nse_mcap m "
            "WHERE u.universe = ? AND u.listing_category IS NULL AND m.filing_id = u.evidence_filing_id "
            "AND m.symbol = u.symbol AND m.series = u.series", [UNIVERSE])  # fmt: skip
    return n


def bse_members(con, as_of: date) -> list[dict]:
    """Members joined by `as_of` whose latest mcap row on or before `as_of` (by their identifier interval valid on
    that file's date) is `Permitted`: listed elsewhere, their filings are on BSE [X166]. Each row carries the current
    ISIN and BSE scrip code (security_identifier_history; NULL until rule BSE1 [X165] or a filing [X111] fills it).
    Keyed on the security, never on an NSE symbol alone."""
    return fetch_dicts(
        con,
        """WITH f AS (SELECT max(trade_date) AS d FROM raw_nse_mcap WHERE trade_date <= ?),
           cat AS (
             SELECT h.security_id, any_value(m.category ORDER BY fi.fetched_at DESC) AS category
             FROM raw_nse_mcap m JOIN f ON m.trade_date = f.d JOIN filings fi USING (filing_id)
             JOIN security_identifier_history h ON h.exchange = m.exchange AND h.symbol = m.symbol
                  AND h.series = m.series AND h.valid_from <= m.trade_date
                  AND (h.valid_to IS NULL OR h.valid_to > m.trade_date)
             GROUP BY 1)
           SELECT u.security_id, u.entity_id, h.symbol, h.series, h.isin, h.bse_scrip_code, u.joined_date,
                  u.listing_category AS category_at_join, c.category AS latest_category
           FROM universe_membership u JOIN cat c USING (security_id)
           JOIN security_identifier_history h ON h.security_id = u.security_id AND h.valid_to IS NULL
           WHERE u.universe = ? AND u.joined_date <= ? AND c.category = ?
           ORDER BY h.symbol""",
        [as_of, UNIVERSE, as_of, PERMITTED],
    )


SERIES_SWITCH_SESSIONS = 5  # X323 CHOICE: observed lags 1-3 sessions (2025-10-31 / 2026-10-30 files)
SERIES_SWITCH_NOTE = "X323: the mcap file lists the new series before the bhavcopy switches; same security"


def _resolve_series_switch_ahead(con, rows: list[dict]) -> set[tuple[str, str]]:
    """Rule X323 (in place on `rows`, which resolved to no security): the mcap file of week end W lists a symbol in
    a new series (EQ -> BE) a few sessions before the bhavcopy moves it (GFLLIMITED, NSIL, TVSHLTD...: BE in
    PR301026, BE in the bhavcopy from 2 or 3 Nov 2026). Such a row is the security that holds the same symbol on W in
    another universe series when that security's identifier history opens an interval with the same symbol and the
    row's series within SERIES_SWITCH_SESSIONS promoted sessions after W. Exactly one such security is required; else
    the row stays unresolved. The mcap file carries no ISIN, so the key is the symbol plus the bhavcopy's own later
    switch (whose FinInstrmId / ISIN matching is identity.py's). One batched query. Returns the resolved keys."""
    if not rows:
        return set()
    import pyarrow as pa

    keys = pa.Table.from_pylist([{"trade_date": r["trade_date"], "symbol": r["symbol"], "series": r["series"]}
                                 for r in rows])  # fmt: skip
    con.register("_x323", keys)
    try:
        hits = con.execute(
            """WITH sess AS (SELECT DISTINCT trade_date AS d FROM ohlcv WHERE exchange = 'NSE'),
               cand AS (
                 SELECT DISTINCT k.trade_date, k.symbol, k.series, h.security_id
                 FROM _x323 k
                 JOIN security_identifier_history h ON h.exchange = 'NSE' AND h.symbol = k.symbol
                      AND h.series <> k.series AND h.series IN (SELECT unnest(?)) AND h.valid_from <= k.trade_date
                      AND (h.valid_to IS NULL OR h.valid_to > k.trade_date)
                 JOIN security_identifier_history n ON n.security_id = h.security_id AND n.exchange = 'NSE'
                      AND n.symbol = k.symbol AND n.series = k.series AND n.valid_from > k.trade_date
                 WHERE (SELECT count(*) FROM sess WHERE d > k.trade_date AND d <= n.valid_from) <= ?)
               SELECT c.trade_date, c.symbol, c.series, any_value(c.security_id) AS security_id,
                      any_value(s.entity_id) AS entity_id
               FROM cand c JOIN securities s USING (security_id)
               GROUP BY 1, 2, 3 HAVING count(DISTINCT c.security_id) = 1""",
            [sorted(UNIVERSE_SERIES), SERIES_SWITCH_SESSIONS],
        ).fetchall()
    finally:
        con.unregister("_x323")
    found = {(d, sym, ser): (sec, ent) for d, sym, ser, sec, ent in hits}
    for r in rows:
        hit = found.get((r["trade_date"], r["symbol"], r["series"]))
        if hit is not None:
            r["security_id"], r["entity_id"] = hit
    return {(sym, ser) for _, sym, ser in found}


def _close_series_switched(con, keys: set[tuple[str, str]], now: datetime) -> int:
    """Close open UNRESOLVED_SYMBOL findings of (symbol, series) keys that rule X323 resolved in this run."""
    if not keys:
        return 0
    ids = [q for (q,) in con.execute(
        "SELECT quarantine_id FROM quarantine_queue WHERE stage = 'UNIVERSE' AND reason_code = 'UNRESOLVED_SYMBOL' "
        "AND resolved_at IS NULL AND json_extract_string(details, '$.symbol') || '|' || "
        "json_extract_string(details, '$.series') IN (SELECT unnest(?))",
        [[f"{sym}|{ser}" for sym, ser in sorted(keys)]]).fetchall()]  # fmt: skip
    if ids:
        con.execute(
            "UPDATE quarantine_queue SET resolved_at = ?, resolution = 'FIXED_BY_RULE', resolution_note = ? "
            "WHERE quarantine_id IN (SELECT unnest(?))",
            [now, SERIES_SWITCH_NOTE, ids],
        )
    return len(ids)


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
    members whose entity has no financials yet (the first NSE discovery for the new joiners), except members whose
    latest mcap row is `Permitted`: they file on BSE, not on NSE [X166], so asking NSE again every day finds nothing
    (`bse_members` lists them)."""
    extra = " AND u.entity_id NOT IN (SELECT entity_id FROM filing_meta)" if new_only else ""
    skip = sorted(r["security_id"] for r in bse_members(con, as_of)) if new_only else []
    return [s for (s,) in con.execute(
        "SELECT DISTINCT h.symbol FROM universe_membership u JOIN security_identifier_history h "
        "ON h.security_id = u.security_id AND h.valid_to IS NULL WHERE u.universe = ? AND u.joined_date <= ?"
        " AND u.security_id NOT IN (SELECT unnest(?::VARCHAR[]))" + extra + " ORDER BY 1",
        [UNIVERSE, as_of, skip]).fetchall()]  # fmt: skip


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
    per EQ / BE / BZ security. Reg. 31 stays the primary market-cap count (Issue Size replaces only a Reg. 31
    outlier, rule SHARES_REG31_OUTLIER [X221]; X133: 98.4% within 0.5%, below the 99% bar; Issue Size lags
    allotments until listing, keeps bought-back shares until extinguished on NSE, moves on the ex-date of a bonus /
    split, and excludes partly-paid shares)."""
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
