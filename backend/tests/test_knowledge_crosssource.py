"""One product written in four sources (ATA CMM, S1000D, S2000M, engineering BOM): the knowledge library
reads the same facts from each, finds nothing when they agree, and finds each planted disagreement."""
from collections import Counter
from pathlib import Path

from lxml import etree

from asthra.knowledge.ata_import import import_manual, split_item, vendor_cage, ident
from asthra.knowledge.engineering import column_map, import_bom
from asthra.knowledge.s1000d_import import import_dm
from asthra.knowledge.s2000m_import import import_exchange
from asthra.knowledge.store import KnowledgeStore

F = Path(__file__).parent / "fixtures" / "knowledge" / "ra7100"
ATA = F / "ATA-iSpec2200-SGML" / "CMM-25-21-71_RA-7100.rendered.xml"   # the .sgm as OpenSP renders it
S2K = F / "S2000M" / "PX-RA7100-0001_provisioning.xml"
BOM = F / "BOM" / "RA-7100_engineering-BOM.csv"


def load(edit=lambda name, text: text) -> KnowledgeStore:
    k = KnowledgeStore()
    x = lambda p: etree.fromstring(edit(p.name, p.read_text(encoding="utf-8")).encode("utf-8"))
    import_manual(k, x(ATA), file=ATA.name)
    for f in sorted((F / "S1000D-4.2").glob("*.XML")):
        import_dm(k, x(f), file=f.name)
    import_exchange(k, x(S2K), file=S2K.name)
    import_bom(k, edit(BOM.name, BOM.read_text(encoding="utf-8")).encode("utf-8"), BOM.name)
    return k


def rules(k):
    return Counter(f["rule"] for f in k.consistency())


def test_conventions():
    assert split_item("50A") == ("050", "A") and split_item("-1") == ("001", "") and split_item("1A") == ("001", "A")
    assert vendor_cage("VZZV02") == "ZZV02" and vendor_cage("96906") == "96906"
    el = etree.fromstring('<task chapnbr="25" sectnbr="21" subjnbr="71" func="000" seq="801" confltr="A" varnbr="1"/>')
    assert ident(el, "TASK") == "TASK 25-21-71-000-801-A01"
    m = column_map(["Find No", "P/N", "Qty", "Parent Part Number", "Mass (kg)"])
    assert m == {"Find No": "find_no", "P/N": "part_number", "Qty": "quantity", "Parent Part Number": "parent", "Mass (kg)": ""}


def test_same_facts_from_every_source():
    k = load()
    lines = k.db.execute("""SELECT s.kind, COUNT(*) FROM catalogue_item c JOIN source s ON s.id=c.source_id GROUP BY s.kind""").fetchall()
    assert dict(lines) == {"ATA-CMM": 16, "S1000D-DM": 16, "S2000M": 16}
    # item 50A: the post-SB spring, same in all three parts lists
    rows = k.db.execute("""SELECT s.kind, p.part_number, c.indenture, c.qty_per_next_assy FROM catalogue_item c
                           JOIN part p ON p.id=c.part_id JOIN source s ON s.id=c.source_id WHERE c.item='050' AND c.item_variant='A'""").fetchall()
    assert {(r[1], r[2], r[3]) for r in rows} == {("RA-7150-2", 2, "1")}
    # ATA tasks carry their tools and consumables
    res = k.db.execute("""SELECT p.part_number FROM information_resource r JOIN part p ON p.id=r.part_id
                          WHERE r.dmc='TASK 25-21-71-400-801-A01' ORDER BY 1""").fetchall()
    assert [r[0] for r in res] == ["ADT-7100-01", "ADT-7100-02", "LOCTITE 242", "MIL-PRF-23827", "TW-0110"]
    # the BOM: structure and CAD attributes
    assert k.db.execute("""SELECT e.quantity FROM part_list_entry e JOIN part a ON a.id=e.parent_id JOIN part c ON c.id=e.child_id
                           WHERE a.part_number='RA-7100-02' AND c.part_number='NAS1352C3-8'""").fetchone()[0] == 4
    assert k.db.execute("""SELECT value FROM part_property pp JOIN part p ON p.id=pp.part_id
                           WHERE p.part_number='RA-7110-1' AND pp.name='Material'""").fetchone()[0] == "AL 7075-T6"


