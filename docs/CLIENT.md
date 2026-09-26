# Desktop client guide

The polmon desktop client is the operator console for a polmon backend. It runs on Windows and
Linux (Qt 6 via PySide6), talks to the backend only over its HTTP API, and never performs
laboratory networking itself. Screenshots of every page, rendered from the running client:
[ui/SCREENSHOTS.md](ui/SCREENSHOTS.md).

## Install and start

| Platform | Get it from the release | Start |
|---|---|---|
| Windows, single file | `polmon-<version>-windows-x64.exe` | double-click; includes the owned backend (unpacks itself on every start) |
| Windows, portable | `polmon-<version>-windows-x64-portable.zip` | unzip; `polmon-client.exe` and `polmon-backend.exe` are side by side |
| Linux | `polmon-<version>-linux-x64.tar.gz` | extract, run `polmon-client`; `--install-desktop-entry` adds a menu entry |
| Any, from source | `pip install "polmon[gui]"` | `polmon-client` |

Verify downloads against `SHA256SUMS.txt` (`scripts/verify-release.sh vX.Y.Z`, or `Get-FileHash`
on Windows). Linux needs glibc 2.35+ and, for X11, `libxcb-cursor0` (see
[BUILD-LINUX.md](../BUILD-LINUX.md)). The client starts without a backend.

Command-line options: `--version`; `--self-test` (checks Qt, its plugins, the main window and the
API client without opening a window; exit status 0 when healthy); `--smoke-start SECONDS` (shows
the window on the native platform and reports start-up time and memory); `--url URL` (prefill the
backend URL and select the remote preset); `--backend-executable PATH` (override the local child);
`--local-backend-self-test`; `--theme system|light|dark`; `--install-desktop-entry` (Linux).

## Connect

Choose a connection type and press **Connect** (Ctrl+Return):

- **Local backend (L0 only)** is the default. The client starts the bundled executable on a free
  `127.0.0.1` port with an ephemeral token, waits for health without blocking the window, and
  stops/reaps it on disconnect or exit. The status bar keeps the fidelity label visible. *Backend
  log* opens the captured stdout/stderr. On Windows a kill-on-close Job Object also reaps the
  child if the client crashes.
- **Remote Linux backend** enables the URL/token fields. The URL drop-down remembers eight
  backends. This is required for L1 namespace and hybrid TAP topologies. Remote backends are best
  reached through an SSH tunnel (`ssh -N -L 8080:127.0.0.1:8080 operator@lab-host`, then
  `http://127.0.0.1:8080`); see [OPERATIONS.md](OPERATIONS.md). The token is held in memory only.

The local backend never silently lowers fidelity. Deploying a topology containing L1 or L2 shows
the same actionable refusal in the UI and API: “Local backend supports L0 synthetic nodes only;
L1/L2 requires a polmon backend on a Linux host with network namespace privileges.”

The LED and the status bar show the connection: *connected*, *unauthorized* (token missing or
wrong — the token field stays editable), or *lost* (the backend stopped answering; the client
retries every 5 s and disables actions until it is back). An older backend connects with an
"Older backend" warning naming the features it lacks.

## Pages

