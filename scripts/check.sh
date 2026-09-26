#!/usr/bin/env bash
# Ordinary development gate: lint plus the rootless test suite (no sudo, no benchmarks).
# Usage: scripts/check.sh [extra pytest arguments]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="$root/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  echo "error: $python not found; create it with: uv venv --python /usr/bin/python3.12" >&2
  exit 1
fi
version="$("$python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [[ "$version" != "3.12" ]]; then
  echo "error: project interpreter is Python $version; Python 3.12 is required" >&2
  exit 1
fi

cd "$root"
echo "== ruff" >&2
"$python" -m ruff check .
echo "== pytest (not privileged and not performance)" >&2
"$python" -m pytest -m "not privileged and not performance" "$@"
