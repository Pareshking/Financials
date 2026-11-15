"""Corporate lineage: mergers, amalgamations and demergers between entities (architecture §11.7).

`entity_lineage` is a directed, append-only edge list read as "child RELATION parent". This module holds the pure
logic (current edges, the demerger cost-of-acquisition split, position conversion for backtests), the read of the
current edges and the `lineage` CLI. Every write goes through `financials.admin` (single writer, audited).

Prices: a merger never back-adjusts the acquirer (price factor 1.0, architecture §11.1, G57) and the target's own
history stays as traded; nothing here writes `corp_actions`. A demerger's parent price factor is the observed gap of
the DEMERGER action [C3]; lineage only adds who the child is, the entitlement ratio and the cost split.

Sources: the NSE corporate-actions feed carries no merger or amalgamation purpose in any committed or live-scanned
window [CA11, CA14], so merger edges are entered by hand (`lineage add`, with an evidence URL). Demerger edges come
from `reference/entity_lineage.csv`, whose rows are pinned to committed fixtures by a test [CA14]; a DEMERGED_FROM edge
needs the parent's accepted DEMERGER action on the effective date. Entitlement ratios and COA percentages are stored
only from evidence an admin supplies (R7, the Tata Motors COA, is UNVERIFIED and is not hard-coded).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

MERGE_RELATIONS = frozenset({"MERGED_INTO", "AMALGAMATED"})
RELATIONS = MERGE_RELATIONS | {"DEMERGED_FROM"}
STATES = frozenset({"ACTIVE", "RETIRED"})
HUNDRED = Decimal(100)
COA_TOLERANCE = Decimal("0.01")  # percentage points; announced splits are given to 2 dp
MANIFEST_COLUMNS = ("relation", "parent", "child", "effective_date", "ratio_num", "ratio_den", "coa_pct",
                    "parent_coa_pct", "evidence_fixture", "evidence_url", "evidence_quote")  # fmt: skip


class LineageError(ValueError):
    pass


@dataclass(frozen=True)
class LineageEdge:
    lineage_id: str
    parent_entity_id: str
    child_entity_id: str
    relation: str
    effective_date: date
    swap_ratio_num: Decimal | None = None
    swap_ratio_den: Decimal | None = None
    coa_pct: Decimal | None = None
    parent_coa_pct: Decimal | None = None
    state: str = "ACTIVE"
    supersedes_lineage_id: str | None = None

    def __post_init__(self) -> None:
        if self.relation not in RELATIONS:
            raise LineageError(f"relation must be one of {sorted(RELATIONS)}")
        if self.state not in STATES:
            raise LineageError(f"state must be one of {sorted(STATES)}")
        if self.parent_entity_id == self.child_entity_id:
            raise LineageError("parent and child must differ")
        if (self.swap_ratio_num is None) != (self.swap_ratio_den is None):
            raise LineageError("swap ratio needs both numerator and denominator")
        for v in (self.swap_ratio_num, self.swap_ratio_den):
            if v is not None and v <= 0:
                raise LineageError("swap ratio terms must be positive")
        if self.relation in MERGE_RELATIONS and (self.coa_pct is not None or self.parent_coa_pct is not None):
            raise LineageError("a cost-of-acquisition split belongs to a demerger only")
        for v in (self.coa_pct, self.parent_coa_pct):
            if v is not None and not 0 <= v <= HUNDRED:
                raise LineageError("COA percentages lie in 0..100")

    @property
    def ratio(self) -> Decimal | None:
        return None if self.swap_ratio_num is None else self.swap_ratio_num / self.swap_ratio_den


def parse_ratio(text: str | None) -> tuple[Decimal | None, Decimal | None]:
    """'A:B' = A shares received per B shares held. Empty -> (None, None)."""
    if text is None or not str(text).strip():
        return None, None
    a, sep, b = str(text).partition(":")
    if not sep:
        raise LineageError(f"ratio {text!r} must be A:B")
    num, den = Decimal(a.strip()), Decimal(b.strip())
    if num <= 0 or den <= 0:
        raise LineageError(f"ratio {text!r} terms must be positive")
    return num, den


def current_edges(rows: Iterable[LineageEdge]) -> list[LineageEdge]:
    """ACTIVE rows that no other row supersedes, ordered by effective date."""
    rows = list(rows)
    superseded = {r.supersedes_lineage_id for r in rows if r.supersedes_lineage_id}
    return sorted((r for r in rows if r.lineage_id not in superseded and r.state == "ACTIVE"),
                  key=lambda r: (r.effective_date, r.parent_entity_id, r.child_entity_id))  # fmt: skip


@dataclass(frozen=True)
class CoaSplit:
    parent_entity_id: str
    effective_date: date
    parent_pct: Decimal | None
    children: dict[str, Decimal | None]

    @property
    def total(self) -> Decimal | None:
        parts = [self.parent_pct, *self.children.values()]
        return None if any(p is None for p in parts) else sum(parts, Decimal(0))

    @property
    def complete(self) -> bool:
        return self.total is not None and abs(self.total - HUNDRED) <= COA_TOLERANCE


def coa_split(edges: Iterable[LineageEdge], parent_entity_id: str, effective_date: date) -> CoaSplit:
    """The cost-of-acquisition split of one demerger scheme (G51): every current DEMERGED_FROM edge of the parent on
    that date. Raises when the children disagree on the parent's share or the known parts exceed 100%."""
    scheme = [e for e in current_edges(edges) if e.relation == "DEMERGED_FROM"
              and e.parent_entity_id == parent_entity_id and e.effective_date == effective_date]  # fmt: skip
    if not scheme:
        raise LineageError(f"no demerger of {parent_entity_id} on {effective_date}")
    parent_pcts = {e.parent_coa_pct for e in scheme if e.parent_coa_pct is not None}
    if len(parent_pcts) > 1:
        raise LineageError(f"children disagree on the parent's COA share: {sorted(parent_pcts)}")
    split = CoaSplit(parent_entity_id, effective_date, next(iter(parent_pcts), None),
                     {e.child_entity_id: e.coa_pct for e in scheme})  # fmt: skip
    known = sum((p for p in [split.parent_pct, *split.children.values()] if p is not None), Decimal(0))
    if known > HUNDRED + COA_TOLERANCE:
        raise LineageError(f"COA split of {parent_entity_id} on {effective_date} sums to {known}% (> 100)")
    if split.total is not None and not split.complete:
        raise LineageError(f"COA split of {parent_entity_id} on {effective_date} sums to {split.total}%, not 100")
    return split


