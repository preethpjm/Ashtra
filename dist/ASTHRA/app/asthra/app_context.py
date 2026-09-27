"""Wires services together. One instance per data root."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .documents.service import DocumentService
from .projects.service import ProjectService
from .registry.service import SchemaRegistry
from .storage.db import Database


@dataclass
class AppContext:
    settings: Settings
    db: Database
    registry: SchemaRegistry
    projects: ProjectService
    documents: DocumentService

    @classmethod
    def open(cls, settings: Settings) -> "AppContext":
        settings.ensure()
        db = Database(settings.db_path)
        registry = SchemaRegistry(db, settings.registry_root)
        projects = ProjectService(db, settings.projects_root)
        documents = DocumentService(db, projects, registry, settings.max_import_bytes)
        return cls(settings, db, registry, projects, documents)

    def close(self) -> None:
        self.db.close()
