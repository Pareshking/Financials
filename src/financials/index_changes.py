"""Backward point-in-time reconstruction of index membership from NSE Indices change notices.

Inputs (docs/references.md IDX4-IDX7):
- NSE Indices press releases ("Replacement(s) in indices"), converted with `pdftotext -layout`.
  The parser reads only the deterministic layout: a section header `1) Nifty 500` / `b) Nifty 500`,
  then "being excluded" / "being included" tables whose last column is the symbol. The effective
  date is the first "w.e.f. / effective from <Month DD, YYYY>" in the text.
- Prose-only notices (dummy/demerger exclusions) are not parsed: they need manual manifest rows.

Walking backward from a known membership at `as_of`:
- an ADD effective E is reverted (the security must currently be a member; it was not before E);
- a REMOVE effective E is restored (it must not be a member; it was a member until E, exclusive).
Membership only changes on event dates, so checking the count after every step checks every day.
Events name the symbol in use at that time, so symbols are resolved to securities at the event
date (REMOVE: E - 1 day, ADD: E); renames such as AKZOINDIA -> JSWDULUX are handled there [IDX6].
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from financials.parsers import ParseError

_SECTION = re.compile(r"^\s*(?:\d+|[a-z])\)\s*(.+?)\s*$")
_ROW = re.compile(r"^\s*\d+\s+(.+?)\s{2,}([A-Z0-9&\-]+)\s*$")
_EFFECTIVE = re.compile(r"(?:w\.?e\.?f\.?|effective from)\s+([A-Z][a-z]+ \d{1,2},? \d{4})", re.I)
MANIFEST_FIELDS = ("effective_date", "action", "symbol", "kind", "source")


class IndexInvariantError(ValueError):
    def __init__(self, effective_date: date, message: str) -> None:
        super().__init__(f"{effective_date}: {message}")
        self.effective_date = effective_date


@dataclass(frozen=True, order=True)
class IndexEvent:
    effective_date: date
    action: str  # ADD | REMOVE
    symbol: str
    kind: str = "REGULAR"  # REGULAR | TEMPORARY (e.g. a listed spin-off held until its exclusion)
    source: str = ""


def parse_change_notice(text: str, index_name: str, source: str) -> list[IndexEvent]:
    """Events for `index_name` in one notice; [] if the notice has no table section for it."""
    flat = " ".join(text.split())
    m = _EFFECTIVE.search(flat)
    in_section, mode, rows = False, None, {"REMOVE": [], "ADD": []}
    for line in text.splitlines():
        sec = _SECTION.match(line)
        if sec and not _ROW.match(line):
            in_section, mode = sec.group(1).strip().lower() == index_name.lower(), None
            continue
        if not in_section:
            continue
        low = line.lower()
        if "being excluded" in low:
            mode = "REMOVE"
        elif "being included" in low:
            mode = "ADD"
        elif mode and (r := _ROW.match(line)):
            rows[mode].append(r.group(2))
    if not rows["REMOVE"] and not rows["ADD"]:
        return []
    if m is None:
        raise ParseError(f"{source}: {index_name} changes without an effective date")
    eff = datetime.strptime(m.group(1).replace(",", ""), "%B %d %Y").date()
    if len(rows["REMOVE"]) != len(rows["ADD"]):
        raise ParseError(f"{source}: unbalanced {index_name} replacement {len(rows['REMOVE'])}/{len(rows['ADD'])}")
    return [IndexEvent(eff, action, sym, "REGULAR", source) for action in ("REMOVE", "ADD") for sym in rows[action]]


def write_manifest(events: Iterable[IndexEvent]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(MANIFEST_FIELDS)
    for e in sorted(events):
        w.writerow([e.effective_date.isoformat(), e.action, e.symbol, e.kind, e.source])
    return buf.getvalue()


def read_manifest(text: str) -> list[IndexEvent]:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
        raise ParseError(f"manifest header must be {','.join(MANIFEST_FIELDS)}")
    out = []
    for i, r in enumerate(reader, start=2):
        if r["action"] not in ("ADD", "REMOVE") or r["kind"] not in ("REGULAR", "TEMPORARY"):
            raise ParseError(f"manifest line {i}: bad action/kind")
        out.append(
            IndexEvent(date.fromisoformat(r["effective_date"]), r["action"], r["symbol"], r["kind"], r["source"])
        )
    return out


@dataclass(frozen=True)
class MembershipInterval:
    key: Hashable
    valid_from: date
    valid_to: date | None  # exclusive


@dataclass(frozen=True)
class Step:
    effective_date: date
    members_on_or_after: int
    members_before: int


def reconstruct_backward(
    current: Iterable[Hashable],
    as_of: date,
    events: Iterable[IndexEvent],
    start: date,
    resolve: Callable[[str, date], Hashable | None],
    *,
    expected_count: int,
) -> tuple[list[MembershipInterval], list[Step]]:
    """Intervals [valid_from, valid_to) for every member between `start` and `as_of`.

    Raises IndexInvariantError on an unresolvable symbol, an inconsistent event, or a real-member
    count that differs from `expected_count` + active TEMPORARY members.
    """
    members: dict[Hashable, date | None] = {k: None for k in current}  # key -> valid_to of open interval
    temporary: set[Hashable] = set()
    if len(members) != expected_count:
        raise IndexInvariantError(as_of, f"{len(members)} members at as_of, expected {expected_count}")
    intervals: list[MembershipInterval] = []
    steps: list[Step] = []
    by_date: dict[date, list[IndexEvent]] = {}
    for e in events:
        if start < e.effective_date <= as_of:
            by_date.setdefault(e.effective_date, []).append(e)
    for eff in sorted(by_date, reverse=True):
        after = len(members)
        need = expected_count + len(temporary & members.keys())
        if after != need:
            raise IndexInvariantError(eff, f"{after} members on/after, expected {need}")
        for e in sorted(by_date[eff], key=lambda x: (x.action != "ADD", x.symbol)):
            key = resolve(e.symbol, eff if e.action == "ADD" else eff - timedelta(days=1))
            if key is None:
                raise IndexInvariantError(eff, f"cannot resolve {e.symbol} ({e.source})")
            if e.action == "ADD":
                if key not in members:
                    raise IndexInvariantError(eff, f"ADD {e.symbol} is not a member after {eff} ({e.source})")
                intervals.append(MembershipInterval(key, eff, members.pop(key)))
            else:
                if key in members:
                    raise IndexInvariantError(eff, f"REMOVE {e.symbol} is already a member before {eff} ({e.source})")
                members[key] = eff
                if e.kind == "TEMPORARY":
                    temporary.add(key)
        steps.append(Step(eff, after, len(members)))
        if len(members) != expected_count + len(temporary & members.keys()):
            raise IndexInvariantError(eff, f"{len(members)} members before, expected {expected_count}")
    intervals.extend(MembershipInterval(k, start, to) for k, to in members.items())
    return intervals, steps
