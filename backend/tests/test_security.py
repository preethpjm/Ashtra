import json
import stat
import zipfile

import pytest

from asthra.registry.service import RegistryError
from asthra.security.paths import PathViolation, confine, safe_extract_zip
from tests.conftest import DOCS, copy_pkg


def test_confine_blocks_traversal(tmp_path):
    assert confine(tmp_path, "a/b.xml") == (tmp_path / "a/b.xml").resolve()
    for bad in ("../x", "a/../../x", "/etc/passwd"):
        with pytest.raises(PathViolation):
            confine(tmp_path, bad)


def test_zip_slip_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../escaped.txt", "x")
    with pytest.raises(PathViolation):
        safe_extract_zip(z, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()


def test_zip_symlink_rejected(tmp_path):
    z = tmp_path / "link.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(PathViolation):
        safe_extract_zip(z, tmp_path / "out")


def test_xxe_is_never_expanded(project, loaded):
    doc = loaded.documents.import_path(project["id"], DOCS / "xxe_attack.xml")
    rep = loaded.documents.validate(doc["id"])
    blob = json.dumps(doc) + rep.model_dump_json()
    assert "root:" not in blob            # /etc/passwd content never appears
    assert rep.structural_status.value == "failed"
    rules = {d.rule_id for d in rep.diagnostics}
    assert "ASTHRA-SEC-003" in rules and "ASTHRA-SEC-001" in rules      # refused by the confined loader


def test_remote_schema_import_is_blocked(ctx, tmp_path):
    """A schema that imports from a URL not mapped in the local catalog must fail
    at install time instead of being fetched."""
    pkg = copy_pkg("s1000d-synth", tmp_path)
    m = json.loads((pkg / "asthra-package.json").read_text())
    m["catalog"] = {}
    (pkg / "asthra-package.json").write_text(json.dumps(m))
    with pytest.raises(RegistryError, match="refused|failed to compile"):
        ctx.registry.install(pkg)


def test_local_path_detection_is_windows_safe():
    """Regression: urlparse reads 'C:\\x' as scheme 'c', which blocked every local
    schema on Windows."""
    from asthra.security.xml_safe import to_local_path
    assert to_local_path(r"C:\Users\p\pkg\xsd\descript.xsd") is not None
    assert to_local_path("C:/Users/p/pkg/xsd/descript.xsd") is not None
    assert to_local_path(r"\\server\share\a.xsd") is not None
    assert to_local_path("file:///tmp/a.xsd") is not None
    assert to_local_path("xsd/common.xsd") is not None
    for remote in ("http://example.invalid/a.xsd", "https://x/a.xsd", "ftp://x/a", "urn:oem:types/types.xsd"):
        assert to_local_path(remote) is None


def test_offline_guard_blocks_external_but_allows_loopback():
    """The guard itself must be trustworthy: external blocked, loopback allowed
    (Windows asyncio needs a 127.0.0.1 socketpair for its event loop)."""
    import socket
    for target in (("93.184.216.34", 80), ("example.com", 443)):
        with pytest.raises(AssertionError, match="network access"):
            socket.create_connection(target, timeout=1)
    with pytest.raises(AssertionError, match="network access"):
        socket.getaddrinfo("example.com", 80)
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    cli = socket.socket()
    try:
        cli.connect(srv.getsockname())        # loopback: allowed
    finally:
        cli.close(); srv.close()
    a, b = socket.socketpair(); a.close(); b.close()
