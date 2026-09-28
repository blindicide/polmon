# VNC console

VNC is available only for deployed `l1` nodes on a Linux backend. The intended
stack is `Xvfb` for a private display, `xclock` as the documented X client, and
`x11vnc` bound to the node's lab address. The client uses the authenticated
backend relay and never opens a direct unauthenticated lab socket.

The server uses the relay as a key-only access path: `x11vnc` has no standalone password because
its listener exists only inside the node namespace, while the API bearer token and opaque
per-session relay identifier are required before the backend starts the authenticated proxy. The
proxy is the only route from the client to that listener; VNC ports are not opened on the host.

`GET /v1/deployments/{topology}/nodes/{node}/console/readiness` reports each
prerequisite. `POST .../console/vnc` refuses L0 nodes and missing packages with
stable codes. The implementation never presents an empty or synthetic
framebuffer as a successful session.

The prerequisite check reports the installed paths and apt candidates for any missing tool. The
headless V.4 gate exercises the real `xclock` display stack, TCP/RFB 3.8 handshake, framebuffer
update, and pointer input through the authenticated relay. A human visual check is intentionally
left to the Windows operator because the phase host has no display; see
`v4.no_visual_validation_on_headless_server` in the phase evidence.
