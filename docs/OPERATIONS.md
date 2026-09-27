# Operations runbook

For local L0 use on Windows and for operators running polmon on a dedicated Linux laboratory host.
Read [SECURITY.md](../SECURITY.md) first.

## 0. Windows local backend (L0 only)

Download either Windows client artifact, select **Local backend (L0 only)** and press *Connect*.
The client owns the bundled backend, its loopback port, ephemeral token and log; disconnecting or
exiting stops it. No Python, service installation, administrator access or network-namespace tool
is needed. This path supports L0 topologies, scenarios, telemetry, reports and L0 benchmarks.
L1/L2 requests are refused with the Linux-host requirement. Windows executables are currently
unsigned, so SmartScreen can warn on first launch; verify `SHA256SUMS.txt` and do not bypass a hash
mismatch.

## 1. Prepare the laboratory host

- Linux with `iproute2`, `setpriv` (util-linux), `ping` (iputils, with `cap_net_raw`) and, for
  hybrid operation, `/dev/net/tun`; optionally `tcpdump` to inspect captures. The self-contained
  bundle needs no Python, pip, uv or virtual environment.
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

For the release bundle, extract `polmon-backend-<version>-linux-x64.tar.gz` and run
`./polmon-backend-<version>-linux-x64/polmon-backend --lab-readiness`. Start that executable in
place of `.venv/bin/polmon-backend` below. The accompanying
`polmon-backend-bundled.service` targets a bundle installed at `~/polmon-backend/`; the original
unit remains for source/venv installations.

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
.venv/bin/polmon-backend --token-file ~/.config/polmon/api-token          # foreground
cp packaging/linux/polmon-backend.service ~/.config/systemd/user/          # adjust paths first
systemctl --user daemon-reload && systemctl --user enable --now polmon-backend
```

The backend refuses to listen on a non-loopback address without a token. Resource limits are
backend flags (`--max-endpoints`, `--max-namespaces`, `--memory-reserve-mb`, ...; see
[RESOURCE-MANAGEMENT.md](RESOURCE-MANAGEMENT.md)). Data (telemetry SQLite, captures, reports)
is written under `var/` in the working directory, or wherever `--data-dir PATH` points; a
directory that cannot be created or written is reported as
`polmon-backend: cannot use data directory …` instead of a traceback. The standalone Windows
`polmon-backend.exe` follows the same rule, so start it with `--data-dir` (for example
`--data-dir %LOCALAPPDATA%\polmon\backend-data`) when its own folder is not writable.

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
