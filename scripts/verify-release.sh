#!/usr/bin/env bash
# Download a GitHub Release's Windows executable and verify name, version, and SHA-256.
#
# Exit codes: 0 verified; 1 mismatch or missing executable; 2 release has no SHA256SUMS.txt
# (releases published before v0.0.13 and never repaired) — the computed hash is still printed.
# Usage: scripts/verify-release.sh vX.Y.Z [owner/repo]
set -euo pipefail

tag="${1:?usage: $0 vX.Y.Z [owner/repo]}"
repo="${2:-blindicide/polmon}"
version="${tag#v}"
version="${version%%+*}"
exe="polmon-${version}-windows-x64.exe"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
gh release download "$tag" --repo "$repo" --dir "$workdir" --pattern '*.exe' \
  --pattern 'SHA256SUMS.txt' 2>/dev/null || true
if [[ ! -f "$workdir/$exe" ]]; then
  echo "FAIL: release $tag has no $exe" >&2
  ls -l "$workdir" >&2
  exit 1
fi
(cd "$workdir" && sha256sum "$exe")
if [[ ! -f "$workdir/SHA256SUMS.txt" ]]; then
  echo "UNVERIFIED: release $tag has no SHA256SUMS.txt; compare the hash above independently" >&2
  exit 2
fi
if (cd "$workdir" && sha256sum --check --strict SHA256SUMS.txt); then
  echo "VERIFIED: $tag $exe matches SHA256SUMS.txt" >&2
else
  echo "FAIL: $tag checksum mismatch" >&2
  exit 1
fi
