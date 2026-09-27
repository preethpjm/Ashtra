"""Content-addressed, immutable source storage and atomic writes (spec §18)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..security.hashing import sha256_bytes, sha256_file
from ..security.paths import make_read_only


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class ImmutableStore:
    """Stores originals under sources/sha256/ab/<hash>; never rewrites them."""

    def __init__(self, root: Path):
        self.root = root

    def rel_path(self, digest: str) -> Path:
        return Path("sources") / "sha256" / digest[:2] / digest

    def put(self, data: bytes) -> tuple[str, Path]:
        digest = sha256_bytes(data)
        rel = self.rel_path(digest)
        full = self.root / rel
        if full.exists():
            if sha256_file(full) != digest:
                raise IOError(f"stored original is corrupt: {rel}")
            return digest, rel
        atomic_write(full, data)
        make_read_only(full)
        return digest, rel

    def get(self, rel: Path, expected: str) -> bytes:
        data = (self.root / rel).read_bytes()
        if sha256_bytes(data) != expected:
            raise IOError(f"integrity failure: {rel} does not match recorded SHA-256")
        return data
