"""Adjusted prices and the total-return index (architecture §11, references C2).

- Adjusted prices use only share-count / demerger price factors. Dividends never touch them.
- The total-return index compounds daily returns that add accepted cash dividends on the ex-date:
      r_t = (close_t + dividends_t) / (close_{t-1} * F_t) - 1
  where F_t is the product of accepted price factors with ex_date == t.
- Both series stop at the first unresolved GAP quarantine for the security.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from financials.corp_actions import ACCEPTED_STATUSES, CorpAction


def _frozen_from(con, security_id: str) -> date | None:
    return con.execute(
        "SELECT min(CAST(json_extract_string(details, '$.trade_date') AS DATE)) FROM quarantine_queue "
        "WHERE stage = 'GAP' AND security_id = ? AND resolved_at IS NULL",
        [security_id],
    ).fetchone()[0]


def total_return_index(
    con, security_id: str, actions: list[CorpAction], exchange: str = "NSE", base: Decimal = Decimal(100)
) -> list[tuple[date, Decimal]]:
    bars = con.execute(
        "SELECT trade_date, close FROM ohlcv WHERE security_id = ? AND exchange = ? ORDER BY trade_date",
        [security_id, exchange],
    ).fetchall()
    frozen = _frozen_from(con, security_id)
    factor: dict[date, Decimal] = defaultdict(lambda: Decimal(1))
    cash: dict[date, Decimal] = defaultdict(Decimal)
    for a in actions:
        if a.status not in ACCEPTED_STATUSES:
            continue
        if a.action_type == "DIVIDEND":
            cash[a.ex_date] += a.cash_per_share or Decimal(0)
        elif a.price_factor is not None:
            factor[a.ex_date] *= a.price_factor
    out: list[tuple[date, Decimal]] = []
    level = base
    prev_close: Decimal | None = None
    for d, close in bars:
        if frozen is not None and d >= frozen:
            break
        if prev_close is not None:
            level = level * (close + cash[d]) / (prev_close * factor[d])
        out.append((d, level))
        prev_close = close
    return out
