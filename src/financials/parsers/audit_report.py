"""Audit-opinion flags from the auditor's report text and the Integrated Filing audit fields (pure: text in, flags
out; owner decision 2026-11-17: the text decides, because the Reg. 34 checkbox is unreliable) [X121-X124].

Annual (Reg. 34): `DisclosureInAuditorsReportExplanatory` is the independent auditor's report as filed (HTML in all
but 3 of 1,458 vaulted filings; one filing per scope, so standalone and consolidated are read separately). The text is
split into lines at block tags (p, br, div, td, li, ...; raw newlines inside HTML are spaces), each line is
normalised for heading matching (leading enumerators "1." / "(a)" / "**" removed, then letters only, lower case: so
"Basisfor Opinion", "Emphasisof Matters" and letter-spaced "O pi n i on" match too) and the report body is the lines
before the first "Report on Other Legal and Regulatory Requirements" heading or annexure heading ("Annexure ..." with
"referred", "report" or "auditor": the internal-financial-controls report and CARO annexures carry their own
"Opinion" headings and are never read; an exhibit label such as "Annexure-X" above the report is not one). A line
that starts with a quotation mark is a quotation (a component auditor's report reproduced in a consolidated report),
never a heading. A heading glued after the last sentence end of a paragraph ("... a basis for our opinion. Emphasis
of Matter") counts. Rules, in order:

- OPINION_HEADING: the opinion headings of SA 700 / SA 705 in the body: "Opinion" / "Basis for Opinion" (UNMODIFIED;
  also "Unmodified Opinion", "Basis of Opinion"), "Qualified Opinion" / "Basis for Qualified Opinion" (QUALIFIED),
  "Adverse Opinion" / "Basis for Adverse Opinion" (ADVERSE), "Disclaimer of Opinion" / "Basis for Disclaimer of
  Opinion" (DISCLAIMER), each alone on its line (optionally "on the ... statements" after it, "Report on the Audit of
  the ... Statements" before it, or the first words of the paragraph after it). The most severe heading wins
  (DISCLAIMER > ADVERSE > QUALIFIED > UNMODIFIED). A line naming internal financial controls is never an opinion
  heading. Sentences are never headings: "our opinion is not modified in respect of this matter", "in our opinion
  ...", "we do not provide a separate opinion on these matters" and the responsibility paragraphs do not match.
- OPINION_PARAGRAPH (only when the body has no opinion heading; e.g. a report filed as one paragraph): the body text
  says "basis for disclaimer of opinion" or "we do not express an opinion on the accompanying ... statements"
  (DISCLAIMER), "basis for adverse opinion" or "do not give a true and fair view" (ADVERSE), "basis for qualified
  opinion" or "except for the (possible) effects of" (QUALIFIED), else "in our opinion" with "true and fair view"
  (UNMODIFIED).
- NO_REPORT: anything else ("As per attachment", empty, an annexure only): audit_opinion None.
- GOING_CONCERN_MU: a body heading "Material Uncertainty Related (Relating / in Relation / with Respect) to Going
  Concern" (SA 570). The routine sentences ("the going concern basis of accounting", "if we conclude that a material
  uncertainty exists", "cease to continue as a going concern", "we have not identified any material uncertainty") are
  not headings and never set it. In a body without any heading (OPINION_PARAGRAPH) the phrase itself sets it.
- GOING_CONCERN_COMPONENT (consolidated reports): such a section about a component only (its heading names a
  subsidiary / joint venture / associate / component, it sits under an entity sub-heading such as "(ii) In respect of
  <company>" or "3. <COMPANY> LIMITED", or every paragraph reports another auditor's finding) sets
  going_concern_component instead of going_concern_uncertainty.
- EMPHASIS_OF_MATTER: a body heading starting "Emphasis of Matter(s)" (SA 706; "Emphasis of Matter - <topic>" too).
  Informational only. In a body without headings the phrase itself sets it.
Key audit matters are not counted: they are filed as tables whose rows split into an unreliable number of lines.

Checkbox: `WhetherAuditorsReportHasBeenQualifiedOrHasAnyReservationsOrContainsAdverseRemarks` (true / false, any case
or spacing; anything else None), the same value as filing_meta.auditor_qualified [X75]. `opinion_conflict` = (the text
opinion is QUALIFIED / ADVERSE / DISCLAIMER) != checkbox, None when either is None.

Results (Integrated Filing, SEBI format): `DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification`
(non-dimensional) "Declaration of unmodified opinion" -> UNMODIFIED, "Not applicable" -> None (no audit opinion in this
filing), "Statement on impact of audit qualification" -> the non-dimensional `OpinionOfAuditors` ("Qualified opinion" /
"Disclaimer of opinion" / "Adverse opinion"), else the most severe `TypeOfAuditQualification` of the
`AuditQualificationAxis` members, else None. `qualification_count` = members with a type; `qualification_repetitive`
= any `FrequencyOfAuditQualification` "Repetitive". The results "checkbox" is the declaration itself (statement ->
True, unmodified -> False, else None). The results text sections (DetailsOfAuditQualificationExplanatory, ...) are
the company's list of qualifications, not the auditor's report: going concern / emphasis of matter stay None there.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass

AUDIT_PARSER_VERSION = "audit-1"

REPORT_ELEMENT = "DisclosureInAuditorsReportExplanatory"
CHECKBOX_ELEMENT = "WhetherAuditorsReportHasBeenQualifiedOrHasAnyReservationsOrContainsAdverseRemarks"
DECLARATION_ELEMENT = "DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification"
OPINION_ELEMENT = "OpinionOfAuditors"
TYPE_ELEMENT = "TypeOfAuditQualification"
FREQUENCY_ELEMENT = "FrequencyOfAuditQualification"
QUALIFICATION_AXIS = "AuditQualificationAxis"
ANNUAL_ELEMENTS = (REPORT_ELEMENT, CHECKBOX_ELEMENT)
RESULTS_ELEMENTS = (DECLARATION_ELEMENT, OPINION_ELEMENT, TYPE_ELEMENT, FREQUENCY_ELEMENT)

OPINIONS = ("UNMODIFIED", "QUALIFIED", "ADVERSE", "DISCLAIMER")  # ascending severity
MODIFIED = frozenset(OPINIONS[1:])

_BLOCK = re.compile(r"</?(?:p|br|div|tr|td|th|li|h[1-6]|table|tbody|thead|ul|ol)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")
_ENUM = re.compile(r"^(?:[\s*_\-–—•]*(?:[(\[]?(?:\d{1,3}|[a-z]|[ivx]{1,5})[)\].:]))*[\s*_\-–—•:.]*", re.I)
_NOT_LETTER = re.compile(r"[^a-z]")
_MAX_HEADING = 200  # letters
_MAX_TAIL = 80  # letters of a heading glued to the end of a paragraph
_SENTENCE_END = re.compile(r"[.:;]\s+")

_PRE = r"(?:reportontheauditof[a-z]{0,90}?)?"
_POST = r"(?:onthe[a-z]{0,80}statements?|wehaveaudited.*|wewereengaged.*)?"
_HEADINGS = (
    ("DISCLAIMER", re.compile(rf"{_PRE}(?:basisfor)?disclaimerofopinion{_POST}")),
    ("ADVERSE", re.compile(rf"{_PRE}(?:basisfor)?adverseopinion{_POST}")),
    ("QUALIFIED", re.compile(rf"{_PRE}(?:basisfor)?qualifiedopinion{_POST}")),
    ("UNMODIFIED", re.compile(rf"{_PRE}(?:basis(?:for|of))?(?:unmodified|unqualified)?opinion{_POST}")),
)
_GOING_CONCERN = re.compile(r"materialuncertaint(?:y|ies)(?:relat(?:ed|ing)|inrelation|withrespect|inrespect)to"
                            r"(?:the)?goingconcern")  # fmt: skip
_EOM = "emphasisofmatter"
_LEGAL = "reportonotherlegalandregulatoryrequirement"
_ANNEX_WORDS = re.compile(r"referred|report|auditor")
_FLAT_END = re.compile(rf"{_LEGAL}|annexure[a-z]{{0,4}}referredto")
_ENUMERATED = re.compile(r"^\s*[(\[]?(?:\d{1,3}|[a-z]|[ivx]{1,5})[)\].]", re.I)
_ENTITY_SUBHEADING = re.compile(r"^\s*(?:[(\[]?(?:\d{1,3}|[a-z]|[ivx]{1,5})[)\].]\s*)?"
                                r"(?:(?i:in\s+respect\s+of)\b|[A-Z0-9&.,()' -]+$)")  # fmt: skip
_COMPONENT = re.compile(r"subsidiar|jointventure|associate|component")
_OTHER_AUDITOR = re.compile(
    r"auditorsof[a-z]{0,120}?ha(?:ve|s)(?:also)?(?:highlighted|drawn|reported|expressed|included)"
    r"|^(?:the)?(?:statutory)?auditorsof"
)
_IFC = "internalfinancialcontrol"
_QUOTES = ("“", '"', "‘", "'", "„", "«")
_DISCLAIMER_PARAGRAPH = (
    r"basisfordisclaimerofopinion|wedonotexpressanopinionon(?:the)?(?:accompanying)?[a-z]{0,40}statements"
)
_PARAGRAPH = (
    ("DISCLAIMER", re.compile(_DISCLAIMER_PARAGRAPH)),
    ("ADVERSE", re.compile(r"basisforadverseopinion|donotgiveatrueandfairview")),
    ("QUALIFIED", re.compile(r"basisforqualifiedopinion|exceptforthe(?:possible)?effects?of")),
)
_UNMODIFIED_PARAGRAPH = ("inouropinion", "trueandfairview")


@dataclass(frozen=True)
class ReportFlags:
    audit_opinion: str | None  # UNMODIFIED | QUALIFIED | ADVERSE | DISCLAIMER; None = no report text
    opinion_rule: str  # OPINION_HEADING | OPINION_PARAGRAPH | NO_REPORT
    going_concern_uncertainty: bool | None  # None only without a report
    emphasis_of_matter: bool | None
    going_concern_component: bool | None  # GOING_CONCERN_COMPONENT: a section about a component only


def report_lines(text: str) -> list[str]:
    """The report's lines: HTML split at block tags (raw newlines are spaces; entity-escaped markup too), plain text
    at newlines; whitespace collapsed, empty lines dropped."""
    if _TAG.search(text) or _TAG.search(html.unescape(text)):
        t = _BLOCK.sub("\n", _SPACE.sub(" ", text))
        t = html.unescape(_TAG.sub(" ", t))
        t = _TAG.sub(" ", _BLOCK.sub("\n", t.replace("\r", " ")))
        parts = t.split("\n")
    else:
        parts = text.splitlines()
    return [s for s in (_SPACE.sub(" ", p).strip() for p in parts) if s]


def compact(line: str) -> str:
    """Letters only, lower case, after removing leading enumerators and markup ("1.", "(a)", "**", "-")."""
    return _NOT_LETTER.sub("", _ENUM.sub("", line).lower())


def _kind(line: str) -> str | None:
    if line.lstrip().startswith(_QUOTES):
        return None  # a quotation (e.g. a component auditor's report reproduced in a consolidated report)
    c = compact(line)
    if c.startswith(_EOM):
        return "EMPHASIS"
    if _GOING_CONCERN.match(c):
        return "GOING_CONCERN"
    if _IFC in c:
        return None
    head = c[:_MAX_HEADING]
    for kind, pattern in _HEADINGS:
        if pattern.fullmatch(c) and (len(c) <= _MAX_HEADING or "wehaveaudited" in head or "wewereengaged" in head):
            return kind
    return None


def heading_kind(line: str) -> str | None:
    """UNMODIFIED / QUALIFIED / ADVERSE / DISCLAIMER for an opinion heading line, GOING_CONCERN / EMPHASIS for those
    section headings, else None (module doc). A heading glued to the end of the previous paragraph ("... a basis for
    our opinion. Emphasis of Matter") counts too: the text after the line's last sentence end, when short."""
    kind = _kind(line)
    if kind is None:
        tail = _SENTENCE_END.split(line)[-1]
        if tail != line and len(compact(tail)) <= _MAX_TAIL:
            kind = _kind(tail)
    return kind


def _is_body_end(line: str) -> bool:
    c = compact(line)
    return len(c) <= _MAX_HEADING and (c.startswith(_LEGAL) or (c.startswith("annexure") and _ANNEX_WORDS.search(c)))


def report_body(lines: list[str]) -> list[str]:
    """The lines before the first "Report on Other Legal and Regulatory Requirements" heading or annexure heading
    ("Annexure A to the Independent Auditor's Report", "Annexure '1' referred to in paragraph ..."; an exhibit label
    such as "Annexure-X" above the report is not one)."""
    return next((lines[:i] for i, line in enumerate(lines) if _is_body_end(line)), lines)


def _section(body: list[str], i: int) -> list[str]:
    """The paragraphs of the section whose heading is body[i]: up to the next heading-like line (short, no sentence
    end, not enumerated), without the closing "our opinion is not modified ..." sentence."""
    out = []
    for line in body[i + 1 :]:
        if heading_kind(line) or (len(line) <= 100 and not line.rstrip().endswith((".", ":", ";"))
                                  and not _ENUMERATED.match(line)):  # fmt: skip
            break
        if not compact(line).startswith("ouropinion"):
            out.append(line)
    return out


def component_going_concern(body: list[str], i: int) -> bool:
    """The GOING_CONCERN_COMPONENT rule (consolidated reports): the section at body[i] is about a component, not the
    group: its heading names one ("... of Subsidiary Companies"), it sits under an entity sub-heading ("(ii) In
    respect of <company>", "3. <COMPANY> LIMITED"), or every paragraph reports another auditor's finding ("The
    auditors of <company> ... have drawn attention", "... wherein the auditors of <company> have highlighted ...")."""
    if _COMPONENT.search(compact(body[i])):
        return True
    before = body[i - 1].strip() if i > 0 else ""
    if (before and len(before) <= 100 and not before.endswith((".", ":", ";")) and heading_kind(before) is None
                   and _ENTITY_SUBHEADING.match(before)):  # fmt: skip
        return True
    paragraphs = _section(body, i)
    return bool(paragraphs) and all(_OTHER_AUDITOR.search(compact(p)) for p in paragraphs)


def classify_report(text: str | None, scope: str | None = None) -> ReportFlags:
    """The flags of one auditor's report text (module doc); `scope` CONSOLIDATED applies GOING_CONCERN_COMPONENT."""
    body = report_body(report_lines(text or ""))
    kinds = [heading_kind(line) for line in body]
    opinions = [k for k in OPINIONS if k in kinds]
    if opinions:
        going = [i for i, k in enumerate(kinds) if k == "GOING_CONCERN"]
        component = [i for i in going if scope == "CONSOLIDATED" and component_going_concern(body, i)]
        return ReportFlags(opinions[-1], "OPINION_HEADING", len(going) > len(component), "EMPHASIS" in kinds,
                           bool(component))  # fmt: skip
    # a body filed without headings: one paragraph, or several with the headings dropped
    flat = compact(" ".join(body))
    cut = _FLAT_END.search(flat)
    flat = flat[: cut.start()] if cut else flat
    opinion = next((k for k, p in _PARAGRAPH if p.search(flat)), None)
    if opinion is None and all(p in flat for p in _UNMODIFIED_PARAGRAPH):
        opinion = "UNMODIFIED"
    if opinion is None:
        return ReportFlags(None, "NO_REPORT", None, None, None)
    return ReportFlags(opinion, "OPINION_PARAGRAPH", bool(_GOING_CONCERN.search(flat)), _EOM in flat, False)


def checkbox(value: str | None) -> bool | None:
    return {"true": True, "false": False}.get((value or "").strip().lower())


def is_modified(opinion: str | None) -> bool | None:
    return None if opinion is None else opinion in MODIFIED


def conflict(opinion: str | None, box: bool | None) -> bool | None:
    return None if opinion is None or box is None else is_modified(opinion) != box


_RESULT_OPINIONS = {"qualified opinion": "QUALIFIED", "adverse opinion": "ADVERSE",
                    "disclaimer of opinion": "DISCLAIMER"}  # fmt: skip
_DECLARATIONS = {"declaration of unmodified opinion": "UNMODIFIED", "not applicable": "NOT_APPLICABLE",
                 "statement on impact of audit qualification": "STATEMENT"}  # fmt: skip


def _norm(value: str | None) -> str:
    return _SPACE.sub(" ", (value or "").strip().lower())


def worst(opinions) -> str | None:
    found = [o for o in opinions if o in OPINIONS]
    return max(found, key=OPINIONS.index) if found else None


@dataclass(frozen=True)
class ResultsFlags:
    declaration: str | None  # UNMODIFIED | NOT_APPLICABLE | STATEMENT | the text as filed
    audit_opinion: str | None
    opinion_rule: str  # DECLARATION | OPINION_OF_AUDITORS | TYPE_OF_QUALIFICATION | NO_OPINION
    checkbox: bool | None
    qualification_count: int | None
    qualification_repetitive: bool | None


def classify_results(declaration: str | None, opinion_of_auditors: str | None, types: list[str | None],
                     frequencies: list[str | None]) -> ResultsFlags:  # fmt: skip
    """The flags of one Integrated Filing's audit fields (module doc)."""
    decl = _DECLARATIONS.get(_norm(declaration), declaration.strip() if declaration else None)
    typed = [_RESULT_OPINIONS.get(_norm(t)) for t in types if t is not None]
    count = len([t for t in types if t is not None]) or None
    repetitive = (any(_norm(f) == "repetitive" for f in frequencies) if any(f is not None for f in frequencies)
                  else None)  # fmt: skip
    box = {"STATEMENT": True, "UNMODIFIED": False}.get(decl)
    if decl == "UNMODIFIED":
        opinion, rule = "UNMODIFIED", "DECLARATION"
    elif decl == "STATEMENT" and _RESULT_OPINIONS.get(_norm(opinion_of_auditors)):
        opinion, rule = _RESULT_OPINIONS[_norm(opinion_of_auditors)], "OPINION_OF_AUDITORS"
    elif decl == "STATEMENT" and worst(typed):
        opinion, rule = worst(typed), "TYPE_OF_QUALIFICATION"
    else:
        opinion, rule = None, "NO_OPINION"
    return ResultsFlags(decl, opinion, rule, box, count, repetitive)


# ── one filing's row (staging and the vault backfill call this with the parsed instance) ─────────────────────────


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _local(qname: str) -> str:
    return qname.split(":")[-1]


def audit_row(inst, *, annual: bool, scope: str | None = None) -> dict | None:
    """The audit_opinions values of one parsed filing (without ids, entity and visibility), or None when the filing
    files none of the elements. Non-dimensional facts only, except the per-qualification facts on
    AuditQualificationAxis. A report element filed more than once keeps the longest text."""
    plain: dict[str, list[str]] = {}
    per_member: dict[str, dict[str, str]] = {}
    wanted = ANNUAL_ELEMENTS if annual else RESULTS_ELEMENTS
    for f in inst.facts:
        if f.name not in wanted:
            continue
        dims = {_local(a): _local(m) for a, m in inst.contexts[f.context_id].dimensions}
        if not dims:
            plain.setdefault(f.name, []).append(f.value_text)
        elif set(dims) == {QUALIFICATION_AXIS}:
            per_member.setdefault(dims[QUALIFICATION_AXIS], {})[f.name] = f.value_text
    if not plain and not per_member:
        return None
    if annual:
        text = max(plain.get(REPORT_ELEMENT, []), key=len, default=None)
        flags = classify_report(text, scope)
        box = checkbox((plain.get(CHECKBOX_ELEMENT) or [None])[0])
        return {"source_kind": "ANNUAL", "audit_opinion": flags.audit_opinion, "opinion_rule": flags.opinion_rule,
                "going_concern_uncertainty": flags.going_concern_uncertainty,
                "emphasis_of_matter": flags.emphasis_of_matter,
                "going_concern_component": flags.going_concern_component, "checkbox_qualified": box,
                "opinion_conflict": conflict(flags.audit_opinion, box), "declaration": None,
                "qualification_count": None, "qualification_repetitive": None,
                "text_len": None if text is None else len(text),
                "text_sha256": None if text is None else text_sha256(text)}  # fmt: skip
    members = sorted(per_member)
    r = classify_results((plain.get(DECLARATION_ELEMENT) or [None])[0], (plain.get(OPINION_ELEMENT) or [None])[0],
                         [per_member[m].get(TYPE_ELEMENT) for m in members],
                         [per_member[m].get(FREQUENCY_ELEMENT) for m in members])  # fmt: skip
    return {"source_kind": "RESULTS", "audit_opinion": r.audit_opinion, "opinion_rule": r.opinion_rule,
            "going_concern_uncertainty": None, "emphasis_of_matter": None, "going_concern_component": None,
            "checkbox_qualified": r.checkbox,
            "opinion_conflict": conflict(r.audit_opinion, r.checkbox), "declaration": r.declaration,
            "qualification_count": r.qualification_count, "qualification_repetitive": r.qualification_repetitive,
            "text_len": None, "text_sha256": None}  # fmt: skip
