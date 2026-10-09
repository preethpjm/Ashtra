"""Cross-reference: one generic name per piece of data (S-Series common data model), whatever standard it came
from, shown in the words of any standard or installed schema. The data model fixture is synthetic, shaped like
an Enterprise Architect XMI export of an S-Series model."""
from pathlib import Path

import pytest
from lxml import etree

from asthra.crossref.facts import read_document
from asthra.crossref.names import SchemaIndex
from asthra.crossref.vocab import Vocabulary
from asthra.crossref.xmi import inherited_attrs, read_xmi
from asthra.knowledge.engineering import import_bom
from tests.conftest import DOCS, FIX

XR = FIX / "crossref"
MODEL = XR / "synthetic_s3000l_model.xmi"
EXTRACT = XR / "bike_s3000l_extract.xml"
BOM = FIX / "knowledge" / "ra7100" / "BOM" / "RA-7100_engineering-BOM.csv"


def test_xmi_model_is_read_with_xml_names_keys_and_inheritance():
    m = read_xmi(MODEL)
    assert (m["spec"], m["issue"]) == ("S3000L", "2.0")
    hw = m["classes"]["HardwarePartAsDesigned"]
    assert hw["xml"] == "hwPart" and hw["supers"] == ["PartAsDesigned"] and hw["common"]
    attrs = {a["name"]: a for a in inherited_attrs(m, "HardwarePartAsDesigned")}
    assert attrs["partIdentifier"]["xml"] == "partId" and attrs["partIdentifier"]["key"]
    assert attrs["partIdentifier"]["inherited_from"] == "PartAsDesigned"
    assert m["datatypes"]["IdentifierType"]["attrs"][1]["xml"] == "setBy"
    assert "«class»" in m["classes"]["PartAsDesigned"]["doc"]


def test_vocabulary_names_each_term_in_every_standard():
    v = Vocabulary([read_xmi(MODEL)])
    t = v.terms["PartAsDesigned.partIdentifier"]
    assert t["names"]["S3000L 2.0"]["path"] == "part/partId/id" and t["key"]
    assert t["names"]["S1000D"]["tag"] == "partRef/@partNumberValue" and t["names"]["ATA iSpec 2200"]["tag"] == "pnr"
    assert v.terms["PartAsDesigned.partIdentifier.identifierSetBy"]["names"]["S3000L 2.0"]["path"] == "part/partId/setBy"
    assert "ASTHRA:CatalogueItem.figureNumber" in v.terms                  # data the S-Series model does not define
    assert [x["id"] for x in v.search("pnr")][:1] == ["PartAsDesigned.partIdentifier"]


def test_names_resolve_against_an_installed_schema(loaded):
    v = Vocabulary([read_xmi(MODEL)])
    from asthra.crossref.names import schema_names
    key = next(p.manifest.key for p in loaded.registry.list() if p.manifest.standard == "S1000D")
    n = schema_names(v, [], "S1000D", loaded.registry.schema_model(key, "ipd"))
    assert n["PartAsDesigned.partIdentifier"]["path"].endswith("catalogSeqNumber/itemSeqNumber/partRef/@partNumberValue")
    assert n["ASTHRA:CatalogueItem.figureNumber"]["path"].endswith("catalogSeqNumber/@figureNumber")
    s2k = next(p.manifest.key for p in loaded.registry.list() if p.manifest.standard == "S2000M")
    n = schema_names(v, [], "S2000M", loaded.registry.schema_model(s2k, "provisioning"))
    assert n["PartAsDesigned.partIdentifier"]["path"].endswith("part/partNumber") and n["PartAsDesigned.partIdentifier"]["from"].startswith("name match")


def test_any_s_series_document_is_read_through_its_model():
    m = read_xmi(MODEL)
    facts = read_document(m, Vocabulary([m]), etree.parse(str(EXTRACT)).getroot())
    got = {(f["subject"], f["key"], f["term"], f["value"]) for f in facts}
    assert ("Part", "BP-0001|D2635", "PartAsDesigned.partName", "Brake Pad Set") in got
    assert ("BreakdownElement", "B5-A-A7-31-02-00A", "BreakdownElement.breakdownElementName", "SB5 Front Brake Pads") in got
    assert ("Task", "T00002", "TaskRevision.taskName", "Replace Front Brake Pads") in got   # a revision belongs to its task
    assert not any(f["key"] == "PC-1000|PC-1000" for f in facts)                         # a missing CAGE is not invented


