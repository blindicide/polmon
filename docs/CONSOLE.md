# SSH and VNC console (v0.5.0)

The Console page opens a real OpenSSH session inside a deployed L1 Linux network namespace. L0
nodes have no application stack and are refused with `console.l1_required`; L2 remains outside the
implemented fidelity boundary. The Windows local backend is L0-only, so Windows operators connect
the client to a remote Linux backend.

## Prerequisites and account policy

Run `scripts/lab-prerequisites.sh` and `polmon-diagnostics --lab`. The host needs `ip`, `sudo`,
`setpriv`, `ping`, `ssh`, `sshd`, and `ssh-keygen`, plus the existing restricted passwordless
namespace policy. This phase deliberately uses the account that runs the backend when it is an
existing unprivileged laboratory operator. `--create-lab-account` exits with reason code
`console.account_policy_existing_user`; polmon never silently creates or changes a host account.

Add an `ssh` TCP service to each console-capable L1 node (port defaults to 22):

```yaml
services:
  - {id: shell, protocol: tcp, implementation: ssh}
```

Each deployment generates an Ed25519 server key and client key. Private material, the daemon
configuration and authorised-keys file live below
`<data-dir>/runs/deployments/<topology>/<deployment-id>/console`
with directory mode `0700` and file mode `0600`; none is packaged or checked in. Password and
keyboard-interactive authentication, root login and PAM are disabled. `sshd` runs inside the node
namespace and changes to the invoking unprivileged account after key authentication.

## API and bounds

`GET .../console/readiness` reports exact prerequisite and node-class codes. `POST .../console/exec`
accepts an argv list from the closed basic-command catalogue, a 0.1–60 second timeout, and returns
the machine name, ID, UUID, exit status, stdout, stderr, duration, timeout and truncation state.
Output is drained while at most 256 KiB is retained. Metacharacters and commands outside the
catalogue are refused before SSH is invoked.

Interactive sessions use `POST .../console/sessions`, cursor polling through `GET .../stream`,
bounded input through `POST .../input`, and `DELETE` for teardown. OpenSSH allocates the remote PTY
(`ssh -tt`). The backend retains a 512 KiB live ring and writes the complete per-session transcript
under `<data-dir>/runs/console/<topology>/<node>/`; the transcript endpoint remains available after
session close. Sessions idle for 15 minutes are terminated. The client strips ANSI control
sequences for display, caps the visible document, performs HTTP work off the GUI thread, supports
history with Up/Down, and sends Ctrl+C as an interrupt byte.

## Threat model and audit

The interactive shell is intentionally free-form but exists only inside an isolated lab network
namespace, as a non-root user, without a configured route to the host or external network. It is
not a host shell. Authentication tokens remain mandatory whenever the API binds off loopback.
Commands and transcripts are retained; structured per-command audit records are described in
[LOGS.md](LOGS.md). Destroy/reset closes sessions before removing namespaces. The privileged gate
proves the default route, host interfaces and firewall state remain unchanged and that no lab
namespace or interface survives.

For graphical L1 services, the same Console page can request the VNC relay when the node declares
the graphical prerequisites. The backend returns an authenticated WebSocket session; the client
speaks RFB 3.8 and supports the Raw and Hextile encodings used by the namespace `x11vnc` process.
The headless server gate validates the RFB handshake, framebuffer bytes and pointer relay; visual
desktop acceptance remains a client-side operator check.
