# Editor Document-Model Strategy

> **As implemented in Milestone 2** (`frontend/src/adm.ts`): the source text is the single
> authority. After the browser's XML parser confirms it is well-formed, a tokenizer records
> exact source spans for every element and every comment/PI/CDATA. Element identity (`nid`)
> is document order. Visual edits may change text only (a ProseMirror filter rejects any
> transaction that changes the element skeleton), so each edit is applied as a splice of
> that one element's content; every other byte is preserved. Attribute edits splice the
> value inside the start tag, preserving quote style and layout. Source edits reparse and
> rebuild the visual view. Documents with DOCTYPE internal subsets are Source-only so
> entities are never expanded. Sections below describe the Milestone 3 extension
> (schema-derived structure editing) on top of this model.

## 1. One authoritative model: the ADM

The **ASTHRA Document Model (ADM)** is an XML-faithful tree: elements (QName, ordered
attributes, namespace declarations in scope), text, comments, processing instructions,
CDATA flags, entity references, and a stable `asthra:nid` per node. It is serializable
to and from XML losslessly for all constructs lxml preserves; anything not preserved is
recorded in a `fidelity_notes` list attached to the document revision.

Clean, Tags and Source modes are **views** of the ADM:

| Mode   | View                                                   | Edits become |
|--------|--------------------------------------------------------|--------------|
| Clean  | ProseMirror doc; structure hidden, styling by element  | ADM transactions |
| Tags   | same ProseMirror doc; node views show element labels   | ADM transactions |
| Source | Monaco text of the ADM serialization                   | reparse → ADM diff |

## 2. Schema-derived ProseMirror schema

ProseMirror's own schema is generated at load time from the normalized content model of
the active XSD (M3 `schemamodel`): each element type becomes a node type; content
expressions are compiled from XSD particles (sequence/choice/all, min/max occurs) into
deterministic automata. ProseMirror's content expressions are too weak for some XSD
models, so node types use a permissive expression and every transaction is checked by
the compiled automata before commit. Invalid transactions are rejected or held as a
visibly marked **draft**; they never reach a committed revision.

## 3. Contextual queries

The backend ships each document type's compiled content model to the frontend as JSON,
so these answers are synchronous in the editor and identical to the backend's:

* valid insertions at cursor = transitions available from the automaton state at that
  child position, filtered by what can still complete to an accepting state;
* required attributes/children for insertion = attribute uses with `use="required"` and
  the minimal accepting completion of the child automaton → drives the inline dialog;
* can delete = does removing the node keep the parent's sequence acceptable.

AI never participates in these answers.

## 4. Unsupported content

Any element without a registered view renders as a **protected node**: an atom showing
its label and a collapsed XML preview, editable only in Source mode or its attribute
panel. Its subtree is stored verbatim in the ADM and round-trips byte-for-byte within
lxml's serialization guarantees.

## 5. Source-mode synchronization

Monaco edits reparse into a candidate ADM. If well-formed, a tree diff keyed by
`asthra:nid` (with positional fallback) produces a minimal transaction so selection and
undo history survive. If not well-formed, the visual views freeze on the last good ADM
and show the parse diagnostics; nothing is lost or guessed.

## 6. Revisions

Commit = full Stage 1–3 validation (+ rules when M3 lands) → atomic write of the
serialized ADM to `revisions/` → revision row with parent, hash and validation run id.
The imported original is never the target of a write.

## 7. SGML (M4)

SGML sources are parsed by OpenSP (`onsgmls`) into ESIS, converted to an ADM with a
normalization record (tag minimization inferred, entity resolutions, case folding).
ASTHRA claims source-level SGML round trip only for dialects whose export has passed a
round-trip test suite.