@dataclass(frozen=True)
class Holding:
    """`shares` exact (fractional entitlements are kept, cash in lieu is not modelled); `cost_fraction` = the share of
    the original position's cost basis now carried by this holding (None when a COA split is not complete)."""

    entity_id: str
    shares: Decimal
    cost_fraction: Decimal | None


def convert_position(
    edges: Iterable[LineageEdge],
    entity_id: str,
    shares: Decimal | int,
    on_date: date,
    *,
    held_since: date | None = None,
) -> list[Holding]:
    """Map a position in `entity_id` through every lineage event with held_since < effective_date <= on_date (G58).

    Merger / amalgamation: target shares become acquirer shares by the swap ratio; cost carries over in full.
    Demerger: the parent position stays and the child position (parent shares x entitlement ratio) is added; the cost
    is split by the scheme's COA percentages (parent + children = 100), or None while the split is incomplete.
    Events chain in effective-date order (a merged target whose acquirer later demerges ends in both). An event that
    touches the position without a verified ratio raises LineageError: a backtest must not guess it.
    """
    edges = current_edges(edges)
    holdings: dict[str, Holding] = {entity_id: Holding(entity_id, Decimal(shares), Decimal(1))}
    window = [e for e in edges if e.effective_date <= on_date and (held_since is None or e.effective_date > held_since)]
    for day in sorted({e.effective_date for e in window}):
        todays = [e for e in window if e.effective_date == day]
        for e in todays:  # mergers first: a target merged and its acquirer demerged on one day is not modelled apart
            if e.relation in MERGE_RELATIONS and e.child_entity_id in holdings:
                held = holdings.pop(e.child_entity_id)
                ratio = _ratio(e)
                _add(holdings, Holding(e.parent_entity_id, held.shares * ratio, held.cost_fraction))
        for parent in sorted({e.parent_entity_id for e in todays if e.relation == "DEMERGED_FROM"}):
            if parent not in holdings:
                continue
            held = holdings[parent]
            split = coa_split(edges, parent, day)
            cost = held.cost_fraction if split.complete else None
            holdings[parent] = replace(held, cost_fraction=None if cost is None else cost * split.parent_pct / HUNDRED)
            for e in todays:
                if e.relation == "DEMERGED_FROM" and e.parent_entity_id == parent:
                    child_cost = None if cost is None else cost * split.children[e.child_entity_id] / HUNDRED
                    _add(holdings, Holding(e.child_entity_id, held.shares * _ratio(e), child_cost))
    return sorted(holdings.values(), key=lambda h: h.entity_id)


def _ratio(e: LineageEdge) -> Decimal:
    if e.ratio is None:
        raise LineageError(f"{e.relation} {e.child_entity_id} -> {e.parent_entity_id} on {e.effective_date}: no "
                           f"verified swap/entitlement ratio ({e.lineage_id}); `lineage amend` adds it")  # fmt: skip
    return e.ratio


def _add(holdings: dict[str, Holding], h: Holding) -> None:
    old = holdings.get(h.entity_id)
    if old is None:
        holdings[h.entity_id] = h
        return
    cost = None if old.cost_fraction is None or h.cost_fraction is None else old.cost_fraction + h.cost_fraction
    holdings[h.entity_id] = Holding(h.entity_id, old.shares + h.shares, cost)


