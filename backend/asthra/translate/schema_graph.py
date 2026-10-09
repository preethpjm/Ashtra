"""Questions about a schema model (asthra/schema/model.py) that translation needs: child order, what repeats,
what is required, where a value can be written (slots), and how to reach an element from the root."""
from __future__ import annotations



def _flat(p, mult: bool = False, out=None):
    """(name, min_ok, repeats) for every element in a particle, in schema order."""
    out = [] if out is None else out
    if not p:
        return out
    rep = mult or p.get("max") is None or (p.get("max") or 1) > 1
    if p["k"] == "el":
        out.append((p["n"], p.get("min", 1), rep))
    elif p["k"] in ("seq", "choice", "all"):
        for it in p.get("items", []):
            _flat(it, rep, out)
    return out


def el(model: dict, name: str) -> dict | None:
    return model["elements"].get(name)


def children(model: dict, name: str) -> list[tuple[str, int, bool]]:
    e = el(model, name)
    if not e:
        return []
    seen, out = set(), []
    for n, mn, rep in _flat(e.get("content")):
        if n not in seen:
            seen.add(n)
            out.append((n, mn, rep))
    return out


def order(model: dict, name: str) -> list[str]:
    return [c for c, _, _ in children(model, name)]


def is_text(model: dict, name: str) -> bool:
    e = el(model, name) or {}
    return bool(e.get("text") or e.get("mixed"))


def is_empty(model: dict, name: str) -> bool:
    return bool((el(model, name) or {}).get("empty"))


def attrs(model: dict, name: str) -> list[dict]:
    return (el(model, name) or {}).get("attrs", [])


def repeating(model: dict) -> set[str]:
    out = set()
    for n in model["elements"]:
        for c, _, rep in children(model, n):
            if rep:
                out.add(c)
    return out


def required_children(model: dict, name: str, present: set[str]) -> list[str]:
    """Children a new element needs: required ones in sequences; the first option of a required choice
    unless an option is already present."""
    e = el(model, name) or {}
    out: list[str] = []

    def walk(p, required: bool):
        if not p:
            return
        req = required and p.get("min", 1) >= 1
        if p["k"] == "el":
            if req and p["n"] not in out:
                out.append(p["n"])
        elif p["k"] in ("seq", "all"):
            for it in p.get("items", []):
                walk(it, req)
        elif p["k"] == "choice":
            if not req:
                return
            names = [x for x, _, _ in _flat(p)]
            if any(n in present for n in names):
                return
            first = p["items"][0] if p.get("items") else None
            walk(first, True)

    walk(e.get("content"), True)
    return out


def _edges(model: dict, name: str) -> list[tuple[str, float]]:
    """Children with the cost of going through them: later options of a choice (alternatives such as an
    incremental revision or a temporary revision) and optional children cost more than the main content."""
    out: dict[str, float] = {}

    def walk(p, cost: float):
        if not p:
            return
        if p["k"] == "el":
            c = cost + (0.3 if p.get("min", 1) == 0 else 0)
            out[p["n"]] = min(out.get(p["n"], 99.0), c)
        elif p["k"] == "choice":
            for i, it in enumerate(p.get("items", [])):
                walk(it, cost + 0.5 * i)
        else:
            for it in p.get("items", []):
                walk(it, cost)

    walk((el(model, name) or {}).get("content"), 1.0)
    return list(out.items())


def path_to(model: dict, target: str, root: str | None = None) -> list[str] | None:
    """The main chain of element names from the root to target (inclusive): cheapest by _edges."""
    import heapq
    root = root or model["root"]
    best, prev = {root: 0.0}, {root: None}
    heap = [(0.0, root)]
    while heap:
        d, n = heapq.heappop(heap)
        if d > best.get(n, 1e9):
            continue
        if n == target:
            out = []
            while n is not None:
                out.append(n)
                n = prev[n]
            return out[::-1]
        for c, w in _edges(model, n):
            nd = d + w
            if nd < best.get(c, 1e9):
                best[c], prev[c] = nd, n
                heapq.heappush(heap, (nd, c))
    return None


def slots(model: dict, record: str, depth: int = 4) -> list[dict]:
    """Every place below a record element where a value can be written: its attributes, text elements and
    their attributes, as paths relative to the record ("@item", "itemSeqNumber/partRef/@partNumberValue")."""
    out: list[dict] = []

    def visit(name: str, prefix: str, d: int, seen: tuple):
        for a in attrs(model, name):
            out.append({"path": f"{prefix}@{a['name']}", "leaf": a["name"], "kind": "attr", "parent": name,
                        "required": a.get("required", False), "attr_kind": a.get("kind")})
        if d >= depth:
            return
        for c, mn, rep in children(model, name):
            if c in seen:
                continue
            p = f"{prefix}{c}"
            if is_text(model, c):
                out.append({"path": p, "leaf": c, "kind": "text", "parent": name, "required": mn >= 1, "repeats": rep})
            visit(c, p + "/", d + 1, seen + (c,))

    visit(record, "", 0, (record,))
    return out
