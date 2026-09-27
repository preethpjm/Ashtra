import json
import os
import shutil
import stat
import zipfile

import pytest

from asthra.registry.service import RegistryError
from tests.conftest import PKGS, copy_pkg


def test_three_sseries_packages_install_as_peers(loaded):
    pk = {p.manifest.standard: p for p in loaded.registry.list()}
    assert set(pk) == {"S1000D", "S2000M", "S3000L"}
    assert all(p.manifest.provenance == "synthetic" for p in pk.values())
    assert {d.id for d in pk["S1000D"].manifest.doc_types} == {"descript", "proced", "ipd"}
    for p in pk.values():
        assert len(p.checksum) == 64 and loaded.registry.verify_integrity(p.manifest.key)


def test_catalog_resolves_dependency_locally(loaded):
    schema, pkg, dt = loaded.registry.schema_for("s1000d/synthetic-5.0-subset/asthra-fixture", "descript")
    assert schema is not None and dt.content_family == "description"


def test_duplicate_install_rejected(loaded):
    with pytest.raises(RegistryError, match="already installed"):
        loaded.registry.install(PKGS / "s2000m-synth")


def test_missing_listed_file_rejected(ctx, tmp_path):
    pkg = copy_pkg("s2000m-synth", tmp_path)
    (pkg / "xsd/provisioning.xsd").unlink()
    with pytest.raises(RegistryError, match="missing file"):
        ctx.registry.install(pkg)


def test_unknown_standard_rejected(ctx, tmp_path):
    pkg = copy_pkg("s2000m-synth", tmp_path)
    m = json.loads((pkg / "asthra-package.json").read_text()); m["standard"] = "S9999X"
    (pkg / "asthra-package.json").write_text(json.dumps(m))
    with pytest.raises(RegistryError, match="unknown standard"):
        ctx.registry.install(pkg)


def test_declared_checksum_mismatch_rejected(ctx, tmp_path):
    pkg = copy_pkg("s3000l-synth", tmp_path)
    m = json.loads((pkg / "asthra-package.json").read_text()); m["checksum"] = "0" * 64
    (pkg / "asthra-package.json").write_text(json.dumps(m))
    with pytest.raises(RegistryError, match="checksum"):
        ctx.registry.install(pkg)


def test_tampered_package_refused_at_use(loaded):
    key = "s3000l/synthetic-2-subset/asthra-fixture"
    f = loaded.registry.get(key).path / "xsd/lsa.xsd"
    os.chmod(f, stat.S_IWUSR | stat.S_IRUSR)
    f.write_text(f.read_text().replace("removal", "removalX"))
    assert not loaded.registry.verify_integrity(key)
    with pytest.raises(RegistryError, match="integrity"):
        loaded.registry.schema_for(key, "lsa")


def test_unresolved_package_dependency(ctx, tmp_path):
    pkg = copy_pkg("s2000m-synth", tmp_path)
    m = json.loads((pkg / "asthra-package.json").read_text()); m["dependencies"] = ["oem/1/base"]
    (pkg / "asthra-package.json").write_text(json.dumps(m))
    with pytest.raises(RegistryError, match="unresolved package dependency"):
        ctx.registry.install(pkg)


def test_oem_package_with_cross_package_dependency(ctx, tmp_path):
    """OEM schemas are first-class: an extension package can import from a base package."""
    base = tmp_path / "base"; (base / "xsd").mkdir(parents=True)
    (base / "xsd/types.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:oem:types">'
        '<xs:simpleType name="pn"><xs:restriction base="xs:string"><xs:pattern value="[A-Z]{2}-[0-9]+"/>'
        '</xs:restriction></xs:simpleType></xs:schema>')
    (base / "asthra-package.json").write_text(json.dumps({
        "package_id": "base", "name": "OEM base types", "standard": "OEM", "issue": "1", "provenance": "oem",
        "doc_types": [], "files": ["xsd/types.xsd"]}))
    ext = tmp_path / "ext"; (ext / "xsd").mkdir(parents=True)
    (ext / "xsd/cmm.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:t="urn:oem:types">'
        '<xs:import namespace="urn:oem:types" schemaLocation="urn:oem:types/types.xsd"/>'
        '<xs:element name="cmm"><xs:complexType><xs:sequence><xs:element name="pn" type="t:pn"/>'
        '</xs:sequence></xs:complexType></xs:element></xs:schema>')
    (ext / "asthra-package.json").write_text(json.dumps({
        "package_id": "cmm", "name": "OEM CMM", "standard": "OEM", "issue": "1", "provenance": "oem",
        "dependencies": ["oem/1/base"], "catalog": {"urn:oem:types/types.xsd": "xsd/types.xsd"},
        "doc_types": [{"id": "cmm", "label": "CMM", "content_family": "other", "schema_file": "xsd/cmm.xsd",
                       "match": {"local_name": "cmm"}}], "files": ["xsd/cmm.xsd"]}))
    ctx.registry.install(base)
    ctx.registry.install(ext)
    schema, *_ = ctx.registry.schema_for("oem/1/cmm", "cmm")
    from lxml import etree
    assert schema.validate(etree.fromstring(b"<cmm><pn>AB-12</pn></cmm>"))
    assert not schema.validate(etree.fromstring(b"<cmm><pn>bad</pn></cmm>"))


def test_install_from_zip(ctx, tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in (PKGS / "s3000l-synth").rglob("*"):
            if f.is_file():
                zf.write(f, "pkg/" + str(f.relative_to(PKGS / "s3000l-synth")))
    p = ctx.registry.install(z)
    assert p.manifest.standard == "S3000L"


def test_disable_and_enable(loaded):
    key = "s2000m/synthetic-6-subset/asthra-fixture"
    loaded.registry.set_enabled(key, False)
    with pytest.raises(RegistryError, match="disabled"):
        loaded.registry.schema_for(key, "provisioning")
    loaded.registry.set_enabled(key, True)
    assert loaded.registry.schema_for(key, "provisioning")[0] is not None
