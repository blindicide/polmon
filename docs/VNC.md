# VNC console

VNC is available only for deployed `l1` nodes on a Linux backend. The stack is `Xvfb` for a
private display, `xclock` as the documented X client, and `x11vnc` bound to the node namespace's
own loopback (`127.0.0.1:5900+<last octet>`, IPv6 disabled). The client uses the authenticated
backend relay and never opens a direct unauthenticated lab socket.

The server uses the relay as a key-only access path: `x11vnc` has no standalone password because
its listener is reachable only from inside the node namespace — not from the host, and not from a
peer node on the lab network (over IPv4 or IPv6 link-local) — while the API bearer token and
opaque per-session relay identifier are required before the backend starts the proxy. The proxy
runs in the namespace as the invoking unprivileged user and is the only route from the client to
that listener; VNC ports are not opened on the host.

## Bounds

- One display stack per node: repeating `POST .../console/vnc` returns the running display (a
  partly dead stack is stopped and replaced), so repeated clicks never start extra `Xvfb`,
  `xclock` or `x11vnc` processes. `x11vnc` starts only after the `Xvfb` socket exists; a display
  that cannot start is refused with `console.vnc_unavailable`.
- Starting a new display is admitted against memory: it needs 96 MiB (a display measured 89 MiB
  RSS, about 51 MiB PSS, on the development host — `scripts/measure-console-stack.py`) plus the
  backend's memory reserve to be available, otherwise HTTP 429 `console.vnc_memory`. Joining a
  running display is not charged again.
- At most 32 relay grants are held; the oldest is forgotten first, and destroy/reset drop the
  grants of the topology.
- At most 8 relays run at once, 2 per node. A further WebSocket is closed with code `4429` and a
  `console.vnc.relay_limit` log record. When the display side ends, the relay closes the
  WebSocket with code `1000`; when the client leaves, the proxy is stopped, including when the
  relay task is cancelled by a server shutdown.

`GET /v1/deployments/{topology}/nodes/{node}/console/readiness` reports each
prerequisite. `POST .../console/vnc` refuses L0 nodes and missing packages with
stable codes. The implementation never presents an empty or synthetic
framebuffer as a successful session.

The prerequisite check reports the installed paths and apt candidates for any missing tool. The
headless V.4 gate exercises the real `xclock` display stack, TCP/RFB 3.8 handshake, framebuffer
update, and pointer input through the authenticated relay. A human visual check is intentionally
left to the Windows operator because the phase host has no display; see
`v4.no_visual_validation_on_headless_server` in the phase evidence.
