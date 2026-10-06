"""The S-Series "Bike example" (S-Series User Forum 2024, "End-to-end IPS Business Process"),
front brake system, loaded into the knowledge model. Only facts shown in the presentation."""
from ..store import KnowledgeStore

BE = [  # BEI, name, type, parent, LSA candidate, realising part
    ("B5-A-00-00-00-00A", "Yeti SB5 Beti Assembly214", "product", None, "full", "YBA-001"),
    ("B5-A-A7-00-00-00A", "SB5 Transmission System", "system", "B5-A-00-00-00-00A", "none", None),
    ("B5-A-A7-30-00-00A", "SB5 Brake System", "subsystem", "B5-A-A7-00-00-00A", "none", None),
    ("B5-A-A7-31-00-00A", "SB5 Front Brake System", "sub-subsystem", "B5-A-A7-30-00-00A", "full", "FBA-0001"),
    ("B5-A-A7-31-01-00A", "SB5 Front Brake Caliper", "equipment", "B5-A-A7-31-00-00A", "full", "FBCL-0001"),
    ("B5-A-A7-31-02-00A", "SB5 Front Brake Pads", "equipment", "B5-A-A7-31-00-00A", "full", "BP-0001"),
    ("B5-A-A7-31-05-00A", "SB5 Wheel Brake Disk", "equipment", "B5-A-A7-31-00-00A", "full", "WBD-0001"),
    ("B5-A-B3-51-00-00A", "SB5 Wheel Assembly Front", "sub-subsystem", None, "full", None),
]
PARTS = [  # part number, NCAGE, name, type
    ("YBA-001", "B6865", "Mountain bike", "part"), ("FBA-0001", "B6865", "Front wheel brake", "part"),
    ("FBCL-0001", "H1T06", "Brake caliper", "part"), ("BP-0001", "D2635", "Brake pad set (contains 2 parts)", "part"),
    ("WBD-0001", "H1T06", "Brake disk assy", "part"), ("WBDP-0001", "H1T06", "Brake disk plate", "component"),
    ("WBDL-0001", "H1T06", "Brake disk lock", "component"), ("WBDB-0001", "H1T06", "Wheel brake disk bolt", "component"),
    ("ISO4762-MAX40-STEEL 10.9", "I9006", "Front brake pad bolt", "part"),
    ("PC-1000", "", "Paper cloth", "consumable"), ("BST-001", "", "Bike stand special tool", "support-equipment"),
    ("ALLKEY5MM", "", "5mm allen key", "support-equipment"), ("PLI-001", "", "Pliers", "support-equipment"),
    # post mod
    ("FBA-0002", "B6865", "Front brake system (new pad bolt)", "part"), ("BP-0002", "D2635", "Front brake pads (new bolt)", "part"),
    ("ISO4762-M4X40-A2", "I9006", "Front brake pad bolt (corrosion-free)", "part"),
    ("MOLYKOTEBR2 Plus", "", "Graphite gliding paste", "consumable"), ("EXXOL D60", "", "Naphtha aliphatic", "consumable"),
]
STEPS_V1 = [  # id, description, DM, duration
    ("T00002-01", "Remove front wheel", "B5-A-B3-51-01-00A-520A-D", 3),
    ("T00002-02", "Remove old Front Brake Pads", "B5-A-A7-31-02-00A-520A-D", 3),
    ("T00002-03", "Clean both caliper surfaces with paper cloth", None, 2),
    ("T00002-04", "Install new Front Brake Pads", "B5-A-A7-31-02-00A-720A-D", 5),
    ("T00002-05", "Install front wheel", "B5-A-B3-51-01-00A-720A-D", 4),
    ("T00002-06", "Test Front Brake System", "B5-A-A7-31-00-00A-320A-D", 2),
]
STEPS_V2 = [
    ("T00002-01", "Remove front wheel", "B5-A-B3-51-01-00A-520A-D", 3),
    ("T00002-02", "Remove old Front Brake Pads", "B5-A-A7-31-02-00A-520A-D", 3),
    ("T00002-03", "Clean caliper inside surfaces and rotor with paper cloth and appropriate detergent", None, 3),
    ("T00002-04", "Grease gliding surfaces of the brake pad bolt, the brake pads and the caliper housing", None, 3),
    ("T00002-05", "Install new Front Brake Pads", "B5-A-A7-31-02-00A-720A-D", 5),
    ("T00002-06", "Install front wheel", "B5-A-B3-51-01-00A-720A-D", 4),
    ("T00002-07", "Clean brake disc and brake pads with paper cloth and appropriate detergent", None, 2),
    ("T00002-08", "Test Front Brake System", "B5-A-A7-31-00-00A-320A-D", 2),
]


