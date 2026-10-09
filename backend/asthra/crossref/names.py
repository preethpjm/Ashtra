"""What a schema calls each term, and where it sits: the "translation of field names".

For an installed schema the answer is resolved against the schema itself (its element and attribute
declarations), so it is always a place that schema really has:

1. a name the user confirmed for that schema;
2. the S-Series data model of the same specification (XML names from its XMI): exact;
3. ASTHRA's crosswalk for the standard family (S1000D, ATA iSpec 2200);
4. otherwise, any name the term has in another standard that the schema happens to use.
"""
from __future__ import annotations

import re

from ..translate import schema_graph as g
from .vocab import CROSSWALK, model_label

FAMILY = {"S1000D": "S1000D", "ATA2200": "ATA iSpec 2200", "ATA": "ATA iSpec 2200", "ATA iSpec 2200": "ATA iSpec 2200"}


def family_of(standard: str, models: list[dict]) -> list[str]:
    """The vocabulary columns that describe a schema of this standard, best first."""
    s = (standard or "").upper().replace(" ", "")
    out = [model_label(m) for m in models if (m.get("spec") or "").upper() == s]
    for k, v in FAMILY.items():
        if s == k.upper().replace(" ", ""):
            out.append(v)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s).lower())


# leaf names too common to place a term on their own: they need the class around them
WEAK_LEAVES = {"id", "name", "unit", "time", "date", "type", "code", "value", "text", "descr", "description", "task",
               "uom", "number", "nbr", "qty", "quantity", "item"}
# parts of a schema that never hold item data: signatures, message headers, security marking, layout
NOT_DATA = {"signature", "signedinfo", "keyinfo", "msgdate", "msgheader", "secclass", "secclassdefref", "seccls",
            "projattrs", "projattr"}


def class_words(term_id: str) -> tuple[set[str], set[str]]:
    """The words of the class a term belongs to ('PartAsDesigned.partName' -> part, designed) and its initials."""
    cls = term_id.split(":")[-1].split(".")[0]
    ws = [w for w in _words(cls) if w not in ("as", "of", "and", "data")]
    inits = {"".join(w[0] for w in ws[:i]) for i in range(2, len(ws) + 1)}
    return set(ws), inits


def in_context(term_id: str, path: str) -> bool:
    """Whether a place sits inside its term's class (a part's name under a part element, an organization's
    identifier under an organization): checked for places found only by a borrowed or similar name."""
    segs = [x.lstrip("@") for x in path.strip("/").split("/") if x]
    if any(_norm(x) in NOT_DATA for x in segs):
        return False
    if any(x.lower().endswith("ref") for x in segs[:-1]):     # a reference to an entry, not the entry
        return False
    ws, inits = class_words(term_id)
    if not ws:
        return True
    for seg in segs[1:]:
        for w in _words(seg):
            if w in ws or (len(w) >= 3 and any(c.startswith(w) or w.startswith(c) for c in ws)) \
                    or any(w.startswith(i) for i in inits):
                return True
    return False


def plausible(term_id: str, path: str) -> bool:
    """A borrowed name is plausible when its leaf is distinctive, or it sits inside its term's class."""
    segs = [x for x in path.strip("/").split("/") if x]
    if any(_norm(x.lstrip("@")) in NOT_DATA for x in segs):
        return False
    leaf = _norm(segs[-1].lstrip("@")) if segs else ""
    return in_context(term_id, path) if leaf in WEAK_LEAVES or len(leaf) <= 4 else True


class SchemaIndex:
    """Element/attribute names of one schema model, for resolving relative paths ("partRef/@partNumberValue")."""

    def __init__(self, model: dict):
        self.m = model
        self.by_name: dict[str, list[str]] = {}
        for n in model["elements"]:
            self.by_name.setdefault(_norm(n), []).append(n)
        self._paths: dict[str, list[str] | None] = {}

    def _root_path(self, el: str) -> list[str] | None:
        if el not in self._paths:
            self._paths[el] = g.path_to(self.m, el)
        return self._paths[el]

    def resolve(self, rel: str) -> list[dict]:
        """Every place in the schema matching a relative path: [{path, tag}] (path from the root)."""
        if not rel or " " in rel.strip() or "(" in rel:
            return []
        steps = [s for s in rel.strip("/").split("/") if s]
        first = steps[0]
        out = []
        if first.startswith("@"):                       # an attribute on any element
            for n, e in self.m["elements"].items():
                if any(_norm(a["name"]) == _norm(first[1:]) for a in e.get("attrs", [])):
                    rp = self._root_path(n)
                    if rp:
                        out.append({"path": "/".join(rp) + "/" + first, "tag": first})
            return out[:5]
        for el in self.by_name.get(_norm(first), []):
            cur, ok = el, True
            for st in steps[1:]:
                if st.startswith("@"):
                    ok = any(_norm(a["name"]) == _norm(st[1:]) for a in g.attrs(self.m, cur))
                    break
                nxt = next((c for c in g.order(self.m, cur) if _norm(c) == _norm(st)), None)
                if not nxt:
                    ok = False
                    break
                cur = nxt
            if ok:
                rp = self._root_path(el)
                if rp:
                    out.append({"path": "/".join(rp[:-1] + [el] + steps[1:]), "tag": steps[-1]})
        return out[:5]


def schema_names(vocab, models: list[dict], standard: str, schema_model: dict, overrides: dict[str, dict] | None = None,
                 terms: list[str] | None = None) -> dict[str, dict]:
    """term -> {tag, path, from, others} for one installed schema."""
    idx = SchemaIndex(schema_model)
    fams = family_of(standard, models)
    overrides = overrides or {}
    out: dict[str, dict] = {}
    for tid in terms or list(vocab.terms):
        t = vocab.terms.get(tid)
        if not t:
            continue
        if tid in overrides:
            o = overrides[tid]
            if o["path"] == "-":                                    # a person said: this schema has no place for it
                continue
            out[tid] = {"tag": o.get("tag") or o["path"].split("/")[-1], "path": o["path"], "from": "confirmed"}
            continue
        found = None
        for fam in fams:                                            # the standard's own names
            n = t["names"].get(fam)
            if not n:
                continue
            cands = [n["path"]] if n.get("path") else list(n.get("all") or [n["tag"]])
            for c in cands:
                hits = idx.resolve(c)
                if hits:
                    found = {"tag": hits[0]["tag"], "path": hits[0]["path"], "from": n["from"], "others": [h["path"] for h in hits[1:]]}
                    break
            if found:
                break
        if not found:                                               # not under its own names: borrow other standards' names
            for fam, n in t["names"].items():
                for c in ([n["path"]] if n.get("path") else list(n.get("all") or [n["tag"]])):
                    hits = [h for h in idx.resolve(c) if plausible(tid, h["path"])]
                    if hits:
                        found = {"tag": hits[0]["tag"], "path": hits[0]["path"], "from": f"name match ({fam})",
                                 "others": [h["path"] for h in hits[1:]]}
                        break
                if found:
                    break
        if found:
            out[tid] = found
    return out


def standard_names(vocab, column: str) -> dict[str, dict]:
    """term -> {tag, path, from} for a vocabulary column (a data model or a crosswalk family)."""
    return {tid: t["names"][column] for tid, t in vocab.terms.items() if column in t["names"]}


__all__ = ["schema_names", "standard_names", "family_of", "SchemaIndex", "CROSSWALK", "in_context", "plausible"]
