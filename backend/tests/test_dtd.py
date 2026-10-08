"""DTD validation (ATA iSpec 2200-style XML). Fixtures are synthetic."""
import shutil
from pathlib import Path

import pytest

from asthra.registry.builder import BuildError
from asthra.registry.dtd_builder import build_dtd_package, read_catalogs
from asthra.render.profiles import resolve
from tests.conftest import DOCS, FIX

ATA = FIX / "dtd" / "ata-synth"
PUB = "-//ASTHRA//DTD Synthetic ATA-style CMM//EN"


@pytest.fixture
def ata(ctx, tmp_path):
    m = build_dtd_package(ATA, "ATA2200", "synthetic-1", tmp_path / "ata.zip")
    ctx.registry.install(tmp_path / "ata.zip")
    return ctx, m


def test_builder_reads_catalog_and_root(tmp_path):
    cat = read_catalogs(ATA)
    assert cat[PUB] == "cmm.dtd" and cat["-//ASTHRA//ENTITIES Synthetic ISO subset//EN"] == "isoent.ent"
    m = build_dtd_package(ATA, "ATA2200", "synthetic-1", tmp_path / "a.zip")
    (dt,) = m["doc_types"]
    assert dt["id"] == "cmm" and dt["schema_kind"] == "dtd" and dt["match"]["local_name"] == "cmm"
    assert PUB.replace("/", "/") in dt["match"]["public_id_pattern"].replace("\\", "")


def test_unclear_root_asks_for_it(tmp_path):
    d = tmp_path / "two"; d.mkdir()
    (d / "frag.dtd").write_text("<!ELEMENT a (#PCDATA)><!ELEMENT b (#PCDATA)>")
    with pytest.raises(BuildError, match="--root frag="):
        build_dtd_package(d, "OEM", "1", tmp_path / "x.zip")
    m = build_dtd_package(d, "OEM", "1", tmp_path / "x.zip", roots={"frag": "b"})
    assert m["doc_types"][0]["match"]["local_name"] == "b"


def test_missing_entity_file_fails_at_install(ctx, tmp_path):
    d = tmp_path / "broken"; shutil.copytree(ATA, d); (d / "isoent.ent").unlink()
    (d / "CATALOG").write_text('PUBLIC "-//ASTHRA//DTD Synthetic ATA-style CMM//EN" "cmm.dtd"\n')
    with pytest.raises(BuildError):
        build_dtd_package(d, "ATA2200", "x", tmp_path / "b.zip")


def test_identified_by_public_id_and_valid_with_entities(ata):
    ctx, _ = ata
    p = ctx.projects.create("ata")
    d = ctx.documents.import_path(p["id"], DOCS / "ata_cmm_valid.xml")
    assert d["identification"]["status"] == "identified" and d["standard"] == "ATA2200"
    assert any("public identifier" in e for e in d["identification"]["candidates"][0]["evidence"])
    rep = ctx.documents.validate(d["id"])
    assert rep.structural_status.value == "passed", rep.diagnostics
    assert rep.entities["mdash"] == "\u2014" and rep.entities["deg"] == "\u00b0"


def test_invalid_document_explained_and_located(ata):
    ctx, _ = ata
    p = ctx.projects.create("ata")
    d = ctx.documents.import_path(p["id"], DOCS / "ata_cmm_invalid.xml")
    rep = ctx.documents.validate(d["id"])
    assert rep.structural_status.value == "failed"
    by = {x.rule_id: x for x in rep.diagnostics}
    miss = next(x for x in rep.diagnostics if x.attribute == "sectnbr")
    assert "missing the required attribute sectnbr" in miss.message and miss.element_path == "/cmm"
    enum = next(x for x in rep.diagnostics if x.value == "Nm")
    assert enum.fix and enum.fix.value == "N.m" and enum.element_path.endswith("torque[2]")
    assert any("&bogus;" in x.message for x in rep.diagnostics)
    assert any("<bogus> is not defined" in x.message for x in rep.diagnostics)
    refs = [x for x in rep.diagnostics if x.value == "T-999"]
    assert len(refs) == 1                                   # ASTHRA's own check, reported once
    assert refs[0].attribute == "refid" and refs[0].element_path.endswith("refint") and refs[0].line
    assert all(x.line for x in rep.diagnostics if x.stage == 3)


