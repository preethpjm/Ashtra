# ASTHRA Knowledge Core — Canonical Model Specification (v0.1, target M5)

## 1. Purpose and non-goals

The knowledge core records *what the engineering information says and where it came from*.
It is not a lowest-common-denominator schema into which documents are flattened. Documents
remain authoritative in their own standard; the core indexes, relates and translates them.

Alignment: entity classes follow the S-Series Common Data Model (SX002D) and terminology
(SX001G). **The exact class and attribute correspondence must be taken from the SX002D issue
the project licenses and is recorded per entity in a versioned alignment table
(`core_alignment`).** This specification defines ASTHRA's structure; it does not reproduce
or assume SX002D content that has not been checked against the published issue.

## 2. Three layers of every fact

| Layer         | Meaning                                                           |
|---------------|-------------------------------------------------------------------|
| Source        | the immutable original bytes (SHA-256)                            |
| Extracted     | a value read from a source by a declared, versioned extraction rule |
| Asserted      | a value authored or confirmed by a person, or produced by mapping  |

Extracted and asserted values never overwrite each other. Conflicts are data, surfaced by
the consistency checks.

## 3. Core entity types

Each is a row in `entity` with `type`, a stable ASTHRA id, and typed attributes in
`entity_attr`; standard-specific data lives in `entity_extension` keyed by
`(standard, issue, name)`.

Product · ProductVariant/Configuration · BreakdownElement (S3000L-style hardware/
functional breakdown) · Assembly · Part · PartRevision · Document · DocumentRevision
(data module issue, provisioning exchange issue, LSA exchange) · Figure · FigureItem
(IPD item: figure number, item, variant, indenture, quantity) · Procedure · ProceduralStep
· MaintenanceTask · Subtask · Tool/SupportEquipment · Consumable/Material · Warning ·
Caution · Note · Applicability (kept as the source expression plus a normalized form; the
two are never assumed equal) · ManufacturingOperation · InspectionRequirement ·
SourceReference.

## 4. Relationship types (initial)

`PART_OF_ASSEMBLY` · `APPEARS_IN_FIGURE` (via FigureItem) · `PROCEDURE_REFERENCES_PART` ·
`PROCEDURE_USES_TOOL` · `TASK_ON_BREAKDOWN_ELEMENT` · `TASK_REALIZED_BY_PROCEDURE` ·
`DOCUMENT_REFERENCES_DOCUMENT` · `APPLIES_TO_CONFIGURATION` · `DERIVED_FROM_SOURCE` ·
`SUPERSEDES` · `SAME_AS_CANDIDATE` (unconfirmed cross-standard identity) · `SAME_AS`
(confirmed, with who/when).

Cross-standard identity (the S2000M part that is the S1000D `partRef` that is the S3000L
breakdown element's part) is **never inferred silently**. Deterministic keys (e.g.
manufacturer code + part number) create `SAME_AS_CANDIDATE`; promotion to `SAME_AS`
requires a rule marked authoritative for the project or a human decision.

## 5. Provenance record (mandatory on every extracted value)

```
source_file_sha256, source_document_revision, standard, issue, schema_package_checksum,
element_path, source_line, extraction_rule_id + version, mapping_rule_id (if any),
provenance_status: direct | transformed | preserved-unmapped | missing-required |
                   needs-interpretation | newly-authored,
actor, timestamp
```

## 6. Order, mixed content and fidelity

The core stores *references into* documents (element path + node id), not copies of prose.
Document order, mixed content and inline markup stay in the document model (see
04-EDITOR-DOCUMENT-MODEL). Where a translation must carry prose, the mapping copies the
source subtree and records it as `transformed` with the rule that did so.

## 7. Storage (SQLite, M5 migration sketch)

```sql
entity(id, type, core_version, created_at)
entity_attr(entity_id, name, value, value_type, layer, provenance_id)
entity_extension(entity_id, standard, issue, name, value_json, provenance_id)
relation(id, type, from_id, to_id, layer, provenance_id, valid_from_rev, valid_to_rev)
provenance(id, source_file_id, doc_revision, standard, issue, pkg_checksum,
           element_path, line, rule_id, rule_version, status, actor, at)
core_alignment(core_type, core_attr, framework, framework_issue, target_class, target_attr, note)
```

NetworkX graphs are rebuilt from `relation` on demand; the backend can be swapped later
(e.g. for an embedded graph database) behind `graph.GraphStore`.

## 8. Access control hook

Every query passes a `Principal` and workspace. Phase 1 has one local user, but the query
layer already filters by `project_id` and entity-level ACL rows, so granting a document
never implicitly grants linked records.
