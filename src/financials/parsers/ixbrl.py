"""Inline XBRL (iXBRL 1.1) -> an equivalent XBRL instance, for BSE's shareholding [X167, X170] and results [X265] files.

BSE publishes each Reg. 31 pattern as XHTML with `ix:` facts (`XBRLFILES/SHPXBRLDataXML/<code>_<ts>_SP.html`), of the
same `in-bse-shp` taxonomy that NSE's SHP XML instances use. This module rebuilds the instance those facts denote, so
the existing shareholding parser reads them unchanged. Only what the committed BSE files use is supported; anything
else raises ParseError (never guessed):

- `ix:header/ix:resources`: `xbrli:context` and `xbrli:unit`, copied as filed.
- `ix:nonFraction`: `name`, `contextRef`, `unitRef`, `decimals`; `scale` (value x 10^scale: BSE writes percentages as
  points with scale -2, giving NSE's fractions, 74.99 -> 0.7499, and results amounts in crores with scale 7,
  1,951.01 -> 19510100000 rupees [X265]); `sign="-"`; no `format` (plain digits and one decimal point),
  `ixt:num-dot-decimal` / `ixt2:numdotdecimal` (thousands commas removed) or `ixt3:numdotdecimalin` (Indian
  grouping 12,34,567.89, checked, then commas removed) [X265].
- `ix:nonNumeric`: the text content; `ixt2:datedaymonthyear` (DD-MM-YYYY -> ISO date); `ixt2:booleantrue` /
  `ixt2:booleanfalse` under rule IXBRL1_BOOLEAN_TEXT (below).
- `ix:continuation`, `ix:exclude`, `ix:footnote`, `ix:tuple`, `ix:fraction` and nested facts: ParseError.

Rule IXBRL1_BOOLEAN_TEXT [X170]: BSE tags every Yes / No answer `ixt2:booleantrue`, whatever it says (all 4 committed
files: 151 such facts, 146 "No" and 5 "Yes"). The registry transform would make every one of them true; the displayed
word is the filer's answer and agrees with the figures (542910: "Yes" to locked-in shares and 10,361,783 locked-in
shares; ABBOTINDIA: "No" and no locked-in figure). So "Yes" -> true, "No" -> false, any other text -> ParseError.
Extended [X280]: BSE's results files of Jul-2025 .. Feb-2026 display the xs:boolean lexical form itself, "true" /
"false", again always under `ixt2:booleantrue`; that text is the value NSE's XML of the same form carries, and is read
as itself ("true" -> true, "false" -> false).

Rule IXBRL2_VOID_BR [X281]: BSE writes the filer's text blocks into the page unescaped, so a line break the filer typed
as `<BR>` (NSE's XML carries it as the text `&lt;BR&gt;`) becomes an unclosed element and the XHTML is not well-formed.
In HTML `br` is a void element; when a file fails to parse, has no `</BR>`, and every `<BR>` lies inside an
`ix:nonNumeric`, each is read as `<BR/>` (as BSE's own `<br/>` line breaks are, so the text block loses the marker).
Rule IXBRL3_THEAD_CLOSED_BY_TBODY [X282]: BSE's empty "additional disclosure of related party transactions" table
opens `<thead>` and closes it with `</tbody>`; such a `</tbody>` (no `ix:` element, `<thead>` or `<tbody>` between) is
read as `</thead>`. A repaired file is accepted only if it then parses and yields exactly as many facts as the raw text
has `<ix:nonFraction` / `<ix:nonNumeric` start tags; otherwise the original ParseError stands.
Rule IXBRL4_DISPLAYED_REPORTING_PERIOD [X283]: the untagged reporting period of BSE's Jun .. Aug 2025 pages, read from
the displayed rows when they equal the contexts (`_displayed_reporting_period`).
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from financials.parsers import ParseError

IX = "http://www.xbrl.org/2013/inlineXBRL"
XHTML = "http://www.w3.org/1999/xhtml"
XBRLI = "http://www.xbrl.org/2003/instance"
IXBRL1_RULE = "IXBRL1_BOOLEAN_TEXT"
IXBRL2_RULE = "IXBRL2_VOID_BR"
IXBRL3_RULE = "IXBRL3_THEAD_CLOSED_BY_TBODY"
IXBRL4_RULE = "IXBRL4_DISPLAYED_REPORTING_PERIOD"
NUM_FORMATS = {None, "num-dot-decimal", "numdotdecimal", "numdotdecimalin"}
BOOL_FORMATS = {"booleantrue", "booleanfalse"}
UNSUPPORTED = ("continuation", "exclude", "footnote", "tuple", "fraction")
_NUM = re.compile(r"^\d+(\.\d+)?$")
# ixt3:numdotdecimalin (Indian digit grouping, BSE results files [X265]): 1,951.01 / 12,34,567.89 / 999
_NUM_IN = re.compile(r"^(\d{1,3}|\d{1,2}(,\d{2})*,\d{3})(\.\d+)?$")
_DMY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


def is_inline(data: bytes) -> bool:
    head = data[:4096].lstrip()
    return head[:5].lower() == b"<html" and IX.encode() in data[:8192]


def _local(fmt: str | None) -> str | None:
    return None if fmt is None else fmt.split(":")[-1]


def _number(el: ET.Element, name: str) -> str:
    fmt = _local(el.get("format"))
    if fmt not in NUM_FORMATS:
        raise ParseError(f"{name}: unsupported number format {el.get('format')!r}")
    text = "".join(el.itertext()).strip()
    if fmt == "numdotdecimalin":
        if not _NUM_IN.match(text):
            raise ParseError(f"{name}: not an Indian-grouped number {text!r}")
        text = text.replace(",", "")
    elif fmt is not None:
        text = text.replace(",", "")
    if not _NUM.match(text):
        raise ParseError(f"{name}: not a plain number {text!r}")
    try:
        v = Decimal(text).scaleb(int(el.get("scale") or 0))
    except (InvalidOperation, ValueError) as exc:
        raise ParseError(f"{name}: bad value / scale") from exc
    if el.get("sign") == "-":
        v = -v
    elif el.get("sign") not in (None, ""):
        raise ParseError(f"{name}: sign {el.get('sign')!r}")
    s = format(v, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _text(el: ET.Element, name: str) -> str:
    fmt = _local(el.get("format"))
    text = "".join(el.itertext())
    if fmt is None:
        return text
    t = text.strip()
    if fmt in BOOL_FORMATS:  # IXBRL1_BOOLEAN_TEXT
        if t in ("Yes", "true"):  # "true" / "false": X280
            return "true"
        if t in ("No", "false"):
            return "false"
        raise ParseError(f"{name}: boolean text {t!r} is neither Yes nor No")
    if fmt == "datedaymonthyear":
        m = _DMY.match(t)
        if not m:
            raise ParseError(f"{name}: date {t!r} is not DD-MM-YYYY")
        return f"{m[3]}-{m[2]}-{m[1]}"
    raise ParseError(f"{name}: unsupported format {el.get('format')!r}")


def inline_to_instance(data: bytes) -> bytes:
    """The XBRL instance an inline XBRL document denotes (facts in document order; contexts and units as filed)."""
    try:
        namespaces, root = _parse(data)
    except ET.ParseError as exc:
        repaired = repair_xhtml(data)
        if repaired is None:
            raise ParseError(f"inline XBRL: invalid XHTML: {exc}") from exc
        try:
            namespaces, root = _parse(repaired)
        except ET.ParseError:
            raise ParseError(f"inline XBRL: invalid XHTML: {exc}") from exc
        found = sum(1 for el in root.iter() if el.tag in (f"{{{IX}}}nonFraction", f"{{{IX}}}nonNumeric"))
        if namespaces.get("ix") != IX or found != len(_IX_FACT_TAG.findall(data)):
            raise ParseError(f"inline XBRL: invalid XHTML: {exc} (repair lost facts)") from exc
    for bad in UNSUPPORTED:
        if root.find(f".//{{{IX}}}{bad}") is not None:
            raise ParseError(f"inline XBRL: ix:{bad} is not supported")
    resources = root.findall(f".//{{{IX}}}resources")
    if len(resources) != 1:
        raise ParseError(f"inline XBRL: {len(resources)} ix:resources")
    out = ET.Element(f"{{{XBRLI}}}xbrl")
    for el in resources[0]:
        if el.tag in (f"{{{XBRLI}}}context", f"{{{XBRLI}}}unit"):
            out.append(el)
    for el in root.iter():
        kind = el.tag[len(IX) + 2 :] if el.tag.startswith(f"{{{IX}}}") else None
        if kind not in ("nonFraction", "nonNumeric"):
            continue
        qname = el.get("name") or ""
        prefix, _, local = qname.partition(":")
        if not local or prefix not in namespaces:
            raise ParseError(f"inline XBRL: fact name {qname!r} has no declared prefix")
        if el.find(f".//{{{IX}}}nonFraction") is not None or el.find(f".//{{{IX}}}nonNumeric") is not None:
            raise ParseError(f"inline XBRL: nested facts in {qname}")
        fact = ET.SubElement(out, f"{{{namespaces[prefix]}}}{local}", {"contextRef": el.get("contextRef", "")})
        if kind == "nonFraction":
            fact.set("unitRef", el.get("unitRef", ""))
            if el.get("decimals") is not None:
                fact.set("decimals", el.get("decimals"))
            fact.text = _number(el, qname)
        else:
            fact.text = _text(el, qname)
    _displayed_reporting_period(data, out, namespaces)
    for prefix, uri in namespaces.items():
        if prefix and uri not in (IX, XHTML):
            ET.register_namespace(prefix, uri)
    xml = ET.tostring(out, encoding="utf-8", xml_declaration=True)
    return _declare_all(xml, namespaces)


_PERIOD_ROW = re.compile(
    rb">Date of (start|end) of reporting period</td>"
    rb"<td[^>]*>(\d{2}-\d{2}-\d{4})</td><td[^>]*>(\d{2}-\d{2}-\d{4})</td></tr>"
)
_PERIOD_ELEMENTS = {"start": "DateOfStartOfReportingPeriod", "end": "DateOfEndOfReportingPeriod"}


def _displayed_reporting_period(data: bytes, out: ET.Element, namespaces: dict[str, str]) -> None:
    """Rule IXBRL4_DISPLAYED_REPORTING_PERIOD [X283]: BSE's results pages of Jun .. Aug 2025 display the declared
    reporting period in the first "Date of start / end of reporting period" rows (two columns, quarter and year to
    date) as plain text, not tagged; the later template tags the same cells `contextRef='OneD'` and, when the file has
    that context, `'FourD'`. When no DateOf{Start,End}OfReportingPeriod fact is tagged, the first displayed start and
    end rows are read as those facts on OneD (column 1) and FourD (column 2, only if that context exists), and only
    if each displayed pair equals that context's period; otherwise nothing is added (NO_DECLARED_PERIOD stands)."""
    uri = namespaces.get("in-capmkt")
    if uri is None:
        return
    for element in _PERIOD_ELEMENTS.values():  # a tagged one on OneD / FourD (StatementStatic<n>D ones do not count)
        if any(f.get("contextRef") in ("OneD", "FourD") for f in out.findall(f"{{{uri}}}{element}")):
            return
    first: dict[str, tuple[str, str]] = {}
    for m in _PERIOD_ROW.finditer(data):
        first.setdefault(m[1].decode(), (m[2].decode(), m[3].decode()))
    if set(first) != {"start", "end"}:
        return
    periods = {}
    for ctx in out.findall(f"{{{XBRLI}}}context"):
        start, end = ctx.find(f".//{{{XBRLI}}}startDate"), ctx.find(f".//{{{XBRLI}}}endDate")
        if start is not None and end is not None:
            periods[ctx.get("id")] = ((start.text or "").strip(), (end.text or "").strip())

    def iso(dmy: str) -> str:
        return f"{dmy[6:]}-{dmy[3:5]}-{dmy[:2]}"

    facts = []
    for col, ctx_id in enumerate(("OneD", "FourD")):
        shown = (iso(first["start"][col]), iso(first["end"][col]))
        if ctx_id not in periods:
            if ctx_id == "OneD":
                return
            continue
        if periods[ctx_id] != shown:
            return
        facts += [(kind, ctx_id, value) for kind, value in zip(("start", "end"), shown, strict=True)]
    for kind, ctx_id, value in facts:
        ET.SubElement(out, f"{{{uri}}}{_PERIOD_ELEMENTS[kind]}", {"contextRef": ctx_id}).text = value


