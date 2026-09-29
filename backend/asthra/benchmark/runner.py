"""Validation benchmark: planted-defect suites and known-good corpora, scored.

A suite is a folder with suite.json and cases:  <case>.xml (or .sgm) + <case>.expect.json

    suite.json   {"name": "...", "description": "...",
                  "schema": {"standard": "S1000D", "issue": "4.1", "doc_type": "proced"},   # default for cases
                  "uses": "installed" | "fixture:<package folder under tests/fixtures/packages>"}
    expect.json  {"title": "...", "clean": false, "schema": {...optional override...},
                  "expect": [{"category": "missing-element", "element": "brexDmRef", "line": 42,
                              "value": null, "note": "why this is a defect"}]}

Scoring per case and overall:
    detected       expected problems that ASTHRA reported (same category, element/value, line ±1)
    missed         expected problems not reported
    false positive independent errors that match no expected problem (consequences of another
                   error are not counted twice)
    exact line     detected problems reported on exactly the expected line
    actionable     detected problems that come with a suggestion or a fix
Corpus mode: every file in a folder must validate without errors; each error is a false positive.
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..identify.service import identify, parse_xml, sniff
from ..validation.pipeline import validate_bytes

SUITES = Path(__file__).parent / "suites"
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


@dataclass
class CaseResult:
    suite: str
    case: str
    title: str
    status: str = "run"                 # run | skipped
    reason: str = ""
    detected: list = field(default_factory=list)
    missed: list = field(default_factory=list)
    false_pos: list = field(default_factory=list)
    exact_line: int = 0
    actionable: int = 0
    seconds: float = 0.0


def _find_package(registry, schema: dict):
    for p in registry.list(False):
        if p.manifest.standard.upper() == schema["standard"].upper() and p.manifest.issue == schema["issue"]:
            if any(d.id == schema["doc_type"] for d in p.manifest.doc_types):
                return p.manifest.key
    return None


def _matches(e: dict, d) -> bool:
    if d.category != e["category"]:
        return False
    if e.get("element"):
        el = e["element"]
        hay = f"{d.message} {d.suggestion or ''} {d.element_path or ''}"
        if f"<{el}>" not in hay and not (d.element_path or "").split("[")[0].endswith("/" + el):
            return False
    if e.get("value") is not None and d.value != e["value"] and e["value"] not in (d.message or ""):
        return False
    if e.get("line") and d.line and abs(d.line - e["line"]) > 1:
        return False
    return True


def _errors(rep):
    return [d for d in rep.diagnostics if d.severity.value in ("error", "fatal")]


def run_case(registry, suite: str, xml: Path, spec: dict, default_schema: dict | None) -> CaseResult:
    res = CaseResult(suite, xml.stem, spec.get("title", xml.stem))
    data = xml.read_bytes()
    schema = spec.get("schema") or default_schema
    key = dt = None
    if schema:
        key, dt = _find_package(registry, schema), schema["doc_type"]
        if not key:
            res.status, res.reason = "skipped", f"{schema['standard']} {schema['issue']} ({schema['doc_type']}) is not installed"
            return res
    else:
        tree, _ = parse_xml(data)
        ident = identify(tree.getroot() if tree is not None else None, registry.list(False), sniff(data), data)
        if ident.chosen:
            key, dt = ident.chosen.package_id, ident.chosen.doc_type
    t0 = time.perf_counter()
    rep, _ = validate_bytes(data, xml.name, registry, key, dt)
    res.seconds = time.perf_counter() - t0
    errs = _errors(rep)
    used = set()
    for e in spec.get("expect", []):
        hit = next((d for i, d in enumerate(errs) if i not in used and _matches(e, d)), None)
        if hit is None:
            res.missed.append(e)
            continue
        used.add(errs.index(hit))
        res.detected.append((e, hit))
        if e.get("line") and hit.line == e["line"]:
            res.exact_line += 1
        if hit.suggestion or hit.fix:
            res.actionable += 1
    if not spec.get("allow_extra"):
        res.false_pos = [d for i, d in enumerate(errs) if i not in used and not d.consequence_of]
    return res


def run_suite(folder: Path, user_registry=None) -> list[CaseResult]:
    meta = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
    uses = meta.get("uses", "installed")
    out: list[CaseResult] = []

    def go(registry):
        for exp in sorted(folder.glob("*.expect.json")):
            stem = exp.name[: -len(".expect.json")]
            xml = next((p for p in folder.glob(stem + ".*") if p.suffix.lower() in (".xml", ".sgm")), None)
            if xml is None:
                continue
            out.append(run_case(registry, meta["name"], xml, json.loads(exp.read_text(encoding="utf-8")), meta.get("schema")))

    if uses.startswith("fixture:"):
        from ..app_context import AppContext
        from ..config import Settings
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AppContext.open(Settings(data_root=Path(tmp)))
            try:
                ctx.registry.install(FIXTURES / "packages" / uses.split(":", 1)[1])
                go(ctx.registry)
            finally:
                ctx.close()
    else:
        go(user_registry)
    return out


def run_corpus(registry, folder: Path, schema: dict | None = None) -> list[CaseResult]:
    """Known-good files: every error is a false positive. Files whose schema is not installed are skipped."""
    out = []
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in (".xml", ".sgm") and p.is_file())
    for f in files:
        spec = {"title": f.name, "clean": True, "expect": [], "schema": schema}
        r = run_case(registry, "corpus", f, spec, None)
        if r.status == "run" and not schema:
            data = f.read_bytes()
            tree, _ = parse_xml(data)
            ident = identify(tree.getroot() if tree is not None else None, registry.list(False), sniff(data), data)
            if not ident.chosen:
                r.status, r.reason, r.false_pos = "skipped", f"no installed schema identifies it ({ident.status})", []
        r.case = str(f.relative_to(folder))
        out.append(r)
    return out


def summary(results: list[CaseResult]) -> dict:
    ran = [r for r in results if r.status == "run"]
    det = sum(len(r.detected) for r in ran)
    mis = sum(len(r.missed) for r in ran)
    fp = sum(len(r.false_pos) for r in ran)
    exp_lines = sum(1 for r in ran for e, _ in r.detected if e.get("line"))
    s = {
        "cases_run": len(ran), "cases_skipped": len(results) - len(ran),
        "expected": det + mis, "detected": det, "missed": mis, "false_positives": fp,
        "detection_rate": round(det / (det + mis), 4) if det + mis else None,
        "precision": round(det / (det + fp), 4) if det + fp else None,
        "exact_line_rate": round(sum(r.exact_line for r in ran) / exp_lines, 4) if exp_lines else None,
        "actionable_rate": round(sum(r.actionable for r in ran) / det, 4) if det else None,
        "clean_cases_without_errors": sum(1 for r in ran if not r.missed and not r.false_pos and not r.detected),
        "seconds": round(sum(r.seconds for r in ran), 3),
    }
    if s["detection_rate"] is not None and s["precision"] is not None and (s["detection_rate"] + s["precision"]):
        s["f1"] = round(2 * s["detection_rate"] * s["precision"] / (s["detection_rate"] + s["precision"]), 4)
    elif s["expected"] == 0 and ran:
        s["f1"] = 1.0 if fp == 0 else 0.0
    return s


def to_json(results: list[CaseResult]) -> dict:
    def diag(d):
        return {"category": d.category, "message": d.message, "line": d.line, "rule": d.rule_id}
    return {"summary": summary(results), "cases": [{
        "suite": r.suite, "case": r.case, "title": r.title, "status": r.status, "reason": r.reason,
        "detected": [{"expected": e, "reported": diag(d)} for e, d in r.detected],
        "missed": r.missed, "false_positives": [diag(d) for d in r.false_pos], "seconds": round(r.seconds, 3),
    } for r in results]}


def print_report(results: list[CaseResult], out=print) -> None:
    by_suite: dict[str, list[CaseResult]] = {}
    for r in results:
        by_suite.setdefault(r.suite, []).append(r)
    for suite, rs in by_suite.items():
        out(f"\n== {suite}")
        for r in rs:
            if r.status == "skipped":
                out(f"   -  {r.case:<34} skipped: {r.reason}")
                continue
            mark = "OK" if not r.missed and not r.false_pos else "!!"
            out(f"   {mark} {r.case:<34} found {len(r.detected)}/{len(r.detected) + len(r.missed)}"
                f"   false+ {len(r.false_pos)}   {r.seconds * 1000:.0f} ms")
            for e in r.missed:
                out(f"        MISSED   {e['category']}" + (f" <{e['element']}>" if e.get("element") else "")
                    + (f" line {e['line']}" if e.get("line") else "") + (f"  ({e['note']})" if e.get("note") else ""))
            for d in r.false_pos:
                out(f"        FALSE+   {d.category} line {d.line}: {d.message}")
    s = summary(results)
    pct = lambda v: "n/a" if v is None else f"{v * 100:.1f}%"
    out("\n== Scorecard")
    out(f"   cases run {s['cases_run']}  (skipped {s['cases_skipped']})")
    out(f"   planted problems detected   {s['detected']}/{s['expected']}   {pct(s['detection_rate'])}")
    out(f"   false positives             {s['false_positives']}   precision {pct(s['precision'])}")
    out(f"   reported on the exact line  {pct(s['exact_line_rate'])}")
    out(f"   with a suggestion or fix    {pct(s['actionable_rate'])}")
    if s.get("f1") is not None:
        out(f"   overall (F1)                {s['f1'] * 10:.1f} / 10")