def test_consistent_set_has_no_disagreements():
    assert rules(load()) == Counter({"identity-suggestion": 1})   # ATA parts without a vendor code: suggested, not merged


def test_planted_disagreements_are_found():
    def edit(name, text):
        if name.endswith("941A-C_001-00_EN-US.XML"):        # S1000D: nut quantity 2
            text = text.replace('<quantityPerNextHigherAssy>1</quantityPerNextHigherAssy><partRef manufacturerCodeValue="96906" partNumberValue="MS21042L4"/>',
                                '<quantityPerNextHigherAssy>2</quantityPerNextHigherAssy><partRef manufacturerCodeValue="96906" partNumberValue="MS21042L4"/>')
        if name == S2K.name:                                  # S2000M: wrong packing part number
            text = text.replace("<partNumber>M83248/1-210</partNumber>", "<partNumber>M83248/1-211</partNumber>")
        if name == BOM.name:                                  # BOM: three screws instead of four; a part the IPL lacks
            text = text.replace("1,90,NAS1352C3-8,80205,\"Screw, Cap, Socket Head\",4,", "1,90,NAS1352C3-8,80205,\"Screw, Cap, Socket Head\",3,")
            text += "1,140,RA-7210-1,ZZD01,\"Shim, Housing\",1,EA,All,RA-7100-01; RA-7100-02,Part,Make,0.001,CRES 302,RA-7210-1.step\n"
        return text
    r = rules(load(edit))
    assert r["catalogue-quantity"] == 2          # S1000D vs ATA, S1000D vs S2000M
    assert r["catalogue-part"] == 2              # S2000M vs ATA, S2000M vs S1000D
    assert r["bom-quantity"] >= 2                # screws: each top assembly
    assert r["catalogue-missing-bom-line"] >= 2  # the shim, against each parts list
    assert r["bom-missing"] >= 1                 # S2000M lists M83248/1-211, the BOM does not


def test_reimport_replaces():
    k = load()
    import_bom(k, BOM.read_bytes(), BOM.name)
    import_manual(k, etree.parse(str(ATA)).getroot(), file=ATA.name)
    assert k.db.execute("SELECT COUNT(*) FROM bom_line").fetchone()[0] == 26
    assert k.db.execute("SELECT COUNT(*) FROM catalogue_item").fetchone()[0] == 48
    assert rules(k) == Counter({"identity-suggestion": 1})


def test_engineering_json():
    k = KnowledgeStore()
    data = b'''{"format": "asthra-engineering/1", "source": {"system": "PLM", "document": "EBOM-1", "revision": "B"},
      "items": [{"part_number": "A-1", "cage": "ZZD01", "name": "Assy"},
                {"part_number": "B-2", "cage": "ZZD01", "quantity": 2, "parent": "A-1", "properties": {"mass_kg": 0.5}}]}'''
    r = import_bom(k, data, "ebom.json")
    assert r["lines"] == 2 and r["structure"] == 1 and r["properties"] == 1
    assert k.db.execute("SELECT document, issue FROM source WHERE kind='ENG-BOM'").fetchone()[:] == ("EBOM-1", "B")


def test_engineering_api(tmp_path):
    from fastapi.testclient import TestClient
    from asthra.api.app import create_app
    from asthra.config import Settings
    c = TestClient(create_app(Settings(data_root=tmp_path)), headers={"X-Asthra": "1"})
    r = c.post("/api/knowledge/engineering", files={"file": (BOM.name, BOM.read_bytes(), "text/csv")})
    assert r.status_code == 200 and r.json()["imported"][0]["lines"] == 16
    assert c.get("/api/knowledge/summary").json()["counts"]["BOM lines"] == 26
    bad = c.post("/api/knowledge/engineering", files={"file": ("x.csv", b"Name,Qty\nfoo,1\n", "text/csv")})
    assert bad.status_code == 400 and "part number" in bad.json()["detail"]
