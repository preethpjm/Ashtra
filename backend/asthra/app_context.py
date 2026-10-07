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
    knowledge: "KnowledgeService"

    @classmethod
    def open(cls, settings: Settings) -> "AppContext":
        settings.ensure()
        db = Database(settings.db_path)
        registry = SchemaRegistry(db, settings.registry_root)
        from .brex.library import BrexLibrary
        registry.brex = BrexLibrary(settings.data_root / "brex")      # business rules travel with the schemas
        projects = ProjectService(db, settings.projects_root)
        documents = DocumentService(db, projects, registry, settings.max_import_bytes)
        from .knowledge.service import KnowledgeService
        knowledge = KnowledgeService(settings, documents, projects)
        return cls(settings, db, registry, projects, documents, knowledge)

    def close(self) -> None:
        self.db.close()
        self.knowledge.store.db.close()
