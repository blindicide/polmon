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

