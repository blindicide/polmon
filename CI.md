# Continuous integration

`ci.yml` lints and tests every push to `main` and every pull request with read-only permissions.
`build-windows.yml` uses a GitHub-hosted Windows runner and uploads the verified executable. In a
workflow run, open **Artifacts** and download `polmon-windows-x64`. Test XML is uploaded even after
a failing Linux test so failures remain inspectable. Pull-request jobs receive no repository
secrets.

