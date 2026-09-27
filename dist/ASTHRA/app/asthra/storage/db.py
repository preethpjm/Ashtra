"""SQLite persistence with forward-only, numbered migrations.

Milestone 1 tables cover projects, immutable sources, documents, schema packages
and validation history. Later milestones append migrations (canonical entities,
relationships, revisions, mappings) without editing earlier ones.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: list[str] = [
    # 0001 — Milestone 1 core
    """
    CREATE TABLE project (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        root_path TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE schema_package (
        id TEXT PRIMARY KEY,                 -- e.g. s1000d/synthetic-5.0-subset/asthra-fixture
        standard TEXT NOT NULL,
        issue TEXT NOT NULL,
        name TEXT NOT NULL,
        provenance TEXT NOT NULL,            -- official | oem | synthetic
        install_path TEXT NOT NULL,
        checksum TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        installed_at TEXT NOT NULL
    );
    CREATE INDEX ix_pkg_standard ON schema_package(standard, issue);
    CREATE TABLE source_file (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES project(id),
        original_name TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        blob_path TEXT NOT NULL,             -- relative to project root, read-only
        imported_at TEXT NOT NULL,
        UNIQUE(project_id, sha256)
    );
    CREATE TABLE document (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES project(id),
        source_file_id TEXT NOT NULL REFERENCES source_file(id),
        syntax TEXT NOT NULL,                -- xml | sgml | unknown
        standard TEXT,
        issue TEXT,
        doc_type TEXT,
        package_id TEXT REFERENCES schema_package(id),
        identity_json TEXT NOT NULL DEFAULT '{}',
        identification_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE TABLE validation_run (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES document(id),
        package_id TEXT,
        package_checksum TEXT,
        started_at TEXT NOT NULL,
        structural_status TEXT NOT NULL,     -- see validation.model.Status
        business_rule_status TEXT NOT NULL,
        reference_status TEXT NOT NULL,
        engineering_status TEXT NOT NULL,
        summary_json TEXT NOT NULL
    );
    CREATE TABLE diagnostic (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES validation_run(id),
        stage INTEGER NOT NULL,
        severity TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        source_file TEXT,
        element_path TEXT,
        line INTEGER,
        col INTEGER,
        message TEXT NOT NULL,
        suggestion TEXT,
        reference TEXT
    );
    CREATE TABLE audit_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        subject TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}'
    );
    """,
    # 0002 — Milestone 2: working copies and committed revisions
    """
    CREATE TABLE working_copy (
        document_id TEXT PRIMARY KEY REFERENCES document(id),
        rel_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        based_on_revision TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE revision (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES document(id),
        number INTEGER NOT NULL,
        parent_id TEXT REFERENCES revision(id),
        rel_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        structural_status TEXT NOT NULL,
        validation_run_id TEXT REFERENCES validation_run(id),
        created_at TEXT NOT NULL,
        UNIQUE(document_id, number)
    );
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
            done = {r[0] for r in self._conn.execute("SELECT version FROM schema_migrations")}
            for i, sql in enumerate(MIGRATIONS, start=1):
                if i in done:
                    continue
                # executescript manages its own transaction; keep the migration
                # and its version record atomic inside one script.
                script = f"BEGIN;\n{sql}\nINSERT INTO schema_migrations(version) VALUES ({i});\nCOMMIT;"
                try:
                    self._conn.executescript(script)
                except Exception:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise

    @contextmanager
    def tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params))

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        self._conn.close()
