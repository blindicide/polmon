#!/usr/bin/env python3
"""Fail when user-visible text in the desktop client bypasses the translation catalogs.

Usage: python scripts/i18n-lint.py [FILE ...]   (default: every non-exempt client module)
Suppress a deliberate case with an ``# i18n: allow`` comment on (or just above) the line.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from i18n_audit import EXEMPT_MODULES, client_modules, lint  # noqa: E402


def main(argv: list[str]) -> int:
    paths = [Path(arg).resolve() for arg in argv] or client_modules()
    findings = lint(paths)
    for finding in findings:
        print(finding)
    print(
        f"i18n-lint: {len(paths)} modules checked, {len(EXEMPT_MODULES)} exempt, "
        f"{len(findings)} hard-coded user-facing literal(s)"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