def load(k: KnowledgeStore) -> KnowledgeStore:
    sx = k.source("SX000i", "Mbike programme data", note="UF2024 Bike example")
    lsa = k.source("S3000L", "Mbike LSA dataset", schema="S3000L 2.0")
    ipc = k.source("S2000M", "Mbike IPC fig 03", schema="S2000M 7.0")
    dm = k.source("S1000D-DM", "B5-A-A7-31-02-00A-921A-D", issue="001-00")
    mod = k.source("S3000L", "Mbike LSA dataset (post mod CH1602)", schema="S3000L 2.0")
    ins = k.source("S5000F", "Mbike in-service data")

    k.add("organization", id="Yeti", name="Yeti", description="Developer and manufacturer", source_id=sx)
    k.add("organization", id="MF", name="Müller Fahrräder", description="Manufacturer under licence", source_id=sx)
    k.add("organization", id="SBH3", name="Schultz Bike Hire", description="Bike hiring company", source_id=sx)
    k.add("organization_code", code="B6865", organization_id="Yeti")
    k.add("organization_role", organization_id="Yeti", role="manufacturer", product_id="YB")
    k.add("organization_role", organization_id="MF", role="licensee", product_id="YB")
    k.add("organization_role", organization_id="SBH3", role="operator", product_id="YB")
    k.add("project", id="Mbike", name="Mountain Bike", duration="1 year", source_id=sx)
    for code, name in [("ML1", "User on bike"), ("ML2", "User garage"), ("ML3", "Bike shop"), ("ML4", "Bike manufacturer")]:
        k.add("maintenance_level", code=code, name=name)
    k.add("trade", code="MECH", name="Mechanics"); k.add("trade", code="ELEC", name="Electronics")
    k.add("skill_level", code="A-Basic", name="Basic")
    k.add("operational_scenario", id="cycling", name="Cycling", hours_per_year=400)
    k.add("product", id="YB", name="Yeti Beti", model_ident_code="B5", project_id="Mbike", source_id=sx)
    k.add("product_variant", id="YBSB5", product_id="YB", name="Yeti SB5 Beti")
    k.add("serialized_item", id="YBSB5-46", variant_id="YBSB5", serial_number="46", mod_state="PRE-MOD")

    for pn, cage, name, typ in PARTS:
        k.part(pn, cage, name, typ, source_id=mod if pn in ("FBA-0002", "BP-0002", "ISO4762-M4X40-A2", "MOLYKOTEBR2 Plus", "EXXOL D60") else lsa)
    P = k.part_id
    for bei, name, typ, parent, cand, part in BE:
        k.add("breakdown_element", bei=bei, name=name, be_type=typ, parent_bei=parent, lsa_candidate=cand, source_id=lsa)
        if part:
            k.add("breakdown_realization", bei=bei, part_id=P(part), applicability="PRE-MOD")
    k.add("breakdown_realization", bei="B5-A-A7-31-02-00A", part_id=P("BP-0002"), applicability="POST-MOD CH1602")
    for child, qty in [("WBDP-0001", 1), ("WBDL-0001", 1), ("WBDB-0001", 6)]:
        k.add("part_list_entry", parent_id=P("WBD-0001"), child_id=P(child), quantity=qty, source_id=lsa)
    for child in ("FBCL-0001", "BP-0001", "WBD-0001"):
        k.add("part_list_entry", parent_id=P("FBA-0001"), child_id=P(child), quantity=1, source_id=lsa)
    for item, ind, pn, qna, smr in [("001", 1, "FBCL-0001", "1", "PAODD"), ("007", 3, "BP-0001", "1", "PAOZZ"),
                                    ("009", 2, "WBD-0001", "1", "PAOOF"), ("012", 3, "WBDB-0001", "6", "PAOZZ")]:
        k.add("catalogue_item", bei="B5-A-A7-31-00-00A", figure="03", item=item, indenture=ind, part_id=P(pn),
              qty_per_next_assy=qna, smr_code=smr, icn="ICN-B6865-10003-001-01", source_id=ipc)

    k.add("task_requirement", id="PMTR1", origin="S4000P-PMA", bei="B5-A-00-00-00-00A",
          description="Operational test of the front brake before every ride", interval_type="before every operation", source_id=lsa)
    k.add("task_requirement", id="TR-00009", origin="FMECA", bei="B5-A-A7-31-02-00A",
          description="Replace the front brake pads when worn", interval_type="on condition", source_id=lsa)
    k.add("task_requirement", id="PMTR3", origin="S4000P-PMA", bei="B5-A-A7-31-00-00A",
          description="Overhaul front brake system", interval_type="calendar", interval_value="5 years", source_id=lsa)
    for rev, steps, spares, cons, src in [("1.0", STEPS_V1, ["BP-0001", "ISO4762-MAX40-STEEL 10.9"], ["PC-1000"], lsa),
                                          ("2.0", STEPS_V2, ["BP-0002", "ISO4762-M4X40-A2"], ["PC-1000", "MOLYKOTEBR2 Plus", "EXXOL D60"], mod)]:
        k.add("task", id="T00002", revision=rev, name="Replace Front Brake Pads", task_type="rectifying",
              bei="B5-A-A7-31-02-00A", part_id=P(spares[0]), maintenance_level="ML1", source_id=src)
        for i, (sid, desc, dmc, minutes) in enumerate(steps, 1):
            k.add("subtask", task_id="T00002", task_revision=rev, id=sid, seq=i, description=desc, dm_ref=dmc,
                  skill_level="A-Basic", trade="MECH", persons=1, labour_minutes=minutes, duration_minutes=minutes)
        for pn in spares:
            k.add("task_resource", task_id="T00002", task_revision=rev, kind="spare", part_id=P(pn), quantity=1)
        for pn in cons:
            k.add("task_resource", task_id="T00002", task_revision=rev, kind="consumable", part_id=P(pn))
        for pn in ("BST-001", "ALLKEY5MM", "PLI-001"):
            k.add("task_resource", task_id="T00002", task_revision=rev, kind="support-equipment", part_id=P(pn), quantity=1)
    k.add("task_covers", task_id="T00002", requirement_id="TR-00009")
    k.add("safety_statement", kind="condition", text="Hold the mountain bike secure for easy work", task_id="T00002", source_id=lsa)
    k.add("safety_statement", kind="condition", text="Do not actuate the brake when the wheel is removed", task_id="T00002", source_id=lsa)
    k.add("safety_statement", kind="warning", task_id="T00002", source_id=mod,
          text="Severe injury may result if brake pad set is installed without graphite gliding paste on indicated surfaces.")
    k.add("safety_statement", kind="caution", task_id="T00002", source_id=mod,
          text="Keep brake disc surface free from any gliding paste or oil contamination during maintenance.")
    k.add("training_need", task_id="T00002", objective="Replace front brake pads (performance objective)", medium="on-line course")

    for dmc, title, info in [("B5-A-A7-31-02-00A-921A-D", "Front brake pads - Replace", "921"),
                             ("B5-A-A7-31-02-00A-520A-D", "Front brake pads - Remove", "520"),
                             ("B5-A-A7-31-02-00A-720A-D", "Front brake pads - Install", "720"),
                             ("B5-A-B3-51-01-00A-520A-D", "Wheel front - Remove", "520"),
                             ("B5-A-B3-51-01-00A-720A-D", "Wheel front - Install", "720"),
                             ("B5-A-A7-31-00-00A-320A-D", "Front brake system - Test", "320")]:
        bei = dmc[: -len(f"-{info}A-D")]
        k.add("information_item", dmc=dmc, issue="001-00", title=title, bei=bei, info_code=info, item_location="D", source_id=dm)
    k.add("information_item", dmc="B5-A-A7-31-00-010-941A-D", issue="001-00", title="Front brake system - IPD",
          bei="B5-A-A7-31-00-00A", info_code="941", item_location="D", source_id=dm)
    k.add("information_link", dmc="B5-A-A7-31-02-00A-921A-D", target_kind="task", target_id="T00002")
    k.add("information_property", dmc="B5-A-A7-31-02-00A-921A-D", name="maintenance_level", value="ML2")
    k.add("information_property", dmc="B5-A-A7-31-02-00A-921A-D", name="estimated_minutes", value="25")

    k.add("event", id="EV2347", status="Confirmed", description="Mountain bike left the road and crashed against tree.",
          event_group="Accident", occurred_at="2022-07-30T11:22", severity="Critical", reported_by="Police",
          serialized_item_id="YBSB5-46", location="AL-4402, Ohanes, Sierra Nevada, Spain", usage_phase="Descent", source_id=ins)
    k.add("logbook_entry", id="MTB2k46-40", serialized_item_id="YBSB5-46", at="2022-07-30T07:53", counter="678 km",
          entry_type="Pre-check", entry="Activation of brake lever not detected", event_id=None)
    k.add("safety_issue", id="SISS20220730A", title="Mountain bike Yeti SB5 Beti brake failure", status="Engineering investigation pending",
          criticality="Major", created="2022-07-30", variant_id="YBSB5", event_id="EV2347")
    k.add("safety_instruction", id="SIN20220803A", safety_issue_id="SISS20220730A", kind="instruction",
          title="Yeti SB5 Beti brake safety instructions", status="Approved", criticality="Major", priority="High",
          valid_from="2022-08-14", valid_to="2022-12-31")
    k.add("safety_action", instruction_id="SIN20220803A", seq=1, action_type="Mandatory", priority="High",
          description="The brake pad set must always be installed using graphite gliding paste on clean gliding surfaces.",
          released="2022-08-14", required_by="2022-08-30")
    k.add("design_change", id="CH1602", title="Corrosion-free front brake pad bolt", reason="Finding 1 of accident investigation",
          safety_issue_id="SISS20220730A", embodiment_required_by="2022-12-31", embodiment_type="Mandatory")
    for old, new in [("BP-0001", "BP-0002"), ("ISO4762-MAX40-STEEL 10.9", "ISO4762-M4X40-A2"), ("FBA-0001", "FBA-0002")]:
        k.add("part_supersession", old_part_id=P(old), new_part_id=P(new), change_id="CH1602")
    k.add("service_bulletin", id="SB1607", change_id="CH1602", title="Yeti SB5 Beti brake bolt replacement",
          description="Replace pre-mod steel pad bolt by corrosion-free ISO4762-M4X40-A2 bolt", status="Approved",
          issued="2022-09-29", sb_type="Mandatory", priority="High", embodiment_limit="2022-12-31", cost="Free")
    k.db.commit()
    return k