def _parse(data: bytes) -> tuple[dict[str, str], ET.Element]:
    namespaces: dict[str, str] = {}
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        namespaces.setdefault(prefix, uri)
    return namespaces, ET.fromstring(data)


_IX_FACT_TAG = re.compile(rb"<ix:(?:nonFraction|nonNumeric)\b")
_NON_NUMERIC = re.compile(rb"(<ix:nonNumeric\b[^>]*>)(.*?)(</ix:nonNumeric>)", re.S)
_THEAD_TBODY = re.compile(rb"(<thead\b[^>]*>)((?:(?!</?thead\b|</?tbody\b|<ix:).)*)</tbody>", re.S)


def repair_xhtml(data: bytes) -> bytes | None:
    """Rules IXBRL2_VOID_BR and IXBRL3_THEAD_CLOSED_BY_TBODY [X281, X282] (module docstring), for a file that does
    not parse; None when neither applies. The caller re-parses and checks the fact count."""
    out, applied = data, False
    if b"<BR>" in out and b"</BR>" not in out:
        fixed = _NON_NUMERIC.sub(lambda m: m[1] + m[2].replace(b"<BR>", b"<BR/>") + m[3], out)
        if b"<BR>" not in fixed:  # every <BR> was inside an ix:nonNumeric
            out, applied = fixed, True
    fixed = _THEAD_TBODY.sub(lambda m: m[1] + m[2] + b"</thead>", out)
    if fixed != out:
        out, applied = fixed, True
    return out if applied else None


_ROOT = re.compile(rb"<(?:[\w.-]+:)?xbrl\b([^>]*)>")


def _declare_all(xml: bytes, namespaces: dict[str, str]) -> bytes:
    """Every prefix the XHTML root declares, declared on the instance root as well [X265]: ElementTree writes only the
    prefixes its elements use, but readers need some that only name a schema, e.g. `in-capmkt-ent` (the accounting
    profile's entity namespace, `Instance.entity_namespace`)."""
    m = _ROOT.search(xml)
    if m is None:
        raise ParseError("inline XBRL: instance root not written")
    declared = set(re.findall(rb"xmlns:([\w.-]+)=", m.group(1)))
    extra = b"".join(
        b' xmlns:%s="%s"' % (p.encode(), u.encode())
        for p, u in sorted(namespaces.items())
        if p and u not in (IX, XHTML) and p.encode() not in declared and _QNAME_PREFIX.match(p)
    )
    return xml[: m.end(1)] + extra + xml[m.end(1) :]


_QNAME_PREFIX = re.compile(r"^[A-Za-z_][\w.-]*$")
