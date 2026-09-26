# Topology format

Topologies are UTF-8 YAML mappings containing an identifier, networks, and nodes. Identifiers use
lowercase letters, digits, and hyphens. Networks require strict IPv4 CIDRs. Every interface names a
network and has a globally unique unicast MAC and usable IPv4 host address inside that subnet.
Overlapping networks, duplicate identifiers/keys/addresses, unknown fields, and conflicting service
bindings are rejected before deployment.

Node classes are `l0` (shared-process synthetic), `l1` (Linux namespace), and `l2` (future VM).
Resource requirements use MiB and millicores. Missing requirements receive conservative per-class
estimation defaults; estimation never deploys anything. Services use named built-in implementations,
not arbitrary shell commands. L0 services remain unsupported until an application protocol exists.

Validate and inspect the example without privileges:

```bash
.venv/bin/polmon-topology examples/topologies/hybrid-small.yml
.venv/bin/polmon-topology examples/topologies/hybrid-small.yml --normalized
```

Network subnets must lie inside the controlled laboratory ranges: RFC 1918 (`10.0.0.0/8`,
`172.16.0.0/12`, `192.168.0.0/16`) or the RFC 2544 benchmarking range (`198.18.0.0/15`). Public,
shared (`100.64.0.0/10`), loopback, link-local, and multicast ranges are rejected. Phase I has no
configuration that authorises external addresses.
