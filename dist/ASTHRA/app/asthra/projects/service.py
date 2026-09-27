from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..security.paths import confine
from ..storage.db import Database

_NAME = re.compile(r"^[\w .()\-]{1,120}$")


class ProjectError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectService:
    def __init__(self, db: Database, root: Path):
        self.db, self.root = db, root

    def create(self, name: str, description: str = "") -> dict:
        name = name.strip()
        if not _NAME.match(name):
            raise ProjectError("project name must be 1–120 letters, digits, spaces, . ( ) - _")
        pid = uuid.uuid4().hex
        path = confine(self.root, pid)
        for sub in ("sources", "working", "revisions", "exports", "reports"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        with self.db.tx() as c:
            c.execute("INSERT INTO project VALUES (?,?,?,?,?)", (pid, name, description, str(path), now()))
            c.execute("INSERT INTO audit_event(at,actor,action,subject,detail_json) VALUES (?,?,?,?,?)",
                      (now(), "local", "project.create", pid, json.dumps({"name": name})))
        return self.get(pid)

    def get(self, pid: str) -> dict:
        r = self.db.one("SELECT * FROM project WHERE id=?", (pid,))
        if not r:
            raise ProjectError(f"no such project: {pid}")
        d = dict(r)
        d["document_count"] = self.db.one("SELECT COUNT(*) n FROM document WHERE project_id=?", (pid,))["n"]
        return d

    def list(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM project ORDER BY created_at")]
