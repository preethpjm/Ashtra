"""Knowledge library service: the shared library in the data folder, imports, and the screen's queries."""
from __future__ import annotations

import threading

from ..identify.service import parse_xml
from .s1000d_import import import_dm
from .store import KnowledgeStore

TABLES = {"parts": "part", "breakdown elements": "breakdown_element", "tasks": "task", "data modules": "information_item",
          "catalogue lines": "catalogue_item", "task requirements": "task_requirement", "warnings and cautions": "safety_statement",
          "organisations": "organization", "events": "event", "design changes": "design_change", "sources": "source"}


class KnowledgeService:
    def __init__(self, settings, documents, projects):
        self.store = KnowledgeStore(settings.knowledge_db)
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
        report = {"imported": [], "skipped": []}
        for d in self.documents.list(pid):
            name = d.get("original_name") or d["id"]
            if d.get("syntax") != "xml":
                report["skipped"].append({"file": name, "reason": "not XML (SGML is imported in a later step)"})
                continue
            ident = d.get("identification") or {}
            std = (d.get("package_id") or "").split("/")[0]
            if std != "s1000d":
                report["skipped"].append({"file": name, "reason": "not an identified S1000D data module"})
                continue
            rep = self.documents.validate(d["id"])
            if rep.structural_status.value != "passed" and not include_invalid:
                report["skipped"].append({"file": name, "reason": f"structure {rep.structural_status.value}: fix it first"})
                continue
            data, _ = self.documents.current_bytes(d["id"])
            tree, _ = parse_xml(data)
            if tree is None:
                report["skipped"].append({"file": name, "reason": "could not be read"})
                continue
            with self.lock:
                res = import_dm(self.store, tree.getroot(), schema=d.get("package_id") or "", file=name)
            (report["imported"] if res.get("imported") else report["skipped"]).append({"file": name, **res})
        return report

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
            imp["contains"] = self._rows("""SELECT c.part_number, c.name, e.quantity FROM part_list_entry e
                                            JOIN part c ON c.id=e.child_id WHERE e.parent_id=?""", part_id)
            return {"part": p[0], "impact": imp}

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