# ── database reads ─────────────────────────────────────────────────────────


def _edge(r: Sequence) -> LineageEdge:
    return LineageEdge(*r)


EDGE_SQL = (
    "SELECT lineage_id, parent_entity_id, child_entity_id, relation, effective_date, swap_ratio_num, swap_ratio_den, "
    "coa_pct, parent_coa_pct, state, supersedes_lineage_id FROM entity_lineage"
)


def load_edges(con) -> list[LineageEdge]:
    """Current edges (one query; the table is small)."""
    return current_edges(_edge(r) for r in con.execute(EDGE_SQL).fetchall())


def read_manifest(text: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and tuple(rows[0]) != MANIFEST_COLUMNS:
        raise LineageError(f"manifest columns must be {MANIFEST_COLUMNS}")
    return rows


# ── CLI (`python -m financials lineage ...`) ─────────────────────────────


def add_cli(sub) -> None:
    lp = sub.add_parser("lineage", help="merger / demerger lineage and demerger COA split (audited)")
    ls = lp.add_subparsers(dest="lcmd", required=True)
    ls.add_parser("list", help="current lineage edges")
    la = ls.add_parser("add", help="record a merger, amalgamation or demerger edge (child RELATION parent)")
    la.add_argument("--parent", required=True, help="entity id, ISIN or NSE symbol (acquirer / demerging company)")
    la.add_argument("--child", required=True, help="entity id, ISIN or NSE symbol (target / resulting company)")
    la.add_argument("--relation", required=True, choices=sorted(RELATIONS))
    la.add_argument("--effective", required=True, type=date.fromisoformat, help="ex-date (YYYY-MM-DD)")
    la.add_argument("--ratio", help="A:B = A shares received per B shares held")
    la.add_argument("--evidence-url", required=True)
    la.add_argument("--note", required=True)
    am = ls.add_parser("amend", help="set the swap / entitlement ratio of an edge (appends a superseding row)")
    am.add_argument("--id", required=True)
    am.add_argument("--ratio", required=True)
    am.add_argument("--evidence-url", required=True)
    am.add_argument("--note", required=True)
    co = ls.add_parser("coa", help="demerger cost-of-acquisition split; parent + children must sum to 100")
    co.add_argument("--parent", required=True)
    co.add_argument("--effective", required=True, type=date.fromisoformat)
    co.add_argument("--parent-pct", required=True, type=Decimal)
    co.add_argument("--child", action="append", required=True, metavar="CHILD=PCT")
    co.add_argument("--evidence-url", required=True)
    co.add_argument("--note", required=True)
    rt = ls.add_parser("retire", help="withdraw an edge (appends a RETIRED row; a merged target becomes ACTIVE)")
    rt.add_argument("--id", required=True)
    rt.add_argument("--note", required=True)
    lo = ls.add_parser("load", help="load verified edges from a manifest (reference/entity_lineage.csv)")
    lo.add_argument("--manifest", type=Path, required=True)


def run_cli(con, args, out) -> int:
    from financials import admin

    try:
        if args.lcmd == "list":
            from dataclasses import asdict

            result = [asdict(e) for e in load_edges(con)]
        elif args.lcmd == "add":
            num, den = parse_ratio(args.ratio)
            result = admin.add_lineage(con, parent=args.parent, child=args.child, relation=args.relation,
                                       effective_date=args.effective, ratio_num=num, ratio_den=den,
                                       evidence_url=args.evidence_url, note=args.note)  # fmt: skip
        elif args.lcmd == "amend":
            num, den = parse_ratio(args.ratio)
            result = admin.amend_lineage(con, args.id, ratio_num=num, ratio_den=den, evidence_url=args.evidence_url,
                                         note=args.note)  # fmt: skip
        elif args.lcmd == "coa":
            children = {}
            for item in args.child:
                name, sep, pct = item.partition("=")
                if not sep:
                    raise LineageError(f"--child {item!r} must be CHILD=PCT")
                children[name.strip()] = Decimal(pct.strip())
            result = admin.set_demerger_coa(con, parent=args.parent, effective_date=args.effective,
                                            parent_pct=args.parent_pct, children=children,
                                            evidence_url=args.evidence_url, note=args.note)  # fmt: skip
        elif args.lcmd == "retire":
            result = admin.retire_lineage(con, args.id, note=args.note)
        else:
            result = admin.load_lineage_manifest(con, read_manifest(args.manifest.read_text(encoding="utf-8")),
                                                 source=args.manifest.name)  # fmt: skip
    except (admin.AdminError, LineageError) as exc:
        print(f"error: {exc}", file=out)
        return 1
    print(json.dumps(result, default=str, indent=1), file=out)
    return 0
