"""make-package: builds an installable package from a folder shaped like the
official S1000D schema download (files here are small stand-ins, not official)."""
import shutil

import pytest

from asthra.registry.builder import BuildError, build_s1000d_package, issue_marker
from tests.conftest import DOCS, PKGS

ANNOT = ('<xs:annotation><xs:documentation>Issue number: 4.1</xs:documentation>'
         '<xs:documentation>URL: http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd</xs:documentation>'
         '<xs:documentation>Root element: dmodule</xs:documentation></xs:annotation>')


def fake_official(tmp_path, remote_import=False):
    d = tmp_path / "S1000D_4-1" / "xml_schema_flat"
    d.mkdir(parents=True)
    src = (PKGS / "s1000d-synth" / "xsd")
    shutil.copy(src / "xlink.xsd", d / "xlink.xsd")
    common = (src / "common.xsd").read_text()
    if not remote_import:
        common = common.replace('schemaLocation="http://www.example.invalid/xlink.xsd"', 'schemaLocation="xlink.xsd"')
    else:
        common = common.replace('http://www.example.invalid/xlink.xsd', 'http://www.s1000d.org/S1000D_4-1/xml_schema_flat/xlink.xsd')
    (d / "common.xsd").write_text(common)
    proced = (src / "proced.xsd").read_text().replace('elementFormDefault="unqualified">', 'elementFormDefault="unqualified">' + ANNOT, 1)
    (d / "proced.xsd").write_text(proced)
    return d


def test_issue_marker():
    assert issue_marker("4.1") == "S1000D_4-1" and issue_marker("4.0.1") == "S1000D_4-0-1"
    with pytest.raises(BuildError):
        issue_marker("latest")


def test_build_install_and_identify_exact_issue(ctx, tmp_path):
    folder = fake_official(tmp_path, remote_import=True)
    m = build_s1000d_package(folder, "4.1", tmp_path / "s1000d-4.1.zip")
    assert [d["id"] for d in m["doc_types"]] == ["proced"]              # common/xlink are dependencies
    assert m["catalog"] == {"http://www.s1000d.org/S1000D_4-1/xml_schema_flat/xlink.xsd": "xlink.xsd"}
    ctx.registry.install(PKGS / "s1000d-synth")                          # both installed at once
    ctx.registry.install(tmp_path / "s1000d-4.1.zip")
    p = ctx.projects.create("real")
    src = (DOCS / "s1000d_proced_valid.xml").read_text().replace(
        'xsi:noNamespaceSchemaLocation="proced.xsd"',
        'xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd"')
    d = ctx.documents.import_bytes(p["id"], "dm.xml", src.encode())
    assert d["identification"]["status"] == "identified"
    assert d["package_id"] == "s1000d/4.1/official" and d["identity"]["display"].startswith("DMC-ASTHRA")
    # a 4.0 document is not claimed by the 4.1 package
    d40 = ctx.documents.import_bytes(p["id"], "dm40.xml", src.replace("S1000D_4-1", "S1000D_4-0").encode())
    assert d40["identification"]["status"] == "needs-choice" and d40["package_id"] is None


def test_missing_dependency_is_reported(tmp_path):
    folder = fake_official(tmp_path)
    (folder / "xlink.xsd").unlink()
    with pytest.raises(BuildError, match="xlink.xsd"):
        build_s1000d_package(folder, "4.1", tmp_path / "x.zip")


def add_broken_scorm(folder):
    (folder / "scormcontentpackage.xsd").write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:annotation>'
        '<xs:documentation>Issue number: 4.1</xs:documentation>'
        '<xs:documentation>Root element: scormContentPackage</xs:documentation></xs:annotation>'
        '<xs:include schemaLocation="../lom_schema/lom.xsd"/></xs:schema>')


