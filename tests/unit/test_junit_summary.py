"""Unit tests for the JUnit-to-Markdown report (no emulator needed)."""

import pytest

from tools.junit_summary import _split_target, main, parse, to_markdown

TARGETS = ["web-function", "function-url"]

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="6">
  <testcase
    classname="tests.integration.test_deployment" name="test_table_schema" time="0.12"/>
  <testcase
    classname="tests.integration.test_deployment" name="test_web_function_endpoint_serves_our_code" time="0.30">
    <skipped type="pytest.xfail" message="AWS Emulator does not run Web Function code yet"/>
  </testcase>
  <testcase
    classname="tests.e2e.test_items_contract" name="test_health[web-function]" time="0.01"/>
  <testcase
    classname="tests.e2e.test_items_contract" name="test_health[function-url]" time="0.20"/>
  <testcase
    classname="tests.e2e.test_items_contract" name="test_validation_errors[web-function-empty-name]" time="0.02"/>
  <testcase
    classname="tests.e2e.test_items_contract" name="test_validation_errors[function-url-empty-name]" time="0.21">
    <failure message="assert 500 == 400&#10;second line">Traceback | with pipe
AssertionError: assert 500 == 400</failure>
  </testcase>
</testsuite></testsuites>
"""


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "emulator.xml"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "name, expected",
    [
        ("test_x[web-function]", ("test_x", "web-function")),
        ("test_x[function-url-empty-name]", ("test_x[empty-name]", "function-url")),
        ("test_x[empty-name-web-function]", ("test_x[empty-name]", "web-function")),
        ("test_x[a-web-function-b]", ("test_x[a-b]", "web-function")),
        ("test_x[other]", ("test_x[other]", None)),
        ("test_x", ("test_x", None)),
    ],
)
def test_split_target(name, expected):
    assert _split_target(name, TARGETS) == expected


def test_parse_statuses(report):
    cases = parse([report], TARGETS)
    assert [c.status for c in cases] == ["passed", "xfail", "passed", "passed", "passed", "failed"]
    assert cases[0].module == "tests/integration/test_deployment.py"
    assert cases[5].message == "assert 500 == 400"


def test_markdown_matrix_and_list(report):
    md = to_markdown(parse([report], TARGETS), "Emulator tests", TARGETS)
    assert md.startswith("### ❌ Emulator tests: 4 passed, 1 failed, 1 expected failures")
    assert "| Test | web-function | function-url |" in md
    assert "| test_validation_errors[empty-name] | ✅ 0.02 s | ❌ 0.21 s |" in md
    assert "| ⚠️ | test_web_function_endpoint_serves_our_code | 0.30 s | expected failure: AWS Emulator" in md
    failed = "tests/e2e/test_items_contract.py::test_validation_errors[empty-name] on function-url"
    assert f"<details><summary>❌ {failed}" in md


def test_main_writes_summary_and_annotations(report, tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main([str(report), "--title", "Emulator tests", "--targets", ",".join(TARGETS)]) == 0
    assert "#### `tests/e2e/test_items_contract.py`" in summary.read_text(encoding="utf-8")
    assert "::error title=Test failed on function-url::" in capsys.readouterr().out


def test_missing_report_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main([str(tmp_path / "nope.xml"), "--title", "Emulator tests"]) == 0
    assert "no report found" in capsys.readouterr().out
