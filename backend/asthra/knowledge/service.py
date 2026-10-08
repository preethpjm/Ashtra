"""Knowledge library service: the shared library in the data folder, imports, and the screen's queries."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..identify.service import parse_xml
from .ata_import import import_manual
from .engineering import import_bom
from .s1000d_import import import_dm
from .models import glb_node_names, node_shows
from .s2000m_import import import_exchange
from .store import KnowledgeStore

TABLES = {"parts": "part", "breakdown elements": "breakdown_element", "tasks": "task", "data modules": "information_item",
          "catalogue lines": "catalogue_item", "task requirements": "task_requirement", "warnings and cautions": "safety_statement",
          "organisations": "organization", "events": "event", "design changes": "design_change",
          "BOM lines": "bom_line", "service bulletins": "service_bulletin", "sources": "source"}


class KnowledgeService:
    def __init__(self, settings, documents, projects):
        self.store = KnowledgeStore(settings.knowledge_db)
        self.models_dir = Path(settings.knowledge_db).parent / "models"
        self.documents, self.projects = documents, projects
        self.lock = threading.Lock()

    def _rows(self, sql, *args):
        return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]

    # ---------------------------------------------------------------- overview
    def summary(self) -> dict:
        with self.lock:
            counts = {label: self.store.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for label, t in TABLES.items()}
            sources = self._rows("SELECT kind, COUNT(*) AS n, MAX(imported_at) AS last FROM source GROUP BY kind ORDER BY kind")
            findings = len(self.store.consistency())
        return {"counts": counts, "sources": sources, "findings": findings}

    # ---------------------------------------------------------------- imports
    def import_project(self, pid: str, include_invalid: bool = False) -> dict:
        """Every document of the project that ASTHRA can read facts from: S1000D data modules, ATA manuals
        (SGML or XML) and S2000M provisioning data. Documents whose structure did not pass are skipped."""
        from lxml import etree
        from ..render.profiles import ATA_ROOTS
        report = {"imported": [], "skipped": []}
        for d in self.documents.list(pid):
            name = d.get("original_name") or d["id"]
            if d.get("syntax") not in ("xml", "sgml"):
                report["skipped"].append({"file": name, "reason": "not XML or SGML"})
                continue
            rep = self.documents.validate(d["id"])
            status = rep.structural_status.value
            if d.get("syntax") == "sgml":
                if not rep.rendered_xml:
                    report["skipped"].append({"file": name, "reason": "SGML could not be read (is OpenSP installed and the DTD package?)"})
                    continue
                root = etree.fromstring(rep.rendered_xml.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
            else:
                data, _ = self.documents.current_bytes(d["id"])
                tree, _ = parse_xml(data)
                if tree is None:
                    report["skipped"].append({"file": name, "reason": "could not be read"})
                    continue
                root = tree.getroot()
            local = etree.QName(root).localname
            kind = ("s1000d" if local == "dmodule" else "ata" if local.lower() in ATA_ROOTS
                    else "s2000m" if local == "provisioningExchange" or (d.get("package_id") or "").startswith("s2000m") else "")
            if not kind:
                report["skipped"].append({"file": name, "reason": f"<{local}> is not a document ASTHRA reads facts from yet"})
                continue
            if status == "failed" and not include_invalid:
                report["skipped"].append({"file": name, "reason": "structure failed: fix it first"})
                continue
            with self.lock:
                if kind == "s1000d":
                    res = import_dm(self.store, root, schema=d.get("package_id") or "", file=name)
                elif kind == "ata":
                    res = import_manual(self.store, root, schema=d.get("package_id") or "", file=name)
                else:
                    res = import_exchange(self.store, root, schema=d.get("package_id") or "", file=name)
            res["kind"] = {"s1000d": "S1000D", "ata": "ATA iSpec 2200", "s2000m": "S2000M"}[kind]
            if d.get("syntax") == "sgml" and rep.rendered_preview:
                res["note"] = "read without its DTD: structure approximate"
            elif status != "passed":
                res["note"] = "not validated: no installed schema covers it"
            (report["imported"] if res.get("imported") else report["skipped"]).append({"file": name, **res})
        return report

    ENG_TABLE = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm")

    def import_engineering_set(self, files: list[tuple[str, bytes]]) -> dict:
        """Several engineering files at once, e.g. the folder the STEP→GLB / MBOM tool writes: BOMs (CSV, Excel)
        first, then JSON (reconciliation or engineering BOM), then 3D models (GLB). A model is coloured by the
        reconciliation imported with it. A .zip is opened and read the same way. Other files are listed as skipped."""
        import io
        import zipfile
        flat: list[tuple[str, bytes]] = []
        report = {"imported": [], "skipped": []}
        for name, data in files:
            if name.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        for info in z.infolist():
                            if not info.is_dir() and not info.filename.startswith("__MACOSX/") and info.file_size < 2_000_000_000:
                                flat.append((f"{name}/{info.filename}", z.read(info)))
                except zipfile.BadZipFile:
                    report["skipped"].append({"file": name, "reason": "not a readable zip"})
            else:
                flat.append((name, data))
        base = lambda n: n.replace("\\", "/").rsplit("/", 1)[-1]
        rank = lambda n: 0 if n.lower().endswith(self.ENG_TABLE) else 1 if n.lower().endswith(".json") else 2 if n.lower().endswith(".glb") else 3
        recon: list[int] = []
        for name, data in sorted(flat, key=lambda f: (rank(f[0]), f[0])):
            short = base(name)
            low = short.lower()
            try:
                if low.endswith(self.ENG_TABLE) or low.endswith(".json"):
                    with self.lock:
                        res = import_bom(self.store, data, short)
                    if res.get("source_id"):
                        recon.append(res["source_id"])
                    res.pop("source_id", None)
                    report["imported"].append({"file": name, "kind": "3D ↔ MBOM reconciliation" if res.get("links") is not None else "Engineering BOM", **res})
                elif low.endswith(".glb"):
                    m = self.add_model(short, data, source_id=recon[-1] if len(recon) == 1 else None)
                    report["imported"].append({"file": name, "kind": "3D model", "dmc": m["name"], "title": m["name"],
                                               "nodes": m["nodes"], "linked": m["linked"]})
                else:
                    why = ("a STEP model: import the GLB the reconciliation tool made from it" if low.endswith((".stp", ".step"))
                           else "not engineering data ASTHRA reads (BOM as CSV / Excel / JSON, reconciliation JSON, GLB)")
                    report["skipped"].append({"file": name, "reason": why})
            except (ValueError, UnicodeDecodeError) as e:
                report["skipped"].append({"file": name, "reason": f"could not be read: {e}"})
        return report

    def import_engineering(self, filename: str, data: bytes) -> dict:
        """An engineering BOM (CSV, Excel or JSON) from PLM / ERP / CAD."""
        with self.lock:
            res = import_bom(self.store, data, filename)
        return {"imported": [{"file": filename, "kind": "Engineering BOM", **res}], "skipped": []}

    def load_bike_example(self) -> dict:
        from .examples.bike_uf2024 import load
        with self.lock:
            if self.store.db.execute("SELECT COUNT(*) FROM source WHERE note='UF2024 Bike example'").fetchone()[0]:
                return {"loaded": False, "reason": "already in the library"}
            load(self.store)
        return {"loaded": True}

    def reset(self) -> None:
        with self.lock:
            tables = [r[0] for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.store.db.execute("PRAGMA foreign_keys = OFF")
            for t in tables:
                if t != "layer":
                    self.store.db.execute(f"DELETE FROM {t}")
            self.store.db.execute("PRAGMA foreign_keys = ON")
            self.store.db.commit()
        if self.models_dir.is_dir():
            for f in self.models_dir.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)

    # ---------------------------------------------------------------- lists and details
    def parts(self, q: str = "", kind: str = "") -> list[dict]:
        like = f"%{q.strip()}%"
        types = {"support-equipment": ("support-equipment",), "consumable": ("consumable",),
                 "spare": ("part", "component")}.get(kind)
        sql = """SELECT p.id, p.part_number, p.manufacturer_code, p.name, p.part_type,
                   (SELECT COUNT(*) FROM (SELECT task_id AS t FROM task_resource WHERE part_id=p.id
                                          UNION SELECT id FROM task WHERE part_id=p.id)) AS tasks,
                   (SELECT COUNT(DISTINCT dmc) FROM information_resource r WHERE r.part_id=p.id) AS data_modules,
                   (SELECT COUNT(*) FROM catalogue_item c WHERE c.part_id=p.id) AS catalogue,
                   (SELECT n.part_number FROM part_supersession s JOIN part n ON n.id=s.new_part_id WHERE s.old_part_id=p.id LIMIT 1) AS superseded_by,
                   (SELECT kind || ' · ' || document FROM source WHERE id=p.source_id) AS source
                 FROM part p WHERE (p.part_number LIKE ? OR p.name LIKE ?)"""
        args = [like, like]
        if types:
            sql += f" AND p.part_type IN ({','.join('?' * len(types))})"
            args += list(types)
        with self.lock:
            return self._rows(sql + " ORDER BY p.part_number LIMIT 500", *args)

    def part_detail(self, part_id: int) -> dict:
        with self.lock:
            p = self._rows("""SELECT p.*, s.kind AS source_kind, s.document AS source_document FROM part p
                              LEFT JOIN source s ON s.id=p.source_id WHERE p.id=?""", part_id)
            if not p:
                raise KeyError(part_id)
            imp = self.store.impact_of_part(p[0]["part_number"]) if self._unique_pn(p[0]["part_number"]) else {}
            imp["required_by_dms"] = self._rows("""SELECT DISTINCT r.dmc, r.kind, i.title FROM information_resource r
                                                   LEFT JOIN information_item i ON i.dmc=r.dmc WHERE r.part_id=?""", part_id)
            # the same part number from every source (with or without a CAGE): parts lists, BOM, engineering attributes
            key = p[0]["part_number_key"]
            same = "SELECT id FROM part WHERE part_number_key=?"
            imp["same_number"] = self._rows("""SELECT p.id, p.manufacturer_code, p.name, s.kind, s.document FROM part p
                                               LEFT JOIN source s ON s.id=p.source_id WHERE p.part_number_key=? AND p.id<>?""", key, part_id)
            imp["catalogue_lines"] = self._rows(f"""SELECT s.kind, s.document, c.figure, c.item, c.item_variant, c.indenture,
                                                    c.qty_per_next_assy, c.usable_on_code FROM catalogue_item c JOIN source s ON s.id=c.source_id
                                                    WHERE c.part_id IN ({same}) ORDER BY s.kind, c.figure, c.item""", key)
            imp["contains"] = self._rows(f"""SELECT c.part_number, c.name, MAX(e.quantity) AS quantity FROM part_list_entry e
                                             JOIN part c ON c.id=e.child_id WHERE e.parent_id IN ({same})
                                             GROUP BY c.part_number_key ORDER BY c.part_number""", key)
            imp["used_in"] = self._rows(f"""SELECT a.part_number, MAX(e.quantity) AS quantity FROM part_list_entry e
                                            JOIN part a ON a.id=e.parent_id WHERE e.child_id IN ({same})
                                            GROUP BY a.part_number_key ORDER BY a.part_number""", key)
            imp["properties"] = self._rows(f"""SELECT pp.name, pp.value, s.document FROM part_property pp JOIN source s ON s.id=pp.source_id
                                               WHERE pp.part_id IN ({same}) ORDER BY pp.name""", key)
            imp["cad"] = self._rows(f"""SELECT l.cad_name, l.cad_label, l.cad_qty, l.status, l.confidence, l.quantity_match, l.flags, s.document
                                        FROM cad_link l JOIN source s ON s.id=l.source_id WHERE l.part_id IN ({same})""", key)
            res = {"part": p[0], "impact": imp}
        res["models"] = self.locate(p[0]["part_number"])
        return res

    def _unique_pn(self, pn: str) -> bool:
        from .identity import normalize_part_number
        return self.store.db.execute("SELECT COUNT(*) FROM part WHERE part_number_key=?", (normalize_part_number(pn),)).fetchone()[0] == 1

    def breakdown(self) -> list[dict]:
        with self.lock:
            return self._rows("""SELECT b.bei, b.revision, b.name, b.be_type, b.parent_bei, b.lsa_candidate,
                                   (SELECT GROUP_CONCAT(p.part_number || CASE WHEN r.applicability IS NOT NULL THEN ' (' || r.applicability || ')' ELSE '' END, ', ')
                                    FROM breakdown_realization r JOIN part p ON p.id=r.part_id WHERE r.bei=b.bei) AS parts,
                                   (SELECT COUNT(*) FROM information_item i WHERE i.bei=b.bei) AS data_modules,
                                   (SELECT COUNT(*) FROM task t WHERE t.bei=b.bei) AS tasks
                                 FROM breakdown_element b ORDER BY b.bei""")

    def tasks(self) -> list[dict]:
        with self.lock:
            return self._rows("""SELECT t.id, t.revision, t.name, t.task_type, t.bei, t.maintenance_level,
                                   (SELECT COUNT(*) FROM subtask s WHERE s.task_id=t.id AND s.task_revision=t.revision) AS subtasks,
                                   (SELECT GROUP_CONCAT(requirement_id, ', ') FROM task_covers c WHERE c.task_id=t.id) AS requirements,
                                   (SELECT kind || ' · ' || document FROM source WHERE id=t.source_id) AS source
                                 FROM task t ORDER BY t.id, t.revision""")

    def task_detail(self, task_id: str, revision: str) -> dict:
        with self.lock:
            pre = self.store.procedure_requirements(task_id, revision)
            docs = self._rows("SELECT l.dmc, i.title FROM information_link l LEFT JOIN information_item i ON i.dmc=l.dmc "
                              "WHERE l.target_kind='task' AND l.target_id=?", task_id)
            return {"procedure": pre, "documented_by": docs}

    def data_modules(self, q: str = "") -> list[dict]:
        like = f"%{q.strip()}%"
        with self.lock:
            return self._rows("""SELECT i.dmc, i.issue, i.title, i.info_code, i.bei,
                                   (SELECT COUNT(*) FROM information_resource r WHERE r.dmc=i.dmc) AS resources,
                                   (SELECT COUNT(*) FROM safety_statement w WHERE w.dmc=i.dmc) AS safety,
                                   (SELECT COUNT(*) FROM information_ref f WHERE f.dmc=i.dmc) AS refs,
                                   (SELECT kind || ' · ' || COALESCE(note, document) FROM source WHERE id=i.source_id) AS source
                                 FROM information_item i WHERE i.dmc LIKE ? OR i.title LIKE ? ORDER BY i.dmc LIMIT 1000""", like, like)

    def data_module_detail(self, dmc: str) -> dict:
        with self.lock:
            item = self._rows("SELECT * FROM information_item WHERE dmc=?", dmc)
            if not item:
                raise KeyError(dmc)
            return {
                "item": item[0],
                "properties": self._rows("SELECT name, value FROM information_property WHERE dmc=?", dmc),
                "resources": self._rows("""SELECT r.kind, r.name, r.quantity, r.unit, p.id AS part_id, p.part_number, p.manufacturer_code
                                           FROM information_resource r LEFT JOIN part p ON p.id=r.part_id WHERE r.dmc=? ORDER BY r.kind""", dmc),
                "safety": self._rows("SELECT kind, text FROM safety_statement WHERE dmc=? ORDER BY id", dmc),
                "references": self._rows("""SELECT f.ref_dmc, i.title FROM information_ref f LEFT JOIN information_item i ON i.dmc=f.ref_dmc
                                            WHERE f.dmc=?""", dmc),
                "referenced_by": self._rows("""SELECT f.dmc, i.title FROM information_ref f LEFT JOIN information_item i ON i.dmc=f.dmc
                                               WHERE f.ref_dmc=?""", dmc) +
                                 self._rows("SELECT DISTINCT 'task ' || task_id || ' rev ' || task_revision AS dmc, description AS title "
                                            "FROM subtask WHERE dm_ref=?", dmc),
                "documents": self._rows("""SELECT l.target_kind AS kind, l.target_id AS id, t.revision, t.name FROM information_link l
                                           LEFT JOIN task t ON l.target_kind='task' AND t.id=l.target_id
                                             AND t.revision=(SELECT MAX(revision) FROM task WHERE id=l.target_id)
                                           WHERE l.dmc=?""", dmc),
                "breakdown": self._rows("SELECT bei, name, be_type FROM breakdown_element WHERE bei=?", item[0]["bei"]),
                "catalogue": self._rows("""SELECT c.figure, c.item, c.indenture, c.qty_per_next_assy, p.part_number, p.name
                                           FROM catalogue_item c JOIN part p ON p.id=c.part_id WHERE c.bei=? ORDER BY c.figure, c.item""", item[0]["bei"])
                             if item[0]["info_code"].startswith("94") else [],
            }

    def findings(self) -> list[dict]:
        with self.lock:
            return self.store.consistency()

    def sources(self) -> list[dict]:
        with self.lock:
            return self._rows("SELECT id, kind, document, issue, schema, imported_at, note FROM source ORDER BY imported_at DESC LIMIT 500")

    # ---------------------------------------------------------------- 3D models (GLB)
    def add_model(self, filename: str, data: bytes, source_id: int | None = None) -> dict:
        names = glb_node_names(data)            # raises ValueError for anything that is not a GLB
        self.models_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "model.glb"
        with self.lock:
            cur = self.store.db.execute("INSERT INTO cad_model(name, file, nodes, bytes, imported_at, source_id) VALUES (?,?,?,?,?,?)",
                                        (Path(filename).stem, "", len(names), len(data), datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                         source_id))
            mid = cur.lastrowid
            file = f"{mid}-{safe}"
            (self.models_dir / file).write_bytes(data)
            self.store.db.execute("UPDATE cad_model SET file=? WHERE id=?", (file, mid))
            self.store.db.executemany("INSERT INTO cad_node(model_id, idx, name) VALUES (?,?,?)",
                                      [(mid, i, n) for i, n in enumerate(names) if n])
            self.store.db.commit()
        status = self.model_status(mid)
        return {"id": mid, "name": Path(filename).stem, "nodes": len(names), "linked": sum(1 for v in status.values() if v.get("part_id"))}

    def models(self) -> list[dict]:
        with self.lock:
            return self._rows("""SELECT m.id, m.name, m.nodes, m.bytes, m.imported_at, s.document AS reconciliation
                                 FROM cad_model m LEFT JOIN source s ON s.id=m.source_id ORDER BY m.id DESC""")

    def model_path(self, mid: int) -> Path:
        with self.lock:
            r = self.store.db.execute("SELECT file FROM cad_model WHERE id=?", (mid,)).fetchone()
        if not r or not (self.models_dir / r["file"]).is_file():
            raise KeyError(mid)
        return self.models_dir / r["file"]

    def delete_model(self, mid: int) -> None:
        p = None
        try:
            p = self.model_path(mid)
        except KeyError:
            pass
        with self.lock:
            self.store.db.execute("DELETE FROM cad_node WHERE model_id=?", (mid,))
            self.store.db.execute("DELETE FROM cad_model WHERE id=?", (mid,))
            self.store.db.commit()
        if p:
            p.unlink(missing_ok=True)

    def _candidates(self, source_id: int | None = None) -> list[dict]:
        """Everything a node name can show: reconciliation links (3D name → part, with status) — only those of the
        reconciliation imported with the model, when there is one — and part numbers."""
        q = """SELECT l.cad_name, l.members, l.status, l.quantity_match, l.confidence, l.part_id, p.part_number, p.name
               FROM cad_link l LEFT JOIN part p ON p.id=l.part_id"""
        links = self._rows(q + " WHERE l.source_id=?", source_id) if source_id else self._rows(q)
        out = []
        for l in links:
            names = [l["cad_name"]] + [m for m in json.loads(l["members"] or "[]") if m != l["cad_name"]]
            status = ("unmatched" if not l["part_id"] else "quantity" if l["quantity_match"] == 0
                      else "fuzzy" if l["status"] != "matched" else "matched")
            out += [{"name": n, "status": status, "part_id": l["part_id"], "part_number": l["part_number"], "part_name": l["name"]}
                    for n in names if n]
        return out

    def model_status(self, mid: int) -> dict:
        """node name -> {status, part_id, part_number} for every node of the model that shows something known."""
        with self.lock:
            nodes = [r[0] for r in self.store.db.execute("SELECT DISTINCT name FROM cad_node WHERE model_id=?", (mid,))]
            row = self.store.db.execute("SELECT source_id FROM cad_model WHERE id=?", (mid,)).fetchone()
            cands = self._candidates(row["source_id"] if row else None)
            parts = self._rows("SELECT id, part_number, name FROM part WHERE length(part_number) >= 4")
        out = {}
        for n in nodes:
            hit = next((c for c in cands if node_shows(n, c["name"])), None)
            if hit:
                out[n] = {"status": hit["status"], "part_id": hit["part_id"], "part_number": hit["part_number"], "name": hit["part_name"]}
                continue
            p = next((p for p in parts if node_shows(n, p["part_number"])), None)
            if p:
                out[n] = {"status": "linked", "part_id": p["id"], "part_number": p["part_number"], "name": p["name"]}
        return out

    def locate(self, pn: str) -> list[dict]:
        """The models (and their nodes) that show a part number: directly, or through the 3D ↔ MBOM links."""
        from .identity import normalize_part_number
        key = normalize_part_number(pn)
        with self.lock:
            names = {pn}
            for l in self._rows("""SELECT l.cad_name, l.members FROM cad_link l JOIN part p ON p.id=l.part_id
                                   WHERE p.part_number_key=?""", key):
                names.add(l["cad_name"])
                names.update(json.loads(l["members"] or "[]"))
            models = self._rows("SELECT id, name FROM cad_model ORDER BY id DESC")
            out = []
            for m in models:
                nodes = [r[0] for r in self.store.db.execute("SELECT DISTINCT name FROM cad_node WHERE model_id=?", (m["id"],))]
                hit = sorted({n for n in nodes if any(node_shows(n, c) for c in names if c)})
                if hit:
                    out.append({"model_id": m["id"], "model": m["name"], "nodes": hit})
        return out
