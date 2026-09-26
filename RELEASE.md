# Releases

After a milestone gate passes, update the central version and changelog, commit, and create an
annotated SemVer tag. Push the commit and tag. The release workflow builds and smoke-tests the
executable on Windows and attaches it to the corresponding GitHub Release.

Download the executable and verify its SHA-256 value:

```powershell
Get-FileHash .\polmon-0.0.1-windows-x64.exe -Algorithm SHA256
```

Compare this with a hash obtained independently from the downloaded workflow or release artifact.
Never tag incomplete work and never treat an unexecuted binary as validated.

Each release also carries `SHA256SUMS.txt`, computed on the release job from the artifact the
Windows job verified; compare it with your local `Get-FileHash` result.

## Repairing a tag whose release run failed

Tags are never moved, deleted, or force-pushed. When a tag's tag-triggered release run failed for a
reason that is already fixed on `main` (for example a test that cannot run on Windows at that tag),
dispatch the release workflow from `main` and pin the build to the existing tag:

```bash
gh workflow run release.yml --ref main \
  -f tag=v0.0.7 \
  -f pytest-deselect='tests/unit/test_namespace_backend.py::test_namespace_command_plan_is_isolated_and_cleanup_is_idempotent' \
  -f notes='Repair release: ... (state what was deselected and why, with the Linux CI run ID)'
```

The executable is built, tested, and smoke-tested from the tag's own source; only the workflow
definition comes from `main`. The release job refuses an executable whose file name does not match
the tag version. Every deselected test must be named in the release notes and in the milestone
report together with the evidence that it passed elsewhere; a failure that cannot be explained that
way is reported as a blocked release instead.