@pytest.fixture
def xr(loaded):
    loaded.crossref.add_model("synthetic_s3000l_model.xmi", MODEL.read_bytes())
    return loaded


def test_service_shows_one_item_from_every_source_in_the_chosen_standard(xr, project):
    xr.knowledge.load_bike_example()
    xr.documents.import_path(project["id"], EXTRACT)
    rep = xr.knowledge.import_project(project["id"], include_invalid=True)
    assert any(i.get("kind", "").startswith("S3000L 2.0") and i["facts"] > 10 for i in rep["imported"]), rep
    hits = xr.crossref.subjects("BP-0001")
    assert any(h["subject"] == "Part" and h["label"] == "BP-0001" for h in hits)
    it = xr.crossref.item("Part", "BP-0001", "ATA iSpec 2200")
    rows = {r["term"]: r for r in it["rows"]}
    pn = rows["PartAsDesigned.partIdentifier"]
    assert pn["name"]["tag"] == "pnr"                                          # shown with the ATA name …
    assert {v["read_as"] for v in pn["values"] if v["source"]["document"] == EXTRACT.name} == {"partId"}   # … read from S3000L's
    assert rows["ASTHRA:CatalogueItem.figureNumber"]["name"]["tag"] == "figure/@fignbr"
    name = rows["PartAsDesigned.partName"]
    assert name["conflict"]                                                    # the library and the extract disagree on the name
    s3 = xr.crossref.item("Part", "BP-0001", "S3000L 2.0")
    assert {r["term"] for r in s3["not_in_view"]} >= {"ASTHRA:CatalogueItem.figureNumber"}   # S3000L has no IPD figure
    ov = xr.crossref.overview()
    assert ov["models"][0]["label"] == "S3000L 2.0" and any(v["kind"] == "installed schema" for v in ov["views"])


def test_a_person_can_confirm_where_a_term_sits(xr):
    key = next(p.manifest.key for p in xr.registry.list() if p.manifest.standard == "S2000M")
    view = f"pkg:{key}|provisioning"
    assert xr.crossref.names_for(view, ["PartAsDesigned.partName"]) == {}
    t = xr.crossref.confirm_name(key, "provisioning", "PartAsDesigned.partName", "provisioningExchange/parts/part/description")
    row = next(s for s in t["schemas"] if s["view"] == view)
    assert row["from"] == "confirmed" and row["tag"] == "description"
    xr.knowledge.reset()                                                       # confirmations are settings: they stay
    assert xr.crossref.names_for(view, ["PartAsDesigned.partName"])["PartAsDesigned.partName"]["from"] == "confirmed"


def test_library_data_without_any_model_still_cross_references(loaded):
    import_bom(loaded.knowledge.store, BOM.read_bytes(), BOM.name)
    it = loaded.crossref.item("Part", "RA-7150-2", "S1000D")
    rows = {r["term"]: r for r in it["rows"]}
    assert rows["PartAsDesigned.partIdentifier"]["name"]["tag"] == "partRef/@partNumberValue"
    assert "PartAsDesignedPartsListEntry.partsListEntryQuantity" not in rows          # S1000D has no BOM quantity …
    assert "PartAsDesignedPartsListEntry.partsListEntryQuantity" in {r["term"] for r in it["not_in_view"]}   # … so it is listed apart
    bom = loaded.crossref.item("Part", "RA-7150-2", "Engineering BOM")
    assert {r["name"]["tag"] for r in bom["rows"]} >= {"Part Number", "Qty", "Find No"}


