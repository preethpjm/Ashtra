"""Engineering data (BOM from PLM/ERP/CAD, CSV / Excel / JSON) → knowledge facts.

What it reads, per line:  part number, CAGE, name, quantity, unit, parent assembly (or the level of an
indented BOM), find number, effectivity, make/buy, and any other columns as part properties
(mass, material, CAD file, CAD node …).
What it writes:            part, part_list_entry (parent contains child), bom_line (the line as written),
                           part_property (the extra columns).
Columns are recognised by name (see COLUMNS); a JSON file may use the ASTHRA engineering format
(FORMAT below) or a plain list of objects with the same column names.

    {"format": "asthra-engineering/1",
     "source": {"system": "PLM", "document": "RA-7100 EBOM", "revision": "B", "date": "2026-10-08"},
     "items": [{"part_number": "RA-7110-1", "cage": "ZZD01", "name": "Housing, actuator", "quantity": 1,
                "unit": "EA", "parent": "RA-7100-01", "find_no": "10", "level": 1, "effectivity": "-01",
                "properties": {"mass_kg": 0.21, "material": "AL 7075-T6", "cad_file": "RA-7110-1.step"}}]}

A line may name several parents separated by ";" (a detail part used in two top assemblies).
Re-importing the same document replaces what was imported from it before.
"""
from __future__ import annotations

import csv
import io
import json
import re

from .identity import normalize_part_number
from .store import KnowledgeStore

KIND = "ENG-BOM"
FORMAT = "asthra-engineering/1"

COLUMNS = {   # field -> header names it is recognised by (compared without case, spaces, dots, underscores)
    "part_number": ["part number", "partnumber", "pn", "p/n", "part no", "part", "item number", "component", "material number"],
    "cage": ["cage", "ncage", "cage code", "manufacturer code", "mfr code", "mfr", "vendor code", "supplier code"],
    "name": ["description", "name", "nomenclature", "part name", "title", "item description"],
    "quantity": ["qty", "quantity", "qpa", "qty per assy", "quantity per assembly", "qty per", "upa"],
    "unit": ["uom", "unit", "unit of measure", "uoi", "unit of issue"],
    "level": ["level", "lvl", "bom level", "indenture"],
    "find_no": ["find no", "find number", "find", "item no", "item", "pos", "position", "balloon", "fig item"],
    "parent": ["parent", "parent part number", "parent pn", "parent part", "next higher assy", "nha", "assembly"],
    "effectivity": ["effectivity", "eff", "applicability", "usable on", "eff code"],
    "item_type": ["item type", "type", "category", "part type"],
    "make_buy": ["make/buy", "make buy", "makebuy", "source code", "procurement"],
}
_norm = lambda s: re.sub(r"[\s._\-]+", " ", str(s or "").strip().lower()).strip()
_LOOKUP = {_norm(n): f for f, names in COLUMNS.items() for n in [f, *names]}


def column_map(headers: list[str]) -> dict[str, str]:
    """header as written -> field ('' when the column is an extra property)."""
    out, taken = {}, set()
    for h in headers:
        f = _LOOKUP.get(_norm(h), "")
        if f and f in taken:
            f = ""
        out[h] = f
        taken.add(f)
    return out


