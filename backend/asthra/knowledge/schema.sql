-- ASTHRA master knowledge model — schema v1 (docs/06-KNOWLEDGE-MODEL.md).
-- Classes follow the S-Series common data model (SX002D) and what the S-Series "Bike example"
-- (UF2024) exchanges end to end. One row = one fact about the product; every row carries its
-- provenance (source_id) and the layer it belongs to (shared library or an organisation overlay).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source (           -- where facts came from
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL,                -- S1000D-DM | ATA-CMM | S2000M | S3000L | S4000P | S5000F | S6000T | SX000i | ENG-BOM | manual
  document      TEXT NOT NULL,                -- DMC, file name, dataset id …
  issue         TEXT,                         -- document issue / revision
  schema        TEXT,                         -- e.g. "S3000L 2.0"
  imported_at   TEXT NOT NULL,
  note          TEXT
);

CREATE TABLE IF NOT EXISTS layer (            -- shared library and organisation / customer overlays
  id    TEXT PRIMARY KEY,                     -- "shared" or an organisation id
  name  TEXT NOT NULL,
  parent TEXT REFERENCES layer(id)
);
INSERT OR IGNORE INTO layer(id, name) VALUES ('shared', 'Shared library');

-- ------------------------------------------------------------------ SX000i: programme, parties
CREATE TABLE IF NOT EXISTS organization (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
  source_id INTEGER REFERENCES source(id), layer TEXT NOT NULL DEFAULT 'shared' REFERENCES layer(id));
CREATE TABLE IF NOT EXISTS organization_code (   -- CAGE/NCAGE: one per site, several per organisation
  code TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organization(id), site TEXT);
CREATE TABLE IF NOT EXISTS organization_role (
  organization_id TEXT REFERENCES organization(id), role TEXT NOT NULL,   -- manufacturer | licensee | operator | owner | customer | supplier
  product_id TEXT, PRIMARY KEY (organization_id, role, product_id));
CREATE TABLE IF NOT EXISTS person (
  id TEXT PRIMARY KEY, given_name TEXT, family_name TEXT, organization_id TEXT REFERENCES organization(id));
CREATE TABLE IF NOT EXISTS project (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, duration TEXT, source_id INTEGER REFERENCES source(id));
CREATE TABLE IF NOT EXISTS maintenance_level (
  code TEXT PRIMARY KEY, name TEXT NOT NULL);               -- ML1 user on-bike … ML4 manufacturer
CREATE TABLE IF NOT EXISTS trade (
  code TEXT PRIMARY KEY, name TEXT NOT NULL);               -- MECH, ELEC …
CREATE TABLE IF NOT EXISTS skill_level (
  code TEXT PRIMARY KEY, name TEXT NOT NULL);               -- A-Basic …
CREATE TABLE IF NOT EXISTS operational_scenario (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, hours_per_year REAL);

-- ------------------------------------------------------------------ product and configuration
CREATE TABLE IF NOT EXISTS product (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, model_ident_code TEXT, project_id TEXT REFERENCES project(id),
  source_id INTEGER REFERENCES source(id), layer TEXT NOT NULL DEFAULT 'shared' REFERENCES layer(id));
