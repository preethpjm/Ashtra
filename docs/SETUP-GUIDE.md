# ASTHRA — Setup and Configuration Guide

This guide covers everything needed to set ASTHRA up from scratch and configure it for your
standards: S1000D (every issue), ATA iSpec 2200 / ATA Spec 2300, OEM formats such as ATR's,
and S2000M / S3000L — as XSD schemas, XML DTDs or SGML DTDs.

It describes the software as it is today (version m2.x). Where something is not built or not
yet tested with real data, it says so.

---

## Contents

1. [How ASTHRA validates — the five ideas you need](#1-how-asthra-validates)
2. [Installing ASTHRA](#2-installing-asthra)
3. [Installing OpenSP (only for SGML)](#3-installing-opensp-only-for-sgml)
4. [Which schema source do I have?](#4-which-schema-source-do-i-have)
5. [Recipes: installing each kind of schema](#5-recipes)
   - 5.1 [S1000D — XSD (Issue 4.x, 5.0, 6 …)](#51-s1000d--xsd-issue-4x-50-6-)
   - 5.2 [S1000D — DTDs (older issues, XML or SGML)](#52-s1000d--dtds-older-issues-xml-or-sgml)
   - 5.3 [ATA iSpec 2200 / ATA Spec 2300 — XML with DTDs](#53-ata-ispec-2200--ata-spec-2300--xml-with-dtds)
   - 5.4 [ATA iSpec 2200 — SGML](#54-ata-ispec-2200--sgml)
   - 5.5 [ATR and other OEM formats](#55-atr-and-other-oem-formats)
   - 5.6 [XSD-based sets: S2000M, S3000L, ATA or OEM XSDs](#56-xsd-based-sets-s2000m-s3000l-ata-or-oem-xsds)
   - 5.7 [Ready-made ASTHRA packages and schema sets](#57-ready-made-asthra-packages-and-schema-sets)
6. [Procedure, Description and IPD/IPL](#6-procedure-description-and-ipdipl)
7. [Checking that it works](#7-checking-that-it-works)
8. [When a document is not identified](#8-when-a-document-is-not-identified)
9. [Managing installed schemas](#9-managing-installed-schemas)
10. [Setting up a new computer](#10-setting-up-a-new-computer)
11. [Configuration reference](#11-configuration-reference)
12. [Troubleshooting](#12-troubleshooting)
13. [What is not built yet](#13-what-is-not-built-yet)
14. [Command reference](#14-command-reference)

---

## 1. How ASTHRA validates

**1. Everything is local.** ASTHRA never goes online. Schemas, DTDs and entity files are
installed once from files you have; references to web addresses inside schemas or
documents are mapped to those local copies or ignored.

**2. A schema package** is one installed set of schema files for one standard and one
issue/revision, for example *S1000D Issue 4.1* or *ATA iSpec 2200 revision 2023.1 (SGML)*.
You never write packages by hand: you point ASTHRA at the folder you downloaded, and it
builds the package.

**3. A package contains document types.** For S1000D these are the schema files:
`proced` (Procedure), `descript` (Description), `ipd` (Illustrated parts data), `fault`,
`crew`, and so on. For a DTD set, each `.dtd` file is a document type (for example `cmm`,
`amm`, `ipc`). You choose which ones to install.

**4. Each document is validated against exactly one document type, the one it declares:**

| Source | What in the document decides it |
|---|---|
| S1000D XSD | `xsi:noNamespaceSchemaLocation`, e.g. `http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd` → Issue 4.1, `proced` |
| XML with DTD | the DOCTYPE public identifier (e.g. `-//ATA//DTD …//EN`) or the DTD file name |
| SGML | the DOCTYPE name and public identifier |
| Other XSD (S2000M, S3000L, OEM) | the root element and its namespace |

ASTHRA never guesses. If a document declares nothing, or declares an issue you have not
installed, it lists the installed schemas that fit and **you choose**; every result then
says "schema chosen by you" (see [section 8](#8-when-a-document-is-not-identified)).

**5. Several issues live side by side.** You can have S1000D 4.1 and 6, or an SGML and an
XML DTD set of the same ATA revision, installed at the same time; each document goes to its own.

---

## 2. Installing ASTHRA

### Requirements

- Windows 10/11 (Linux works too)
- Python 3.10 or newer — check with `python --version`
- For SGML only: OpenSP ([section 3](#3-installing-opensp-only-for-sgml))

Node.js is **not** needed: the user interface is already built into the package.

### First installation

```powershell
cd C:\Users\<you>\Downloads
Expand-Archive .\asthra-m2.xx.zip -DestinationPath .\asthra-m2.xx
cd .\asthra-m2.xx\asthra\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
python -m asthra.cli doctor
python -m asthra
```

- `pytest` should report everything passed. A few tests are **skipped** on Windows (they use
  Linux-only stand-ins) and the SGML tests are skipped until OpenSP is installed — both normal.
- `doctor` shows Python, the XML library, OpenSP, the data folder and installed schemas.
- `python -m asthra` starts ASTHRA and opens it at **http://127.0.0.1:8765**. Keep the
  PowerShell window open; **Ctrl+C** stops it.

If `Activate.ps1` is blocked, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Portable edition (no installation, for locked-down corporate PCs)

A folder you unzip and double-click: no installer, no administrator rights, nothing written
outside the folder, and every program in it is a known one (the official, signed `python.exe`
from python.org, libraries from PyPI, OpenSP from MSYS2, and plain-text `.bat` launchers).
Build it once, on a Windows PC where ASTHRA already runs (same Python version you want inside):

```powershell
cd C:\...\asthra-m3.x\asthra
python tools\make_portable.py
```
It downloads the matching embeddable Python from python.org and the libraries from PyPI, copies
ASTHRA and OpenSP (with exactly the DLLs it needs, found by reading the programs' import tables)
and writes `dist\ASTHRA\` plus `dist\ASTHRA-portable-<version>-win64.zip` (about 35 MB).

No internet on that PC? Download the two things yourself and build offline:
```powershell
# python-3.10.11-embed-amd64.zip from python.org (same version as `python --version`)
pip download --only-binary=:all: --platform win_amd64 --python-version 3.10 -d wheels -r backend\requirements-runtime.txt
python tools\make_portable.py --python-zip C:\dl\python-3.10.11-embed-amd64.zip --wheels wheels
```
Options: `--opensp-dir <folder>` (default: the OpenSP ASTHRA already uses), `--no-opensp`,
`--pyc-only` (ship compiled `.pyc` files instead of `.py` sources).

Using it: unblock the zip (right-click → Properties → Unblock), extract it anywhere you can write
(e.g. `C:\Users\<you>\ASTHRA`), double-click **ASTHRA.bat**. Schemas and projects are kept in
its `data` folder, so copying the folder copies everything. `ASTHRA-cli.bat` gives the command
line (`ASTHRA-cli doctor`, `ASTHRA-cli add-schemas …`). Details are in `README-PORTABLE.txt`.

If IT policy blocks programs in user folders (AppLocker), ask for `python\python.exe` in that
folder to be allowed; that is the only executable that starts (plus OpenSP for SGML).

### Where your data lives

Everything you install or create is kept in the **data folder**, not in the program folder:

```
%LOCALAPPDATA%\ASTHRA\            (C:\Users\<you>\AppData\Local\ASTHRA)
  asthra.sqlite3                  projects, documents, validation history
  registry\                       installed schema packages
  projects\<id>\                  imported originals (read-only), drafts, revisions
  tools\                          OpenSP, if installed with install-opensp
```

### Updating ASTHRA

Unzip the new version into a **new** folder and create a fresh `.venv` there (same steps as
above). Your schemas and projects stay, because they are in the data folder. Delete the old
program folder when the new one works. If the browser shows the old interface, press **Ctrl+F5**.

---

## 3. Installing OpenSP (only for SGML)

SGML (legacy ATA iSpec 2200, older OEM data) is read by **OpenSP**, the standard open-source
SGML parser. It is a C++ program, not a Python package, so it is not installed with pip.
You do not need it for XML (S1000D XSD, XML with DTDs).

### Recommended on Windows: MSYS2

1. Install MSYS2 from **msys2.org** (default location `C:\msys64`).
2. Start **"MSYS2 MSYS"** from the Start menu (not UCRT64/MINGW64) and run:
   ```bash
   pacman -S opensp
   ```
   Answer **Y**. If pacman reports an outdated database, run `pacman -Syu`, reopen the window, repeat.
3. In PowerShell (with the `.venv` active):
   ```powershell
   python -m asthra.cli install-opensp C:\msys64\usr\bin
   python -m asthra.cli doctor
   ```
   `doctor` must show `OpenSP … "OpenSP" version "1.5.2"`. The SGML tests now run as well.

`install-opensp` test-runs OpenSP exactly the way ASTHRA uses it before accepting it. A large
shared folder such as MSYS2's `usr\bin` is used **in place**; a small OpenSP folder or zip is
**copied** into the data folder. Nothing is installed if the test fails.

**Not recommended:** the old Win32 zip on SourceForge (openjade project). On current Windows
it usually fails with "a required DLL is missing" (it needs the Visual C++ 2003 runtime).

### How ASTHRA finds OpenSP

In this order: the `ASTHRA_OPENSP` environment variable (a folder) → the data folder
(`install-opensp`) → `backend\asthra\vendor\opensp\` (for packaged installers) → the system PATH.

### Safety

OpenSP is run in restricted mode on a private copy of the document, with a copy of the
installed DTD set: it can read nothing else, and web addresses are removed before it runs.
If OpenSP cannot run, documents are reported as **"NOT checked"** — never as passed.

---

## 4. Which schema source do I have?

Look at the files in what you downloaded:

| You see | It is | Recipe | Needs OpenSP |
|---|---|---|---|
| `proced.xsd`, `descript.xsd`, `ipd.xsd` … with an S1000D header | S1000D XSD (Issue 4.x and later) | [5.1](#51-s1000d--xsd-issue-4x-50-6-) | no |
| `.dtd` files, S1000D public identifiers, **no** `- O` flags | S1000D XML DTDs (older issues) | [5.2](#52-s1000d--dtds-older-issues-xml-or-sgml) | no |
| `.dtd` files with `<!ELEMENT para - O …>` or a `.dcl` file | an **SGML** DTD set (S1000D, ATA or OEM) | [5.2](#52-s1000d--dtds-older-issues-xml-or-sgml) / [5.4](#54-ata-ispec-2200--sgml) | **yes** |
| `.dtd` files, ATA public identifiers, XML syntax | ATA iSpec 2200 / Spec 2300 XML | [5.3](#53-ata-ispec-2200--ata-spec-2300--xml-with-dtds) | no |
| `.dtd` or `.xsd` from an airframer/engine maker | OEM (e.g. ATR) | [5.5](#55-atr-and-other-oem-formats) | if SGML |
| `.xsd` files, namespaced, no S1000D header | S2000M, S3000L, ATA or OEM XSD | [5.6](#56-xsd-based-sets-s2000m-s3000l-ata-or-oem-xsds) | no |
| `asthra-package.json` or `asthra-schema-set.zip` | an ASTHRA package / schema set | [5.7](#57-ready-made-asthra-packages-and-schema-sets) | no |

**You do not have to decide yourself.** Both installers below detect the kind automatically
and tell you what they found. The table is for knowing what to expect.

### Where to get schemas

| Standard | Source |
|---|---|
| S1000D (schemas, entities, BREX) | s1000d.org — free after registering and accepting the S1000D terms |
| ATA iSpec 2200, ATA Spec 2300 (DTDs / schemas) | Airlines for America (A4A), publisher of the ATA specifications, or the OEM whose manuals you handle |
| ATR and other OEM formats | the OEM (customer technical-publications support / portal) |
| S2000M, S3000L and other S-Series | the specification's official site / the S-Series steering committees |

ASTHRA ships only **synthetic test schemas** (marked "test schema"). Use official files for real work.

### The two ways to install

- **Browser:** sidebar → **Schemas → Manage → Choose folder…** (or **Choose zip…**). Only
  schema files are uploaded (`.xsd .dtd .ent .mod .elm .cat .soc .dcl`, `CATALOG`,
  `ISOEntities`, catalog `.xml`) — never manuals, PDFs or images. ASTHRA shows what it found,
  you confirm, and click **Install** (or **Replace installed schemas**).
- **Command line:** `python -m asthra.cli add-schemas "<folder or zip>" [options]` — the same
  detection; it shows what it found and asks before installing (add `--yes` to skip the question).

---

## 5. Recipes

Always put paths with spaces in quotes. Replace example paths with yours.

### 5.1 S1000D — XSD (Issue 4.x, 5.0, 6 …)

**What to point at:** the whole issue folder you downloaded is fine (for example
`Issue 4.1\`). ASTHRA finds every copy of the schemas inside it — original release, patches,
data dictionary — and preselects the **latest patch**. It also finds the ISO **entity** folder
(`ent\` or `XML Schema package\entities\`, with `ISOEntities` and `iso-*.ent`) and bundles it,
so documents using `&deg;`, `&mdash;` … validate.

**Browser:** Schemas → Manage → Choose folder… → select the issue folder →
check *Schema copy* (latest patch), *Issue* (read from the schemas), *Document types*
(Procedure, Description and IPD ticked), *Entity files* → **Install**.

**Command line:**
```powershell
# see what is inside and install Procedure, Description and IPD (the default types)
python -m asthra.cli add-schemas "C:\Users\<you>\Downloads\Issue 4.1"

# the same without the question
python -m asthra.cli add-schemas "C:\Users\<you>\Downloads\Issue 4.1" --yes

# other document types
python -m asthra.cli add-schemas "C:\...\Issue 4.1" --types proced,descript,ipd,fault,crew,checklist --yes

# add types later to an installed issue (documents stay linked)
python -m asthra.cli add-schemas "C:\...\Issue 4.1" --types proced,descript,ipd,fault --replace --yes
```

Options you may need:
- `--folder "<path as listed>"` — choose a different schema copy than the preselected one.
  Use the path exactly as `add-schemas` prints it in its list.
- `--entities none` — do not bundle entity files.
- `--issue 4.1` — normally read from the schemas; ASTHRA refuses a value that contradicts them.

**Each issue is installed separately**, in its own folder: install 4.1 from the 4.1
download and 6 from the 6 download. Do not mix issues in one folder.

**Only one schema copy?** You can also point at the `xml_schema_flat` folder directly, or use
the older command, which takes an absolute entity folder:
```powershell
python -m asthra.cli make-package "C:\...\xml_schema_flat" --issue 4.1 --only proced,descript,ipd --entities "C:\...\ent" --install
```

Package name after installing: `s1000d/<issue>/official`, e.g. `s1000d/4.1/official`.

**S1000D document types (schema file → content):**

| Type | Content | Type | Content |
|---|---|---|---|
| `proced` | Procedure | `descript` | Description |
| `ipd` | Illustrated parts data (IPD/IPL) | `fault` | Fault isolation/reporting |
| `crew` | Crew/operator information | `checklist` | Checklist |
| `schedul` | Maintenance planning | `process` | Process data module |
| `sb` | Service bulletin | `learning` | Learning |
| `pm` | Publication module | `dml` | Data module list |
| `brex` | Business rules exchange | `comment`, `ddn` | Comments, data dispatch notes |
| `wrngdata`, `wrngflds` | Wiring data | `appliccrossreftable` … | Cross-reference tables |

A type whose schema needs files that are not in the download (for example
`scormcontentpackage`, which needs a separate LOM schema) is skipped and named in the output;
the others install normally.

### 5.2 S1000D — DTDs (older issues, XML or SGML)

Older S1000D issues were also published with DTDs (XML and/or SGML syntax). If your issue came
with DTDs, install them as a **DTD set** and label it S1000D:

**Browser:** Schemas → Manage → Choose folder… → the DTD folder → ASTHRA shows
*"a DTD set"* (XML) or *"an SGML DTD set"* → Standard **S1000D**, Issue e.g. `3.0` → Install.

**Command line:**
```powershell
python -m asthra.cli add-schemas "C:\...\S1000D_3.0_DTDs" --standard S1000D --issue 3.0 --yes
```

SGML DTD sets need OpenSP ([section 3](#3-installing-opensp-only-for-sgml)).

Honest notes: this path is tested with synthetic DTDs, not with real S1000D DTD issues.
Older S1000D issues also use different element names from Issue 4.x onwards, so the document
view's S1000D layout rules may only partly apply to them (validation is unaffected);
see [render_roles](#display-rules-render_roles) to adjust the display.

### 5.3 ATA iSpec 2200 / ATA Spec 2300 — XML with DTDs

**What to point at:** one folder with the `.dtd` files, their entity/module files
(`.ent`, `.mod`, `.elm`) and the **catalog** (an OASIS `catalog.xml` or an SGML-style
`CATALOG` file). The catalog tells ASTHRA which public identifier belongs to which DTD; that
is how documents are recognised.

**Browser:** Choose folder… → *"a DTD set"* → Standard **ATA2200** (or ATA2300), **Issue /
revision** (for example `2023.1` — it cannot be read from the files), tick the document types →
Install. If a DTD's top element cannot be determined, pick it from the list shown in that row.

**Command line:**
```powershell
python -m asthra.cli add-schemas "C:\...\ATA_iSpec2200_DTDs" --standard ATA2200 --issue 2023.1 --yes

# only some DTDs
python -m asthra.cli add-schemas "C:\...\ATA_iSpec2200_DTDs" --standard ATA2200 --issue 2023.1 --types cmm,amm,ipc --yes

# a DTD whose top element is unclear (the output tells you which)
python -m asthra.cli add-schemas "C:\...\ATA_iSpec2200_DTDs" --standard ATA2200 --issue 2023.1 --root amm=amm --yes
```

Package name: `ata2200/<revision>/official`.

**Documents must have a DOCTYPE.** DTD-based XML identifies itself through its DOCTYPE. A file
without one is offered as *needs-choice*; and a file without a DOCTYPE that uses named
entities (`&mdash;`) is not well-formed XML — ASTHRA says so and why.

Honest note: tested with a synthetic ATA-style DTD. The document view's ATA layout uses common
iSpec 2200 element names (`pgblk`, `task`, `subtask`, `list1`–`list7`, `l1item`…, CALS tables);
if your DTDs differ, adjust with [render_roles](#display-rules-render_roles).

### 5.4 ATA iSpec 2200 — SGML

Legacy iSpec 2200 data is often SGML: tags may be upper case, end tags left out, attribute
values unquoted. It needs OpenSP ([section 3](#3-installing-opensp-only-for-sgml)).

**What to point at:** the SGML DTD folder — `.dtd`, entity files (`.ent`), the `CATALOG`,
and the SGML declaration (`.dcl`) if the set has one. ASTHRA recognises it as SGML from the
DTD's tag-omission flags or the `.dcl` file.

**Browser:** Choose folder… → *"an SGML DTD set"* → Standard **ATA2200**, revision → Install.

**Command line:**
```powershell
python -m asthra.cli add-schemas "C:\...\ATA_SGML_DTDs" --standard ATA2200 --issue 2019.1 --yes
```

Package name: `ata2200/<revision>/sgml` — so an SGML and an XML DTD set of the same
revision can both be installed.

**How SGML documents behave in ASTHRA:**
- Validation with line numbers and plain-language messages (OpenSP's messages, explained).
- The **Document** view shows OpenSP's XML conversion of the file, **read-only**; edit the
  SGML itself in **Source** — the view updates after each check.
- No one-click fixes for SGML (the suggestion is shown instead).

**Try it first with the example:** `ispec2200-sgml-example.zip` contains a synthetic
ATA-style SGML DTD set and two documents (one valid, one with five deliberate errors):
```powershell
python -m asthra.cli add-schemas "C:\...\ispec2200-sgml-example\DTD set (synthetic ATA-style CMM)" --issue example-1 --standard ATA2200 --yes
```
The Samples project (**Load sample documents**) contains the same example.

### 5.5 ATR and other OEM formats

OEM formats are installed exactly like the recipe that matches their files, with the
standard **OEM** and a name you will recognise:

| OEM files are | Use | Example |
|---|---|---|
| XML DTDs | [5.3](#53-ata-ispec-2200--ata-spec-2300--xml-with-dtds) | `add-schemas "C:\...\ATR_CMM_DTD" --standard OEM --issue 3.2 --name "ATR CMM DTD 3.2" --yes` |
| SGML DTDs | [5.4](#54-ata-ispec-2200--sgml) | `add-schemas "C:\...\ATR_SGML" --standard OEM --issue 3.2 --name "ATR CMM SGML 3.2" --yes` |
| XSD schemas | [5.6](#56-xsd-based-sets-s2000m-s3000l-ata-or-oem-xsds) | `add-schemas "C:\...\ATR_XSD" --standard OEM --issue 3.2 --name "ATR schemas 3.2" --yes` |

If an OEM format is an ATA iSpec 2200 derivative, you may prefer `--standard ATA2200` so the
ATA document layout is used; validation is the same either way.

### 5.6 XSD-based sets: S2000M, S3000L, ATA or OEM XSDs

**What to point at:** the folder with the `.xsd` files (and anything they include/import).

ASTHRA lists candidate **document roots**: global elements that no other element uses, in
schemas that no other schema includes. You tick the ones your files start with. It guesses
the standard from the namespace (S2000M, S3000L …) — correct it if needed.

**Browser:** Choose folder… → *"an XSD schema set"* → Standard, **Issue**, tick the roots → Install.

**Command line:**
```powershell
python -m asthra.cli add-schemas "C:\...\S2000M_6.1_schemas" --standard S2000M --issue 6.1 --yes
python -m asthra.cli add-schemas "C:\...\S3000L_2.0_schemas" --standard S3000L --issue 2.0 --types <rootElement> --yes
```
(`--types` takes root element names as listed in the proposal.)

Documents are recognised by root element and namespace. If two installed issues share the
same namespace and root, ASTHRA reports *ambiguous* and you choose.

Honest note: tested with synthetic S2000M/S3000L schemas; please report how it behaves with
the official ones.

### 5.7 Ready-made ASTHRA packages and schema sets

- A **package** (a zip or folder containing `asthra-package.json`, e.g. from **Export** in the
  schema manager) installs as it is: Choose zip… or `add-schemas <zip> --yes`.
- A **schema set** (`asthra-schema-set.zip`, from **Export all schemas**) installs every package
  it contains: **Import schema set…** or `python -m asthra.cli schemas import-set <zip>`.

---

## 6. Procedure, Description and IPD/IPL

| Content | S1000D | ATA iSpec 2200 | What ASTHRA does |
|---|---|---|---|
| **Procedure** | document type `proced` (`<procedure>`) | tasks and subtasks inside a manual DTD (e.g. `cmm`, `amm`) | validates; renders numbered steps (1., 1.1. for S1000D; A., (1), (a) for ATA), preliminary requirements, warnings/cautions/notes, tables |
| **Description** | `descript` (`<description>`) | descriptive page blocks inside the manual DTD | validates; renders sections, headings, paragraphs, figures, tables |
| **IPD / IPL** | `ipd` (`<illustratedPartsCatalog>`) | the IPC / illustrated parts list DTD | validates; renders catalog items as framed records (figure/item/part/quantity) |

For **S1000D**, install the three types together (they are the default):
```powershell
python -m asthra.cli add-schemas "C:\...\Issue 6" --types proced,descript,ipd --yes
```
ASTHRA tells them apart from the schema location in each document
(`…/proced.xsd`, `…/descript.xsd`, `…/ipd.xsd`), and — for documents that declare no schema —
from the content (`<procedure>`, `<description>`, `<illustratedPartsCatalog>`).

For **ATA**, procedure and description content usually live in the same manual DTD, so you
install the DTDs for the manuals you handle (CMM, AMM, IPC …).

The IPD/IPL display is currently a list of framed records; a dedicated illustrated-parts table
and figure workspace is part of the document-view work ([section 13](#13-what-is-not-built-yet)).

---

## 7. Checking that it works

```powershell
python -m asthra.cli doctor             # Python, XML library, OpenSP, data folder, every package (intact?)
python -m asthra.cli schemas list       # installed packages, enabled or not, how many documents use each
python -m asthra.cli why "C:\...\file.xml"   # which installed schema matches an XML file, and why not
```

`why` prints, for every installed document type: root element ok?, does the document declare
it?, content filter ok? — and the final result. It works for XML; SGML is identified on import.

**Then in the browser:** create a project, **Import** a document, open it. The header shows the
standard, issue and document type (e.g. **S1000D 4.1 · proced**); the right panel shows
**Structure: Passed/Failed**; the Problems panel lists what is wrong with line numbers.
Click a problem to jump to it; in **Source** errors are underlined, **Ctrl+.** offers a fix
where the correct value is certain.

**Print / PDF:** Export → **Print / Save as PDF…** prints the document view on A4 pages with a
running header (code and title) and footer (issue, date, "Page n of m"). Choose "Save as PDF"
as the printer to get a PDF.

**Editing with the schema** (any installed XSD, XML DTD or SGML DTD):
- Select an element and press **Ctrl+Enter** (or **+ Insert…** in the Element panel). The menu lists
  only what the schema allows *after*, *before* or *inside* the element, and inline elements *at the
  cursor* in text (references, quantities, emphasis …). A table is simply not offered where it is not allowed.
- New elements come with their required children and attributes. IDs are generated; values the
  schema lists are offered as choices; references are chosen from the document's own IDs
  ("Figure 2 (fig-0002)").
- **Enter** at the end of a paragraph adds another one where the schema allows it.
- The **Attributes** panel marks required attributes (*), lets you remove optional ones and add
  missing ones; allowed values and ID references are lists.
- **Delete** and **↑ ↓** check the schema: moving into an order the schema forbids is refused;
  deleting a required element asks first.
- **SGML** documents are edited the same way. Each change is written back as SGML and checked by
  OpenSP. The saved SGML is *normalised*: all end tags are written out and attribute values are
  quoted and lower case — valid, equivalent SGML, but not byte-identical to hand-written shorthand.

A passed structure is **not** engineering approval; business rules (BREX), references and
engineering checks are shown separately as "not available yet".

---

## 8. When a document is not identified

The header and the banner above the document say which case you are in:

| Status | Meaning | What to do |
|---|---|---|
| **identified** | the document declares an installed schema | nothing |
| **needs-choice** | it fits installed schemas but does not declare one (no schema location, a relative path, no DOCTYPE), or declares an issue you have not installed | install the declared issue, **or** pick one under *Validate against* in the right panel; results then say "schema chosen by you" |
| **ambiguous** | two installed packages match exactly | pick one in the right panel, or disable one package |
| **unidentified** | no installed schema fits its root element | install its schema package |
| **SGML, not identified** | SGML whose DOCTYPE matches no installed SGML set | install its SGML DTD set (and OpenSP) |

Documents imported **before** you installed their schema are identified again automatically
when you open them. A schema you chose yourself is never changed automatically.

---

## 9. Managing installed schemas

**Browser:** Schemas → **Manage** — the list shows each package with an on/off switch,
the number of documents using it, **Export** and **Remove**.

**Command line:**
```powershell
python -m asthra.cli schemas list
python -m asthra.cli schemas remove s1000d/4.1/official             # refused if documents use it
python -m asthra.cli schemas remove s1000d/4.1/official --force     # unlinks those documents
python -m asthra.cli schemas export s1000d/4.1/official s1000d-4.1.zip
```

- **Replace** (reinstall a new build of the same issue, e.g. with more document types):
  install again and choose **Replace**, or add `--replace`. Documents stay linked; a replacement
  that would drop a document type still in use is refused.
- **Disable** hides a package from identification without removing it.
- **Remove --force** unlinks documents that used it; they are identified again when opened.
- Each package is checksummed; `doctor` reports a damaged package ("DAMAGED – reinstall").

---

## 10. Setting up a new computer

On the configured computer:
```powershell
python -m asthra.cli schemas export-all asthra-schema-set.zip
```
(or Schemas → Manage → **Export all schemas**)

On the new computer: install ASTHRA ([section 2](#2-installing-asthra)), OpenSP if you use SGML
([section 3](#3-installing-opensp-only-for-sgml)), then:
```powershell
python -m asthra.cli schemas import-set asthra-schema-set.zip
python -m asthra.cli doctor
```
Identical packages are skipped, newer builds replace older ones. Projects and documents are not
part of the schema set; to move them too, copy the whole data folder (with ASTHRA stopped).

---

## 11. Configuration reference

### Environment variables

| Variable | Meaning |
|---|---|
| `ASTHRA_DATA` | data folder (default `%LOCALAPPDATA%\ASTHRA`) |
| `ASTHRA_OPENSP` | folder containing `onsgmls` and `osx`; overrides the other OpenSP locations |

Every command also accepts `--data <folder>` to use another data folder (for example a test setup):
```powershell
python -m asthra --data C:\asthra-test serve --open
python -m asthra.cli --data C:\asthra-test schemas list
```

### Port

```powershell
python -m asthra.cli serve --open --port 8800
```
ASTHRA only listens on 127.0.0.1 (this computer).

### Package identifiers

| Source | Identifier |
|---|---|
| S1000D XSD | `s1000d/<issue>/official` |
| XML DTD set | `<standard>/<revision>/official` |
| SGML DTD set | `<standard>/<revision>/sgml` |
| XSD set | `<standard>/<issue>/official` (`oem/<issue>/oem` for OEM) |

### Display rules (render_roles)

The document view renders by **role** (step, list level, warning, table, record …), using a
built-in profile per standard: S1000D, ATA (iSpec 2200 / Spec 2300), S2000M/S3000L, and a
generic one. Roles affect only the display, never validation.

To change or extend them for an OEM or older format, add `render_roles` to the package's
`asthra-package.json` and reinstall it (with Replace):
1. Export the package (schema manager → Export), unzip it.
2. Edit `asthra-package.json`, add for example:
   ```json
   "render_roles": { "procstep": "step", "prcitem": "item", "subproc": "step-seq", "effectivity": "meta" }
   ```
3. Zip the folder again and install it (Choose zip… → Replace).

Available roles are listed at the top of `backend/asthra/render/profiles.py`
(`section`, `title`, `para`, `step-seq`, `step`, `list-alpha`, `list-paren-num`, `item`,
`warning`, `caution`, `note`, `table`, `figure`, `record`, `field`, `meta`, `hidden` …).
The manifest format itself is described in `docs/03-SCHEMA-ADAPTER-INTERFACE.md`.

### Packaging ASTHRA with SGML support

Put `onsgmls(.exe)`, `osx(.exe)`, their DLLs and OpenSP's `COPYING` file into
`backend\asthra\vendor\opensp\`. ASTHRA finds them automatically. OpenSP's licence is
permissive (MIT-style) and requires keeping the copyright notice.

---

## 12. Troubleshooting

| Message / symptom | Cause | Fix |
|---|---|---|
| `these schemas declare Issue X, not Y` | the folder is a different S1000D issue | use `--issue X`, or the other issue's folder |
| `skipped (missing dependency) scormcontentpackage …` | that type needs files not in the download | ignore, or add the missing schema folder |
| `no .xsd files found` / `Not found` | wrong path (or a placeholder like `C:\path\to\…`) | use the real folder; quote paths with spaces |
| `The issue/revision is required` | DTD/SGML/XSD sets cannot state their revision | add `--issue <revision>` (or fill it in the form) |
| `top element could not be determined` | a DTD with several possible roots | `--root <dtd>=<element>` or choose it in the form |
| `already installed` | that issue is installed | `--replace` (or **Replace** in the form) |
| document **needs-choice** though its issue is installed | it declares no or a relative schema location | pick the schema in the right panel; `why <file>` shows details |
| `ASTHRA-SEC-003 … not part of the installed schema package` | the document refers to a file that is not installed (often the ISO entity sets) | rebuild the S1000D package with its entity folder (it is found automatically in a full issue download) |
| `&xyz; is a named entity … needs a DOCTYPE` | named entities in a file without DOCTYPE | add the DOCTYPE, or replace the entity with the character |
| `ASTHRA-SGML-001 … OpenSP was not found` | SGML without OpenSP | [section 3](#3-installing-opensp-only-for-sgml) |
| `ASTHRA-SGML-002 … NOT checked: OpenSP could not run` | OpenSP is installed but fails | `doctor` shows OpenSP's own error; reinstall via MSYS2 |
| `a required DLL is missing (0xC0000135)` | old SourceForge OpenSP build | use the MSYS2 build |
| blank page / old interface | browser cache, or the old program folder | **Ctrl+F5**; check you started the new folder |
| `Activate.ps1 cannot be loaded` | PowerShell policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

When asking for help, the output of `python -m asthra.cli doctor` and, for a specific file,
`python -m asthra.cli why "<file>"` answer most questions.

---

## 13. What is not built yet

| Area | Status |
|---|---|
| Business-rule validation (S1000D BREX, project rules) | planned; shown as "not available yet" |
| Splitting a paragraph at the cursor, wrapping/unwrapping selected text in an element | planned (inserting, deleting, moving and attribute editing are done) |
| On-screen page breaks and a table of contents | next (print/PDF already paginates; figure/table numbering done) |
| Graphics: showing ICN images (PNG/JPG/SVG); CGM files | next milestone (CGM will show as a card) |
| Knowledge graph and translation between standards (S2000M/S3000L → S1000D, ATA ↔ S1000D) | planned (Milestones 5–6) |
| One-click fixes for SGML problems | the suggestion is shown; SGML is otherwise edited like XML |
| Windows installer | planned (Milestone 7) |

---

## 14. Command reference

All commands: `python -m asthra.cli [--data <folder>] <command> …`
(`python -m asthra` alone starts the server and opens the browser.)

| Command | Purpose |
|---|---|
| `serve [--open] [--port N]` | start ASTHRA on 127.0.0.1 |
| `doctor` | check the installation |
| `add-schemas <folder\|zip> [--issue] [--standard] [--name] [--types] [--folder] [--entities] [--root D=E] [--replace] [--yes]` | install any schema source |
| `schemas list` | list installed packages |
| `schemas remove <id> [--force]` | uninstall |
| `schemas export <id> [file]` | export one package |
| `schemas export-all [file]` | export every package as a schema set |
| `schemas import-set <file>` | install a schema set |
| `install-opensp <folder\|zip>` | make OpenSP available for SGML |
| `why <xml file>` | explain schema matching for a file |
| `schema-issue <folder>` | show which S1000D issue a schema folder contains |
| `make-package <xsd folder> --issue I [--only types] [--entities folder] [--install] [--replace]` | S1000D packages (older, direct command) |
| `make-dtd-package <folder> --standard S --issue I [--root D=E] [--install] [--replace]` | XML DTD packages (older, direct command) |
| `new-project <name>` · `projects` | create / list projects |
| `import <project-id> <file> [--package id --doc-type t]` | import a document (optionally with a chosen schema) |
| `documents <project-id>` | list a project's documents |
| `validate <document-id>` | validate and print the results |
| `demo` | install the synthetic samples and validate them |
