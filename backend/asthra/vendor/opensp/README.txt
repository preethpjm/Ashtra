Packaging ASTHRA with SGML support
==================================
Put the OpenSP programs for the target platform in this folder (any sub-folder is fine):
onsgmls(.exe), osx(.exe) and the libraries/DLLs that come with them, plus OpenSP's COPYING
file (OpenSP is distributed under a permissive MIT-style licence that requires keeping
the copyright notice). ASTHRA finds them automatically; users then need no separate install.

Search order: ASTHRA_OPENSP  ->  <data folder>/tools/opensp  ->  this folder  ->  system PATH.
Check with:  python -m asthra.cli doctor