| Page | What you do there |
|---|---|
| Dashboard (Ctrl+1) | Backend identity and round-trip time; live counters (endpoints, namespaces, deployments/experiments, backend RSS, current CPU, memory headroom above the reserve, swap, data directory) with sparklines; the backend's admission limits. |
| Topologies (Ctrl+2) | Open YAML from the library folder or a file (Ctrl+O), edit with highlighting, validate on the backend (automatic while typing, or Ctrl+Shift+V). Errors list the field, message and line — double-click jumps to it. Inspect nodes, interfaces, MAC and IPv4 addresses, networks, and whether the topology fits the admission limits. *Load to backend*, *Deploy…*, save (Ctrl+S). |
| Deployment (Ctrl+3) | Deploy (Ctrl+D), destroy (Ctrl+Shift+D), reset everything (Ctrl+Shift+R). A refused deployment names each violated limit. Owned resources and backend details of the selected deployment, and the live counters. Cancelling a deployment rolls it back when the backend call returns. |
| Scenarios (Ctrl+4) | Open and validate a scenario against its topology (loaded, deployed, compatible). *Deploy required topology* when needed, then *Run experiment* (Ctrl+R): per-action status, progress with percent, step, elapsed time and ETA. *Cancel* (Esc) asks the backend to stop after the current action; a second Esc abandons waiting. |
| Telemetry (Ctrl+5) | The experiment's event stream, live while it runs; filter by category and text; payload of the selected event; capture summary (frames, bytes, dropped, truncated). *Export CSV…* saves the rows shown; *Save capture…* downloads the PCAP. |
| Reports (Ctrl+6) | Experiments on the backend (including those of earlier backend runs). Overall status, expected versus actual conditions, observations, errors, resource statistics, the Markdown report and the raw JSON; save as JSON or Markdown. |
| Benchmarks (Ctrl+7) | Run a bounded benchmark job on the backend host with explicit limits (checked against the backend's own limits; one job at a time, never during an experiment), follow its progress, cancel it, and inspect retained results. |

Long operations run in the background: the status bar shows what is running with percent, step,
elapsed time, ETA and a Cancel button, and the window stays responsive. When an experiment or a
benchmark finishes while you are on another page (or in another window) the status bar says so
and the task bar flashes. The *Activity* dock (Ctrl+Shift+L) logs every operation and its result.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+Return | Connect / disconnect |
| Ctrl+L | Focus the backend URL |
| F5 | Refresh backend state now |
| Ctrl+O / Ctrl+Shift+O | Open topology / scenario |
| Ctrl+S | Save the topology or scenario being edited |
| Ctrl+Shift+V | Validate the topology in the editor |
| Ctrl+D / Ctrl+Shift+D | Deploy / destroy the selected topology |
| Ctrl+Shift+R | Reset the environment |
| Ctrl+R | Run the experiment |
| Esc | Cancel the running operation (twice: abandon) |
| Ctrl+1 … Ctrl+7 | Switch page |
| Ctrl+Shift+T | Toggle light/dark theme |
| Ctrl+Shift+L | Show or hide the activity log |
| Ctrl+Q | Quit |

F1 shows the same list in the client. The theme follows the operating system unless chosen in
*View → Theme*.

## Troubleshooting

| Message | Meaning and action |
|---|---|
| Backend unreachable — connection refused | Nothing listens at that URL: start `polmon-backend`, check host, port and tunnel. |
| Backend did not respond | The request exceeded the timeout in the connection bar; the backend is busy or the network is slow. |
| API token required | The backend has a token: enter it (from `POLMON_API_TOKEN` or its token file). |
| Refused by admission control | The listed limits would be exceeded: destroy other deployments, shrink the workload, or raise the backend limits. |
| Rejected / Problems tab | The document is invalid: each problem names the field and line. |
| Unexpected response | The URL does not point at a polmon backend (for example a web server or proxy). |
| Backend lost (during an experiment) | The backend stopped answering mid-run; the outcome is unknown until it is reachable — check the Reports page afterwards. |
| Local backend — L0 only | The owned Windows-compatible backend runs synthetic endpoints only. Select Remote Linux backend for L1/hybrid work. |
| Local backend stopped | The child exited unexpectedly; open *Backend log*, run its `--self-test`, then reconnect. |
| Not supported by this backend / Older backend | The backend is older than the client; upgrade it to the same version. |

`polmon-client --self-test` diagnoses the installation itself; a missing Qt platform plugin is
reported with the directory that was searched. Settings (URL history, timeout, theme, window
layout, last folders — never the token) are stored with `QSettings` under `polmon/polmon-client`.