def read_rows(data: bytes, filename: str) -> tuple[list[dict], dict]:
    """-> (rows as {field or header: value}, source info)"""
    name = filename.lower()
    info = {"document": filename, "revision": "", "system": ""}
    if name.endswith(".json"):
        obj = json.loads(data.decode("utf-8-sig"))
        items = obj.get("items") if isinstance(obj, dict) else obj
        if isinstance(obj, dict):
            s = obj.get("source") or {}
            info.update({k: str(s.get(k) or info.get(k, "")) for k in ("document", "revision", "system")})
        if not isinstance(items, list):
            raise ValueError('JSON must be a list of lines or {"items": [...]}')
        rows = []
        for it in items:
            props = it.get("properties") or {}
            cmap = column_map([k for k in it if k != "properties"])
            row = {(cmap.get(k) or k): v for k, v in it.items() if k != "properties"}
            row.update({f"prop:{k}": v for k, v in props.items()})
            rows.append(row)
        return rows, info
    if name.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError as e:  # pragma: no cover
            raise ValueError("Excel files need the openpyxl package (pip install openpyxl), or save the BOM as CSV") from e
        ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        table = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
    else:
        text = data.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|") if text.strip() else csv.excel
        table = list(csv.reader(io.StringIO(text), dialect))
    table = [r for r in table if any(c.strip() for c in r)]
    if not table:
        return [], info
    # the header is the first row that names a part-number column
    hi = next((i for i, r in enumerate(table[:20]) if "part_number" in column_map(r).values()), None)
    if hi is None:
        raise ValueError("no part number column found (expected a header such as 'Part Number' or 'P/N')")
    cmap = column_map(table[hi])
    rows = []
    for r in table[hi + 1:]:
        row = {}
        for h, v in zip(table[hi], r):
            f = cmap.get(h, "")
            row[f or f"prop:{h.strip()}"] = v.strip()
        rows.append(row)
    return rows, info


def _qty(v) -> float | None:
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def import_bom(k: KnowledgeStore, data: bytes, filename: str) -> dict:
    if filename.lower().endswith(".json"):
        obj = json.loads(data.decode("utf-8-sig"))
        if is_reconciliation(obj):
            return import_reconciliation(k, obj, filename)
    rows, info = read_rows(data, filename)
    doc = info["document"] or filename
    for sid in [r[0] for r in k.db.execute("SELECT id FROM source WHERE kind=? AND document=?", (KIND, doc))]:
        k.db.execute("DELETE FROM bom_line WHERE source_id=?", (sid,))
        k.db.execute("DELETE FROM part_list_entry WHERE source_id=?", (sid,))
        k.db.execute("DELETE FROM part_property WHERE source_id=?", (sid,))
    src = k.source(KIND, doc, issue=info.get("revision", ""), schema=info.get("system", ""), note=filename)
    rows = [r for r in rows if str(r.get("part_number") or "").strip()]
    cage_of = {normalize_part_number(str(r["part_number"])): str(r.get("cage") or "").strip() for r in rows}
    ids: dict[str, int] = {}
    counts = {"lines": 0, "parts": 0, "structure": 0, "properties": 0, "warnings": []}

    def pid_for(pn: str, cage: str = "", name: str = "", kind: str = "part") -> int:
        key = normalize_part_number(pn)
        if key not in ids:
            ids[key] = k.part(pn, cage or cage_of.get(key, ""), name, kind, source_id=src)
            counts["parts"] += 1
        return ids[key]

    stack: dict[int, str] = {}           # indented BOM: level -> part number of the last line at that level
    for n, r in enumerate(rows, 1):
        pn = str(r["part_number"]).strip()
        typ = str(r.get("item_type") or "").lower()
        kind = "consumable" if "consum" in typ else "support-equipment" if ("tool" in typ or "equip" in typ) else "part"
        child = pid_for(pn, str(r.get("cage") or "").strip(), str(r.get("name") or "").strip(), kind)
        lvl = r.get("level")
        lvl = int(float(lvl)) if str(lvl or "").strip().lstrip("-").replace(".", "", 1).isdigit() else None
        parents = [p.strip() for p in re.split(r"[;|]", str(r.get("parent") or "")) if p.strip()]
        if not parents and lvl is not None and lvl > 0:
            prev = stack.get(lvl - 1)
            if prev:
                parents = [prev]
            else:
                counts["warnings"].append(f"line {n}: level {lvl} but no line at level {lvl - 1} above it")
        if lvl is not None:
            stack[lvl] = pn
            for deeper in [x for x in stack if x > lvl]:
                del stack[deeper]
        q = _qty(r.get("quantity"))
        for par in parents:
            parent = pid_for(par)
            k.db.execute("""INSERT INTO part_list_entry(parent_id, child_id, quantity, source_id) VALUES (?,?,?,?)
                            ON CONFLICT(parent_id, child_id) DO UPDATE SET quantity=excluded.quantity, source_id=excluded.source_id""",
                         (parent, child, q if q is not None else 1, src))
            counts["structure"] += 1
        k.db.execute("""INSERT INTO bom_line(source_id, line, parent_id, child_id, find_no, level, quantity, unit, effectivity, make_buy)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (src, n, pid_for(parents[0]) if len(parents) == 1 else None, child, str(r.get("find_no") or "") or None, lvl,
                      q, str(r.get("unit") or "") or None, str(r.get("effectivity") or "") or None, str(r.get("make_buy") or "") or None))
        if len(parents) > 1:
            for par in parents[1:]:
                k.db.execute("""INSERT INTO bom_line(source_id, line, parent_id, child_id, find_no, level, quantity, unit, effectivity, make_buy)
                                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                             (src, n, pid_for(par), child, str(r.get("find_no") or "") or None, lvl, q,
                              str(r.get("unit") or "") or None, str(r.get("effectivity") or "") or None, str(r.get("make_buy") or "") or None))
            k.db.execute("UPDATE bom_line SET parent_id=? WHERE source_id=? AND line=? AND parent_id IS NULL",
                         (pid_for(parents[0]), src, n))
        for key, v in r.items():
            if key.startswith("prop:") and str(v).strip() != "":
                k.db.execute("INSERT OR REPLACE INTO part_property(part_id, name, value, source_id) VALUES (?,?,?,?)",
                             (child, key[5:], str(v), src))
                counts["properties"] += 1
        counts["lines"] += 1
    k.db.commit()
    return {"imported": True, "dmc": doc, "title": f"Engineering BOM {doc}", **counts}


