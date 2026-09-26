# Operations runbook

For operators running polmon on a dedicated Linux laboratory host and controlling it from the
Windows client. Read [SECURITY.md](../SECURITY.md) first.

## 1. Prepare the laboratory host

- Linux with `iproute2`, `setpriv` (util-linux), `ping` (iputils, with `cap_net_raw`), `/dev/net/tun`,
  and `/usr/bin/python3.12`; `uv` for the environment; optionally `tcpdump` to inspect captures.
- An account with passwordless `sudo` for laboratory networking. `sudo ip` is root-equivalent
  (SECURITY.md), so use a host and account dedicated to the laboratory.
- Install and check:

  ```bash
  git clone <repository> ~/polmon && cd ~/polmon
  uv venv --python /usr/bin/python3.12 && uv pip install -e .
  .venv/bin/polmon-diagnostics --lab      # read-only lab readiness; exit 1 if not ready
  scripts/check.sh                        # rootless gate
  scripts/privileged-tests.sh             # lab tests + proof the host network is untouched
  ```

## 2. Run the backend

Create an API token that only the service account can read:

```bash
install -d -m 700 ~/.config/polmon
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.config/polmon/api-token
chmod 600 ~/.config/polmon/api-token
mkdir -p ~/polmon-data
```

Run it in the foreground (`--host 127.0.0.1` is the default), or install the example user unit
[`packaging/linux/polmon-backend.service`](../packaging/linux/polmon-backend.service):

```bash
.venv/bin/polmon-backend --api-token-file ~/.config/polmon/api-token      # foreground
cp packaging/linux/polmon-backend.service ~/.config/systemd/user/          # adjust paths first
systemctl --user daemon-reload && systemctl --user enable --now polmon-backend
```

The backend refuses to listen on a non-loopback address without a token. Resource limits are
backend flags (`--max-endpoints`, `--max-namespaces`, `--memory-reserve-mb`, ...; see
[RESOURCE-MANAGEMENT.md](RESOURCE-MANAGEMENT.md)). Data (telemetry SQLite, captures, reports)
is written under `var/` in the working directory.

## 3. Connect the desktop client

Keep the backend on loopback and tunnel from the operator's machine (OpenSSH is built into
Windows and every Linux desktop):

```powershell
ssh -N -L 8080:127.0.0.1:8080 operator@lab-host
```

Start `polmon-<version>-windows-x64.exe` or, for a faster start, `polmon-client.exe` from the
unzipped `polmon-<version>-windows-x64-portable.zip` (Windows), or `polmon-client` from the extracted
`polmon-<version>-linux-x64.tar.gz` (Linux), keep the backend URL `http://127.0.0.1:8080`, paste
the token into *Token*, and press *Connect* (Ctrl+Return). The token stays in memory only. Verify a downloaded executable first with
`scripts/verify-release.sh vX.Y.Z` (or `Get-FileHash` against the release's `SHA256SUMS.txt`).

## 4. Routine checks

| When | Command | Expect |
|---|---|---|
| After install or upgrade | `.venv/bin/polmon-demo` | `demo: passed` (50 L0 + 2 L1, experiment, report, reset) |
| Before a session | `curl -s http://127.0.0.1:8080/v1/health` | `{"status":"ok", "version": ...}` |
| Capacity questions | `scripts/run-benchmarks.sh` | new files in `benchmarks/results/` |
| After any crash | `scripts/lab-cleanup.sh` | `no platform lab resources found` |

## 5. Recovery

- **Stopping the backend** (`systemctl --user stop`, Ctrl-C) tears down every deployment and logs
  `shutdown_cleanup`; `shutdown_cleanup_failed` lists what could not be removed.
- **After SIGKILL, OOM, or power loss** nothing can clean up in-process. Run
  `scripts/lab-cleanup.sh` to list leftover `polmon*` namespaces, bridges, TAPs, `veth*` pairs, and
  processes inside those namespaces, then `scripts/lab-cleanup.sh --apply`.
- **Deployment refused with "already exist"**: a previous run left objects with the same generated
  names, or another backend deployed the same topology. Stop the other deployment or run the cleanup
  script; polmon never adopts objects it did not create.
- **HTTP 429 `resource_limit`**: the request exceeds configured limits or would leave less than the
  memory reserve; reduce the topology or raise the limit deliberately.
  Storage violations (`data_directory`, `disk_free`) mean `var/` or the disk is full: archive
  old captures and reports under `var/`, then retry.

## 6. Upgrades

Stop the backend (this resets the laboratory), `git pull` or check out a release tag, reinstall with
`uv pip install -e .`, run `scripts/check.sh`, `scripts/privileged-tests.sh`, and
`.venv/bin/polmon-demo`, then start the backend again.
