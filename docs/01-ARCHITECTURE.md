# ASTHRA — Repository and System Architecture

Status: Milestone 1 implemented (backend). This document describes the whole Phase 1
target; sections are marked **[M1]** where code exists and passes tests.

## 1. Process model

```
┌──────────────────────────── Windows desktop ─────────────────────────────┐
│  Tauri shell (Rust, WebView2)                                            │
│   └─ React + TypeScript UI (Tiptap/ProseMirror, Monaco)        [M2]      │
│          │  HTTP/JSON on 127.0.0.1 only, per-session token     [M2]      │
│   └─ Python sidecar: FastAPI + services                        [M1]      │
│          ├─ lxml / xmlschema (XML)                              [M1]      │
│          ├─ OpenSP (onsgmls, bundled binary) (SGML)             [M4]      │
│          ├─ SQLite (single file per data root)                  [M1]      │
│          ├─ NetworkX (in-memory projection of SQLite graph)     [M5]      │
│          └─ optional: Ollama / llama.cpp on localhost           [M7]      │
└──────────────────────────────────────────────────────────────────────────┘
```

The Python backend is a sidecar packaged with PyInstaller and launched by Tauri. Nothing
listens on a non-loopback interface. There is no Docker, no external database and no
cloud dependency. The UI is a client of the same API that the CLI and tests use, so every
behaviour the UI exposes is testable without a browser.

## 2. Repository layout

```
asthra/
├─ backend/
│  ├─ asthra/
│  │  ├─ config.py              settings, data root (%LOCALAPPDATA%\ASTHRA)        [M1]
│  │  ├─ app_context.py         service wiring                                     [M1]
│  │  ├─ security/              path confinement, safe unzip, hardened parsers     [M1]
│  │  ├─ storage/               SQLite migrations, immutable blob store            [M1]
│  │  ├─ registry/              schema package manifest + versioned registry       [M1]
│  │  ├─ standards/             one adapter per standard family (peers)            [M1 identify/validate]
│  │  │   ├─ base.py            StandardAdapter interface + capability model
│  │  │   └─ sseries.py         S1000D, S2000M, S3000L, OEM
│  │  ├─ identify/              encoding sniffing, XML/SGML detection, matching    [M1]
│  │  ├─ validation/            7-stage pipeline, diagnostics model                [M1: stages 1–3]
│  │  ├─ projects/, documents/  project + import services                          [M1]
│  │  ├─ api/                   FastAPI (localhost)                                [M1]
│  │  ├─ schemamodel/           normalized content models + cursor queries         [M3]
│  │  ├─ docmodel/              ADM: authoritative document tree, transactions     [M2]
│  │  ├─ revisions/             working copies, revision commits, diff             [M3]
│  │  ├─ sgml/                  OpenSP bridge, normalization record                [M4]
│  │  ├─ rules/                 BREX, Schematron, XPath rule packages              [M3]
│  │  ├─ core/                  canonical knowledge model (SX002D-aligned)         [M5]
│  │  ├─ graph/                 relationship store + NetworkX projection           [M5]
│  │  ├─ mapping/               mapping packages, translation engine, reports      [M6]
│  │  ├─ ai/                    optional local LLM + Laya adapter                  [M7]
│  │  └─ cli.py
│  └─ tests/                    pytest suite + synthetic fixtures                  [M1]
├─ frontend/                    React/Vite/Tiptap/Monaco                            [M2]
├─ desktop/                     Tauri config, sidecar launcher, installer (NSIS)   [M7]
├─ packages/                    user-installable schema / rule / mapping packages
└─ docs/
```

## 3. Layering rules

1. **Security and storage** know nothing about standards.
2. **Registry** stores packages and compiles schemas; it knows only what manifests declare.
3. **Standards adapters** hold standard-specific behaviour (identity formatting, BREX,
   importers/exporters). The rest of the system never branches on a standard's name.
4. **Core** (canonical model) depends on nothing standard-specific. Adapters depend on core,
   never the reverse.
5. **Mapping** packages connect adapters through the core: source → canonical → target.
6. **Workspaces** (Technical Publishing, Material Management, LSA, …) are UI + query
   compositions over the same core. They add no private data stores.

## 4. S-Series as first-class peers

S1000D, S2000M and S3000L each get, independently: registry entries per issue, an adapter,
identification rules, structural validation, and (M3+) rule packages, (M5) an importer
into the knowledge core and (M6) exporter/mapping participation. Workspaces in Phase 1:

| Workspace                   | Standard | Phase 1 depth                                           |
|-----------------------------|----------|---------------------------------------------------------|
| Technical Publishing        | S1000D   | visual authoring, validation, export (IPD, Descr, Proc) |
| Material Management         | S2000M   | import, validate, extract parts/figure-items/provisioning |
| Logistics Support Analysis  | S3000L   | import, validate, extract breakdown/tasks/applicability  |

Adding S4000P, S5000F, S6000T, ATA iSpec 2200 or an OEM schema means: install a schema
package, register an adapter class, optionally install mapping packages. No core changes.

## 5. Data at rest

```
<data root>/
  asthra.sqlite3                     metadata, diagnostics, audit, (M5) knowledge core
  registry/<standard>/<issue>/<pkg>/ installed schema packages (checksummed)
  projects/<project-id>/
    sources/sha256/ab/<hash>         immutable originals (read-only, verified on read)
    working/                         editable working copies            [M3]
    revisions/                       committed revisions (atomic)       [M3]
    exports/, reports/               generated outputs                  [M6]
```

## 6. Security posture [M1]

* Loopback bind only; CORS limited to `tauri://localhost` and local dev origins.
* XML parsed with entity expansion off, DTD loading off, `no_network`.
* Schema includes/imports resolved through `ConfinedResolver`: only files inside the
  package (and declared dependency packages) or explicit catalog mappings. Anything else
  raises; tests prove remote imports fail at install.
* Zip packages: zip-slip, symlink, absolute-path and compression-bomb checks.
* Originals: SHA-256 content addressing, read-only mode, integrity re-verified on every read.
* Schema packages: tree checksum recorded at install, re-verified before first use.
* Tests run with sockets patched to fail, so any accidental network access fails CI.
* Diagnostics avoid echoing document text beyond validator messages; logs carry IDs
  and hashes, not content.