def test_schema_index_resolves_relative_paths():
    m = {"root": "a", "elements": {"a": {"content": {"k": "seq", "items": [{"k": "el", "n": "b"}]}, "attrs": []},
                                   "b": {"content": {"k": "seq", "items": [{"k": "el", "n": "c"}]}, "attrs": [{"name": "x"}]},
                                   "c": {"content": None, "text": True, "attrs": []}}}
    i = SchemaIndex(m)
    assert i.resolve("b/c")[0]["path"] == "a/b/c" and i.resolve("b/@x")[0]["path"] == "a/b/@x"
    assert i.resolve("@x")[0]["path"] == "a/b/@x" and i.resolve("nope") == [] and i.resolve("pnr (V + CAGE)") == []


# ---------------------------------------------------------------- coverage, prompts and review
def test_coverage_says_what_each_standard_still_needs(xr, project):
    xr.documents.import_path(project["id"], EXTRACT)                   # an S3000L document, its XSD not installed
    xr.documents.import_path(project["id"], RA4 := FIX / "knowledge" / "ra7100" / "S1000D-4.2" /
                             "DMC-ASTDEMO-A-25-21-71-00A-941A-C_001-00_EN-US.XML")   # S1000D 4.2: only a synthetic 5.0 installed
    cov = {r["standard"]: r for r in xr.crossref.coverage()["standards"]}
    s3 = cov["S3000L"]                                                 # model loaded; only a synthetic S3000L-style schema installed
    assert s3["model"] and s3["schemas"] and s3["documents"] == 1 and s3["unidentified"] == [EXTRACT.name]
    assert s3["actions"][0]["do"] == "install_schema" and "s3000l/downloads" in s3["where"]["url"]
    assert s3["schemas"][0]["placed"] >= 2 and s3["schemas"][0]["review"] >= 2       # found by name in the synthetic schema
    s2 = cov["S2000M"]
    assert s2["schemas"] and not s2["model"] and {a["do"] for a in s2["actions"]} == {"add_model", "review"}
    s1 = cov["S1000D"]                                                 # 4.2 not installed: the closest installed issue is offered
    choose = next(a for a in s1["actions"] if a["do"] == "choose_schema")
    assert s1["unchosen"] == [RA4.name] and not s1["unidentified"] and not choose["certain"] and choose["doc_type"] == "ipd"
    waiting = {w["name"]: w for w in xr.crossref.coverage()["waiting"]}
    assert "S3000L" in waiting[EXTRACT.name]["message"] and "XML schema" in waiting[EXTRACT.name]["message"]
    assert "closest installed" in waiting[RA4.name]["message"] and waiting[RA4.name]["choose"]["doc_type"] == "ipd"
    hints = xr.crossref.hints("S2000M")
    assert any("data model (XMI)" in h for h in hints) and any("review" in h for h in hints)


def test_review_lists_uncertain_placements_with_alternatives_and_saves_them(xr):
    key = next(p.manifest.key for p in xr.registry.list() if p.manifest.standard == "S2000M")
    view = f"pkg:{key}|provisioning"
    rv = xr.crossref.review(view)
    rows = {r["term"]: r for r in rv["rows"]}
    pn = rows["PartAsDesigned.partIdentifier"]
    assert pn["status"] == "review" and pn["placement"]["path"].endswith("part/partNumber")
    name = rows["PartAsDesigned.partName"]
    assert name["status"] == "missing" and name["candidates"][0].endswith("part/nomenclature")
    assert rows["ASTHRA:CatalogueItem.figureNumber"]["candidates"][0].endswith("ipdItem/figureNumber")
    rv = xr.crossref.confirm_many(key, "provisioning", [
        {"term": "PartAsDesigned.partIdentifier", "path": pn["placement"]["path"]},
        {"term": "PartAsDesigned.partName", "path": name["candidates"][0]},
        {"term": "BreakdownElement.breakdownElementName", "path": "-"}])
    rows = {r["term"]: r for r in rv["rows"]}
    assert rows["PartAsDesigned.partIdentifier"]["status"] == "confirmed" and rows["PartAsDesigned.partName"]["status"] == "confirmed"
    assert rows["BreakdownElement.breakdownElementName"]["status"] == "none"
    cov = {r["standard"]: r for r in xr.crossref.coverage()["standards"]}
    assert cov["S2000M"]["schemas"][0]["confirmed"] == 2


