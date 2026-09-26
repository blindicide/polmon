# L0 engine

L0 endpoints are Python state objects managed by one `SyntheticEngine`; no endpoint launches an OS,
container, thread, or subprocess. Each live logical ID, MAC, and IPv4 address is unique, while each
creation receives a UUID instance identity that is never reused by the engine. Virtual networks are
membership sets and dispatch copies bounded byte payloads only between members of the same network.

The virtual-time scheduler uses a stable sequence number for equal timestamps and has a configurable
event ceiling. Endpoint receive queues are bounded at 256 packets. Endpoint destruction removes its
network membership, queued packets, addresses, and scheduled events. Engine statistics report active
endpoints/networks/events/packets and an explicitly approximate shallow state-size estimate.

