"""Where records come from: an assembly in the engineering BOM (with the project's rules), or a parts list
already in the library (to translate it into another standard)."""
from __future__ import annotations

import re

from ..knowledge.identity import normalize_part_number
from .values import split_item

DEFAULT_RULES = {
    "exclude": [],              # regular expressions on part number or name: process specs, materials, notes …
    "exclude_property": [],     # "name=value" on a part property (e.g. "MBOM authority=NA")
    "skip_zero_quantity": True, # alternates listed with quantity 0
    "numbering": "find_no",     # find_no | step10
    "figure": "1",
    "omit_cage": [],            # CAGEs not written as vendor codes (the manual's own manufacturer, standards bodies)
    "omit_unit": ["EA"],
    "max_depth": 6,
    "uppercase_names": False,   # ATA parts lists print names in capitals
}


def rules_with_defaults(rules: dict | None) -> dict:
    out = dict(DEFAULT_RULES)
    out.update({k: v for k, v in (rules or {}).items() if v is not None})
    return out


def assemblies(db) -> list[dict]:
    """Engineering assemblies: parts that contain others in a BOM and are not inside another."""
    return [dict(r) for r in db.execute("""
        SELECT p.part_number, p.manufacturer_code AS cage, p.name, COUNT(e.child_id) AS children
        FROM part p JOIN part_list_entry e ON e.parent_id=p.id
        WHERE p.part_number_key NOT IN (SELECT c.part_number_key FROM part_list_entry x JOIN part c ON c.id=x.child_id)
        GROUP BY p.part_number_key ORDER BY p.part_number""")]


def parts_lists(db) -> list[dict]:
    """Parts lists in the library: one per source document and figure."""
    return [dict(r) for r in db.execute("""
        SELECT c.source_id, s.kind, s.document, c.figure, COUNT(*) AS lines FROM catalogue_item c JOIN source s ON s.id=c.source_id
        GROUP BY c.source_id, c.figure ORDER BY s.kind, s.document, c.figure""")]


def _excluded(rules: dict, pn: str, name: str, props: dict[str, str]) -> str | None:
    for rx in rules.get("exclude") or []:
        try:
            if re.search(rx, pn, re.I) or re.search(rx, name or "", re.I):
                return f"matches the exclusion “{rx}”"
        except re.error:
            continue
    for cond in rules.get("exclude_property") or []:
        k, _, v = str(cond).partition("=")
        if k.strip() and props.get(k.strip(), "").strip().lower() == v.strip().lower():
            return f"{k.strip()} is {v.strip()}"
    return None


