"""SGML (legacy ATA iSpec 2200 style) through OpenSP. Fixtures are synthetic.
Skipped where OpenSP is not installed; the 'not installed' path is tested regardless."""
import shutil

import pytest

from asthra.registry import installer
from asthra.validation.sgml import find_tools, probe, redirect_doctype
from tests.conftest import DOCS, FIX

SG = FIX / "sgml" / "ata-sgml-synth"
_tools = find_tools()
needs_opensp = pytest.mark.skipif(_tools is None or not probe(_tools)[0],
                                  reason="OpenSP (onsgmls/osx) not installed or not working")


@pytest.fixture
def sg(ctx, tmp_path):
    prop = installer.inspect(SG)
    assert prop["kind"] == "sgml"
    prop["issue"] = "synthetic-1"
    ctx.registry.install(installer.build(SG, prop, tmp_path / "s.zip"))
    return ctx


def test_identified_from_the_doctype(sg):
    p = sg.projects.create("s")
    d = sg.documents.import_path(p["id"], DOCS / "ata_cmm_sgml.sgm")
    assert d["syntax"] == "sgml" and d["identification"]["status"] == "identified"
    assert d["standard"] == "ATA2200" and d["doc_type"] == "cmm"


@needs_opensp
def test_valid_sgml_passes_and_renders(sg):
    p = sg.projects.create("s")
    d = sg.documents.import_path(p["id"], DOCS / "ata_cmm_sgml.sgm")
    chk = sg.documents.check_text(d["id"], sg.documents.source_text(d["id"]))
    rep = chk["report"]
    assert rep["statuses"]["structural"] == "passed", [(x["message"], x.get("suggestion")) for x in rep["diagnostics"]]
    xml = rep["rendered_xml"]
    assert "<cmm " in xml and "</title>" in xml
    # ISO SDATA kept as entity references, declared with the character they stand for
    assert "&deg;" in xml and "&plusmn;" in xml and "&mdash;" in xml
    assert rep["entities"]["deg"] == "\u00b0" and rep["entities"]["mdash"] == "\u2014"
    from lxml import etree
    etree.fromstring(xml.encode(), etree.XMLParser(resolve_entities=False, no_network=True))   # well-formed XML
    assert chk["outline"]["root"]["name"] == "cmm"


@needs_opensp
def test_invalid_sgml_explained_with_lines(sg):
    p = sg.projects.create("s")
    d = sg.documents.import_path(p["id"], DOCS / "ata_cmm_sgml_invalid.sgm")
    rep = sg.documents.validate(d["id"])
    assert rep.structural_status.value == "failed"
    msgs = {x.message for x in rep.diagnostics}
    assert "A required attribute sectnbr is missing." in msgs
    assert any("&bogus;" in m for m in msgs) and any("<bogus> is not defined" in m for m in msgs)
    assert any("'NM' is not an allowed value" in m for m in msgs)
    assert any("T999" in m for m in msgs)
    assert sum("bogus;" in m for m in msgs) == 1                        # no triple reporting
    assert all(x.line for x in rep.diagnostics if x.stage == 3)


@needs_opensp
def test_sgml_cannot_read_other_files(sg):
    p = sg.projects.create("s")
    src = (DOCS / "ata_cmm_sgml.sgm").read_text().replace(
        '<!DOCTYPE CMM PUBLIC "-//ASTHRA//DTD Synthetic ATA-style CMM SGML//EN">',
        '<!DOCTYPE CMM PUBLIC "-//ASTHRA//DTD Synthetic ATA-style CMM SGML//EN" [\n<!ENTITY s SYSTEM "/etc/passwd">\n]>'
    ).replace("All synthetic pump configurations", "&s;")
    d = sg.documents.import_bytes(p["id"], "x.sgm", src.encode())
    chk = sg.documents.check_text(d["id"], src)
    assert "root:" not in (chk["report"]["rendered_xml"] or "")
    assert any(x["rule_id"] == "ASTHRA-SEC-003" for x in chk["report"]["diagnostics"])


def test_remote_addresses_are_removed_from_the_copy():
    t = '<!DOCTYPE CMM PUBLIC "-//X//DTD//EN" "http://evil.example/x.dtd" [\n<!ENTITY e SYSTEM "https://evil.example/e">\n]>\n<CMM>'
    out, removed = redirect_doctype(t, "cmm", "cmm.dtd")
    assert "http" not in out and removed == 1 and out.count("\n") == t.count("\n")
    assert out.startswith('<!DOCTYPE CMM SYSTEM "cmm.dtd"')