CREATE TABLE IF NOT EXISTS product_variant (
  id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES product(id), name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS serialized_item (   -- a physical product: serial number, owner, operating counters
  id TEXT PRIMARY KEY, variant_id TEXT REFERENCES product_variant(id), serial_number TEXT NOT NULL,
  owner_id TEXT REFERENCES organization(id), mod_state TEXT);   -- e.g. PRE-MOD / POST-MOD CH1602

-- ------------------------------------------------------------------ parts (S2000M / S3000L / PLM)
CREATE TABLE IF NOT EXISTS part (             -- identity: manufacturer code + part number (identity.part_key)
  id INTEGER PRIMARY KEY,
  manufacturer_code TEXT NOT NULL DEFAULT '', -- CAGE/NCAGE ('' = unqualified)
  part_number TEXT NOT NULL,                  -- as written
  part_number_key TEXT NOT NULL,              -- normalised for matching
  name TEXT, part_type TEXT,                  -- part | component | consumable | support-equipment | raw-material …
  nsn TEXT, unit_of_issue TEXT,
  source_id INTEGER REFERENCES source(id), layer TEXT NOT NULL DEFAULT 'shared' REFERENCES layer(id),
  UNIQUE (manufacturer_code, part_number_key, layer));
CREATE TABLE IF NOT EXISTS part_list_entry (  -- BOM: parent part contains child part
  parent_id INTEGER NOT NULL REFERENCES part(id), child_id INTEGER NOT NULL REFERENCES part(id),
  quantity REAL NOT NULL DEFAULT 1, source_id INTEGER REFERENCES source(id),
  PRIMARY KEY (parent_id, child_id));
CREATE TABLE IF NOT EXISTS bom_line (         -- engineering BOM line as written (PLM / ERP / CAD export)
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES source(id), line INTEGER,
  parent_id INTEGER REFERENCES part(id), child_id INTEGER NOT NULL REFERENCES part(id),
  find_no TEXT, level INTEGER, quantity REAL, unit TEXT, effectivity TEXT, make_buy TEXT);
CREATE TABLE IF NOT EXISTS part_property (    -- engineering attributes: mass, material, CAD file, CAD node …
  part_id INTEGER NOT NULL REFERENCES part(id), name TEXT NOT NULL, value TEXT,
  source_id INTEGER REFERENCES source(id), PRIMARY KEY (part_id, name, source_id));
CREATE TABLE IF NOT EXISTS cad_link (         -- 3D model item ↔ part, from a STEP/GLB ↔ BOM reconciliation
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES source(id),
  part_id INTEGER REFERENCES part(id),        -- NULL: an item of the 3D model with no BOM line
  cad_name TEXT NOT NULL,                     -- the item's part number / name in the 3D model (node name)
  cad_label TEXT, cad_qty REAL, status TEXT,  -- matched | fuzzy_candidate | unmatched …
  confidence REAL, quantity_match INTEGER, members TEXT, flags TEXT);
CREATE TABLE IF NOT EXISTS cad_model (        -- a 3D model (GLB) kept in the data folder
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, file TEXT NOT NULL, nodes INTEGER, bytes INTEGER, imported_at TEXT NOT NULL,
  source_id INTEGER REFERENCES source(id));   -- the reconciliation imported with it (its 3D ↔ BOM links colour this model)
CREATE TABLE IF NOT EXISTS cad_node (
  model_id INTEGER NOT NULL REFERENCES cad_model(id), idx INTEGER NOT NULL, name TEXT NOT NULL, PRIMARY KEY (model_id, idx));
CREATE TABLE IF NOT EXISTS engineering_finding ( -- what an engineering tool reported (e.g. STEP ↔ MBOM reconciliation)
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES source(id), rule TEXT NOT NULL, subject TEXT NOT NULL,
  message TEXT NOT NULL, part_id INTEGER REFERENCES part(id));
CREATE TABLE IF NOT EXISTS part_supersession ( -- pre-mod part replaced by post-mod part
  old_part_id INTEGER NOT NULL REFERENCES part(id), new_part_id INTEGER NOT NULL REFERENCES part(id),
  change_id TEXT REFERENCES design_change(id), interchangeability TEXT,   -- e.g. one-way / two-way
  PRIMARY KEY (old_part_id, new_part_id));

-- ------------------------------------------------------------------ breakdown (S3000L, key for S1000D/S2000M)
CREATE TABLE IF NOT EXISTS breakdown_element (
  bei TEXT NOT NULL,                          -- Breakdown Element Identifier, e.g. B5-A-A7-31-02-00A
  revision TEXT NOT NULL DEFAULT '1.0',
  name TEXT NOT NULL,
  be_type TEXT,                               -- product | general | system | subsystem | sub-subsystem | equipment
  breakdown TEXT NOT NULL DEFAULT 'physical', -- physical | functional | zonal
  parent_bei TEXT,
  lsa_candidate TEXT,                         -- full | partial | none
  lsa_justification TEXT,
  source_id INTEGER REFERENCES source(id), layer TEXT NOT NULL DEFAULT 'shared' REFERENCES layer(id),
  PRIMARY KEY (bei, revision, layer));
CREATE TABLE IF NOT EXISTS breakdown_realization (  -- which part realises a breakdown element (per mod state)
  bei TEXT NOT NULL, part_id INTEGER NOT NULL REFERENCES part(id), applicability TEXT,
  PRIMARY KEY (bei, part_id));
CREATE TABLE IF NOT EXISTS catalogue_item (   -- IPC / IPD line (S2000M, S1000D 941)
  id INTEGER PRIMARY KEY, bei TEXT, figure TEXT NOT NULL, figure_variant TEXT DEFAULT '', item TEXT NOT NULL,
  item_variant TEXT DEFAULT '', indenture INTEGER, part_id INTEGER NOT NULL REFERENCES part(id),
  qty_per_next_assy TEXT, usable_on_code TEXT, smr_code TEXT, icn TEXT,
  source_id INTEGER REFERENCES source(id));

-- ------------------------------------------------------------------ analysis (S4000P / S3000L)
CREATE TABLE IF NOT EXISTS task_requirement (
  id TEXT PRIMARY KEY,                        -- PMTR1, TR-00009 …
  origin TEXT NOT NULL,                       -- S4000P-PMA | FMECA | damage | special-event | operational
  bei TEXT, description TEXT,
  interval_type TEXT, interval_value TEXT,    -- e.g. before every operation; 5 years; on condition
  source_id INTEGER REFERENCES source(id));
CREATE TABLE IF NOT EXISTS task (
  id TEXT NOT NULL, revision TEXT NOT NULL DEFAULT '1.0', name TEXT NOT NULL,
  task_type TEXT,                             -- rectifying | inspection | servicing …
  bei TEXT, part_id INTEGER REFERENCES part(id), maintenance_level TEXT REFERENCES maintenance_level(code),
  estimated_minutes REAL,
  source_id INTEGER REFERENCES source(id), layer TEXT NOT NULL DEFAULT 'shared' REFERENCES layer(id),
  PRIMARY KEY (id, revision, layer));
CREATE TABLE IF NOT EXISTS task_covers (      -- task covers task requirement(s)
  task_id TEXT NOT NULL, requirement_id TEXT NOT NULL REFERENCES task_requirement(id),
  PRIMARY KEY (task_id, requirement_id));
CREATE TABLE IF NOT EXISTS subtask (
  task_id TEXT NOT NULL, task_revision TEXT NOT NULL DEFAULT '1.0', id TEXT NOT NULL, seq INTEGER NOT NULL,
  description TEXT NOT NULL, dm_ref TEXT,     -- the S1000D data module the step refers to (DMC)
  skill_level TEXT REFERENCES skill_level(code), trade TEXT REFERENCES trade(code),
  persons INTEGER, labour_minutes REAL, duration_minutes REAL,
  PRIMARY KEY (task_id, task_revision, id));
CREATE TABLE IF NOT EXISTS task_resource (    -- spares, consumables, support equipment, facilities
  task_id TEXT NOT NULL, task_revision TEXT NOT NULL DEFAULT '1.0',
  kind TEXT NOT NULL,                         -- spare | consumable | support-equipment | facility
  part_id INTEGER REFERENCES part(id), description TEXT, quantity REAL, unit TEXT,
  PRIMARY KEY (task_id, task_revision, kind, part_id));
CREATE TABLE IF NOT EXISTS safety_statement ( -- warnings / cautions / notes and conditions
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, -- warning | caution | note | condition
  text TEXT NOT NULL, task_id TEXT, subtask_id TEXT, bei TEXT, dmc TEXT, source_id INTEGER REFERENCES source(id));
CREATE TABLE IF NOT EXISTS time_limit (       -- maintenance planning (S4000P → S1000D schedule DMs)
  id INTEGER PRIMARY KEY, bei TEXT, part_id INTEGER REFERENCES part(id), requirement_id TEXT,
  limit_type TEXT, threshold TEXT);           -- on condition / one month …

-- ------------------------------------------------------------------ publications (S1000D)
CREATE TABLE IF NOT EXISTS information_item (
  dmc TEXT NOT NULL, issue TEXT NOT NULL DEFAULT '', title TEXT, info_name TEXT,
  bei TEXT,                                   -- the SNS part of the DMC (links to the breakdown)
  info_code TEXT, item_location TEXT,         -- 520 remove, 720 install, 320 test, 921 replace, 941 IPD …
  source_id INTEGER REFERENCES source(id), layer TEXT NOT NULL DEFAULT 'shared' REFERENCES layer(id),
  PRIMARY KEY (dmc, issue, layer));
CREATE TABLE IF NOT EXISTS information_property (  -- what a data module itself states (e.g. its maintenance level)
  dmc TEXT NOT NULL, name TEXT NOT NULL, value TEXT, PRIMARY KEY (dmc, name));
CREATE TABLE IF NOT EXISTS information_resource (  -- what a data module requires (S1000D preliminary requirements)
  id INTEGER PRIMARY KEY, dmc TEXT NOT NULL, kind TEXT NOT NULL,   -- support-equipment | consumable | spare
  part_id INTEGER REFERENCES part(id), name TEXT, quantity TEXT, unit TEXT);
CREATE TABLE IF NOT EXISTS information_ref (      -- references from one data module to another
  dmc TEXT NOT NULL, ref_dmc TEXT NOT NULL, PRIMARY KEY (dmc, ref_dmc));
CREATE TABLE IF NOT EXISTS information_link ( -- what a data module documents
  dmc TEXT NOT NULL, target_kind TEXT NOT NULL,  -- task | subtask | breakdown | part | requirement
  target_id TEXT NOT NULL, PRIMARY KEY (dmc, target_kind, target_id));

-- ------------------------------------------------------------------ training (S6000T)
CREATE TABLE IF NOT EXISTS training_need (
  id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, subtask_id TEXT, objective TEXT, medium TEXT,
  performance_level TEXT, source_id INTEGER REFERENCES source(id));

-- ------------------------------------------------------------------ in service (S5000F / SX000i)
CREATE TABLE IF NOT EXISTS event (
  id TEXT PRIMARY KEY, status TEXT, description TEXT, event_group TEXT, occurred_at TEXT, severity TEXT,
  reported_by TEXT, serialized_item_id TEXT REFERENCES serialized_item(id), location TEXT, usage_phase TEXT,
  related_event_id TEXT REFERENCES event(id), source_id INTEGER REFERENCES source(id));
CREATE TABLE IF NOT EXISTS damage (
  id TEXT PRIMARY KEY, event_id TEXT REFERENCES event(id), family TEXT, description TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS operational_period (
  id TEXT PRIMARY KEY, serialized_item_id TEXT REFERENCES serialized_item(id), name TEXT,
  scheduled TEXT, actual TEXT, result TEXT, operator TEXT);
CREATE TABLE IF NOT EXISTS logbook_entry (
  id TEXT PRIMARY KEY, serialized_item_id TEXT REFERENCES serialized_item(id), at TEXT, counter TEXT,
  entry_type TEXT, entry TEXT, event_id TEXT REFERENCES event(id));
CREATE TABLE IF NOT EXISTS safety_issue (
  id TEXT PRIMARY KEY, title TEXT, description TEXT, status TEXT, criticality TEXT, created TEXT,
  variant_id TEXT REFERENCES product_variant(id), event_id TEXT REFERENCES event(id));
CREATE TABLE IF NOT EXISTS safety_instruction (   -- safety warnings and safety instructions
  id TEXT PRIMARY KEY, safety_issue_id TEXT REFERENCES safety_issue(id), kind TEXT,   -- warning | instruction
  title TEXT, status TEXT, criticality TEXT, priority TEXT, valid_from TEXT, valid_to TEXT);
CREATE TABLE IF NOT EXISTS safety_action (
  instruction_id TEXT NOT NULL REFERENCES safety_instruction(id), seq INTEGER NOT NULL, action_type TEXT,
  description TEXT, priority TEXT, released TEXT, required_by TEXT, PRIMARY KEY (instruction_id, seq));

-- ------------------------------------------------------------------ change (design modification → embodiment)
CREATE TABLE IF NOT EXISTS design_change (
  id TEXT PRIMARY KEY, title TEXT, reason TEXT, safety_issue_id TEXT REFERENCES safety_issue(id),
  embodiment_required_by TEXT, embodiment_type TEXT);          -- mandatory …
CREATE TABLE IF NOT EXISTS service_bulletin (
  id TEXT PRIMARY KEY, change_id TEXT REFERENCES design_change(id), title TEXT, description TEXT,
  status TEXT, issued TEXT, sb_type TEXT, priority TEXT, embodiment_limit TEXT, cost TEXT);

-- ------------------------------------------------------------------ consistency findings and conflicts
CREATE TABLE IF NOT EXISTS finding (
  id INTEGER PRIMARY KEY, rule TEXT NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL,
  values_json TEXT, found_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open');

-- ------------------------------------------------------------------ translator (schema bindings)
CREATE TABLE IF NOT EXISTS binding (          -- where a concept's fields live in one installed schema
  package_id TEXT NOT NULL, doc_type TEXT NOT NULL, concept TEXT NOT NULL,
  json TEXT NOT NULL, saved_at TEXT NOT NULL,
  PRIMARY KEY (package_id, doc_type, concept));
CREATE TABLE IF NOT EXISTS translate_setting (   -- the project rules last used (exclusions, numbering …)
  key TEXT PRIMARY KEY, json TEXT NOT NULL);
