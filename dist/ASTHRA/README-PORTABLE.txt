ASTHRA 0.1.0-m1 - portable edition for Windows
==============================================

No installation and no administrator rights are needed. Nothing is written outside this folder.

START
  1. If you downloaded the zip: right-click it > Properties > tick "Unblock" > OK   (before extracting)
  2. Extract the whole zip to a folder you can write to, e.g. C:\Users\<you>\ASTHRA
     (not Program Files, and not inside the zip viewer)
  3. Double-click ASTHRA.bat. The browser opens at http://127.0.0.1:8765
     Keep the black window open while you work; closing it stops ASTHRA.

COMMAND LINE (optional)
  Open a Command Prompt in this folder and use ASTHRA-cli.bat, for example:
    ASTHRA-cli doctor
    ASTHRA-cli add-schemas "C:\path\to\Issue 4.1"
    ASTHRA-cli schemas list

YOUR DATA
  Schemas, projects and documents are kept in the "data" folder here, so copying this folder copies
  everything. To use your Windows profile instead, set ASTHRA_DATA before starting, e.g.
    set ASTHRA_DATA=%LOCALAPPDATA%\ASTHRA

SHARING
  - Whole setup: zip this folder (with or without "data") and send it.
  - Schemas only: in ASTHRA, Schemas > Manage > Export all schemas; the other person imports that file.

WHAT IS INSIDE (all readable, nothing packed or obfuscated)
  python\          official embeddable Python 3.10.11 from python.org (python.exe is signed by the PSF)
  app\asthra\      ASTHRA; app\asthra\web\dist is the interface; app\tests\fixtures are the samples
  app\asthra\vendor\opensp\  OpenSP for SGML, with the DLLs it needs and its licences
  ASTHRA.bat       launcher (plain text - open it in Notepad to see exactly what it does)

SECURITY
  ASTHRA only listens on 127.0.0.1 (this computer), never goes online, and reads schema and entity
  files only from what you install. See docs in the project for details.

IF IT DOES NOT START
  - "Windows protected your PC" (SmartScreen): More info > Run anyway, or ask IT to allow the folder.
  - Nothing happens / "not recognized": IT policy (AppLocker) may block programs in your user folders;
    ask IT to allow python\python.exe in this folder.
  - "address already in use": another ASTHRA is running, or start on another port:
      ASTHRA.bat --port 8800
  - Run  ASTHRA-cli doctor  and send its output when asking for help.
