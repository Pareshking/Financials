"""Visibility memo of an incremental materialisation run (architecture §11.10).

A handful of `features.compute_rows` readers take `(con, as_of_ts, entities)` and depend on the as-of only through
`visible_from_ts <= as_of_ts` filters on the run's sliced tables (`features.SLICED_TABLES`) and `supplemental_kpis`:
the Reg. 31 / audit-opinion / disclosure / RPT / segment / KPI inputs and `features._preload`. Each returns a dict
keyed by entity (or by a tuple led by the entity), or a tuple of such dicts, and an entity's part depends only on
that entity's rows (and the rows of its filings). While `features.entity_slices` holds those tables fixed for the
run, an entity's part can only change on a day whose as-of passes one of that entity's visibility timestamps. So
the memo keeps each entity's part with the number of its timestamps <= the as-of it was read at, and a call reads
only the entities whose number moved (one batched read for them, as compute_rows does), instead of re-reading every
entity every day (an incremental run used to repeat ~15 of these ~10 ms reads on every one of hundreds of days).
Outside a run (`active() is None`) or for all entities (`entities=None`) the reader runs as before, except in a
full run's memo (`everyone`, features._FullRunSlices): there `entities=None` means every entity of `everyone`, and
the entities whose number moved are read through `reader(stale)`, the connection holding run-scoped slices of the
batch's changing entities (or the database itself when they are not all in the slices).

The result is shared while nothing moves, as the run's FundamentalsCache shares an entity's fundamentals block: its
consumers only read it (`.get`, indexing, iteration). `CHECK_MUTATIONS` (tests/test_incremental_materialize.py)
keeps a deep copy of every part and `verify()` fails when a consumer changed one.
"""

from __future__ import annotations

import bisect
import copy
import functools
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

CHECK_MUTATIONS = False
_ACTIVE: ContextVar[VisibilityMemo | None] = ContextVar("visibility_memo", default=None)


def _entity_of(key) -> str:
    return key if isinstance(key, str) else key[0]


def _split(result, entities) -> tuple[Callable, dict]:
    """(rebuild(parts) -> a result of the same shape, {entity: part}) of a reader result."""
    if isinstance(result, tuple):
        splits = [_split(r, entities) for r in result]
        parts = {e: tuple(s[1][e] for s in splits) for e in entities}
        return (lambda ps: tuple(s[0]([p[i] for p in ps]) for i, s in enumerate(splits))), parts
    if not isinstance(result, dict):
        raise TypeError(f"run_memo: a reader returned {type(result).__name__}, not a dict keyed by entity")
    factory = result.default_factory if isinstance(result, defaultdict) else None
    parts: dict[str, dict] = {e: {} for e in entities}
    for k, v in result.items():
        e = _entity_of(k)
        if e not in parts:
            raise KeyError(f"run_memo: key {k!r} does not belong to a requested entity")
        parts[e][k] = v

    def rebuild(ps):
        out = defaultdict(factory) if factory is not None else {}
        for p in ps:
            out.update(p)
        return out

    return rebuild, parts


class VisibilityMemo:
    def __init__(self, con, timestamps: Mapping[str, list[datetime]], everyone: frozenset[str] | None = None,
                 reader: Callable | None = None) -> None:  # fmt: skip
        """`timestamps`: per entity, every visibility timestamp of its rows and of its filings' rows. `everyone`
        (a full run): the entities an `entities=None` read stands for (every entity a row can belong to); `reader`:
        `reader(stale)` = the connection to read those entities' parts with (default: `con`)."""
        self.con = con
        self.everyone = everyone
        self._reader = reader
        self._ts = {e: sorted(set(v)) for e, v in timestamps.items()}
        self._parts: dict[str, dict[str, tuple[int, object]]] = defaultdict(dict)
        self._rebuild: dict[str, Callable] = {}
        self._last: dict[str, tuple[dict, object]] = {}
        self._pristine: dict[tuple, object] = {}

    def source(self, stale) -> object:
        """The connection to read the entities `stale` with (`reader`, else `con`)."""
        return self.con if self._reader is None else self._reader(stale)

    def interval(self, entity: str, as_of_ts: datetime) -> int:
        """The number of the entity's visibility timestamps <= as_of_ts (equal for two as-ofs = the same rows)."""
        return bisect.bisect_right(self._ts.get(entity, ()), as_of_ts)

    def read(self, name: str, fn: Callable, as_of_ts: datetime, entities) -> object:
        want = {e: self.interval(e, as_of_ts) for e in entities}
        last = self._last.get(name)
        if last is not None and last[0] == want:
            return last[1]
        parts = self._parts[name]
        stale = frozenset(e for e, k in want.items() if e not in parts or parts[e][0] != k)
        if stale:
            rebuild, fresh = _split(fn(self.source(stale), as_of_ts, stale), stale)
            self._rebuild.setdefault(name, rebuild)
            for e, p in fresh.items():
                parts[e] = (want[e], p)
                if CHECK_MUTATIONS:
                    self._pristine[(name, e, want[e])] = (p, copy.deepcopy(p))
        result = self._rebuild[name]([parts[e][1] for e in sorted(want)]) if name in self._rebuild else fn(
            self.con, as_of_ts, frozenset(want)
        )  # fmt: skip
        self._last[name] = (want, result)
        return result

    def verify(self) -> None:
        """With CHECK_MUTATIONS: raise when a shared part no longer equals what its reader returned."""
        changed = sorted({k[0] for k, (part, pristine) in self._pristine.items() if part != pristine})
        changed += sorted({n for n, (_, r) in self._last.items() if r != self._rebuild[n](
            [self._parts[n][e][1] for e in sorted(self._last[n][0])])})  # fmt: skip
        if changed:
            raise AssertionError(f"a consumer changed a shared reader result: {changed}")


def active() -> VisibilityMemo | None:
    return _ACTIVE.get()


@contextmanager
def visibility_memo(con, timestamps: Mapping[str, list[datetime]], everyone: frozenset[str] | None = None,
                    reader: Callable | None = None) -> Iterator[VisibilityMemo]:  # fmt: skip
    memo = VisibilityMemo(con, timestamps, everyone, reader)
    token = _ACTIVE.set(memo)
    try:
        yield memo
    finally:
        _ACTIVE.reset(token)
    if CHECK_MUTATIONS:
        memo.verify()


def by_visibility(fn: Callable) -> Callable:
    """Decorator for a reader `fn(con, as_of_ts, entities=None)` of the kind described in the module doc."""
    name = f"{fn.__module__}.{fn.__qualname__}"

    @functools.wraps(fn)
    def reader(con, as_of_ts: datetime, entities=None):
        memo = _ACTIVE.get()
        if memo is None or con is not memo.con:
            return fn(con, as_of_ts, entities)
        if entities is None:
            entities = memo.everyone  # a full run's memo: every entity (None outside one)
        if entities is None or not entities:
            return fn(con, as_of_ts, entities)
        return memo.read(name, fn, as_of_ts, entities)

    return reader