def test_guessing_the_standard_of_unrecognised_documents():
    from asthra.crossref.coverage import guess_standard
    assert guess_standard({"root": {"local_name": "dmodule"}}) == "S1000D"
    assert guess_standard({"root": {"local_name": "CMM", "public_id": "-//ATA-TEXT//DTD CMM-VER3-LEVEL2//EN"}}) == "ATA2200"
    assert guess_standard({"root": {"local_name": "x", "schema_location": "http://www.s-series.org/s3000l/2.0/xsd"}}) == "S3000L"
    m = read_xmi(MODEL)
    assert guess_standard({"root": {"local_name": "lsaDataSet"}}, {"be", "beId", "hwPart", "partId", "task"}, [m]) == "S3000L"
    assert guess_standard({"root": {"local_name": "foo"}}, {"foo", "bar"}, [m]) is None


def test_same_file_in_several_projects_is_listed_once_and_assigned_in_one_go(xr):
    a, b = xr.projects.create("A"), xr.projects.create("B")
    ra4 = FIX / "knowledge" / "ra7100" / "S1000D-4.2" / "DMC-ASTDEMO-A-25-21-71-00A-941A-C_001-00_EN-US.XML"
    ids = [xr.documents.import_path(p["id"], ra4)["id"] for p in (a, b)]
    w = [x for x in xr.crossref.coverage()["waiting"] if x["name"] == ra4.name]
    assert len(w) == 1 and sorted(w[0]["ids"]) == sorted(ids) and sorted(w[0]["projects"]) == ["A", "B"]
    c = w[0]["choose"]
    r = xr.crossref.assign_schemas([{"doc_id": i, "package_id": c["package_id"], "doc_type": c["doc_type"]} for i in w[0]["ids"]])
    assert r["assigned"] == 2 and not r["failed"]
    assert all(xr.documents.get(i)["package_id"] == c["package_id"] for i in ids)
    assert not [x for x in xr.crossref.coverage()["waiting"] if x["name"] == ra4.name]
    hint = xr.crossref.doc_hint({**xr.documents.get(ids[0])})
    assert hint is None                                                     # nothing left to do for it


def test_a_confirmation_applies_to_every_schema_of_the_standard_where_the_place_exists(xr):
    key = next(p.manifest.key for p in xr.registry.list() if p.manifest.standard == "S1000D")
    path = "dmodule/identAndStatusSection/dmAddress/dmIdent/dmCode/@modelIdentCode"
    rv = xr.crossref.confirm_many(key, "descript", [{"term": "ASTHRA:Part.unitOfIssue", "path": "-"},
                                                    {"term": "Product.productIdentifier", "path": path}])
    assert rv["applied_elsewhere"] == 2                                      # procedure and IPD too
    for dt in ("proced", "ipd"):
        rows = {r["term"]: r for r in xr.crossref.review(f"pkg:{key}|{dt}")["rows"]}
        assert rows["ASTHRA:Part.unitOfIssue"]["status"] == "none"
        assert rows["Product.productIdentifier"]["status"] in ("ok", "confirmed")   # already certain there: left as it was
        assert rows["Product.productIdentifier"]["placement"]["path"] == path
    rv = xr.crossref.confirm_many(key, "descript", [{"term": "Task.taskIdentifier", "path": path}], whole_standard=False)
    assert rv["applied_elsewhere"] == 0


# ---------------------------------------------------------------- a specification that only references the common model
S2K_MODEL = XR / "synthetic_s2000m_model.xmi"
S2K_EXTRACT = XR / "s2000m_ipd_extract.xml"