def test_without_opensp_the_user_is_told_what_to_install(sg, monkeypatch):
    import asthra.validation.sgml as s
    monkeypatch.setattr(s, "find_tools", lambda: None)
    p = sg.projects.create("s")
    d = sg.documents.import_path(p["id"], DOCS / "ata_cmm_sgml.sgm")
    rep = sg.documents.validate(d["id"])
    diag = next(x for x in rep.diagnostics if x.rule_id == "ASTHRA-SGML-001")
    assert "OpenSP" in diag.suggestion and "sourceforge.net/projects/openjade" in diag.suggestion
    assert rep.structural_status.value != "passed"



def test_sgml_and_xml_dtd_sets_do_not_claim_each_others_documents(sg, tmp_path):
    """Regression: an SGML DTD set whose DTD is also called cmm.dtd made the XML ATA samples
    ambiguous. SGML sets only match SGML documents; XML sets only XML documents."""
    from asthra.registry.dtd_builder import build_dtd_package
    build_dtd_package(FIX / "dtd" / "ata-synth", "ATA2200", "synthetic-1", tmp_path / "x.zip")
    sg.registry.install(tmp_path / "x.zip")
    p = sg.projects.create("both")
    x = sg.documents.import_path(p["id"], DOCS / "ata_cmm_valid.xml")
    s = sg.documents.import_path(p["id"], DOCS / "ata_cmm_sgml.sgm")
    # same standard and revision, one SGML and one XML DTD set: both installed, each claims its own documents
    assert x["identification"]["status"] == "identified" and x["package_id"] == "ata2200/synthetic-1/official"
    assert s["identification"]["status"] == "identified" and s["package_id"] == "ata2200/synthetic-1/sgml"



def test_opensp_that_cannot_start_never_passes_a_document(sg, monkeypatch, tmp_path):
    """Regression (Windows): OpenSP missing a DLL produced no messages, and the document was
    reported as passed. A tool failure must be a failure, with the reason."""
    import os, stat
    if os.name == "nt":
        pytest.skip("uses POSIX shell scripts as stand-in programs")
    d = tmp_path / "broken"; d.mkdir()
    for n in ("onsgmls", "osx"):
        f = d / n; f.write_text("#!/bin/sh\nexit 1\n"); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ASTHRA_OPENSP", str(d))
    p = sg.projects.create("s")
    d1 = sg.documents.import_path(p["id"], DOCS / "ata_cmm_sgml_invalid.sgm")
    rep = sg.documents.validate(d1["id"])
    assert rep.structural_status.value == "failed"
    assert any(x.rule_id == "ASTHRA-SGML-002" and "NOT checked" in x.message for x in rep.diagnostics)



def test_opensp_is_given_relative_names_only(monkeypatch, tmp_path):
    """Regression (Windows/MSYS2): restricted mode refuses absolute file names, so
    '-c C:\\...\\CATALOG' failed with 'cannot find'. Catalogs must be passed by relative name,
    and the package folder only through -D."""
    import subprocess
    import asthra.validation.sgml as sg
    seen = []
    class R:  # a clean onsgmls/osx result
        returncode = 0; stdout = b'<?xml version="1.0"?>\n<cmm/>'; stderr = b""
    def fake_run(args, **kw):
        seen.append(args); return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    sg.run("<!DOCTYPE CMM PUBLIC \"x\"><CMM>", "cmm", SG, "cmm.dtd", ["CATALOG", "sub/CATALOG"], None, ("onsgmls", "osx"))
    for args in seen:
        cats = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
        assert cats == ["CATALOG", "sub/CATALOG"]
        dirs = [args[i + 1] for i, a in enumerate(args) if a == "-D"]
        assert dirs == ["."]                                        # only the private working folder
        assert not any(a.startswith("/") or (len(a) > 1 and a[1] == ":") for a in args[1:])   # no absolute path
        assert args[-1] == "doc.sgm"


def test_unopenable_package_files_are_a_setup_problem(monkeypatch):
    import subprocess
    import asthra.validation.sgml as sg
    class R:
        returncode = 1; stdout = b""
        stderr = b'C:/msys64/usr/bin/onsgmls.exe:E: cannot find "CATALOG"; tried "C:/x/CATALOG"\n'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    with pytest.raises(sg.SgmlToolError, match="DTD set"):
        sg.run("<CMM>", "cmm", SG, "cmm.dtd", ["CATALOG"], None, ("onsgmls", "osx"))
