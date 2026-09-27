# Phase 1 Implementation Plan

Each milestone ends with runnable software and passing acceptance tests. A feature is
"done" only when its tests pass. Status below is factual as of this delivery.

| # | Scope | Status |
|---|-------|--------|
| 1 | Projects, immutable import, schema registry (S1000D, S2000M, S3000L, OEM peers), identification, validation stages 1–3 incl. ID/IDREF integrity, API, CLI, 48 tests | **Implemented** |
| 2 | ADM with exact source spans, structure tree, Tiptap visual editor (Clean/Tags, text edits), Monaco source, Split view, live validation with navigation, attribute value editing, drafts, revisions, restore, export, UI served by the backend; 58 backend + 10 frontend tests | **Implemented** (Tauri shell moved to M7 with the installer) |
| 2+ | DTD validation for XML (ATA iSpec 2200 / OEM) via local catalogs; `make-dtd-package`; compatible-schema choice with persistent warning; role-based rendering profiles (S1000D, ATA, S-Series); entity display; readable validation messages with verified fixes | **Implemented** |
| 3 (core) | Unified schema model from XSD / XML DTD / SGML DTD; content-model engine; schema-constrained insert, inline insert, delete, move; required-attribute dialog; schema-driven attribute editing; SGML editing with normalised write-back validated by OpenSP | **Implemented** (split/wrap, revision compare and BREX still open) |
| 3 | Normalized schema model + cursor queries, schema-constrained insertion dialogs, diagnostics panel, revisions + compare, BREX/Schematron/XPath rule packages | Not started |
| 4 | OpenSP bridge, DTD validation, SGML normalization record, SGML export for tested dialects | Not started |
| 5 | Knowledge core + importers: S1000D (IPD, Descr, Proc), S2000M (parts, figure items, provisioning), S3000L (breakdown, tasks, applicability); graph explorer; cross-doc references | Not started |
| 6 | Mapping engine; flows S2000M→S1000D IPD and S3000L→S1000D Procedure; exception report; field provenance; target validation; cross-standard consistency checks | Not started |
| 7 | Optional Ollama/llama.cpp + Laya adapter, Windows installer (Tauri + PyInstaller sidecar + OpenSP), offline end-to-end regression | Not started |

## Milestone 6 flows (the S-Series completion criterion)

**S2000M → S1000D IPD.** S2000M importer extracts Part, FigureItem (figure, item,
indenture, quantity, effectivity) into the core with provenance. The mapping writes
S1000D `catalogSeqNumber`/`itemSeqNumber` through the S1000D adapter. Required target
data not present in S2000M (e.g. data module code, ICN references) is reported as
`missing-required` and must be supplied by the author; never generated.

**S3000L → S1000D Procedure.** Tasks/subtasks and resources become Procedure,
ProceduralStep, Tool/Consumable. Warnings/cautions absent from the LSA data are
`missing-required` where the target business rules demand them — not invented.

**Consistency checks.** Shared parts (S2000M part ↔ S1000D partRef ↔ S3000L breakdown
part), product structure alignment, applicability expressions compared in both source
form and normalized form, task references between S3000L tasks and S1000D procedures.

Mappings take the official S1000X specification as their starting point, per issue, once
the licensed text is available to the project; each rule cites its clause.

## Risks and dependencies

1. **Official schemas and specifications.** Phase 1 ships only synthetic test schemas.
   Real validation requires installing official S1000D/S2000M/S3000L schema packages and
   having licensed access to SX002D, SX001G and S1000X text. The first task of M5/M6 is to
   pin exact issues.
2. **libxml2 limits.** libxml2 does not enforce ID/IDREF during XSD validation; M1 adds a
   second engine (xmlschema) for that. Other libxml2 XSD 1.0 limitations (and no XSD 1.1)
   must be tracked per official schema.
3. **OpenSP on Windows.** Bundle a vetted build; M4 includes an install-time self-test.
4. **Round-trip fidelity.** Claims limited to what tests prove (see 04 §4, §7).
5. **Scope.** M5–M6 are the largest milestones; they are planned narrow-first: one
   document type, one issue, end to end, then widen.
