"""Runtime configuration. All paths are local; nothing here reaches the network."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_root: Path
    host: str = "127.0.0.1"          # localhost only by default (spec §19)
    port: int = 8765
    max_import_bytes: int = 200 * 1024 * 1024
    allow_network: bool = False       # never True in Phase 1; explicit for audit

    @property
    def db_path(self) -> Path:
        return self.data_root / "asthra.sqlite3"

    @property
    def registry_root(self) -> Path:
        return self.data_root / "registry"

    @property
    def projects_root(self) -> Path:
        return self.data_root / "projects"

    @property
    def knowledge_db(self) -> Path:
        return self.data_root / "knowledge" / "library.sqlite3"

    def ensure(self) -> "Settings":
        for p in (self.data_root, self.registry_root, self.projects_root, self.knowledge_db.parent):
            p.mkdir(parents=True, exist_ok=True)
        return self


def default_data_root() -> Path:
    root = os.environ.get("ASTHRA_DATA")
    if root:
        return Path(root)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ASTHRA"
    return Path.home() / ".asthra"


def default_settings() -> Settings:
    return Settings(data_root=default_data_root()).ensure()
