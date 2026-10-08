"""The knowledge store (SQLite) and the questions it answers across the S-Series.

Three questions prove the model is one brain rather than several files:
  impact_of_part     what depends on a part: tasks, subtasks, data modules, IPC lines, breakdown,
                     supersession, training (e.g. "BP-0001 is replaced by BP-0002 — what changes?")
  procedure_requirements
                     an S1000D procedure's preliminary requirements and steps, derived from the
                     S3000L task analysis (persons, skill, trade, support equipment, supplies, spares…)
  consistency        findings where sources disagree (maintenance level in LSA vs data module,
                     subtask durations vs estimated time, superseded parts still used …)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .identity import normalize_part_number

SCHEMA = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeStore:
    def __init__(self, path: Path | str = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))
        # columns added after a table first shipped
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(cad_model)")}
        if "source_id" not in cols:
            self.db.execute("ALTER TABLE cad_model ADD COLUMN source_id INTEGER REFERENCES source(id)")
            self.db.commit()

    # ---------------------------------------------------------------- writing
    def source(self, kind: str, document: str, issue: str = "", schema: str = "", note: str = "") -> int:
        cur = self.db.execute("INSERT INTO source(kind, document, issue, schema, imported_at, note) VALUES (?,?,?,?,?,?)",
                              (kind, document, issue, schema, _now(), note))
        return cur.lastrowid

    def part(self, part_number: str, manufacturer_code: str = "", name: str = "", part_type: str = "part",
             source_id: int | None = None, layer: str = "shared", **extra) -> int:
        key = normalize_part_number(part_number)
        mfr = (manufacturer_code or "").strip().upper()
        row = self.db.execute("SELECT id FROM part WHERE manufacturer_code=? AND part_number_key=? AND layer=?",
                              (mfr, key, layer)).fetchone()
        if row:
            return row["id"]
        cols = {"manufacturer_code": mfr, "part_number": part_number, "part_number_key": key, "name": name,
                "part_type": part_type, "source_id": source_id, "layer": layer, **extra}
        cur = self.db.execute(f"INSERT INTO part({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        return cur.lastrowid

    def part_id(self, part_number: str, manufacturer_code: str | None = None) -> int:
        key = normalize_part_number(part_number)
        q, args = "SELECT id FROM part WHERE part_number_key=?", [key]
        if manufacturer_code is not None:
            q += " AND manufacturer_code=?"
            args.append(manufacturer_code.upper())
        rows = self.db.execute(q, args).fetchall()
        if len(rows) != 1:
            raise KeyError(f"part {part_number!r}: {len(rows)} matches")
        return rows[0]["id"]

    def add(self, table: str, **cols) -> None:
        self.db.execute(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        tuple(cols.values()))

    # ---------------------------------------------------------------- questions
    def impact_of_part(self, part_number: str) -> dict:
        pid = self.part_id(part_number)
        q = lambda sql, *a: [dict(r) for r in self.db.execute(sql, a).fetchall()]
        tasks = q("""SELECT DISTINCT t.id, t.revision, t.name FROM task t
                     LEFT JOIN task_resource r ON r.task_id=t.id AND r.task_revision=t.revision
                     WHERE t.part_id=? OR r.part_id=?""", pid, pid)
        dmcs = set()
        for t in tasks:
            dmcs |= {r["dm_ref"] for r in q("SELECT dm_ref FROM subtask WHERE task_id=? AND task_revision=? AND dm_ref IS NOT NULL",
                                              t["id"], t["revision"])}
            dmcs |= {r["dmc"] for r in q("SELECT dmc FROM information_link WHERE target_kind='task' AND target_id=?", t["id"])}
        beis = [r["bei"] for r in q("SELECT bei FROM breakdown_realization WHERE part_id=?", pid)]
        for b in beis:
            dmcs |= {r["dmc"] for r in q("SELECT dmc FROM information_item WHERE bei=?", b)}
        return {
            "part": part_number,
            "breakdown_elements": beis,
            "tasks": tasks,
            "data_modules": sorted(dmcs),
            "catalogue": q("""SELECT figure, item, indenture, qty_per_next_assy, smr_code FROM catalogue_item
                              WHERE part_id=? ORDER BY figure, item""", pid),
            "used_in": q("""SELECT p.part_number, e.quantity FROM part_list_entry e JOIN part p ON p.id=e.parent_id
                            WHERE e.child_id=?""", pid),
            "superseded_by": q("""SELECT p.part_number, s.change_id, s.interchangeability FROM part_supersession s
                                  JOIN part p ON p.id=s.new_part_id WHERE s.old_part_id=?""", pid),
            "training": q("""SELECT DISTINCT n.task_id, n.objective FROM training_need n
                             WHERE n.task_id IN (SELECT id FROM task WHERE part_id=?)""", pid),
        }

    def procedure_requirements(self, task_id: str, revision: str = "1.0") -> dict:
        """What the S1000D procedure for this task must contain, from the S3000L task analysis."""
        t = self.db.execute("SELECT * FROM task WHERE id=? AND revision=?", (task_id, revision)).fetchone()
        if not t:
            raise KeyError(f"task {task_id} revision {revision}")
        subs = [dict(r) for r in self.db.execute(
            "SELECT * FROM subtask WHERE task_id=? AND task_revision=? ORDER BY seq", (task_id, revision))]
        res = lambda kind: [f"{r['name'] or r['description']} ({r['part_number']})" for r in self.db.execute(
            """SELECT p.name, p.part_number, r.description FROM task_resource r LEFT JOIN part p ON p.id=r.part_id
               WHERE r.task_id=? AND r.task_revision=? AND r.kind=? ORDER BY p.part_number""", (task_id, revision, kind))]
        stmts = lambda kind: [r["text"] for r in self.db.execute(
            "SELECT text FROM safety_statement WHERE task_id=? AND kind=? ORDER BY id", (task_id, kind))]
        return {
            "task": f"{task_id} rev {revision} — {t['name']}",
            "maintenance_level": t["maintenance_level"],
            "persons": max((s["persons"] or 0) for s in subs) if subs else None,
            "skill_levels": sorted({s["skill_level"] for s in subs if s["skill_level"]}),
            "trades": sorted({s["trade"] for s in subs if s["trade"]}),
            "duration_minutes": sum(s["duration_minutes"] or 0 for s in subs),
            "support_equipment": res("support-equipment"),
            "supplies": res("consumable"),
            "spares": res("spare"),
            "conditions": stmts("condition"),
            "warnings": stmts("warning"),
            "cautions": stmts("caution"),
            "steps": [f"{s['description']}" + (f" (refer to {s['dm_ref']})" if s["dm_ref"] else "") for s in subs],
        }

    def consistency(self) -> list[dict]:
        out: list[dict] = []
        def find(rule, subject, message, **values):
            out.append({"rule": rule, "subject": subject, "message": message, "values": values})
        # 1. what a data module states vs the LSA task it documents
        for r in self.db.execute("""SELECT l.dmc, t.id, t.revision, t.maintenance_level,
                                           (SELECT value FROM information_property WHERE dmc=l.dmc AND name='maintenance_level') AS dm_ml,
                                           (SELECT value FROM information_property WHERE dmc=l.dmc AND name='estimated_minutes') AS dm_min,
                                           (SELECT SUM(duration_minutes) FROM subtask s WHERE s.task_id=t.id AND s.task_revision=t.revision) AS lsa_min
                                    FROM information_link l JOIN task t ON t.id=l.target_id
                                    WHERE l.target_kind='task'
                                      AND t.revision=(SELECT MAX(revision) FROM task WHERE id=t.id)"""):
            if r["dm_ml"] and r["maintenance_level"] and r["dm_ml"] != r["maintenance_level"]:
                find("maintenance-level", f"{r['id']} / {r['dmc']}",
                     f"Task {r['id']} rev {r['revision']} is at {r['maintenance_level']} in the LSA, but data module "
                     f"{r['dmc']} says {r['dm_ml']}.", lsa=r["maintenance_level"], dm=r["dm_ml"])
            if r["dm_min"] and r["lsa_min"] and abs(float(r["dm_min"]) - float(r["lsa_min"])) > 0.01:
                find("task-duration", f"{r['id']} / {r['dmc']}",
                     f"Subtask durations of {r['id']} rev {r['revision']} add up to {r['lsa_min']:g} min, but data module "
                     f"{r['dmc']} states {float(r['dm_min']):g} min.", lsa=r["lsa_min"], dm=float(r["dm_min"]))
        # 2. the newest revision of a task still uses a superseded part
        for r in self.db.execute("""SELECT t.id, t.revision, p.part_number, n.part_number AS new_pn, s.change_id
                                    FROM task t JOIN task_resource r ON r.task_id=t.id AND r.task_revision=t.revision
                                    JOIN part_supersession s ON s.old_part_id=r.part_id
                                    JOIN part p ON p.id=s.old_part_id JOIN part n ON n.id=s.new_part_id
                                    WHERE t.revision=(SELECT MAX(revision) FROM task WHERE id=t.id)"""):
            find("superseded-part", f"{r['id']} rev {r['revision']}",
                 f"Task {r['id']} rev {r['revision']} still uses {r['part_number']}, superseded by {r['new_pn']} ({r['change_id']}).")
        # 3. a subtask refers to a data module the library does not know
        for r in self.db.execute("""SELECT DISTINCT s.task_id, s.dm_ref FROM subtask s
                                    WHERE s.dm_ref IS NOT NULL AND s.dm_ref NOT IN (SELECT dmc FROM information_item)"""):
            find("unknown-data-module", r["dm_ref"], f"Task {r['task_id']} refers to {r['dm_ref']}, which is not in the library.")
        # 4. sources describing the same parts list or structure disagree (ATA IPL, S1000D IPD, S2000M, engineering BOM)
        from .crosscheck import check
        out.extend(check(self.db))
        return out

    def record_findings(self, findings: list[dict]) -> None:
        for f in findings:
            self.db.execute("INSERT INTO finding(rule, subject, message, values_json, found_at) VALUES (?,?,?,?,?)",
                            (f["rule"], f["subject"], f["message"], json.dumps(f["values"]), _now()))
