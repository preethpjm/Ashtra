# ASTHRA — Aerospace Structured Technical Hub & Reasoning Architecture

Local, offline-first engineering information platform. S1000D, S2000M and S3000L are
first-class peer standards from Phase 1.

**Current state: Milestones 1 and 2 implemented.** A working desktop-style editor runs in
your browser against a local server. Schema-constrained structural editing (inserting and
removing elements) is Milestone 3. See `docs/05-PHASE1-PLAN.md` for exact status.

> **Portable Windows edition (unzip and double-click, no admin):** `python tools\make_portable.py` —
> see "Portable edition" in [docs/SETUP-GUIDE.md](docs/SETUP-GUIDE.md).
>
> **Design of the master knowledge model** (S1000D / S2000M / S3000L sharing one store of product facts,
> aligned with SX000i / SX002D): [docs/06-KNOWLEDGE-MODEL.md](docs/06-KNOWLEDGE-MODEL.md).
>
> **Setting ASTHRA up, installing schemas (S1000D XSD, DTD and SGML sets, ATA iSpec 2200 /
> Spec 2300, OEM, S2000M/S3000L) and configuring it: see [docs/SETUP-GUIDE.md](docs/SETUP-GUIDE.md).**

## What you can do now

* Load the sample S-Series set (S1000D Description, Procedure, IPD; S2000M provisioning;
  S3000L tasks) with one click, or import your own XML.
* Edit text visually in **Clean** (reads like the publication) or **Tags** (every element
  shown as a labelled bracket), or edit anything in **Source** (Monaco). **Split** shows
  visual and source side by side, kept in sync.
* See problems live as you type, with line numbers, element paths, markers in the source,
  outlines in the visual view and counts in the Structure tree. Click a problem to jump to it.
* Edit attribute values in the inspector.
* Save drafts (Ctrl+S), commit numbered read-only revisions, restore any revision, export
  the current version, the original, or a validation report.
* The imported original is never modified. Visual edits rewrite only the element you
  changed; the rest of the file stays byte-for-byte identical.

## Quick start (Windows PowerShell, Python 3.10+)

```powershell
cd asthra\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q                         # backend tests, network disabled

python -m asthra                            # starts ASTHRA and opens it in your browser
```

Click **Load sample documents** on first start. Data is kept in `%LOCALAPPDATA%\ASTHRA`;
use `python -m asthra --data .\demo serve --open` for a separate data folder.
Stop the server with Ctrl+C in the terminal.

Node.js is **not** needed to run ASTHRA: the UI is pre-built into `backend/asthra/web/dist`.
Only to change the UI: `cd frontend; npm install; npm run dev` (dev server with live reload,
proxies to the backend on port 8765), `npm test`, and `npm run build`.

## Installing schemas

**In the app:** sidebar → Schemas → **Manage** → **Choose folder…** (or **Choose zip…**). Point it at
what you downloaded — the whole S1000D issue folder, a folder of ATA/OEM DTDs, an S2000M/S3000L
XSD folder, or an ASTHRA package. ASTHRA uploads only the schema files (never manuals or PDFs),
works out what they are, and shows a short form:

| Source | What ASTHRA detects | What you confirm |
|---|---|---|
| S1000D download (any issue) | issue from the schemas, every schema copy (latest patch preselected), ISO entity folder | document types (Procedure, Description, IPD ticked) |
| DTD set (ATA iSpec 2200 / Spec 2300 / OEM) | document types, top elements, public identifiers from the catalog | standard, revision, any top element it could not determine |
| XSD set (S2000M, S3000L, OEM) | root elements and namespaces, standard from the namespace | issue, which elements are document roots |
| ASTHRA package | everything | nothing |

Then **Install** (or **Replace** if that issue is already installed; documents stay linked).
The same screen lists installed packages with enable/disable, **Export** and **Remove**.

**New system:** **Export all schemas** on the old one → **Import schema set…** on the new one.

**Command line (same logic):**
```powershell
python -m asthra.cli add-schemas "C:\Users\you\Downloads\Issue 4.1"                # asks before installing
python -m asthra.cli add-schemas "C:\...\ATA_DTDs" --standard ATA2200 --issue 2023.1 --yes
python -m asthra.cli schemas list | remove <id> [--force] | export <id> [file] | export-all [file] | import-set <file>
python -m asthra.cli why "C:\path\to\document.xml"                                  # which schema matches, and why
```
**SGML (legacy ATA iSpec 2200, OEM SGML).** Needs OpenSP (onsgmls + osx), a C++ program (not on pip).
Windows: install MSYS2 (msys2.org), open "MSYS2 MSYS", run `pacman -S opensp`, then
`python -m asthra.cli install-opensp C:\msys64\usr\bin` (used in place, no PATH changes). A small
OpenSP folder or zip is copied into the data folder instead. Either way it is test-run first; check
any time with `python -m asthra.cli doctor`. (The old SourceForge Win32 build often lacks DLLs.)
For a packaged installer, put the OpenSP files in `backend/asthra/vendor/opensp/` (see the README
there); ASTHRA finds them automatically. Install the SGML DTD set like any other (Schemas → Manage);
SGML documents then validate with line-accurate messages and render in the Document view (read-only,
through OpenSP's XML conversion); edit the SGML in Source. OpenSP runs sandboxed: only the document
copy and the installed DTD set can be read, and remote addresses are removed before it runs.

Every document is validated against exactly one installed schema, the one it declares. If it
declares none (or an issue you have not installed), ASTHRA lists the installed schemas that fit
and you choose; the results then say "schema chosen by you". Legacy **SGML** iSpec 2200 files are
validated and rendered through OpenSP (see above).

## The document view

**Document** renders the publication; the **Tags** switch shows every element's bracket
and name on top of it; **Source** is the XML; **Split** shows both, in sync. Rendering
is role-based: each standard has a profile mapping element names to roles (step, list
level, warning, table, record, field…). S1000D gets numbered procedural steps and
labelled requirement sections; ATA gets A. / (1) / (a) / 1) / a) step numbering;
S2000M/S3000L data reads as records with labelled fields. A package can override roles
with `render_roles` in its manifest (see docs/03). Named entities (&mdash;, &deg;) show
as their characters and are written back unchanged.

## Important: test schemas are synthetic

`tests/fixtures/packages/*` are **synthetic** schemas written for this project. They borrow
recognisable element names so the fixtures read naturally, but they are not the official
S1000D, S2000M or S3000L schemas and are labelled `provenance: synthetic`; every validation
against them says so. For real work, install the official schema packages you are licensed
to use. No restricted OEM or licensed standard material is included.

## Documents

1. `docs/01-ARCHITECTURE.md` — process model, repository layout, layering, security
2. `docs/02-CANONICAL-MODEL.md` — knowledge core specification (SX002D-aligned approach)
3. `docs/03-SCHEMA-ADAPTER-INTERFACE.md` — schema packages, adapters, mapping packages
4. `docs/04-EDITOR-DOCUMENT-MODEL.md` — ADM and editor synchronization strategy
5. `docs/05-PHASE1-PLAN.md` — milestones, S-Series flows, risks, status