def from_engineering(db, tops: list[str], rules: dict) -> tuple[list[dict], list[dict]]:
    """A parts list of one or more top assemblies (e.g. RA-7100-01 and its post-SB RA-7100-02): the tops are items
    1, 1A …, each with an effectivity code (A, B …) when there are several; a detail part used in only some of
    them carries their codes. Children are ordered and numbered by find number (or in steps of 10)."""
    rules = rules_with_defaults(rules)
    codes = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    q = lambda sql, *a: [dict(r) for r in db.execute(sql, a)]

    def part(pn: str) -> dict | None:
        rows = q("""SELECT p.*, (SELECT COUNT(*) FROM part_list_entry e WHERE e.parent_id=p.id) AS kids FROM part p
                    WHERE p.part_number_key=? ORDER BY kids DESC, (p.manufacturer_code<>'') DESC""", normalize_part_number(pn))
        return rows[0] if rows else None

    def props(pid: int) -> dict[str, str]:
        return {r["name"]: r["value"] for r in q("SELECT name, value FROM part_property WHERE part_id=?", pid)}

    def kids(pid: int) -> list[dict]:
        return q("""SELECT c.id, c.part_number, c.part_number_key, c.manufacturer_code AS cage, c.name, c.unit_of_issue, e.quantity,
                           (SELECT b.find_no FROM bom_line b WHERE b.child_id=c.id AND b.parent_id=e.parent_id ORDER BY b.id DESC LIMIT 1) AS find_no
                    FROM part_list_entry e JOIN part c ON c.id=e.child_id WHERE e.parent_id=?""", pid)

    records, excluded = [], []
    top_rows = [(t, part(t)) for t in tops]
    missing = [t for t, p in top_rows if p is None]
    if missing:
        raise ValueError(f"not in the library: {', '.join(missing)}")
    many = len(top_rows) > 1
    for i, (t, p) in enumerate(top_rows):
        records.append({"item": "001", "item_variant": "" if i == 0 else codes[i - 1], "indenture": 1, "part_number": p["part_number"],
                        "cage": p["manufacturer_code"], "name": p["name"], "quantity": "1", "top": True, "not_illustrated": True,
                        "unit": p.get("unit_of_issue"), "effectivity": codes[i] if many else None, "figure": rules["figure"]})

    def natural(fn: str | None):
        m = re.match(r"^\s*0*(\d+)\s*([A-Za-z]*)", fn or "")
        return (int(m.group(1)), m.group(2)) if m else (10 ** 6, fn or "")

    def walk(parents: list[tuple[int, str | None]], indenture: int, inherited: str | None):
        """parents: (part id, effectivity code of that parent)"""
        if indenture > rules["max_depth"]:
            return
        merged: dict[str, dict] = {}
        for pid, code in parents:
            for k in kids(pid):
                e = merged.setdefault(k["part_number_key"], {**k, "codes": []})
                if code:
                    e["codes"].append(code)
        all_codes = [c for _, c in parents if c]
        last = 0
        for k in sorted(merged.values(), key=lambda x: (natural(x["find_no"]), x["part_number"])):
            why = _excluded(rules, k["part_number"], k["name"] or "", props(k["id"]))
            if not why and rules["skip_zero_quantity"] and (k["quantity"] or 0) == 0:
                why = "quantity 0 (an alternate)"
            if why:
                excluded.append({"part_number": k["part_number"], "name": k["name"], "reason": why, "indenture": indenture})
                continue
            fn = (k["find_no"] or "").strip()
            if rules["numbering"] == "find_no" and re.match(r"^\d+[A-Za-z]*$", fn):
                item, var = split_item(fn)
                last = int(item)
            else:
                last = (last // 10 + 1) * 10
                item, var = str(last).zfill(3), ""
            eff = None
            if all_codes and sorted(set(k["codes"])) != sorted(set(all_codes)):
                eff = ",".join(sorted(set(k["codes"])))
            eff = eff or inherited
            qty = k["quantity"]
            records.append({"item": item, "item_variant": var, "indenture": indenture, "part_number": k["part_number"],
                            "cage": k["cage"], "name": k["name"], "quantity": f"{qty:g}" if isinstance(qty, float) else str(qty),
                            "unit": k.get("unit_of_issue"), "effectivity": eff, "figure": rules["figure"]})
            if kids(k["id"]):
                walk([(k["id"], None)], indenture + 1, eff)

    walk([(p["id"], codes[i] if many else None) for i, (_, p) in enumerate(top_rows)], 2, None)
    return records, excluded


def from_catalogue(db, source_id: int, figure: str) -> list[dict]:
    """The lines of a parts list already in the library, as records (translation between standards)."""
    rows = db.execute("""SELECT c.*, p.part_number, p.manufacturer_code AS cage, p.name, p.unit_of_issue FROM catalogue_item c
                         JOIN part p ON p.id=c.part_id WHERE c.source_id=? AND c.figure=? ORDER BY c.id""", (source_id, figure)).fetchall()
    out = []
    for r in rows:
        qty = r["qty_per_next_assy"] or ""
        top = r["indenture"] == 1 or qty.upper() in ("RF", "REF")
        out.append({"item": r["item"], "item_variant": r["item_variant"] or "", "indenture": r["indenture"], "part_number": r["part_number"],
                    "cage": r["cage"], "name": r["name"], "quantity": "1" if qty.upper() in ("RF", "REF") else qty, "top": top,
                    "not_illustrated": top, "unit": r["unit_of_issue"], "effectivity": r["usable_on_code"], "figure": figure})
    return out
