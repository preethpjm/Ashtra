# Schema Packages and Standard Adapters

## 1. Schema package (implemented, M1)

A directory or zip with `asthra-package.json`:

```json
{
  "package_id": "official-5.0",
  "name": "S1000D Issue 5.0 schemas",
  "standard": "S1000D", "issue": "5.0", "provenance": "official",
  "doc_types": [{
    "id": "proced", "label": "Procedure", "content_family": "procedure",
    "schema_file": "xml_schema_flat/proced.xsd",
    "match": {"local_name": "dmodule", "namespace": null,
              "schema_location_pattern": "(^|/)proced\\.xsd$"},
    "identity_xpaths": {"modelIdentCode": "/dmodule/.../dmCode/@modelIdentCode"}
  }],
  "files": ["xml_schema_flat/proced.xsd", "..."],
  "dependencies": [], "catalog": {"http://…/xlink.xsd": "xml_schema_flat/xlink.xsd"},
  "validation_rules": [], "transformations": [], "checksum": null
}
```

Rules enforced at install: every listed file exists and is inside the package; every
entry schema compiles using only package files, dependency packages and catalog
mappings; declared checksum (if any) matches; dependencies are already installed.
Identification rules come **from the package**, so ASTHRA recognizes exactly what is
installed and nothing more.

## 2. StandardAdapter (interface implemented, M1; capabilities fill in by milestone)

```python
class StandardAdapter:
    family: str                     # "S1000D", "S2000M", ...
    workspace: str
    capabilities: dict[Cap, CapabilityStatus]   # implemented | planned(milestone)

    def extract_identity(root, manifest, doc_type) -> DocumentIdentity      # M1
    def business_rule_packages(manifest) -> list[RulePackage]              # M3
    def extract_canonical(tree, manifest, doc_type) -> ExtractionResult    # M5
    def export(canonical_slice, manifest, doc_type) -> ExportResult        # M6
```

Unimplemented capabilities raise `NotYetImplemented(adapter, cap, milestone)` and are
reported as `planned` via `GET /api/standards`. The UI must read capabilities rather than
assume them.

## 3. Mapping package (M6)

```
mapping.json: id, version, source {standard, issue, doc_type},
              target {standard, issue, doc_type},
              basis: "S1000X <issue> §… (as licensed)" | "project-defined",
              rules[]: {id, source_selector, canonical_target, transform, status_on_success}
tests/: paired fixtures (source → expected target + expected exception report)
```

A mapping is usable only when its bundled tests pass against the installed schema
packages with matching checksums. The engine never performs tag substitution: it reads
through the source adapter into the core, and writes through the target adapter, which
must produce a document that passes target Stage 3 validation before it is marked
structurally valid.

## 4. Adding a standard

1. Install its schema package(s).
2. Add an adapter class and `register()` it.
3. Optionally add rule packages and mapping packages.
No change to core, registry, validation pipeline or UI shell is required.


## DTD packages (implemented)

A doc type with `"schema_kind": "dtd"` is validated per document: the DTD and all entity
files load only from the package (and dependency packages) through `catalog`, keyed by
public identifier, system identifier or bare file name. The document's DOCTYPE external
identifier is redirected to the doc type's DTD without changing line numbers; a DOCTYPE
is inserted on the root's line when missing. Identification uses `match.public_id_pattern`
and `match.system_id_pattern`. `make-dtd-package` derives all of this from a folder.

## Compatible matches and user choice (implemented)

`match.local_name` (+ `namespace`) and the optional `discriminator` XPath decide whether a
doc type *fits* a document. Fitting without a declaration makes it a *compatible*
candidate: identification status `needs-choice`, never auto-selected. The user's choice
is recorded, and every validation adds `ASTHRA-SCHEMA-CHOSEN` when the document does not
declare the chosen schema.

## Display roles (implemented)

`render_roles: {element: role}` in a manifest overrides the built-in profile of its
standard family (`backend/asthra/render/profiles.py`, which lists all roles). Roles affect
display only.
