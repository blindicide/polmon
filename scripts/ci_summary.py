#!/usr/bin/env python3
"""Render JUnit XML and coverage XML files as a Markdown table for $GITHUB_STEP_SUMMARY.

Usage: python scripts/ci_summary.py TITLE [--coverage coverage.xml] JUNIT.xml [JUNIT.xml ...]
Missing files are listed as "not produced" (a failed earlier step), never silently skipped.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path


def junit_counts(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.attrib.get(key, 0))
    return totals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("junit", nargs="*", type=Path)
    args = parser.parse_args()
    lines = [f"## {args.title}", "", "| Suite | Tests | Failures | Errors | Skipped |",
             "|---|---:|---:|---:|---:|"]
    failed = False
    for path in args.junit:
        if not path.is_file():
            lines.append(f"| `{path.name}` | not produced | | | |")
            failed = True
            continue
        counts = junit_counts(path)
        failed |= bool(counts["failures"] or counts["errors"])
        lines.append(
            f"| `{path.name}` | {counts['tests']} | {counts['failures']} | {counts['errors']} "
            f"| {counts['skipped']} |"
        )
    if args.coverage is not None:
        if args.coverage.is_file():
            rate = float(ElementTree.parse(args.coverage).getroot().attrib.get("line-rate", 0))
            lines += ["", f"Line coverage: **{rate * 100:.1f} %** (`{args.coverage.name}`)"]
        else:
            lines += ["", f"Coverage: `{args.coverage.name}` not produced"]
    print("\n".join(lines) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
