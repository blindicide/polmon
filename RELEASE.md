# Releases

The experimental runtime candidate uses annotated SemVer tag `v0.7.0-rc.3`, canonical Python
version `0.7.0rc3`, and separate addon distribution `0.1.0rc3` pinned to that core.
`scripts/release_metadata.py` validates tag/source/project/lock/addon consistency and
extracts only the exact changelog section. Stable tags retain `vX.Y.Z`; previews use
`vX.Y.Z-alpha.N`, `-beta.N` or `-rc.N`. Debian/RPM metadata uses `~rcN` to sort before
stable; downloadable filenames use the canonical Python version.

Before tagging, run the complete rootless, applicable isolated privileged,
localization/format, shell syntax, wheel and version gates. The optional VM runtime is
implemented but experimental. Real guest/KVM acceptance is
NOT RUN here: `/dev/kvm`, `qemu-system-x86_64` and ISO creation tools are unavailable,
and unprivileged user/network namespace creation is denied. This limitation permits an
explicitly experimental prerelease; it does not permit a VM functionality or security
acceptance claim. Independent real guest boot, networking, clone isolation and failure
cleanup evidence is required before making those claims (see SECURITY.md). Never
present local gates or image/bundle verification as Windows or real guest acceptance.
Operator records, instructions,
CI task, private host state and preserved L0 results must remain unpublished.

Push the gated feature commit and annotated tag without merging main. `release.yml`
validates the candidate, calls both native build/verification workflows and creates
a GitHub **prerelease** with `--latest=false` for preview tags. It never generates
whole-history notes; notes come from the version-scoped changelog. Optional manual
repair notes are prepended explicitly. Assets are:

| Asset | Platform |
|---|---|
| `polmon-<version>-windows-x64.exe` | Windows client (one file) |
| `polmon-<version>-windows-x64-portable.zip` | Windows client, one folder: faster start (from v0.2.1) |
| `polmon-<version>-linux-x64.tar.gz` | Linux client bundle (see [BUILD-LINUX.md](BUILD-LINUX.md)) |
| `polmon-<version>-py3-none-any.whl` | Python package: backend, CLI tools, client (with `[gui]`) |
| `polmon-client_<version>_amd64.deb` | Debian desktop client with embedded L0 and SQLite |
| `polmon-client-<version>-1.x86_64.rpm` | RPM desktop client with embedded L0 and SQLite |
| `package-manifest.json`, `SHA256SUMS-packages.txt` | Package metadata, limits, and build checksums |
| `polmon_l1_vm-<addon-version>-py3-none-any.whl` | Optional experimental Linux QEMU/KVM runtime |
| `SHA256SUMS.txt` | SHA-256 of every file above |

Before publishing, the release job checks every file name against the tag version and each
platform artifact against the checksum its build job recorded after smoke-testing it. After
publishing, `verify-release` downloads the assets from the release itself on Windows and Linux,
checks `SHA256SUMS.txt`, runs each embedded client and its L0 self-test. Release notes say that
ordinary local topology execution is L0-only on both platforms. Namespace L1/hybrid
requires a configured Linux lab backend. Independent VM jobs are Linux-only and require
KVM, QEMU, ISO tools and an authorized isolated lab; bundling does not grant those capabilities.
Linux artifacts contain the addon and pinned read-only guest image; Windows artifacts do not.

Verify a download yourself:

```bash
scripts/verify-release.sh vX.Y.Z          # downloads the release and checks every asset
sha256sum --check --ignore-missing SHA256SUMS.txt
```

```powershell
Get-FileHash .\polmon-<version>-windows-x64.exe -Algorithm SHA256   # compare with SHA256SUMS.txt
```

Never tag incomplete work and never treat an unexecuted binary as validated.

## Repairing a tag whose release run failed

Tags are never moved, deleted, or force-pushed. When a tag's release run failed for a reason that
is already fixed on `main` (for example a test that cannot run on Windows at that tag), dispatch
the release workflow from `main` and pin the build to the existing tag:

```bash
gh workflow run release.yml --ref main \
  -f tag=vX.Y.Z \
  -f pytest-deselect='tests/...::test_name' \
  -f notes='Repair release: ... (state what was deselected and why, with the passing run ID)'
```

The binaries are built, tested, and smoke-tested from the tag's own source; only the workflow
definition comes from `main`. Every deselected test must be named in the release notes and in the
milestone report together with the evidence that it passed elsewhere; a failure that cannot be
explained that way is reported as a blocked release instead.

Tags before v0.2.0 contain the Tkinter client and no Linux packaging, which the current workflows
cannot build. Repair such a tag with the workflow definition of the tag itself, which still has the
same `tag` input: `gh workflow run release.yml --ref vX.Y.Z -f tag=vX.Y.Z ...`.
