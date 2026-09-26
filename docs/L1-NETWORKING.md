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

