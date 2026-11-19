"""Turns pytest JUnit XML reports into a Markdown report for the GitHub job summary.

Usage: python -m tools.junit_summary reports/emulator.xml --title "Emulator tests" --targets web-function,function-url

Tests whose id contains one of the --targets are shown as a matrix (one column per target);
all the others are listed one per row. Appends to $GITHUB_STEP_SUMMARY when set, always prints
the report, and emits an ::error annotation for each failed test. Exit code is always 0:
pytest has already decided whether the step fails.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ICONS = {"passed": "✅", "failed": "❌", "error": "❌", "xfail": "⚠️", "skipped": "⏭️"}
LABELS = {"passed": "passed", "failed": "failed", "error": "errors", "xfail": "expected failures", "skipped": "skipped"}
MAX_TRACE_LINES = 40


@dataclass
class Case:
    module: str  # e.g. tests/e2e/test_items_contract.py
    test: str  # function name plus remaining parameter id, e.g. test_validation_errors[empty-name]
    target: str | None  # e.g. web-function, or None when the test has no target
    status: str  # one of ICONS
    seconds: float
    message: str  # first line of the failure/skip reason, "" when passed
    trace: str  # full failure text, "" when not failed


def _split_target(name: str, targets: list[str]) -> tuple[str, str | None]:
    """'test_x[web-function-empty-name]' -> ('test_x[empty-name]', 'web-function')."""
    m = re.fullmatch(r"(?P<func>[^\[]+)\[(?P<ids>.*)\]", name)
    if not m:
        return name, None
    ids = m["ids"]
    for t in sorted(targets, key=len, reverse=True):
        for pattern in (rf"^{re.escape(t)}$", rf"^{re.escape(t)}-", rf"-{re.escape(t)}$", rf"-{re.escape(t)}(?=-)"):
            rest, n = re.subn(pattern, "", ids, count=1)
            if n:
                return (f"{m['func']}[{rest}]" if rest else m["func"]), t
    return name, None


def _module_path(classname: str) -> str:
    # pytest writes "tests.e2e.test_items_contract" (or "...module.ClassName" for test classes)
    parts = classname.split(".")
    while parts and not parts[-1].startswith("test_"):
        parts.pop()
    return "/".join(parts) + ".py" if parts else classname


def parse(paths: list[pathlib.Path], targets: list[str]) -> list[Case]:
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
            test, target = _split_target(tc.get("name", "?"), targets)
            module, seconds = _module_path(tc.get("classname", "")), float(tc.get("time") or 0)
            cases.append(Case(module, test, target, status, seconds, message, trace))
    return cases


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _fmt_time(seconds: float) -> str:
    return f"{seconds:.2f} s" if seconds < 10 else f"{seconds:.0f} s"


def _detail(c: Case) -> str:
    if c.status == "xfail":
        return f"expected failure: {c.message}" if c.message else "expected failure"
    return c.message if c.status != "passed" else ""


def to_markdown(cases: list[Case], title: str, targets: list[str]) -> str:
    counts = {s: sum(c.status == s for c in cases) for s in ICONS}
    totals = ", ".join(f"{n} {LABELS[s]}" for s, n in counts.items() if n) or "no tests"
    overall = "❌" if counts["failed"] or counts["error"] else "✅"
    lines = [f"### {overall} {title}: {totals} ({_fmt_time(sum(c.seconds for c in cases))})", ""]

    modules: dict[str, list[Case]] = {}
    for c in cases:
        modules.setdefault(c.module, []).append(c)

    for module, mcases in modules.items():
        lines += [f"#### `{module}`", ""]
        if any(c.target for c in mcases):
            cols = [t for t in targets if any(c.target == t for c in mcases)]
            lines += ["| Test | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
            rows: dict[str, dict[str, Case]] = {}
            for c in mcases:
                rows.setdefault(c.test, {})[c.target or ""] = c
            for test, by_target in rows.items():
                cells = []
                for t in cols:
                    c = by_target.get(t)
                    cells.append(f"{ICONS[c.status]} {_fmt_time(c.seconds)}" if c else "")
                lines.append(f"| {_cell(test)} | " + " | ".join(cells) + " |")
        else:
            lines += ["| | Test | Time | Detail |", "|---|---|---|---|"]
            for c in mcases:
                lines.append(f"| {ICONS[c.status]} | {_cell(c.test)} | {_fmt_time(c.seconds)} | {_cell(_detail(c))} |")
        lines.append("")

    notes = [c for c in cases if c.status in ("xfail", "skipped") and c.target]
    if notes:
        lines += ["Expected failures and skips:", ""]
        lines += [f"- {ICONS[c.status]} `{c.test}` on {c.target}: {_cell(_detail(c))}" for c in notes]
        lines.append("")

    for c in cases:
        if c.status in ("failed", "error"):
            where = f" on {c.target}" if c.target else ""
            trace = "\n".join(c.trace.strip().splitlines()[-MAX_TRACE_LINES:])
            lines += [
                f"<details><summary>{ICONS[c.status]} {c.module}::{c.test}{where}: {c.message}</summary>",
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
    parser.add_argument("--targets", default="", help="comma-separated parameter ids shown as matrix columns")
    args = parser.parse_args(argv)
    targets = [t for t in args.targets.split(",") if t]

    present = [p for p in args.reports if p.is_file()]
    if present:
        cases = parse(present, targets)
        report = to_markdown(cases, args.title, targets)
    else:
        cases = []
        report = f"### ❌ {args.title}: no report found ({', '.join(map(str, args.reports))}), the tests did not run\n"

    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    for c in cases:
        if c.status in ("failed", "error"):
            where = f" on {c.target}" if c.target else ""
            print(f"::error title=Test failed{where}::{c.module}::{c.test}: {c.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
