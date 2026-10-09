"""The schema-driven translator: bindings proposed from whatever schema is installed (XSD or SGML DTD), parts lists
built from the engineering BOM or from another standard's parts list, written into documents that still validate,
and read back through the same binding. Fixtures are synthetic."""
import json
import shutil
from pathlib import Path

import pytest
from lxml import etree

from asthra.knowledge.ata_import import import_manual
from asthra.registry import installer
from asthra.translate.extract import extract
from asthra.translate.markup import scan
from asthra.translate.propose import propose
from asthra.translate.service import TranslateError, check_binding
from asthra.translate.values import read, write
from asthra.validation.sgml import find_tools, probe
from tests.conftest import DOCS, FIX

RA = FIX / "knowledge" / "ra7100"
BOM = RA / "BOM" / "RA-7100_engineering-BOM.csv"
IPL = FIX / "sgml" / "ata-ipl-synth"
_tools = find_tools()
needs_opensp = pytest.mark.skipif(_tools is None or not probe(_tools)[0], reason="OpenSP not installed")
TOPS = {"kind": "engineering", "tops": ["RA-7100-01", "RA-7100-02"]}
OWN = {"omit_cage": ["ZZD01", "96906", "80205", "81349"]}


@pytest.fixture
def ipl(loaded, tmp_path):
    prop = installer.inspect(IPL)
    prop["standard"], prop["issue"] = "ATA2200", "synthetic-ipl"
    for t in prop["doc_types"]:
        t["root"] = "cmm"
    loaded.registry.install(installer.build(IPL, prop, tmp_path / "ipl.zip"))
    return loaded


def _key(ctx, doc_type, standard):
    return next(p.manifest.key for p in ctx.registry.list() if p.manifest.standard == standard
                and any(d.id == doc_type for d in p.manifest.doc_types))


# ---------------------------------------------------------------- proposals from the schema alone
def test_binding_proposed_from_an_xsd(loaded):
    m = loaded.registry.schema_model(_key(loaded, "ipd", "S1000D"), "ipd")
    b = propose(m)
    assert b["record"] == "catalogSeqNumber" and b["container"] == ["dmodule", "content", "illustratedPartsCatalog"]
    f = {k: v["path"] for k, v in b["fields"].items()}
    assert f["part_number"] == "itemSeqNumber/partRef/@partNumberValue"
    assert f["cage"] == "itemSeqNumber/partRef/@manufacturerCodeValue"
    assert f["quantity"] == "itemSeqNumber/quantityPerNextHigherAssy" and f["item"] == "@item"
    assert b["fields"]["item"]["format"] == "pad3_join" and not b["problems"]
    assert check_binding(m, b) == []


def test_binding_proposed_from_an_sgml_dtd(ipl):
    m = ipl.registry.schema_model(_key(ipl, "cmm", "ATA2200"), "cmm")
    b = propose(m)
    assert b["record"] == "itemdata" and b["container"] == ["cmm", "ipl", "dplist", "figure", "prtlist"]
    assert b["group"]["element"] == "figure" and b["group"]["attr"] == "fignbr"
    fmt = {k: (v["path"], v.get("format")) for k, v in b["fields"].items()}
    assert fmt["item"] == ("@itemnbr", "join_variant") and fmt["indenture"] == ("@indent", "zero_based")
    assert fmt["quantity"] == ("upa", "rf_top") and fmt["cage"] == ("iplnom/mfr", "vendor_v")
    assert fmt["name"] == ("iplnom/nom/kwd", "split_kwd_adt") and fmt["not_illustrated"] == ("@illusind", "invert01")


def test_a_schema_without_a_parts_list_says_so(loaded):
    m = loaded.registry.schema_model(_key(loaded, "descript", "S1000D"), "descript")
    b = propose(m)
    assert b["record"] is None and "no parts list" in b["problems"][0]


def test_edited_bindings_are_checked_against_the_schema(loaded):
    m = loaded.registry.schema_model(_key(loaded, "ipd", "S1000D"), "ipd")
    b = propose(m)
    b["fields"]["name"] = {"path": "itemSeqNumber/nomenclature"}
    b["container"] = ["dmodule", "illustratedPartsCatalog"]
    probs = check_binding(m, b)
    assert any("nomenclature" in p for p in probs) and any("cannot be inside" in p for p in probs)


