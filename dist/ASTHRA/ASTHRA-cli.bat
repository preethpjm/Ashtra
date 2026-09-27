@echo off
rem ASTHRA command line, e.g.:  ASTHRA-cli doctor   |   ASTHRA-cli add-schemas "C:\path\to\schemas"
setlocal
if not defined ASTHRA_DATA set "ASTHRA_DATA=%~dp0data"
"%~dp0python\python.exe" -m asthra.cli %*
