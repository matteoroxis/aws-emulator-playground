"""Unit tests for the JUnit-to-Markdown report (no emulator needed)."""

import pytest

from tools.junit_summary import main, parse, to_markdown

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.integration.test_deployment" name="test_table_schema" time="0.12"/>
  <testcase classname="tests.integration.test_deployment" name="test_web_function_endpoint_serves_our_code" time="0.30">
    <skipped type="pytest.xfail" message="AWS Emulator does not run Web Function code yet"/>
  </testcase>
  <testcase classname="tests.e2e.test_items_contract" name="test_health_reports_implementation" time="0.20"/>
  <testcase classname="tests.e2e.test_items_contract" name="test_validation_errors[empty-name]" time="0.21">
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


def test_parse_statuses(report):
    cases = parse([report])
    assert [c.status for c in cases] == ["passed", "xfail", "passed", "failed"]
    assert cases[0].module == "tests/integration/test_deployment.py"
    assert cases[3].message == "assert 500 == 400"


def test_markdown_tables(report):
    md = to_markdown(parse([report]), "Emulator tests")
    assert md.startswith("### ❌ Emulator tests: 2 passed, 1 failed, 1 expected failures")
    assert "#### `tests/e2e/test_items_contract.py`" in md
    assert "| ❌ | test_validation_errors[empty-name] | 0.21 s | assert 500 == 400 |" in md
    assert "| ⚠️ | test_web_function_endpoint_serves_our_code | 0.30 s | expected failure: AWS Emulator" in md
    assert "<details><summary>❌ tests/e2e/test_items_contract.py::test_validation_errors[empty-name]" in md
    assert "Traceback | with pipe" in md  # traces stay verbatim inside the code block


def test_main_writes_summary_and_annotations(report, tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main([str(report), "--title", "Emulator tests"]) == 0
    assert "#### `tests/integration/test_deployment.py`" in summary.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "::error title=Test failed::tests/e2e/test_items_contract.py::test_validation_errors" in out


def test_missing_report_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert main([str(tmp_path / "nope.xml"), "--title", "Emulator tests"]) == 0
    assert "no report found" in capsys.readouterr().out
