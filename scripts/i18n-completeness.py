#!/usr/bin/env python3
"""Translation-completeness gate for the desktop client catalogs (CI runs it on both platforms).

Checks: identical key sets, identical placeholders, CLDR plural forms (ru: one/few/many/other,
en: one/other), no empty values, no untranslated English words in Russian outside the kept
terms, no Cyrillic in English, every key the code uses exists (including dynamically built
families and every backend message code), and no unused keys.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from i18n_audit import completeness, summary  # noqa: E402


def main() -> int:
    errors = completeness()
    for error in errors:
        print(error)
    facts = ", ".join(f"{value} {name}" for name, value in summary().items())
    verdict = "FAIL" if errors else "PASS"
    print(f"i18n-completeness: {verdict}: {facts}; {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
