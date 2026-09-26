# Releases

After a milestone gate passes, update the central version (`src/polmon/version.py`,
`pyproject.toml`) and the changelog, commit, and create an annotated SemVer tag on the evidence
commit. Push the commit and the tag. `release.yml` then builds and verifies both platforms and
publishes one GitHub Release with:

| Asset | Platform |
|---|---|
| `polmon-<version>-windows-x64.exe` | Windows client (one file) |
| `polmon-backend-<version>-windows-x64.exe` | Standalone Qt-free Windows backend (L0 only) |
| `polmon-<version>-windows-x64-portable.zip` | Windows client, one folder: faster start (from v0.2.1) |
| `polmon-<version>-linux-x64.tar.gz` | Linux client bundle (see [BUILD-LINUX.md](BUILD-LINUX.md)) |
| `polmon-backend-<version>-linux-x64.tar.gz` | Self-contained Linux backend; no Python install |
| `polmon-<version>-py3-none-any.whl` | Python package: backend, CLI tools, client (with `[gui]`) |
| `polmon-backend.service` | Example systemd user unit for the backend |
| `polmon-backend-bundled.service` | User unit for the extracted backend bundle |
| `SHA256SUMS.txt` | SHA-256 of every file above |

Before publishing, the release job checks every file name against the tag version and each
platform artifact against the checksum its build job recorded after smoke-testing it. After
publishing, `verify-release` downloads the assets from the release itself on Windows and Linux,
checks `SHA256SUMS.txt`, runs both client and backend self-tests, and repeats the Windows owned-
backend workflow. Release notes always say that Windows local execution is L0-only and that Linux
L1/hybrid execution depends on host namespace privileges.

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