def test_only_checks_dependencies_of_requested_types(tmp_path):
    """Regression (Issue 6 folder): scormcontentpackage.xsd needs ../lom_schema/lom.xsd,
    which is not shipped. --only proced must not care."""
    folder = fake_official(tmp_path); add_broken_scorm(folder)
    m = build_s1000d_package(folder, "4.1", tmp_path / "p.zip", only=["proced"])
    assert [d["id"] for d in m["doc_types"]] == ["proced"]
    assert "scormcontentpackage.xsd" not in m["files"] and "proced.xsd" in m["files"]


def test_full_build_skips_broken_types_and_reports_them(tmp_path):
    folder = fake_official(tmp_path); add_broken_scorm(folder)
    m = build_s1000d_package(folder, "4.1", tmp_path / "all.zip")
    assert [d["id"] for d in m["doc_types"]] == ["proced"]
    assert any("scormcontentpackage" in s and "lom.xsd" in s for s in m["_skipped"])
    with pytest.raises(BuildError, match="missing dependencies"):
        build_s1000d_package(folder, "4.1", tmp_path / "x.zip", only=["scormcontentpackage"])
    with pytest.raises(BuildError, match="not found"):
        build_s1000d_package(folder, "4.1", tmp_path / "x.zip", only=["nosuch"])


def test_wrong_issue_is_refused(tmp_path):
    folder = fake_official(tmp_path)
    with pytest.raises(BuildError, match="declare Issue 4.1, not 5.0"):
        build_s1000d_package(folder, "5.0", tmp_path / "x.zip")
    assert build_s1000d_package(folder, "4.1", tmp_path / "ok.zip")      # the stated issue works



def test_replace_adds_types_and_keeps_documents(ctx, tmp_path):
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "a.zip", only=["proced"])
    ctx.registry.install(tmp_path / "a.zip")
    p = ctx.projects.create("r")
    src = (DOCS / "s1000d_proced_valid.xml").read_text().replace(
        'xsi:noNamespaceSchemaLocation="proced.xsd"',
        'xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd"')
    d = ctx.documents.import_bytes(p["id"], "dm.xml", src.encode())
    # second build adds a Description type
    desc = (PKGS / "s1000d-synth" / "xsd" / "descript.xsd").read_text().replace(
        'elementFormDefault="unqualified">', 'elementFormDefault="unqualified">' + ANNOT.replace("proced", "descript"), 1)
    (folder / "descript.xsd").write_text(desc)
    build_s1000d_package(folder, "4.1", tmp_path / "b.zip")
    new = ctx.registry.replace(tmp_path / "b.zip")
    assert {t.id for t in new.manifest.doc_types} == {"proced", "descript"}
    assert ctx.registry.verify_integrity(new.manifest.key)
    assert ctx.documents.validate(d["id"]).structural_status.value == "passed"   # still linked, recompiled
    # a build that drops a type still in use is refused
    build_s1000d_package(folder, "4.1", tmp_path / "c.zip", only=["descript"])
    with pytest.raises(Exception, match="no longer contains"):
        ctx.registry.replace(tmp_path / "c.zip")


