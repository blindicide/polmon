#!/usr/bin/env bash
# Download a GitHub Release and verify its assets' names, versions and SHA-256 values.
#
# Asset expectations follow the release era. The next feature release replaces separate backend
# bundles with embedded L0 clients and adds Debian and RPM packages.
# Exit codes: 0 verified; 1 mismatch or missing asset; 2 release has no SHA256SUMS.txt (releases
# published before v0.0.13 and never repaired) — the computed hashes are still printed.
# Usage: scripts/verify-release.sh vX.Y.Z [owner/repo]
set -euo pipefail

tag="${1:?usage: $0 vX.Y.Z [owner/repo]}"
repo="${2:-blindicide/polmon}"
version="${tag#v}"
version="${version%%+*}"

expected=("polmon-${version}-windows-x64.exe")
IFS=. read -r major minor _ <<< "$version"
IFS=. read -r _ _ patch <<< "$version"
if (( major > 0 || minor >= 2 )); then
  expected+=("polmon-${version}-linux-x64.tar.gz" "polmon-${version}-py3-none-any.whl"
             "polmon-backend.service")
fi
if (( major > 0 || minor > 2 || (minor == 2 && patch >= 1) )); then
  expected+=("polmon-${version}-windows-x64-portable.zip")
fi
if (( major > 0 || minor >= 3 )); then
  expected+=("polmon-backend-${version}-windows-x64.exe"
             "polmon-backend-${version}-linux-x64.tar.gz"
             "polmon-backend-bundled.service")
fi
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
gh release download "$tag" --repo "$repo" --dir "$workdir" >/dev/null
if [[ -f "$workdir/package-manifest.json" ]]; then
  expected=("polmon-${version}-windows-x64.exe"
            "polmon-${version}-windows-x64-portable.zip"
            "polmon-${version}-linux-x64.tar.gz"
            "polmon-${version}-py3-none-any.whl"
            "polmon-client_${version}_amd64.deb"
            "polmon-client-${version}-1.x86_64.rpm"
            "package-manifest.json" "SHA256SUMS-packages.txt")
fi
status=0
for asset in "${expected[@]}"; do
  if [[ ! -f "$workdir/$asset" ]]; then
    echo "FAIL: release $tag has no $asset" >&2
    status=1
  fi
done
(cd "$workdir" && sha256sum "${expected[@]}" 2>/dev/null) || true
if [[ ! -f "$workdir/SHA256SUMS.txt" ]]; then
  echo "UNVERIFIED: release $tag has no SHA256SUMS.txt; compare the hashes above independently" >&2
  exit 2
fi
if (cd "$workdir" && sha256sum --check --strict SHA256SUMS.txt); then
  (( status == 0 )) && echo "VERIFIED: $tag assets match SHA256SUMS.txt" >&2
else
  echo "FAIL: $tag checksum mismatch" >&2
  status=1
fi
exit "$status"
