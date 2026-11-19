"""Turns pytest JUnit XML reports into a Markdown report for the GitHub job summary.

Usage: python -m tools.junit_summary reports/emulator.xml --title "Emulator tests"

Writes one table per test file, one row per test, with the reason next to each expected failure
or skip. Appends to $GITHUB_STEP_SUMMARY when set, always prints the report, and emits an ::error
annotation for each failed test. Exit code is always 0: pytest has already decided whether the
step fails.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ICONS = {"passed": "✅", "failed": "❌", "error": "❌", "xfail": "⚠️", "skipped": "⏭️"}
LABELS = {"passed": "passed", "failed": "failed", "error": "errors", "xfail": "expected failures", "skipped": "skipped"}
MAX_TRACE_LINES = 40


@dataclass
class Case:
    module: str  # e.g. tests/e2e/test_items_contract.py
    test: str  # e.g. test_validation_errors[empty-name]
    status: str  # one of ICONS
    seconds: float
    message: str  # first line of the failure/skip reason, "" when passed
    trace: str  # full failure text, "" when not failed


def _module_path(classname: str) -> str:
    # pytest writes "tests.e2e.test_items_contract" (or "...module.ClassName" for test classes)
    parts = classname.split(".")
    while parts and not parts[-1].startswith("test_"):
        parts.pop()
    return "/".join(parts) + ".py" if parts else classname


def parse(paths: list[pathlib.Path]) -> list[Case]:
    cases = []
    for path in paths:
        for tc in ET.parse(path).getroot().iter("testcase"):
            status, message, trace = "passed", "", ""
            for child in tc:
                if child.tag in ("failure", "error"):
                    status, trace = ("failed" if child.tag == "failure" else "error"), (child.text or "")
                elif child.tag == "skipped":
                    status = "xfail" if child.get("type") == "pytest.xfail" else "skipped"
                else:
                    continue
                message = next(iter((child.get("message") or "").strip().splitlines()), "")
                break
            module, seconds = _module_path(tc.get("classname", "")), float(tc.get("time") or 0)
            cases.append(Case(module, tc.get("name", "?"), status, seconds, message, trace))
    return cases


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _fmt_time(seconds: float) -> str:
    return f"{seconds:.2f} s" if seconds < 10 else f"{seconds:.0f} s"


def _detail(c: Case) -> str:
    if c.status == "xfail":
        return f"expected failure: {c.message}" if c.message else "expected failure"
    return c.message if c.status != "passed" else ""


def to_markdown(cases: list[Case], title: str) -> str:
    counts = {s: sum(c.status == s for c in cases) for s in ICONS}
    totals = ", ".join(f"{n} {LABELS[s]}" for s, n in counts.items() if n) or "no tests"
    overall = "❌" if counts["failed"] or counts["error"] else "✅"
    lines = [f"### {overall} {title}: {totals} ({_fmt_time(sum(c.seconds for c in cases))})", ""]

    modules: dict[str, list[Case]] = {}
    for c in cases:
        modules.setdefault(c.module, []).append(c)

    for module, mcases in modules.items():
        lines += [f"#### `{module}`", "", "| | Test | Time | Detail |", "|---|---|---|---|"]
        for c in mcases:
            lines.append(f"| {ICONS[c.status]} | {_cell(c.test)} | {_fmt_time(c.seconds)} | {_cell(_detail(c))} |")
        lines.append("")

    for c in cases:
        if c.status in ("failed", "error"):
            trace = "\n".join(c.trace.strip().splitlines()[-MAX_TRACE_LINES:])
            lines += [
                f"<details><summary>{ICONS[c.status]} {c.module}::{c.test}: {c.message}</summary>",
                "",
                "```",
                trace,
                "```",
                "</details>",
                "",
            ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reports", nargs="+", type=pathlib.Path, help="JUnit XML files")
    parser.add_argument("--title", default="Tests")
    args = parser.parse_args(argv)

    present = [p for p in args.reports if p.is_file()]
    if present:
        cases = parse(present)
        report = to_markdown(cases, args.title)
    else:
        cases = []
        report = f"### ❌ {args.title}: no report found ({', '.join(map(str, args.reports))}), the tests did not run\n"

    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    for c in cases:
        if c.status in ("failed", "error"):
            print(f"::error title=Test failed::{c.module}::{c.test}: {c.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
