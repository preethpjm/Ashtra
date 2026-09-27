from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest

from asthra.app_context import AppContext
from asthra.config import Settings

FIX = Path(__file__).parent / "fixtures"
PKGS = FIX / "packages"
DOCS = FIX / "documents"


_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple):      # AF_UNIX path or similar local endpoint
        return True
    host = str(address[0]).strip("[]").lower()
    return host in _LOOPBACK or host.startswith("127.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Offline guard: any connection leaving this machine fails the test.

    Loopback stays allowed: asyncio on Windows builds its internal self-pipe with
    socket.socketpair(), which connects to 127.0.0.1. That is not network access."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def blocked(target):
        raise AssertionError(f"network access attempted during an offline test: {target!r}")

    def connect(self, address, *a, **k):
        return real_connect(self, address, *a, **k) if _is_loopback(address) else blocked(address)

    def connect_ex(self, address, *a, **k):
        return real_connect_ex(self, address, *a, **k) if _is_loopback(address) else blocked(address)

    def create_connection(address, *a, **k):
        return real_create(address, *a, **k) if _is_loopback(address) else blocked(address)

    def getaddrinfo(host, *a, **k):
        return real_getaddrinfo(host, *a, **k) if _is_loopback((host,)) else blocked(host)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def ctx(tmp_path):
    c = AppContext.open(Settings(data_root=tmp_path / "data"))
    yield c
    c.close()


@pytest.fixture
def loaded(ctx):
    for name in ("s1000d-synth", "s2000m-synth", "s3000l-synth"):
        ctx.registry.install(PKGS / name)
    return ctx


@pytest.fixture
def project(loaded):
    return loaded.projects.create("Test project")


def copy_pkg(name: str, dest: Path) -> Path:
    out = dest / name
    shutil.copytree(PKGS / name, out)
    return out