# ---------------------------------------------------------------- STEP (3D) ↔ MBOM reconciliation results
def is_reconciliation(obj) -> bool:
    return isinstance(obj, dict) and "matched" in obj and ("unmatched_mbom" in obj or "unmatched_step" in obj)


def _pn(v) -> str:
    """MBOM part numbers carry their level as leading dots ('..MS21209F4-20')."""
    return re.sub(r"^\.+", "", str(v or "").strip())


def import_reconciliation(k: KnowledgeStore, obj: dict, filename: str) -> dict:
    """The result of the STEP→GLB / MBOM reconciliation tool: which 3D item is which MBOM line, with status,
    confidence, quantities and the tool's flags. Writes the MBOM lines (part, bom_line with its level), the 3D
    links (cad_link) and the tool's findings (engineering_finding). The MBOM tree itself is not in this file
    (matched and unmatched lines are listed separately), so parent-child structure comes from the MBOM export."""
    doc = filename
    for sid in [r[0] for r in k.db.execute("SELECT id FROM source WHERE kind='ENG-3D' AND document=?", (doc,))]:
        for t in ("bom_line", "cad_link", "engineering_finding", "part_property"):
            k.db.execute(f"DELETE FROM {t} WHERE source_id=?", (sid,))
    summ = obj.get("summary") or {}
    src = k.source("ENG-3D", doc, schema="STEP-MBOM reconciliation", note=json.dumps(summ)[:500])
    counts = {"lines": 0, "parts": 0, "links": 0, "findings": 0, "warnings": []}
    seen: dict[str, int] = {}

    def part(pn, name="", cage=""):
        key = normalize_part_number(pn)
        if key not in seen:
            seen[key] = k.part(pn, cage or "", name, "part", source_id=src)
            counts["parts"] += 1
        return seen[key]

    def finding(rule, subject, message, pid=None):
        k.db.execute("INSERT INTO engineering_finding(source_id, rule, subject, message, part_id) VALUES (?,?,?,?,?)",
                     (src, rule, subject, message, pid))
        counts["findings"] += 1

    for m in obj.get("matched") or []:
        pn = _pn(m.get("mbom_part_number"))
        pid = part(pn, str(m.get("mbom_description") or "").replace("\n", " "), m.get("mbom_manuf_code") or "") if pn else None
        if pid:
            k.db.execute("""INSERT INTO bom_line(source_id, line, parent_id, child_id, find_no, level, quantity, unit, effectivity, make_buy)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (src, counts["lines"] + 1, None, pid, None, m.get("mbom_level"), _qty(m.get("mbom_qty")), None,
                          m.get("effectivity_code"), None))
            counts["lines"] += 1
        cad = str(m.get("step_part_number") or m.get("step_name") or "").strip()
        status, conf = m.get("status") or "", m.get("confidence")
        k.db.execute("""INSERT INTO cad_link(source_id, part_id, cad_name, cad_label, cad_qty, status, confidence, quantity_match, members, flags)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (src, pid, cad, m.get("step_name"), _qty(m.get("step_qty")), status, conf,
                      None if m.get("quantity_match") is None else int(bool(m.get("quantity_match"))),
                      json.dumps(m.get("member_part_numbers") or []), json.dumps(m.get("flags") or [])))
        counts["links"] += 1
        subj = f"{cad} ↔ {pn}"
        if m.get("quantity_match") is False:
            finding("3d-quantity", subj, f"3D model has {m.get('step_qty')} × {cad}, MBOM has {m.get('mbom_qty')} × {pn}.", pid)
        if status != "matched":
            finding("3d-fuzzy", subj, f"{cad} was matched to {pn} with confidence {conf}: "
                    + (" ".join(m.get("flags") or []) or "verify before trusting."), pid)
        cands = m.get("candidates") or []
        if cands and status == "matched":
            finding("3d-ambiguous", subj, f"{cad} matches {pn}, but " + ", ".join(
                f"{_pn(c.get('mbom_part_number'))} ({c.get('description')})" for c in cands) + " sit in the same branch: verify which is current.", pid)
    for u in obj.get("unmatched_step") or []:
        cad = str(u.get("step_part_number") or "").strip() or str(u.get("step_name") or "").strip()
        k.db.execute("""INSERT INTO cad_link(source_id, part_id, cad_name, cad_label, cad_qty, status, confidence, quantity_match, members, flags)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (src, None, cad, u.get("step_name"), _qty(u.get("step_qty")), u.get("status") or "unmatched", 0, None, "[]",
                      json.dumps(u.get("flags") or [])))
        counts["links"] += 1
        finding("3d-unmatched", cad or "(no name)", f"3D item {cad or '(no part number)'} ({u.get('step_name')}, × {u.get('step_qty')}) has no MBOM line.")
    um = obj.get("unmatched_mbom") or []
    for n, u in enumerate(um, 1):
        pn = _pn(u.get("part_number"))
        if not pn:
            continue
        pid = part(pn, str(u.get("description") or "").replace("\n", " "))
        lvl = u.get("level_depth", u.get("level"))
        k.db.execute("""INSERT INTO bom_line(source_id, line, parent_id, child_id, find_no, level, quantity, unit, effectivity, make_buy)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (src, counts["lines"] + 1, None, pid, None if u.get("find_number") in (None, "---") else u.get("find_number"),
                      int(lvl) if str(lvl or "").isdigit() else None, _qty(u.get("qty")), u.get("unit_measure"), None, None))
        for key in ("equiv", "class", "authority", "amdt"):
            if u.get(key) not in (None, "", "."):
                k.db.execute("INSERT OR REPLACE INTO part_property(part_id, name, value, source_id) VALUES (?,?,?,?)",
                             (pid, f"MBOM {key}", str(u[key]), src))
        counts["lines"] += 1
    if um:
        finding("3d-mbom-only", doc, f"{len(um)} MBOM line(s) have no item in the 3D model (often process specifications, "
                "materials and alternates, which are not modelled).")
    k.db.commit()
    return {"imported": True, "dmc": doc, "title": f"3D ↔ MBOM reconciliation {doc}", "source_id": src, **counts}
