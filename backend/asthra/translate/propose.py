"""Propose a binding for a document type from its schema model: which repeating element is one record, where
the records live, and which attribute or element holds each field. Scores come from the field's usual names;
every choice is shown with its confidence and can be changed by the user."""
from __future__ import annotations

import re

from . import schema_graph as g
from .concepts import CONCEPTS


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _score(leaf: str, parent: str, synonyms: list[str]) -> float:
    n = _norm(leaf)
    best = 0.0
    for i, s in enumerate(synonyms):
        k = _norm(s)
        weight = 1.0 - min(i, 6) * 0.03                     # earlier synonyms are the stronger ones
        if n == k:
            best = max(best, weight)
        elif len(k) >= 4 and (n.startswith(k) or n.endswith(k)):
            best = max(best, 0.6 * weight)
    # a value element named after its role in a parent with the field's name (e.g. nom/kwd)
    if best < 0.5 and parent and any(_norm(parent) == _norm(s) for s in synonyms):
        best = max(best, 0.55)
    return round(best, 2)


def _formats(field: str, slot: dict, mapped: dict) -> str | None:
    """How a neutral value is written in this slot, from the slot's name and neighbours."""
    leaf = _norm(slot["leaf"])
    if field == "item":
        if "item_variant" in mapped:
            return "pad3"
        return "join_variant" if leaf in ("itemnbr", "itemno", "findno", "findnumber") else "pad3_join"
    if field == "indenture" and leaf == "indent":
        return "zero_based"
    if field == "quantity" and leaf == "upa":
        return "rf_top"
    if field == "cage" and leaf == "mfr":
        return "vendor_v"
    if field == "not_illustrated" and leaf == "illusind":
        return "invert01"
    if field in ("not_illustrated", "attaching") and slot["kind"] == "attr":
        return "bool01"
    if field == "not_illustrated" and slot["kind"] != "attr":
        return "presence"
    if field == "name" and leaf == "kwd":
        return "split_kwd_adt"
    return None


def candidates(model: dict, concept: str = "parts_list") -> list[dict]:
    """Repeating elements that look like records of the concept, best first."""
    c = CONCEPTS[concept]
    reps = g.repeating(model)
    out = []
    for r in reps:
        sl = g.slots(model, r)
        fields = {}
        for f, (_, syn) in c["fields"].items():
            best = max(((_score(s["leaf"], s["parent"], syn), s) for s in sl), key=lambda x: x[0], default=(0, None))
            if best[0] >= 0.5:
                fields[f] = best
        if "part_number" not in fields:
            continue
        score = sum(v[0] for v in fields.values()) + (1.5 if any(_norm(h) == _norm(r) for h in c["record_hint"]) else 0)
        out.append({"record": r, "score": round(score, 2), "fields": fields})
    return sorted(out, key=lambda x: -x["score"])


def propose(model: dict, concept: str = "parts_list", record: str | None = None) -> dict:
    """A binding: {concept, root, record, container (path from the root to the record's parent), group, fields}."""
    cands = candidates(model, concept)
    if record:
        cands = [x for x in cands if x["record"] == record] or cands
    if not cands:
        return {"concept": concept, "root": model["root"], "record": None, "container": None, "group": None, "fields": {},
                "problems": ["No repeating element in this schema holds a part number: this document type has no parts list."]}
    best = cands[0]
    chain = g.path_to(model, best["record"]) or [model["root"], best["record"]]
    container = chain[:-1]
    fields: dict[str, dict] = {}
    used: set[str] = set()
    for f, (sc, slot) in sorted(best["fields"].items(), key=lambda kv: -kv[1][0]):
        if slot["path"] in used:
            continue
        used.add(slot["path"])
        fields[f] = {"path": slot["path"], "confidence": sc}
    for f, spec in fields.items():
        slot = next(s for s in g.slots(model, best["record"]) if s["path"] == spec["path"])
        fmt = _formats(f, slot, fields)
        if fmt:
            spec["format"] = fmt
    # a field the record does not carry may sit on an ancestor (ATA: figure/@fignbr above prtlist/itemdata)
    group = None
    syn_fig = CONCEPTS[concept]["fields"]["figure"][1]
    if "figure" not in fields:
        for i in range(len(container) - 1, 0, -1):
            scored = [(_score(a["name"], "", syn_fig), a["name"]) for a in g.attrs(model, container[i])]
            sc, name = max(scored, default=(0, None))
            if sc >= 0.5:
                group = {"level": i, "element": container[i], "field": "figure", "attr": name, "confidence": sc}
                break
    problems = []
    for need in ("part_number", "quantity", "item"):
        if need not in fields:
            problems.append(f"No place found for {CONCEPTS[concept]['fields'][need][0].lower()}: choose one.")
    return {"concept": concept, "root": model["root"], "record": best["record"], "container": container, "group": group,
            "fields": fields, "problems": problems,
            "alternatives": [x["record"] for x in cands[1:5]]}