def test_xxe_blocked_in_dtd_mode(ata, tmp_path):
    ctx, _ = ata
    p = ctx.projects.create("ata")
    src = (DOCS / "ata_cmm_valid.xml").read_text().replace(
        '"cmm.dtd">', '"cmm.dtd" [<!ENTITY s SYSTEM "file:///etc/passwd">]>').replace("synthetic test extract", "&s;")
    d = ctx.documents.import_bytes(p["id"], "x.xml", src.encode())
    rep = ctx.documents.validate(d["id"])
    assert rep.structural_status.value == "failed"
    assert any(x.rule_id == "ASTHRA-SEC-003" for x in rep.diagnostics)
    assert "root:" not in rep.model_dump_json()


def test_no_doctype_needs_choice_then_validates_with_warning(ata):
    ctx, _ = ata
    p = ctx.projects.create("ata")
    d = ctx.documents.import_path(p["id"], DOCS / "ata_cmm_nodoctype.xml")
    assert d["identification"]["status"] == "needs-choice" and d["package_id"] is None
    opts = ctx.documents.schema_options(d["id"])
    assert [(o["doc_type"], o["declared"]) for o in opts] == [("cmm", False)]
    ctx.documents.choose_schema(d["id"], opts[0]["package_id"], "cmm")
    rep = ctx.documents.validate(d["id"])
    assert rep.structural_status.value == "passed"          # entities resolved through the chosen DTD
    warn = [x for x in rep.diagnostics if x.rule_id == "ASTHRA-SCHEMA-CHOSEN"]
    assert warn and "does not declare a schema" in warn[0].message


def test_choosing_a_schema_that_does_not_fit_is_refused(ata, loaded):
    ctx, _ = ata
    ctx.registry.install(FIX / "packages" / "s1000d-synth") if not any(
        k.manifest.standard == "S1000D" for k in ctx.registry.list()) else None
    p = ctx.projects.create("mix")
    d = ctx.documents.import_path(p["id"], DOCS / "ata_cmm_valid.xml")
    from asthra.documents.service import DocumentError
    with pytest.raises(DocumentError, match="does not fit"):
        ctx.documents.choose_schema(d["id"], "s1000d/synthetic-5.0-subset/asthra-fixture", "proced")


def test_render_profiles():
    ata = resolve("ATA2200", "cmm")
    assert ata["roles"]["list1"] == "list-alpha" and ata["roles"]["list2"] == "list-paren-num"
    s1 = resolve(None, "dmodule")
    assert s1["roles"]["proceduralStep"] == "step" and "from root" in s1["profile"]
    assert resolve("OEM", "x", {"myStep": "step", "junk": "not-a-role"})["roles"].get("junk") is None



def test_named_entity_without_doctype_is_explained(ata):
    ctx, _ = ata
    p = ctx.projects.create("ata")
    src = (DOCS / "ata_cmm_valid.xml").read_text().replace(
        '<!DOCTYPE cmm PUBLIC "-//ASTHRA//DTD Synthetic ATA-style CMM//EN" "cmm.dtd">\n', "")
    d = ctx.documents.import_bytes(p["id"], "nodt.xml", src.encode())
    rep = ctx.documents.validate(d["id"])
    wf = [x for x in rep.diagnostics if x.rule_id == "XML-WF"]
    assert wf and "DOCTYPE" in (wf[0].suggestion or "")



def test_idref_check_does_not_depend_on_libxml2(ata, monkeypatch):
    """Regression (Windows): some libxml2 builds do not report unknown IDREFs in DTD mode.
    Simulate that build and check the reference is still caught."""
    import asthra.validation.dtd as dtdmod
    real = dtdmod.validate_dtd
    def no_idref(*a, **k):
        tree, entries, dtd, blocked = real(*a, **k)
        return tree, [e for e in entries if "IDREF" not in e.message], dtd, blocked
    monkeypatch.setattr(dtdmod, "validate_dtd", no_idref)
    ctx, _ = ata
    p = ctx.projects.create("ata")
    d = ctx.documents.import_path(p["id"], DOCS / "ata_cmm_invalid.xml")
    rep = ctx.documents.validate(d["id"])
    assert any(x.rule_id == "DTD-IDREF" and x.value == "T-999" for x in rep.diagnostics)


def test_profiles_carry_publication_numbering():
    from asthra.render.profiles import resolve
    ata = resolve("ATA2200", "cmm")
    assert ata["numbering"]["scheme"] == "ata"
    assert ata["roles"]["prcitem2"] == "proc-item" and ata["roles"]["revst"] == "change-mark"
    assert ata["numbering"]["ident"]["subtask"] == "SUBTASK"
    assert ata["columns"]["prtlist"][1] == "Part number"
    s1k = resolve("S1000D", "dmodule")
    assert s1k["numbering"]["scheme"] == "decimal" and "levelledPara" in s1k["numbering"]["elements"]
    assert resolve(None, "unknown")["numbering"] is None