def test_a_spec_referencing_common_classes_gets_their_names_and_reads_ipd_lines():
    s3, s2 = read_xmi(MODEL), read_xmi(S2K_MODEL)
    assert s2["classes"]["HardwarePartAsDesigned"]["attrs"] == []                 # only referenced
    assert s2["classes"]["Figure"]["attrs"][0]["type"] == "IdentifierType"         # type named in the EA extension
    v = Vocabulary([s3, s2])
    pn = v.terms["PartAsDesigned.partIdentifier"]["names"]["S2000M 7.0"]
    assert pn["path"] == "hwPart/partId/id" and pn["from"] == "data model (common model)"
    assert v.terms["PartAsDesigned.partIdentifier.identifierSetBy"]["names"]["S2000M 7.0"]["path"] == "hwPart/partId/setBy"
    assert v.terms["ASTHRA:CatalogueItem.itemNumber"]["names"]["S2000M 7.0"]["path"] == "figItem/figItemId/id"
    assert v.terms["ASTHRA:CatalogueItem.quantityPerNextHigherAssembly"]["names"]["S2000M 7.0"]["tag"] == "qna"
    facts = read_document(s2, v, etree.parse(str(S2K_EXTRACT)).getroot())
    by = {}
    for f in facts:
        by.setdefault(f["key"], {})[f["term"]] = f["value"]
    spring, screw = by["RA-7150-2|ZZV02"], by["NAS1352C3-8|80205"]
    assert spring["ASTHRA:CatalogueItem.itemNumber"] == "050A" and spring["ASTHRA:CatalogueItem.quantityPerNextHigherAssembly"] == "1"
    assert spring["ASTHRA:CatalogueItem.figureNumber"] == "01" and screw["ASTHRA:CatalogueItem.figureNumber"] == "01"
    assert screw["ASTHRA:CatalogueItem.itemNumber"] == "060" and screw["ASTHRA:CatalogueItem.quantityPerNextHigherAssembly"] == "4"
    assert spring["PartAsDesigned.partName"] == "SPRING, COMPRESSION, HIGH RATE"


def test_the_reference_model_is_not_reported_as_missing_its_schema(xr):
    xr.crossref.add_model("synthetic_s2000m_model.xmi", S2K_MODEL.read_bytes())
    cov = {r["standard"]: r for r in xr.crossref.coverage()["standards"]}
    assert cov["S3000L"]["hub"] and not cov["S2000M"]["hub"]


def test_borrowed_and_suggested_places_must_sit_inside_their_class():
    from asthra.crossref.names import in_context, plausible
    assert in_context("Organization.organizationIdentifier", "mmDataset/invoiceCont/org/orgId/id")
    assert in_context("MaintenanceLevel.maintenanceLevelIdentifier", "ips/productData/maintenanceLevels/mlv/mlvId/id")
    assert in_context("PartAsDesigned.partIdentifier", "lsaDataset/parts/hwPart/partId/id")
    assert not plausible("PartAsDesigned.partName", "ips/secs/sec/secClassDefRef/secClass/name")      # security marking
    assert not plausible("ASTHRA:Part.unitOfIssue", "ips/projAttrs/projAttr/circle/circDiam/unit")    # a measurement unit
    assert not in_context("Task.taskIdentifier", "mmDataset/Signature/KeyInfo/KeyName")              # XML signature
    assert not in_context("TaskRevision.taskDuration", "mmDataset/msgDate/time")                     # message header
    assert not in_context("ASTHRA:CatalogueItem.figureNumber",
                          "dmodule/content/description/figure/graphic/hotspot/catalogSeqNumberRef/@figureNumber")  # a reference
    assert not in_context("ASTHRA:Part.unitOfIssue", "dmodule/identAndStatusSection/dmAddress/dmIdent/issueInfo/@issueNumber")
    assert plausible("PartAsDesigned.partIdentifier", "x/part/partNumber")                           # distinctive leaf


def test_waiting_document_without_a_named_schema_says_so(xr, project):
    d = xr.documents.import_path(project["id"], FIX / "knowledge" / "ra7100" / "S1000D-4.2" /
                                 "DMC-ASTDEMO-A-25-21-71-00A-941A-C_001-00_EN-US.XML")
    opt = {"declared": False}
    named = xr.crossref._choose_message(d, opt, "X 1 · y", "use it")
    blank = {**d, "identification": {"root": {"local_name": "cmm"}}}
    assert "does not name its schema" in xr.crossref._choose_message(blank, opt, "X 1 · y", "use it")
    assert ("declares" in named) == xr.crossref._names_schema(d)
