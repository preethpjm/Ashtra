import os
import stat
from pathlib import Path

import pytest

from asthra.projects.service import ProjectError
from asthra.security.hashing import sha256_file
from tests.conftest import DOCS


def test_project_layout(loaded):
    p = loaded.projects.create("MLG publications")
    root = Path(p["root_path"])
    assert all((root / s).is_dir() for s in ("sources", "working", "revisions", "exports", "reports"))
    with pytest.raises(ProjectError):
        loaded.projects.create("../../etc")


def test_original_preserved_byte_identical_and_read_only(loaded, project):
    src = DOCS / "s1000d_proced_valid.xml"
    before = sha256_file(src)
    d = loaded.documents.import_path(project["id"], src)
    assert d["sha256"] == before == sha256_file(src)          # input untouched
    stored = Path(project["root_path"]) / d["blob_path"]
    assert sha256_file(stored) == before
    assert not os.stat(stored).st_mode & stat.S_IWUSR          # read-only on disk
    assert loaded.documents.original_bytes(d["id"]) == src.read_bytes()
    loaded.documents.validate(d["id"])
    assert sha256_file(stored) == before                       # validation never rewrites


def test_same_bytes_share_one_source_record(loaded, project):
    a = loaded.documents.import_path(project["id"], DOCS / "s3000l_lsa_valid.xml")
    b = loaded.documents.import_path(project["id"], DOCS / "s3000l_lsa_valid.xml")
    assert a["id"] != b["id"] and a["source_file_id"] == b["source_file_id"]


def test_corrupted_original_detected(loaded, project):
    d = loaded.documents.import_path(project["id"], DOCS / "s3000l_lsa_valid.xml")
    stored = Path(project["root_path"]) / d["blob_path"]
    os.chmod(stored, stat.S_IWUSR | stat.S_IRUSR)
    stored.write_bytes(stored.read_bytes().replace(b"Landing", b"Lxnding"))
    with pytest.raises(IOError, match="integrity"):
        loaded.documents.original_bytes(d["id"])


def test_filename_sanitised(loaded, project):
    d = loaded.documents.import_bytes(project["id"], "../../evil.xml", b"<a/>")
    assert d["original_name"] == "evil.xml"


def test_audit_trail(loaded, project):
    loaded.documents.import_path(project["id"], DOCS / "s2000m_provisioning_valid.xml")
    actions = [r["action"] for r in loaded.db.query("SELECT action FROM audit_event")]
    assert actions.count("schema.install") == 3 and "project.create" in actions and "document.import" in actions


def test_all_three_standards_share_one_project(loaded, project):
    for f in ("s1000d_ipd_valid.xml", "s2000m_provisioning_valid.xml", "s3000l_lsa_valid.xml"):
        loaded.documents.import_path(project["id"], DOCS / f)
    stds = {d["standard"] for d in loaded.documents.list(project["id"])}
    assert stds == {"S1000D", "S2000M", "S3000L"}


def test_utf16_document_saved_in_its_own_encoding(loaded, project):
    d = loaded.documents.import_path(project["id"], DOCS / "s2000m_provisioning_utf16.xml")
    text = loaded.documents.source_text(d["id"])
    res = loaded.documents.save_working(d["id"], text.replace("Bolt", "Hex bolt"))
    assert res["report"]["statuses"]["structural"] == "passed"
    data, origin = loaded.documents.current_bytes(d["id"])
    assert origin == "working" and data[:2] in (b"\xff\xfe", b"\xfe\xff")
    assert "Hex bolt" in loaded.documents.decode(data)


def test_revisions_are_immutable_and_checked(loaded, project):
    d = loaded.documents.import_path(project["id"], DOCS / "s3000l_lsa_valid.xml")
    r = loaded.documents.commit_revision(d["id"], "baseline")
    stored = Path(project["root_path"]) / r["rel_path"]
    assert not os.stat(stored).st_mode & stat.S_IWUSR
    os.chmod(stored, stat.S_IWUSR | stat.S_IRUSR)
    stored.write_bytes(stored.read_bytes() + b" ")
    with pytest.raises(IOError, match="integrity"):
        loaded.documents.revision_bytes(d["id"], r["id"])
