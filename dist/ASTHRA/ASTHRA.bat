@echo off
rem ASTHRA portable launcher: starts ASTHRA on this computer only (127.0.0.1) and opens the browser.
setlocal
cd /d "%~dp0"
if not exist "%~dp0python\python.exe" (
  echo python\python.exe is missing. Extract the whole ASTHRA folder first.
  pause & exit /b 1
)
rem Portable data: schemas and projects stay in the "data" folder next to this file.
if not defined ASTHRA_DATA set "ASTHRA_DATA=%~dp0data"
echo Starting ASTHRA ... (data: %ASTHRA_DATA%)
echo Close this window or press Ctrl+C to stop ASTHRA.
"%~dp0python\python.exe" -m asthra.cli serve --open %*
if errorlevel 1 pause