# ---------------------------------------------------------------- values and markup
def test_conventions_round_trip():
    rec = {"item": "050", "item_variant": "A", "indenture": 2, "quantity": "1", "cage": "ZZV02", "top": False,
           "not_illustrated": False, "name": "Spring, Compression"}
    assert write("item", "join_variant", rec, {}) == ["50A"] and write("item", "pad3_join", rec, {}) == ["050A"]
    assert write("indenture", "zero_based", rec, {}) == ["1"] and write("cage", "vendor_v", rec, {}) == ["VZZV02"]
    assert write("cage", "vendor_v", rec, {"omit_cage": ["ZZV02"]}) is None
    assert write("quantity", "rf_top", dict(rec, top=True), {}) == ["RF"]
    assert write("not_illustrated", "invert01", rec, {}) == ["1"]
    assert write("name", "", rec, {"uppercase_names": True}) == ["SPRING, COMPRESSION"]
    assert read("item", "join_variant", "50A") == {"item": "050", "item_variant": "A"}
    assert read("indenture", "zero_based", "1") == {"indenture": 2}
    assert read("quantity", "rf_top", "RF") == {"quantity": "1", "top": True}
    assert read("cage", "vendor_v", "VZZV02") == {"cage": "ZZV02"}


def test_scanner_understands_omitted_end_tags():
    text = (DOCS / "ata_ipl_sgml.sgm").read_text()
    text = text.replace("<UPA>RF\n", "<UPA>RF\n<ITEMDATA ITEMNBR=10><PNR>OLD-2<IPLNOM><NOM><KWD>X<UPA>1\n")
    allowed = {"prtlist": {"itemdata"}, "itemdata": {"pnr", "iplnom", "effcode", "upa"}, "pnr": set(), "iplnom": {"nom", "mfr", "msc"},
               "nom": {"kwd", "adt"}, "kwd": set(), "upa": set(), "title": set()}
    found = scan(text, ["cmm", "ipl", "dplist", "figure", "prtlist"], "itemdata", {"sheet"}, allowed)
    assert len(found) == 1 and found[0]["path_attrs"][3]["fignbr"] == "1"
    recs = [text[a:b] for a, b in found[0]["records"]]
    assert len(recs) == 2 and recs[0].endswith("<UPA>RF") and "OLD-2" in recs[1]


# ---------------------------------------------------------------- engineering BOM → documents
def _bom(ctx):
    ctx.knowledge.import_engineering(BOM.name, BOM.read_bytes())


def test_rules_shape_the_parts_list(loaded):
    _bom(loaded)
    got = loaded.translate.records(TOPS, OWN)
    recs = got["records"]
    assert [(r["item"], r["item_variant"]) for r in recs[:2]] == [("001", ""), ("001", "A")]
    assert [r["effectivity"] for r in recs[:2]] == ["A", "B"]
    spring = [r for r in recs if r["part_number"].startswith("RA-715")]
    assert [(r["item"], r["item_variant"], r["effectivity"]) for r in spring] == [("050", "", "A"), ("050", "A", "B")]
    assert len(recs) == 16 and not got["excluded"]
    got = loaded.translate.records(TOPS, dict(OWN, exclude=["^NAS"]))
    assert len(got["records"]) == 14 and {e["part_number"] for e in got["excluded"]} == {"NAS1352C3-8", "NAS1149C0363R"}
    with pytest.raises(TranslateError, match="not in the library"):
        loaded.translate.records({"kind": "engineering", "tops": ["NOPE-1"]}, None)


def test_generate_into_an_s1000d_ipd_from_the_bom(loaded, project):
    _bom(loaded)
    d = loaded.documents.import_path(project["id"], DOCS / "s1000d_ipd_valid.xml")
    tr = loaded.translate
    b = tr.binding(d["package_id"], d["doc_type"])
    assert not b["saved"] and b["binding"]["record"] == "catalogSeqNumber" and b["slots"]
    tr.save_binding(d["package_id"], d["doc_type"], b["binding"])
    assert tr.binding(d["package_id"], d["doc_type"])["saved"]
    out = tr.generate(d["id"], TOPS, dict(OWN, figure="1"))
    assert out["report"]["written"] == 16 and out["report"]["groups"][0]["replaced"] == 2 and not out["report"]["warnings"]
    assert out["document"]["structural"] == "passed", out["document"]["errors"]
    new = loaded.documents.source_text(out["document"]["id"])
    assert "<dmTitle><techName>Main landing gear</techName>" in new            # the rest of the document is untouched
    assert 'item="050A"' in new and 'itemSeqNumberValue="00A"' in new           # the value every existing line used
    assert 'partNumberValue="RA-7150-2"' in new and "SS-1000-1" not in new
    # read back through the same binding
    root = etree.fromstring(new.encode())
    recs = extract(root, tr.saved_binding(d["package_id"], d["doc_type"]))
    assert len(recs) == 16 and (recs[7]["item"], recs[7]["item_variant"], recs[7]["part_number"]) == ("050", "A", "RA-7150-2")
    res = tr.read_document(loaded.documents.get(out["document"]["id"]), root)
    assert res["imported"] and res["catalogue"] == 16


