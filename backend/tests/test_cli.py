"""The real command line: every subcommand must at least parse and run."""
import pytest

from asthra.cli import main
from tests.conftest import FIX, PKGS


def test_help_parses(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("serve", "add-schemas", "schemas", "why", "make-package", "make-dtd-package", "demo", "doctor"):
        assert cmd in out


def test_add_schemas_and_manage(tmp_path, capsys):
    data = str(tmp_path / "d")
    assert main(["--data", data, "add-schemas", str(FIX / "dtd" / "ata-synth"), "--issue", "2023.1",
                 "--standard", "ATA2200", "--yes"]) == 0
    assert main(["--data", data, "add-schemas", str(PKGS / "s2000m-synth"), "--yes"]) == 0
    assert main(["--data", data, "schemas", "list"]) == 0
    out = capsys.readouterr().out
    assert "ata2200/2023.1/official" in out and "s2000m/" in out
    z = tmp_path / "set.zip"
    assert main(["--data", data, "schemas", "export-all", str(z)]) == 0 and z.is_file()
    assert main(["--data", data, "schemas", "remove", "ata2200/2023.1/official"]) == 0
    assert main(["--data", str(tmp_path / "new"), "schemas", "import-set", str(z)]) == 0
    assert "installed" in capsys.readouterr().out


def test_add_schemas_without_issue_explains(tmp_path, capsys):
    assert main(["--data", str(tmp_path / "d"), "add-schemas", str(FIX / "dtd" / "ata-synth"), "--yes"]) == 2
    assert "--issue" in capsys.readouterr().out



def test_doctor(tmp_path, capsys, monkeypatch):
    (tmp_path / "no-opensp").mkdir()
    monkeypatch.setenv("ASTHRA_OPENSP", str(tmp_path / "no-opensp"))     # independent of this machine
    assert main(["--data", str(tmp_path / "d"), "doctor"]) == 0
    out = capsys.readouterr().out
    assert "OpenSP" in out and "Schemas" in out and "lxml" in out


def test_install_opensp_into_the_data_folder(tmp_path, monkeypatch, capsys):
    """install-opensp copies a downloaded OpenSP into the data folder; ASTHRA then prefers it."""
    import shutil
    onsgmls, osx = shutil.which("onsgmls"), shutil.which("osx")
    if not (onsgmls and osx):
        pytest.skip("OpenSP not available to copy")
    monkeypatch.setenv("ASTHRA_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("ASTHRA_OPENSP", raising=False)
    dl = tmp_path / "OpenSP-download" / "bin"; dl.mkdir(parents=True)
    shutil.copy(onsgmls, dl / "onsgmls"); shutil.copy(osx, dl / "osx")
    (tmp_path / "OpenSP-download" / "COPYING").write_text("Copyright (c) James Clark")
    assert main(["install-opensp", str(tmp_path / "OpenSP-download")]) == 0
    from asthra.validation.sgml import find_tools
    tools = find_tools()
    assert tools and str(tmp_path / "data") in tools[0]
    assert (tmp_path / "data" / "tools" / "opensp" / "COPYING").is_file()
    assert main(["doctor"]) == 0
    assert "[data folder]" in capsys.readouterr().out


def test_install_opensp_rejects_a_folder_without_it(tmp_path, capsys):
    (tmp_path / "nothing").mkdir()
    assert main(["install-opensp", str(tmp_path / "nothing")]) == 2
    assert "No onsgmls and osx" in capsys.readouterr().out



def test_broken_opensp_is_reported_not_installed(tmp_path, monkeypatch, capsys):
    """Regression (Windows): OpenSP that prints nothing (e.g. a missing DLL) crashed the check
    with 'list index out of range'. It must be diagnosed and nothing installed."""
    import os, stat, sys
    if os.name == "nt":
        pytest.skip("uses a POSIX shell script as a stand-in program")
    monkeypatch.setenv("ASTHRA_DATA", str(tmp_path / "data"))
    d = tmp_path / "broken"; d.mkdir()
    for n in ("onsgmls", "osx"):
        f = d / n; f.write_text("#!/bin/sh\nexit 1\n"); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    assert main(["install-opensp", str(d)]) == 2
    out = capsys.readouterr().out
    assert "Nothing was installed" in out and "tiny valid SGML test document" in out
    assert not (tmp_path / "data" / "tools" / "opensp").exists()


def test_windows_start_failures_are_explained():
    from asthra.validation.sgml import explain_exit
    assert "DLL is missing" in explain_exit(0xC0000135)
    assert "DLL is missing" in explain_exit(-1073741515)          # same code as a signed int
    assert explain_exit(1) is None


def test_large_shared_folder_is_registered_in_place(tmp_path, monkeypatch, capsys):
    import os, shutil
    onsgmls, osx = shutil.which("onsgmls"), shutil.which("osx")
    if not (onsgmls and osx) or os.name == "nt":
        pytest.skip("needs OpenSP to copy")
    monkeypatch.setenv("ASTHRA_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("ASTHRA_OPENSP", raising=False)
    big = tmp_path / "msys64" / "usr" / "bin"; big.mkdir(parents=True)
    shutil.copy(onsgmls, big / "onsgmls"); shutil.copy(osx, big / "osx")
    for i in range(70):
        (big / f"other{i}.dll").write_text("x")
    assert main(["install-opensp", str(big)]) == 0
    assert "Using it in place" in capsys.readouterr().out
    from asthra.validation.sgml import find_tools
    assert str(big) in find_tools()[0]
    assert not (tmp_path / "data" / "tools" / "opensp").exists()



def test_add_schemas_sgml_dtd_set(tmp_path, capsys):
    """Regression: add-schemas crashed with KeyError: 'sgml' on an SGML DTD set."""
    data = str(tmp_path / "d")
    assert main(["--data", data, "add-schemas", str(FIX / "sgml" / "ata-sgml-synth"), "--issue", "example-1",
                 "--standard", "ATA2200", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Found: an SGML DTD set" in out and "Installed ata2200/example-1/sgml: cmm" in out



def test_export_then_install_opensp_on_another_pc(tmp_path, monkeypatch, capsys):
    """PC without internet: export OpenSP from a working PC, install the zip on the other."""
    import os, shutil
    from asthra.validation.sgml import find_tools, probe
    tools = find_tools()
    if not tools or os.name == "nt" or not probe(tools)[0]:
        pytest.skip("needs a working OpenSP on Linux")
    z = tmp_path / "opensp-bundle.zip"
    assert main(["--data", str(tmp_path / "pc1"), "export-opensp", str(z)]) == 0
    import zipfile
    names = zipfile.ZipFile(z).namelist()
    assert "OpenSP/usr/bin/onsgmls" in names and "OpenSP/usr/bin/osx" in names and "OpenSP/README.txt" in names
    monkeypatch.setenv("ASTHRA_DATA", str(tmp_path / "pc2"))
    monkeypatch.delenv("ASTHRA_OPENSP", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))          # the other PC has no OpenSP of its own
    assert main(["install-opensp", str(z)]) == 0
    assert "OpenSP installed" in capsys.readouterr().out
    t = find_tools()
    assert t and str(tmp_path / "pc2") in t[0] and probe(t)[0]