def test_content_element_read_from_schema():
    """Official S1000D schemas define <content> through a named type: refs?, then the body."""
    from lxml import etree
    from asthra.registry.builder import content_element
    xsd = etree.fromstring(b'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="content" type="contentElemType"/>
      <xs:complexType name="contentElemType"><xs:sequence>
        <xs:element minOccurs="0" ref="refs"/><xs:element ref="procedure"/>
      </xs:sequence></xs:complexType></xs:schema>''')
    assert content_element(xsd) == "procedure"
    inline = etree.fromstring(b'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="content"><xs:complexType><xs:sequence>
        <xs:element minOccurs="0" ref="refs"/><xs:element ref="description"/></xs:sequence></xs:complexType></xs:element></xs:schema>''')
    assert content_element(inline) == "description"
    two = etree.fromstring(b'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="content"><xs:complexType><xs:choice>
        <xs:element ref="faultReporting"/><xs:element ref="faultIsolation"/></xs:choice></xs:complexType></xs:element></xs:schema>''')
    assert content_element(two) is None          # ambiguous: no discriminator rather than a wrong one



def _ent_folder(tmp_path):
    ent = tmp_path / "ent-src"; ent.mkdir()
    (ent / "ISOEntities").write_text(
        '<!ENTITY % ISOnum PUBLIC "ISO 8879:1986//ENTITIES Numeric and Special Graphic//EN//XML" "iso-num.ent">\n%ISOnum;\n')
    (ent / "iso-num.ent").write_text('<!ENTITY deg "&#176;">\n<!ENTITY plusmn "&#177;">\n')
    return ent


ISO_DOCTYPE = ('<!DOCTYPE dmodule [\n<!ENTITY % ISOEntities PUBLIC "ISO 8879-1986//ENTITIES ISO Character Entities 20030531//EN//XML" '
               '"http://www.s1000d.org/S1000D_4-1/ent/ISOEntities">\n%ISOEntities;\n]>\n')


def _iso_doc():
    src = (DOCS / "s1000d_proced_valid.xml").read_text().replace(
        'xsi:noNamespaceSchemaLocation="proced.xsd"',
        'xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd"')
    src = src.replace('<?xml version="1.0" encoding="UTF-8"?>\n', '<?xml version="1.0" encoding="UTF-8"?>\n' + ISO_DOCTYPE)
    return src.replace("Remove the access panel.", "Remove the access panel at 20&deg;C &plusmn;5&deg;C.")


def test_iso_entities_resolve_from_the_package(ctx, tmp_path):
    """S1000D files that import the ISO entity sets through their DOCTYPE validate offline
    once the entity files are bundled with --entities."""
    folder = fake_official(tmp_path)
    m = build_s1000d_package(folder, "4.1", tmp_path / "e.zip", only=["proced"], entities=[_ent_folder(tmp_path)])
    assert "ent/ISOEntities" in m["files"] and m["catalog"]["ISOEntities"] == "ent/ISOEntities"
    ctx.registry.install(tmp_path / "e.zip")
    p = ctx.projects.create("iso")
    d = ctx.documents.import_bytes(p["id"], "iso.xml", _iso_doc().encode())
    assert d["identification"]["status"] == "identified"
    rep = ctx.documents.validate(d["id"])
    assert rep.structural_status.value == "passed", rep.diagnostics
    assert rep.entities.get("deg") == "\u00b0"


def test_iso_entities_missing_gives_a_clear_hint(ctx, tmp_path):
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "n.zip", only=["proced"])
    ctx.registry.install(tmp_path / "n.zip")
    p = ctx.projects.create("iso")
    d = ctx.documents.import_bytes(p["id"], "iso.xml", _iso_doc().encode())
    rep = ctx.documents.validate(d["id"])
    sec = [x for x in rep.diagnostics if x.rule_id == "ASTHRA-SEC-003"]
    assert sec and "Choose folder" in sec[0].suggestion and rep.structural_status.value == "failed"
    assert sec[0].category == "entity-set-missing"



def test_windows_libxml2_behaviour_is_handled(ctx, tmp_path, monkeypatch):
    """Regression (Windows): some libxml2 builds reject &deg; in the quick structural parse
    even though the DOCTYPE imports its declaration. Simulate that build: the document must
    still be identified, and validated with the entities from the package."""
    import asthra.identify.service as ident
    real = ident._strict_parse
    def strict_like_windows(data):
        if b"&deg;" in data:
            tree, errs = real(data.replace(b"<dmodule", b"<dmodule &deg;", 1))   # force an entity error
            class E:  # minimal log entry
                message = "Entity 'deg' not defined"; line = 12; column = 1
            return None, [E()]
        return real(data)
    monkeypatch.setattr(ident, "_strict_parse", strict_like_windows)
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "w.zip", only=["proced"], entities=[_ent_folder(tmp_path)])
    ctx.registry.install(tmp_path / "w.zip")
    p = ctx.projects.create("win")
    d = ctx.documents.import_bytes(p["id"], "iso.xml", _iso_doc().encode())
    assert d["identification"]["status"] == "identified"
    rep = ctx.documents.validate(d["id"])
    assert rep.structural_status.value == "passed", rep.diagnostics


def test_standalone_undeclared_entity_is_still_an_error():
    from asthra.identify.service import parse_xml
    tree, errs = parse_xml(b"<a>&deg;</a>")
    assert tree is None and errs



def test_explicit_declaration_beats_a_wrong_discriminator(ctx, tmp_path):
    """If a discriminator derived from the schema is wrong, a document that names that exact
    schema must still be identified (the discriminator only gates undeclared matches)."""
    import json, zipfile
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "d.zip", only=["proced"])
    with zipfile.ZipFile(tmp_path / "d.zip") as z:
        names = z.namelist(); blobs = {n: z.read(n) for n in names}
    m = json.loads(blobs["asthra-package.json"]); m["doc_types"][0]["discriminator"] = "/dmodule/content/nothingLikeThis"
    blobs["asthra-package.json"] = json.dumps(m).encode()
    with zipfile.ZipFile(tmp_path / "d2.zip", "w") as z:
        for n, b in blobs.items(): z.writestr(n, b)
    ctx.registry.install(tmp_path / "d2.zip")
    p = ctx.projects.create("x")
    src = (DOCS / "s1000d_proced_valid.xml").read_text().replace(
        'xsi:noNamespaceSchemaLocation="proced.xsd"',
        'xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd"')
    d = ctx.documents.import_bytes(p["id"], "dm.xml", src.encode())
    assert d["identification"]["status"] == "identified" and d["package_id"] == "s1000d/4.1/official"


def test_document_imported_before_its_schema_is_reidentified_on_open(ctx, tmp_path):
    p = ctx.projects.create("late")
    src = (DOCS / "s1000d_proced_valid.xml").read_text().replace(
        'xsi:noNamespaceSchemaLocation="proced.xsd"',
        'xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd"')
    d = ctx.documents.import_bytes(p["id"], "early.xml", src.encode())
    assert d["identification"]["status"] == "unidentified"          # nothing installed yet
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "late.zip", only=["proced"])
    ctx.registry.install(tmp_path / "late.zip")
    st = ctx.documents.state(d["id"])                                # opening the document
    assert st["document"]["identification"]["status"] == "identified"
    assert st["document"]["package_id"] == "s1000d/4.1/official" and st["document"]["identity"]["display"].startswith("DMC-")



def test_s1000d_issue_url_matches_even_if_the_package_rule_is_odd(ctx, tmp_path):
    """Regression (real 4.1 install): the package's stored pattern did not match
    .../S1000D_4-1/xml_schema_flat/proced.xsd. S1000D URLs are now also matched from the
    package's issue and file name, which fixes already-installed packages too."""
    import json, zipfile
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "o.zip", only=["proced"])
    with zipfile.ZipFile(tmp_path / "o.zip") as z:
        blobs = {n: z.read(n) for n in z.namelist()}
    m = json.loads(blobs["asthra-package.json"])
    m["doc_types"][0]["match"]["schema_location_pattern"] = r"(?i)(^|/)S1000D_4\-1_PatchA/xml_schema_(flat|master)/proced\.xsd$"
    blobs["asthra-package.json"] = json.dumps(m).encode()
    with zipfile.ZipFile(tmp_path / "o2.zip", "w") as z:
        for n, b in blobs.items(): z.writestr(n, b)
    ctx.registry.install(tmp_path / "o2.zip")
    p = ctx.projects.create("odd")
    src = (DOCS / "s1000d_proced_valid.xml").read_text().replace(
        'xsi:noNamespaceSchemaLocation="proced.xsd"',
        'xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd"')
    d = ctx.documents.import_bytes(p["id"], "dm.xml", src.encode())
    assert d["identification"]["status"] == "identified" and d["package_id"] == "s1000d/4.1/official"
    # and a different issue is still not claimed
    d6 = ctx.documents.import_bytes(p["id"], "dm6.xml", src.replace("S1000D_4-1", "S1000D_6").encode())
    assert d6["identification"]["status"] != "identified"


def test_s1000d_location_rule():
    from asthra.identify.service import s1000d_location_matches as f
    assert f("4.1", "xml_schema_flat/proced.xsd", "http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd")
    assert f("6", "proced.xsd", "http://www.s1000d.org/S1000D_6/xml_schema_flat/proced.xsd")
    assert f("4.1", "proced.xsd", r"C:\schemas\S1000D_4-1\xml_schema_master\proced.xsd")
    assert not f("4.1", "proced.xsd", "http://www.s1000d.org/S1000D_4-2/xml_schema_flat/proced.xsd")
    assert not f("4.1", "proced.xsd", "http://www.s1000d.org/S1000D_4-1/xml_schema_flat/descript.xsd")
    assert not f("4.1", "proced.xsd", "proced.xsd")


def test_s1000d_file_with_iso_boilerplate_but_no_entities_still_validates(ctx, tmp_path):
    """Regression (real S1000D 4.2 file): DOCTYPE declares %ISOEntities; -> "ent/ISOEntities", the
    package has no entity files, and the document uses no entities: validate, with a warning."""
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "n.zip", only=["proced"])
    ctx.registry.install(tmp_path / "n.zip")
    p = ctx.projects.create("iso")
    src = _iso_doc().replace("&deg;", "degrees ").replace("&plusmn;", "+/-").replace(
        '"http://www.s1000d.org/S1000D_4-1/ent/ISOEntities"', '"ent/ISOEntities"')
    d = ctx.documents.import_bytes(p["id"], "iso.xml", src.encode())
    rep = ctx.documents.validate(d["id"])
    assert rep.structural_status.value == "passed", [x.message for x in rep.diagnostics]
    w = [x for x in rep.diagnostics if x.rule_id == "ASTHRA-ENT-001"]
    assert w and w[0].severity.value == "warning" and "Choose folder" in w[0].suggestion



def test_missing_entity_set_is_an_error_on_windows_too(ctx, tmp_path, monkeypatch):
    """Regression (Windows): the quick parse there replaces &deg; with a placeholder, so the tree
    showed no entities and a document that uses ISO entities was waved through with a warning."""
    import asthra.identify.service as ident
    real = ident._strict_parse
    def strict_like_windows(data):
        if b"&deg;" in data:
            class E:
                message = "Entity 'deg' not defined"; line = 12; column = 1
            return None, [E()]
        return real(data)
    monkeypatch.setattr(ident, "_strict_parse", strict_like_windows)
    folder = fake_official(tmp_path)
    build_s1000d_package(folder, "4.1", tmp_path / "n.zip", only=["proced"])
    ctx.registry.install(tmp_path / "n.zip")
    p = ctx.projects.create("iso")
    d = ctx.documents.import_bytes(p["id"], "iso.xml", _iso_doc().encode())
    rep = ctx.documents.validate(d["id"])
    assert any(x.rule_id == "ASTHRA-SEC-003" for x in rep.diagnostics)
    assert rep.structural_status.value == "failed"
    assert not any(x.rule_id == "ASTHRA-ENT-001" for x in rep.diagnostics)


def test_uses_entities_reads_the_text():
    from asthra.identify.service import sniff
    from asthra.validation.pipeline import _uses_entities
    doc = lambda body: ('<?xml version="1.0"?>\n<!DOCTYPE d [<!ENTITY % I SYSTEM "ent/ISOEntities"> %I; '
                        '<!ENTITY x "&#176;">]>\n<d>' + body + '</d>').encode()
    assert _uses_entities(doc("20&deg;C"), sniff(doc("20&deg;C")))
    assert not _uses_entities(doc("a &amp; b &lt; c &#176; &#xB0;"), sniff(doc("x")))
    assert not _uses_entities(doc("<!-- &deg; --><![CDATA[&deg;]]>"), sniff(doc("x")))
