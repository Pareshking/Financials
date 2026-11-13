"""Exhaustive XBRL inspection: every fact, every context, every dimension, every 'Others' label pairing.

    python scripts/inspect_xbrl_exhaustive.py FILE.xml [...] --dump-dir DIR --registry docs/tag_registry.yaml

For each file:
- writes DIR/<file>.facts.jsonl (one line per fact: ns, element, context, period, dimensions, unit,
  decimals, exact value) - 100% of the instance;
- runs the matching production parser (INDAS_CORP today) and reports issues;
- reports elements present in non-dimensional contexts that the parser does not map, every axis seen,
  and text labels on dimensional "Others" members paired with their amounts.
The registry (YAML) accumulates, per profile, every element seen: how many filings, which context
kinds, whether it is mapped (and to what), and sample signs. It is merged, never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from financials.parsers.igaap_bank import BANK_DURATION_TAGS, BANK_INSTANT_TAGS
from financials.parsers.indas_corp import DURATION_TAGS, IMPLEMENTED_PROFILES, INSTANT_TAGS, detect_profile
from financials.parsers.indas_nbfc import NBFC_DURATION_TAGS, NBFC_INSTANT_TAGS
from financials.parsers.integrated import parse_integrated_results
from financials.parsers.irdai_insurance import SPECS as INSURER_SPECS
from financials.parsers.shareholding import (
    CATEGORIES,
    CATEGORY_AXIS,
    ENCUMBRANCE,
    ENCUMBRANCE_FLAGS,
    MEASURES,
    PUBLIC_HOLDER_AXES,
    SHP_NS_FRAGMENT,
    parse_shareholding,
)
from financials.parsers.xbrl import parse_instance

SHP_PROFILE = "REG31_SHP"
# Reg. 31 is dimensional: every element is registered with the axes it was seen on (not only
# non-dimensional ones), and CategoryOfShareholdersAxis members are registered separately.
SHP_MAPPED = {
    **{k: f"category.{v}" for k, v in MEASURES.items()},
    **{k: f"encumbrance.{v}" for k, v in ENCUMBRANCE.items()},
    **{v: f"meta.flag_{k}" for k, v in ENCUMBRANCE_FLAGS.items()},
    "DateOfReport": "meta.as_of_date",
    "ISIN": "meta.stated_isin",
    "Symbol": "meta.stated_symbol",
    "ScripCode": "meta.stated_scrip_code",
    "WhetherTheListedEntityHasIssuedAnyPartlyPaidUpShares": "meta.has_partly_paid",
    "NameOfTheShareholder": "major_holder.holder_name",
}


def _mapped(duration: dict, instant: dict) -> dict[str, str]:
    return {**{k: v[0] for k, v in duration.items()}, **{k: v[0] for k, v in instant.items()}}


MAPPED_BY_PROFILE = {
    "INDAS_CORP": _mapped(DURATION_TAGS, INSTANT_TAGS),
    "INDAS_NBFC": _mapped(NBFC_DURATION_TAGS, NBFC_INSTANT_TAGS),
    "IGAAP_BANK": _mapped(BANK_DURATION_TAGS, BANK_INSTANT_TAGS),
    **{p: _mapped(spec.duration_tags, spec.instant_tags) for p, spec in INSURER_SPECS.items()},
    SHP_PROFILE: SHP_MAPPED,
}
MEMBERS_BY_AXIS = {SHP_PROFILE: {CATEGORY_AXIS: CATEGORIES}}
AXES_MAPPED = {
    SHP_PROFILE: {CATEGORY_AXIS: "category", **{a: f"major_holder.{v}" for a, v in PUBLIC_HOLDER_AXES.items()}}
}
MAPPED = MAPPED_BY_PROFILE["INDAS_CORP"]


def ctx_kind(c) -> str:
    if c.instant is not None:
        return "instant"
    months = (c.end.year - c.start.year) * 12 + c.end.month - c.start.month + 1
    return f"duration_{months}m"


def inspect(path: Path, dump_dir: Path | None) -> dict:
    data = path.read_bytes()
    inst = parse_instance(data)
    is_shp = any(SHP_NS_FRAGMENT in u and u.endswith("/in-bse-shp") for u in inst.namespaces.values())
    profile = SHP_PROFILE if is_shp else detect_profile(inst.entity_namespace) or "UNKNOWN"
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        with (dump_dir / f"{path.stem}.facts.jsonl").open("w", encoding="utf-8") as fh:
            for f in inst.facts:
                c = inst.contexts[f.context_id]
                fh.write(json.dumps({
                    "seq": f.seq, "ns": f.ns, "element": f.name, "context": f.context_id,
                    "start": str(c.start) if c.start else None, "end": str(c.end) if c.end else None,
                    "instant": str(c.instant) if c.instant else None, "dimensions": dict(c.dimensions),
                    "unit": f.unit_ref, "decimals": f.decimals, "value": f.value_text.strip(),
                }, ensure_ascii=False) + "\n")  # fmt: skip

    elements: dict[str, dict] = {}
    axes = Counter()
    members: dict[str, set] = defaultdict(set)
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        for axis, member in c.dimensions:
            axes[axis.split(":")[-1]] += 1
            if axis.split(":")[-1] == CATEGORY_AXIS:
                members[CATEGORY_AXIS].add(member.split(":")[-1])
        if c.dimensions and not is_shp:
            continue
        e = elements.setdefault(f.name, {"kinds": set(), "numeric": f.is_numeric, "negative": False})
        e["kinds"].add(ctx_kind(c) + "".join(f"@{a.split(':')[-1]}" for a, _ in c.dimensions))
        if f.is_numeric and f.value_text.strip().startswith("-"):
            e["negative"] = True

    # 'Others' pairing: a text label in one context, an amount in another context with the same members.
    by_dims = defaultdict(list)
    for f in inst.facts:
        c = inst.contexts[f.context_id]
        if c.dimensions:
            by_dims[c.dimensions].append((f, c))
    others = []
    for dims, facts in by_dims.items():
        labels = [f.value_text.strip() for f, _ in facts if not f.is_numeric and f.name.startswith("Description")]
        amounts = [(f.name, str(c.instant or c.end), f.value_text.strip()) for f, c in facts if f.is_numeric]
        if labels and amounts:
            others.append({"axis": dims[0][0].split(":")[-1], "member": dims[0][1], "labels": sorted(set(labels)),
                           "amounts": amounts})  # fmt: skip

    if is_shp:
        parsed = parse_shareholding(data)
    else:
        parsed = parse_integrated_results(data) if profile in IMPLEMENTED_PROFILES else None
    mapped = MAPPED_BY_PROFILE.get(profile, {})
    unmapped = sorted(n for n, e in elements.items() if e["numeric"] and n not in mapped)
    return {
        "file": path.name,
        "profile": profile,
        "symbol": inst.first_text("Symbol"),
        "scope": inst.first_text("NatureOfReportStandaloneConsolidated"),
        "facts": len(inst.facts),
        "contexts": len(inst.contexts),
        "parse_ok": None if parsed is None else parsed.ok,
        "issues": [] if parsed is None else [(i.stage, i.reason_code, i.details) for i in parsed.issues],
        "unmapped_numeric": unmapped,
        "axes": dict(axes),
        "others": others,
        "_elements": elements,
        "_members": {k: sorted(v) for k, v in members.items()},
    }


def merge_registry(registry_path: Path, reports: list[dict], batch: str) -> dict:
    reg = yaml.safe_load(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    reg = reg or {}
    profiles = reg.setdefault("profiles", {})
    seen_files = set(reg.setdefault("files", []))
    for r in reports:
        if r["file"] in seen_files:
            continue
        seen_files.add(r["file"])
        prof = profiles.setdefault(r["profile"], {})
        for name, e in r["_elements"].items():
            entry = prof.setdefault(name, {"filings": 0, "context_kinds": [], "numeric": e["numeric"],
                                           "mapped_to": None, "seen_negative": False,
                                           "first_batch": batch})  # fmt: skip
            entry["filings"] += 1
            entry["context_kinds"] = sorted(set(entry["context_kinds"]) | e["kinds"])
            entry["seen_negative"] = entry["seen_negative"] or e["negative"]
        for axis, ms in r.get("_members", {}).items():
            ax = reg.setdefault("members", {}).setdefault(r["profile"], {}).setdefault(axis, {})
            for m in ms:
                ax.setdefault(m, {"filings": 0, "mapped_to": None, "first_batch": batch})["filings"] += 1
        for axis in r["axes"]:
            reg.setdefault("axes", {}).setdefault(r["profile"], {}).setdefault(
                axis, {"mapped_to": None, "first_batch": batch}
            )
    for profile, axes_ in reg.get("members", {}).items():
        for axis, ms in axes_.items():
            for m, entry in ms.items():
                entry["mapped_to"] = MEMBERS_BY_AXIS.get(profile, {}).get(axis, {}).get(m)
    for profile, axes_ in reg.get("axes", {}).items():
        for axis, entry in axes_.items():
            entry["mapped_to"] = AXES_MAPPED.get(profile, {}).get(axis)
    # mapped_to always reflects the current parser, including for elements first seen in earlier batches
    for profile, entries in profiles.items():
        mapped = MAPPED_BY_PROFILE.get(profile, {})
        for name, entry in entries.items():
            entry["mapped_to"] = mapped.get(name)
    reg["files"] = sorted(seen_files)
    registry_path.write_text(
        "# Every XBRL element seen in non-dimensional contexts, per profile (REG31_SHP: every context, with its\n"
        "# axes; `axes`/`members` list dimensional structure). Generated and merged by\n"
        "# scripts/inspect_xbrl_exhaustive.py; mapped_to = canonical tag in the production parser (null = unmapped).\n"
        + yaml.safe_dump(reg, sort_keys=True, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    return reg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--dump-dir", type=Path)
    p.add_argument("--registry", type=Path)
    p.add_argument("--batch", default="adhoc")
    p.add_argument("--json", type=Path, help="write the batch report (without per-element detail) here")
    args = p.parse_args(argv)
    reports = [inspect(f, args.dump_dir) for f in args.files]
    if args.registry:
        merge_registry(args.registry, reports, args.batch)
    unmapped = Counter(u for r in reports for u in r["unmapped_numeric"])
    axes = Counter()
    for r in reports:
        axes.update(r["axes"])
    print(f"batch {args.batch}: {len(reports)} filings, "
          f"{sum(r['parse_ok'] is True for r in reports)} parsed clean, "
          f"{sum(r['parse_ok'] is False for r in reports)} with issues")  # fmt: skip
    for r in reports:
        print(f"  {r['symbol'] or '?':12s} {r['profile']:10s} {r['scope'] or '?':12s} facts={r['facts']:5d} "
              f"parse_ok={r['parse_ok']} issues={[i[:2] for i in r['issues']]}")  # fmt: skip
    print(f"unmapped numeric elements (non-dimensional) across batch: {len(unmapped)}")
    for name, n in unmapped.most_common():
        print(f"  {n:2d}/{len(reports)} {name}")
    print(f"axes: {dict(axes.most_common())}")
    print("text-labelled 'Others' lines:")
    for r in reports:
        for o in r["others"]:
            print(f"  {r['symbol']}: {o['axis']} [{o['member']}] {o['labels']} -> {o['amounts'][:4]}")
    if args.json:
        slim = [{k: v for k, v in r.items() if k != "_elements"} for r in reports]
        args.json.write_text(json.dumps(slim, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
