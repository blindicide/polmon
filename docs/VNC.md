# VNC console

VNC is available only for deployed `l1` nodes on a Linux backend. The intended
stack is `Xvfb` for a private display, `xclock` as the documented X client, and
`x11vnc` bound to the node's lab address. The client uses the authenticated
backend relay and never opens a direct unauthenticated lab socket.

`GET /v1/deployments/{topology}/nodes/{node}/console/readiness` reports each
prerequisite. `POST .../console/vnc` refuses L0 nodes and missing packages with
stable codes. The implementation never presents an empty or synthetic
framebuffer as a successful session.

The prerequisite check reports the installed paths and apt candidates for any
missing tool. The VNC gate must show an actual `xclock` window and exercise
keyboard or pointer input through the authenticated relay.
