"""Cross-source checks: the same product described by several sources must agree.

  catalogue      the parts list of one figure as written in two sources (ATA IPL, S1000D IPD, S2000M):
                 same item → same part number, quantity, indenture and effectivity code
  engineering    the engineering BOM (parent contains child, quantity) against the structure the parts
                 lists imply (indenture), in both directions
  identity       a part number written without a CAGE that matches exactly one part with a CAGE: a
                 suggested match (never merged automatically)

Two parts lists are taken to describe the same figure when they share a top-level part number.
Conventions that are not differences: "RF" (reference assembly) equals quantity 1; effectivity is compared
only where both sides use short codes (A, B …); parts are matched on the part number when one side has no CAGE.
"""
from __future__ import annotations

from collections import defaultdict

SOURCE_LABEL = {"ATA-CMM": "ATA IPL", "S1000D-DM": "S1000D IPD", "S2000M": "S2000M", "ENG-BOM": "BOM", "ENG-3D": "3D model"}


def _q(v) -> str:
    s = str(v or "").strip().upper()
    if s in ("RF", "REF", "AR"):
        return "1" if s != "AR" else "AR"
    try:
        f = float(s)
        return f"{f:g}"
    except ValueError:
        return s


def _short(code) -> bool:
    return bool(code) and all(len(c.strip()) <= 3 for c in str(code).split(","))


def _groups(db) -> list[dict]:
    """parts lists: one per (source, figure), lines in document order."""
    rows = db.execute("""SELECT c.id, c.source_id, c.figure, c.item, c.item_variant, c.indenture, c.qty_per_next_assy AS qty,
                                c.usable_on_code AS eff, p.part_number, p.part_number_key AS key, p.manufacturer_code AS cage,
                                s.kind, s.document
                         FROM catalogue_item c JOIN part p ON p.id=c.part_id JOIN source s ON s.id=c.source_id
                         ORDER BY c.source_id, c.figure, c.id""").fetchall()
    groups: dict[tuple, dict] = {}
    for r in rows:
        g = groups.setdefault((r["source_id"], r["figure"]), {"source": r["source_id"], "kind": r["kind"], "document": r["document"],
                                                               "figure": r["figure"], "lines": []})
        g["lines"].append(dict(r))
    for g in groups.values():
        top = min((l["indenture"] for l in g["lines"] if l["indenture"] is not None), default=None)
        g["tops"] = {l["key"] for l in g["lines"] if l["indenture"] == top}
        g["label"] = f"{SOURCE_LABEL.get(g['kind'], g['kind'])} {g['document']} fig {g['figure']}"
    return list(groups.values())


def _edges(lines: list[dict]) -> dict[tuple[str, str], dict]:
    """(parent key, child key) -> {qty, item}. Variants of one item (1 / 1A: pre- and post-SB assemblies) are
    alternatives; a child belongs to each of them, or only to those with its effectivity code."""
    out: dict[tuple[str, str], dict] = {}
    levels: dict[int, list[dict]] = {}
    prev_ind = None
    for l in lines:
        n = l["indenture"]
        if n is None:
            continue
        if prev_ind == n and levels.get(n) and levels[n][-1]["item"] == l["item"]:
            levels[n].append(l)          # item variants (1 / 1A, 50 / 50A): alternatives at the same place
        else:
            levels[n] = [l]
        for d in [x for x in levels if x > n]:
            del levels[d]
        parents = levels.get(n - 1, [])
        if l["eff"]:
            match = [p for p in parents if not p["eff"] or p["eff"] == l["eff"]]
            parents = match or parents
        for p in parents:
            out[(p["key"], l["key"])] = {"qty": _q(l["qty"]), "item": l["item"] + (l["item_variant"] or ""),
                                         "parent": p["part_number"], "child": l["part_number"]}
        prev_ind = n
    return out


