"""Generic XBRL instance reader (no taxonomy knowledge).

Python's ElementTree does not fetch external entities or DTDs, so instance files cannot
make the parser reach the network.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from financials.parsers import ParseError

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
ENTITY_NS_PREFIX = "in-capmkt-ent"


@dataclass(frozen=True)
class Context:
    id: str
    start: date | None
    end: date | None
    instant: date | None
    dimensions: tuple[tuple[str, str], ...]

    @property
    def is_instant(self) -> bool:
        return self.instant is not None


@dataclass(frozen=True)
class Fact:
    seq: int
    ns: str
    name: str
    context_id: str
    unit_ref: str | None
    decimals: str | None
    value_text: str

    @property
    def is_numeric(self) -> bool:
        return self.unit_ref is not None

    def decimal(self) -> Decimal:
        try:
            return Decimal(self.value_text.strip())
        except InvalidOperation as exc:
            raise ParseError(f"{self.name}@{self.context_id}: not numeric {self.value_text!r}") from exc


@dataclass
class Instance:
    namespaces: dict[str, str]
    contexts: dict[str, Context]
    facts: list[Fact]
    _by_key: dict[tuple[str, str], Fact] = field(default_factory=dict, repr=False)
    # unit id -> INR | INR_PER_SHARE | PURE | SHARES | <CCY> | <CCY>_PER_SHARE
    units: dict[str, str] = field(default_factory=dict)

    def unit_kind(self, unit_ref: str | None) -> str | None:
        return None if unit_ref is None else self.units.get(unit_ref, "UNKNOWN")

    @property
    def entity_namespace(self) -> str | None:
        return self.namespaces.get(ENTITY_NS_PREFIX)

    def get(self, name: str, context_id: str) -> Fact | None:
        return self._by_key.get((name, context_id))

    def text(self, name: str, context_id: str) -> str | None:
        f = self.get(name, context_id)
        return None if f is None else f.value_text.strip()

    def first_text(self, name: str) -> str | None:
        """Value of a non-dimensional text fact, whichever context it sits in."""
        values = {
            f.value_text.strip()
            for f in self.facts
            if f.name == name and not f.is_numeric and not self.contexts[f.context_id].dimensions
        }
        if len(values) > 1:
            raise ParseError(f"{name}: conflicting values {sorted(values)}")
        return next(iter(values), None)


def _date(el: ET.Element | None) -> date | None:
    if el is None or not (el.text or "").strip():
        return None
    return date.fromisoformat(el.text.strip())


def parse_instance(data: bytes, *, undeclared_entity_contexts: frozenset[str] = frozenset()) -> Instance:
    """Parse an XBRL instance. A fact whose context is not declared raises ParseError, except for ids in
    `undeclared_entity_contexts` (named rule SHP16, granted only by the shareholding parser): those become
    dimensionless contexts with no period, so they can never pass a period check."""
    try:
        namespaces: dict[str, str] = {}
        for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
            namespaces.setdefault(prefix, uri)
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"invalid XML: {exc}") from exc

    contexts: dict[str, Context] = {}
    for c in root.findall(f"{{{XBRLI}}}context"):
        cid = c.get("id")
        period = c.find(f"{{{XBRLI}}}period")
        if not cid or period is None:
            raise ParseError("context without id or period")
        dims = tuple(
            sorted(
                (m.get("dimension", ""), (m.text or "").strip() or "".join(m.itertext()).strip())
                for m in c.iter()
                if m.tag in (f"{{{XBRLDI}}}explicitMember", f"{{{XBRLDI}}}typedMember")
            )
        )
        contexts[cid] = Context(
            id=cid,
            start=_date(period.find(f"{{{XBRLI}}}startDate")),
            end=_date(period.find(f"{{{XBRLI}}}endDate")),
            instant=_date(period.find(f"{{{XBRLI}}}instant")),
            dimensions=dims,
        )

    units: dict[str, str] = {}
    for u in root.findall(f"{{{XBRLI}}}unit"):
        measures = [(m.text or "").strip().split(":")[-1] for m in u.iter(f"{{{XBRLI}}}measure")]
        divide = u.find(f"{{{XBRLI}}}divide") is not None
        if divide and len(measures) == 2 and measures[1].lower() == "shares":
            units[u.get("id", "")] = f"{measures[0].upper()}_PER_SHARE"
        elif len(measures) == 1:
            m = measures[0]
            units[u.get("id", "")] = {"pure": "PURE", "shares": "SHARES"}.get(m.lower(), m.upper())
        else:
            units[u.get("id", "")] = "UNKNOWN"

    facts: list[Fact] = []
    by_key: dict[tuple[str, str], Fact] = {}
    ambiguous: set[tuple[str, str]] = set()
    for seq, el in enumerate(root):
        ctx = el.get("contextRef")
        if not ctx:
            continue
        if ctx not in contexts:
            if ctx not in undeclared_entity_contexts:
                raise ParseError(f"fact references unknown context {ctx}")
            contexts[ctx] = Context(id=ctx, start=None, end=None, instant=None, dimensions=())
        ns, _, name = el.tag[1:].partition("}")
        fact = Fact(seq, ns, name, ctx, el.get("unitRef"), el.get("decimals"), el.text or "")
        key = (name, ctx)
        if key in ambiguous:
            facts.append(fact)
            continue
        if key in by_key and by_key[key].value_text.strip() != fact.value_text.strip():
            if ctx not in undeclared_entity_contexts:
                raise ParseError(f"duplicate fact {name}@{ctx} with different values")
            # SHP16: table rows flattened into one undeclared context are positionally ambiguous. Every row stays
            # in `facts` (raw keeps them in document order); no single value is reachable by key.
            ambiguous.add(key)
            del by_key[key]
            facts.append(fact)
            continue
        by_key.setdefault(key, fact)
        facts.append(fact)
    return Instance(namespaces, contexts, facts, by_key, units)