def test_generate_reports_what_it_cannot_place(loaded, project):
    _bom(loaded)
    text = (DOCS / "s1000d_ipd_valid.xml").read_text()
    a, b = text.index("<illustratedPartsCatalog>"), text.index("</illustratedPartsCatalog>") + len("</illustratedPartsCatalog>")
    d = loaded.documents.import_bytes(project["id"], "no-ipc.xml", (text[:a] + text[b:]).encode())
    out = loaded.translate.generate(d["id"], TOPS, OWN)
    assert out["report"]["written"] == 0 and "illustratedPartsCatalog" in out["report"]["problems"][0] and out["document"] is None


def test_translate_an_ata_parts_list_into_s1000d(loaded, project):
    """A parts list already in the library (from the ATA CMM) written into an S1000D IPD."""
    import_manual(loaded.knowledge.store, etree.parse(str(RA / "ATA-iSpec2200-SGML" / "CMM-25-21-71_RA-7100.rendered.xml")).getroot(),
                  file="cmm")
    pl = loaded.translate.sources()["parts_lists"]
    src = next(p for p in pl if p["kind"] == "ATA-CMM")
    d = loaded.documents.import_path(project["id"], DOCS / "s1000d_ipd_valid.xml")
    out = loaded.translate.generate(d["id"], {"kind": "catalogue", "source_id": src["source_id"], "figure": src["figure"],
                                              "renumber_figure": True}, {"figure": "01"})
    assert out["report"]["written"] == 16 and out["document"]["structural"] == "passed"
    new = loaded.documents.source_text(out["document"]["id"])
    assert "<descrForPart>SPRING, COMPRESSION, HIGH RATE</descrForPart>" in new


def test_bindings_and_rules_survive_a_library_reset(loaded):
    k = _key(loaded, "ipd", "S1000D")
    loaded.translate.save_binding(k, "ipd", loaded.translate.binding(k, "ipd")["binding"])
    loaded.translate.save_rules({"exclude": ["^MIL-"], "nonsense": 1})
    loaded.knowledge.reset()
    assert loaded.translate.saved_binding(k, "ipd") and loaded.translate.rules()["exclude"] == ["^MIL-"]
    assert "nonsense" not in loaded.translate.rules()
    with pytest.raises(TranslateError):
        loaded.translate.save_binding(k, "ipd", {"record": "catalogSeqNumber", "container": ["dmodule"], "fields": {}})


@needs_opensp
def test_generate_into_sgml_keeps_it_valid(ipl):
    _bom(ipl)
    p = ipl.projects.create("ipl")
    d = ipl.documents.import_path(p["id"], DOCS / "ata_ipl_sgml.sgm")
    assert d["standard"] == "ATA2200" and d["syntax"] == "sgml"
    out = ipl.translate.generate(d["id"], TOPS, dict(OWN, uppercase_names=True))
    assert out["report"]["written"] == 16 and out["report"]["groups"] == [{"figure": "1", "lines": 16, "replaced": 1}]
    assert out["document"]["structural"] == "passed", out["document"]["errors"]
    new = ipl.documents.source_text(out["document"]["id"])
    assert new.startswith('<!DOCTYPE CMM PUBLIC "-//ASTHRA//DTD Synthetic ATA-style IPL SGML//EN">')
    assert '<itemdata itemnbr="50A" indent="1"' in new and "<kwd>SPRING</kwd><adt>COMPRESSION, HIGH RATE</adt>" in new
    assert "<mfr>VZZV02</mfr>" in new and "<mfr>VZZD01</mfr>" not in new and "<upa>RF</upa>" in new
    assert "OLD-1" not in new and "<SHEET GNBR=\"ICN-RA-7100-01\">" in new
    # a second figure that is not in the document is reported, not invented
    out = ipl.translate.generate(d["id"], TOPS, dict(OWN, figure="2"))
    assert out["report"]["written"] == 0 and "Figure 2 is not in the document" in out["report"]["problems"][0]