def check(db) -> list[dict]:
    out: list[dict] = []

    def find(rule, subject, message, **values):
        out.append({"rule": rule, "subject": subject, "message": message, "values": values})

    groups = _groups(db)
    # 1. catalogue against catalogue
    for i, a in enumerate(groups):
        for b in groups[i + 1:]:
            if a["source"] == b["source"] or not (a["tops"] & b["tops"]):
                continue
            ia = {l["item"] + (l["item_variant"] or ""): l for l in a["lines"]}
            ib = {l["item"] + (l["item_variant"] or ""): l for l in b["lines"]}
            for item in sorted(set(ia) | set(ib)):
                la, lb = ia.get(item), ib.get(item)
                subj = f"item {item.lstrip('0') or '0'}"
                if not la or not lb:
                    have, miss = (a, b) if la else (b, a)
                    l = la or lb
                    find("catalogue-missing", subj, f"Item {item.lstrip('0')} ({l['part_number']}) is in {have['label']} but not in {miss['label']}.",
                         present=have["label"], missing=miss["label"])
                    continue
                if la["key"] != lb["key"]:
                    find("catalogue-part", subj, f"Item {item.lstrip('0')}: {a['label']} has {la['part_number']}, {b['label']} has {lb['part_number']}.",
                         **{a["label"]: la["part_number"], b["label"]: lb["part_number"]})
                elif la["cage"] and lb["cage"] and la["cage"] != lb["cage"]:
                    find("catalogue-cage", subj, f"Item {item.lstrip('0')} {la['part_number']}: CAGE {la['cage']} in {a['label']}, {lb['cage']} in {b['label']}.",
                         **{a["label"]: la["cage"], b["label"]: lb["cage"]})
                if _q(la["qty"]) != _q(lb["qty"]):
                    find("catalogue-quantity", subj, f"Item {item.lstrip('0')} {la['part_number']}: quantity {la['qty']} in {a['label']}, {lb['qty']} in {b['label']}.",
                         **{a["label"]: la["qty"], b["label"]: lb["qty"]})
                if la["indenture"] != lb["indenture"]:
                    find("catalogue-indenture", subj, f"Item {item.lstrip('0')} {la['part_number']}: indenture {la['indenture']} in {a['label']}, {lb['indenture']} in {b['label']}.",
                         **{a["label"]: la["indenture"], b["label"]: lb["indenture"]})
                if _short(la["eff"]) and _short(lb["eff"]) and la["eff"] != lb["eff"]:
                    find("catalogue-effectivity", subj, f"Item {item.lstrip('0')} {la['part_number']}: effectivity {la['eff']} in {a['label']}, {lb['eff']} in {b['label']}.",
                         **{a["label"]: la["eff"], b["label"]: lb["eff"]})

    # 2. engineering BOM against the parts lists
    bom = db.execute("""SELECT pp.part_number_key AS pkey, pp.part_number AS parent, cp.part_number_key AS ckey, cp.part_number AS child,
                               b.quantity, s.document
                        FROM bom_line b JOIN part cp ON cp.id=b.child_id JOIN part pp ON pp.id=b.parent_id JOIN source s ON s.id=b.source_id
                        WHERE b.parent_id IS NOT NULL""").fetchall()
    if bom:
        bom_edges = {(r["pkey"], r["ckey"]): r for r in bom}
        bom_parents = {r["pkey"] for r in bom}
        for g in groups:
            if g["kind"] == "ENG-BOM":
                continue
            edges = _edges([dict(l) for l in g["lines"]])
            if not ({p for p, _ in edges} & bom_parents):
                continue
            for (p, c), e in edges.items():
                r = bom_edges.get((p, c))
                if r is None:
                    if p in bom_parents:
                        find("bom-missing", f"{e['parent']} / {e['child']}",
                             f"{g['label']} lists {e['child']} (item {e['item'].lstrip('0')}) under {e['parent']}, but the engineering BOM does not.",
                             catalogue=g["label"])
                    continue
                if r["quantity"] is not None and _q(r["quantity"]) != e["qty"]:
                    find("bom-quantity", f"{e['parent']} / {e['child']}",
                         f"{e['child']} in {e['parent']}: quantity {e['qty']} in {g['label']}, {_q(r['quantity'])} in BOM {r['document']}.",
                         catalogue=e["qty"], bom=_q(r["quantity"]))
            for (p, c), r in bom_edges.items():
                if p in {pp for pp, _ in edges} and (p, c) not in edges:
                    find("catalogue-missing-bom-line", f"{r['parent']} / {r['child']}",
                         f"BOM {r['document']} has {r['child']} in {r['parent']}, but {g['label']} does not list it.", catalogue=g["label"])

    # 4. what engineering tools reported (STEP ↔ MBOM reconciliation …), with the tool's own wording
    for r in db.execute("""SELECT f.rule, f.subject, f.message, s.document FROM engineering_finding f JOIN source s ON s.id=f.source_id
                           ORDER BY f.id""").fetchall():
        find(r["rule"], r["subject"], r["message"], source=r["document"])

    # 3. identity suggestions: unqualified part number = exactly one qualified part (one finding per source)
    by_src: dict[str, list[str]] = defaultdict(list)
    for r in db.execute("""SELECT u.part_number, u.part_number_key AS key,
                                  (SELECT s.kind || ' ' || s.document FROM source s WHERE s.id=u.source_id) AS src
                           FROM part u WHERE u.manufacturer_code='' ORDER BY u.part_number""").fetchall():
        q = db.execute("SELECT manufacturer_code FROM part WHERE part_number_key=? AND manufacturer_code<>''", (r["key"],)).fetchall()
        if len(q) == 1:
            by_src[r["src"] or "unknown source"].append(f"{r['part_number']} → CAGE {q[0]['manufacturer_code']}")
    for src, items in by_src.items():
        find("identity-suggestion", src,
             f"{len(items)} part number(s) in {src} have no CAGE; each matches exactly one part with a CAGE: " + "; ".join(items) + ".",
             count=len(items))
    return out
