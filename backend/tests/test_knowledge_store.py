"""The knowledge model holds the S-Series Bike example end to end and answers cross-specification questions."""
from asthra.knowledge.store import KnowledgeStore
from tests.fixtures.knowledge.bike_uf2024 import load


def bike():
    return load(KnowledgeStore())


def test_bei_links_breakdown_ipc_and_data_modules():
    k = bike()
    rows = k.db.execute("""SELECT i.dmc FROM information_item i JOIN breakdown_element b ON b.bei = i.bei
                           WHERE b.name = 'SB5 Front Brake Pads' ORDER BY i.dmc""").fetchall()
    assert [r[0] for r in rows] == ["B5-A-A7-31-02-00A-520A-D", "B5-A-A7-31-02-00A-720A-D", "B5-A-A7-31-02-00A-921A-D"]
    fig = k.db.execute("SELECT figure, item FROM catalogue_item c JOIN part p ON p.id=c.part_id WHERE p.part_number='BP-0001'").fetchone()
    assert tuple(fig) == ("03", "007")


def test_impact_of_replacing_the_brake_pads():
    imp = bike().impact_of_part("BP-0001")
    assert imp["breakdown_elements"] == ["B5-A-A7-31-02-00A"]
    assert {(t["id"], t["revision"]) for t in imp["tasks"]} == {("T00002", "1.0")}
    assert "B5-A-A7-31-02-00A-921A-D" in imp["data_modules"] and "B5-A-B3-51-01-00A-520A-D" in imp["data_modules"]
    assert imp["catalogue"][0]["smr_code"] == "PAOZZ"
    assert imp["used_in"] == [{"part_number": "FBA-0001", "quantity": 1.0}]
    assert imp["superseded_by"] == [{"part_number": "BP-0002", "change_id": "CH1602", "interchangeability": None}]


def test_procedure_requirements_come_from_the_lsa():
    pre = bike().procedure_requirements("T00002", "1.0")
    assert pre["persons"] == 1 and pre["skill_levels"] == ["A-Basic"] and pre["trades"] == ["MECH"]
    assert pre["support_equipment"] == ["5mm allen key (ALLKEY5MM)", "Bike stand special tool (BST-001)", "Pliers (PLI-001)"]
    assert pre["supplies"] == ["Paper cloth (PC-1000)"] and "Brake pad set (contains 2 parts) (BP-0001)" in pre["spares"]
    assert pre["steps"][0] == "Remove front wheel (refer to B5-A-B3-51-01-00A-520A-D)" and len(pre["steps"]) == 6
    post = bike().procedure_requirements("T00002", "2.0")
    assert len(post["steps"]) == 8 and "Graphite gliding paste (MOLYKOTEBR2 Plus)" in post["supplies"]
    assert post["warnings"] and post["cautions"]                        # the two new safety statements


def test_consistency_findings_in_the_example_itself():
    f = bike().consistency()
    rules = {x["rule"]: x for x in f}
    assert rules["maintenance-level"]["values"] == {"lsa": "ML1", "dm": "ML2"}          # LSA table vs data module
    assert sum(x["rule"] == "maintenance-level" for x in f) == 1                         # current revision only
    assert not any(x["rule"] == "task-duration" for x in f)                              # rev 2.0: 25 min = 25 min
    assert not any(x["rule"] == "superseded-part" for x in f)                            # rev 2.0 uses the new parts
    assert all(x["rule"] != "unknown-data-module" for x in f)


def test_superseded_part_is_flagged_when_the_newest_task_still_uses_it():
    k = bike()
    k.db.execute("DELETE FROM task WHERE id='T00002' AND revision='2.0'")
    f = k.consistency()
    assert any(x["rule"] == "superseded-part" and "BP-0001" in x["message"] for x in f)


def test_in_service_chain():
    k = bike()
    chain = k.db.execute("""SELECT e.id, s.id, i.id, c.id, b.id FROM event e
                            JOIN safety_issue s ON s.event_id = e.id
                            JOIN safety_instruction i ON i.safety_issue_id = s.id
                            JOIN design_change c ON c.safety_issue_id = s.id
                            JOIN service_bulletin b ON b.change_id = c.id""").fetchone()
    assert tuple(chain) == ("EV2347", "SISS20220730A", "SIN20220803A", "CH1602", "SB1607")


def test_duration_finding_for_the_original_revision():
    k = bike()
    k.db.execute("DELETE FROM task WHERE id='T00002' AND revision='2.0'")
    assert any(x["rule"] == "task-duration" and x["values"]["lsa"] == 19 for x in k.consistency())   # 3+3+2+5+4+2 vs 25 min
