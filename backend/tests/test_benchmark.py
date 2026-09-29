"""The validation benchmark: it must score the synthetic suite perfectly, and it must
actually catch misses and false positives (a benchmark that always passes proves nothing)."""
import json
import shutil

from asthra.benchmark.runner import SUITES, run_corpus, run_suite, summary
from asthra.cli import main
from tests.conftest import DOCS


def test_synthetic_suite_scores_perfectly():
    res = run_suite(SUITES / "synthetic")
    s = summary(res)
    assert s["cases_run"] == 11 and s["cases_skipped"] == 0
    assert s["detection_rate"] == 1.0 and s["false_positives"] == 0
    assert s["exact_line_rate"] == 1.0 and s["actionable_rate"] == 1.0


def test_benchmark_detects_a_miss(tmp_path):
    suite = tmp_path / "s"
    shutil.copytree(SUITES / "synthetic", suite)
    spec = json.loads((suite / "00-clean.expect.json").read_text())
    spec["expect"] = [{"category": "duplicate-id", "value": "nope"}]      # claims a defect the file does not have
    (suite / "00-clean.expect.json").write_text(json.dumps(spec))
    s = summary(run_suite(suite))
    assert s["missed"] == 1


def test_benchmark_counts_false_positives(tmp_path):
    suite = tmp_path / "s"
    shutil.copytree(SUITES / "synthetic", suite)
    spec = json.loads((suite / "04-duplicate-id.expect.json").read_text())
    spec["expect"] = []                                                  # the real defect is now unexpected
    (suite / "04-duplicate-id.expect.json").write_text(json.dumps(spec))
    assert summary(run_suite(suite))["false_positives"] == 1


def test_corpus_mode(loaded, tmp_path):
    good = tmp_path / "good"; good.mkdir()
    shutil.copy(DOCS / "s1000d_proced_valid.xml", good)
    shutil.copy(DOCS / "s1000d_descript_valid.xml", good)
    shutil.copy(DOCS / "unknown_root.xml", good)                        # no schema for it: skipped, not a failure
    res = run_corpus(loaded.registry, good)
    s = summary(res)
    assert s["cases_run"] == 2 and s["cases_skipped"] == 1 and s["false_positives"] == 0
    shutil.copy(DOCS / "s1000d_proced_invalid.xml", good)
    assert summary(run_corpus(loaded.registry, good))["false_positives"] > 0


def test_cli_benchmark(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert main(["--data", str(tmp_path / "d"), "benchmark", "synthetic", "--json", str(out)]) == 0
    assert "overall (F1)                10.0 / 10" in capsys.readouterr().out
    assert json.loads(out.read_text())["summary"]["detected"] == 12
