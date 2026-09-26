# L1 namespace networking

The L1 backend creates one Linux network namespace per L1 node, one isolated `polmon*` bridge per
declared network, and one `veth*` pair per interface. It enables loopback, assigns declared MAC/IPv4
addresses inside namespaces, and relies only on directly connected laboratory routes. It never
changes the primary interface, default route, firewall, DNS, or external forwarding.

All privileged commands are argv-only, time-bounded calls through a small runner. Generated Linux
names are deterministic, platform-prefixed, and at most 15 characters. Services are named built-ins;
`static_http` uses the project Python 3.12 interpreter and drops to the invoking uid/gid after entering
the namespace. Stop tracks processes, while destroy removes namespaces before bridges and is safe to
repeat. Privileged tests are opt-in with `pytest -m privileged`.

The built-in `static_http` service (`polmon/backends/namespace/static_http.py`) is a standalone
standard-library responder run by path with `python -I -S` after `setpriv` drops to the invoking
user. It answers `GET`/`HEAD` with a fixed plain-text body, `405` for other methods, and `400` for
malformed or oversized (> 8 KiB) requests; request paths are ignored and no file is ever read, so
a lab peer cannot see the backend's working directory. Reads time out after 5 s and at most 32
connections are served concurrently.

