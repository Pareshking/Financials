"""Timestamps are stored as naive UTC; IST only at parse/display boundaries."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def ist_to_utc(d: date, t: time) -> datetime:
    """Combine an IST wall-clock date/time and return naive UTC."""
    return datetime.combine(d, t, tzinfo=IST).astimezone(UTC).replace(tzinfo=None)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def utc_to_ist_date(ts: datetime) -> date:
    """IST calendar date of a naive-UTC timestamp."""
    return ts.replace(tzinfo=UTC).astimezone(IST).date()
