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

## Machine identity

Every node has three deliberately separate identities:

- `id` is the stable, lowercase machine-readable key used by links, scenarios and API paths.
- `uuid` is the stable global identity. It is an RFC 4122 version-4 UUID, generated when an older
  document is first loaded, serialized canonically in exports, and never changed by renaming.
- `name` is the human label shown throughout the client, reports and logs. It defaults to `id`, may
  contain 1–64 UTF-8 characters but no control characters, and is unique within the topology when
  compared case-insensitively.

Save or export a normalized older document once to persist its generated UUIDs. Editing `name`
does not change either `id` or `uuid`.

Validate and inspect the example without privileges:

```bash
.venv/bin/polmon-topology examples/topologies/hybrid-small.yml
.venv/bin/polmon-topology examples/topologies/hybrid-small.yml --normalized
```

## Address spaces and allocation

The default `address_space: lab-profile` accepts only the eleven networks
`192.168.230.0/24` through `192.168.240.0/24`. This narrow, conspicuous range makes accidental
contact with production networks less likely and makes review and cleanup predictable. The studio
and public allocation helpers choose the first free profile `/24`, the first usable free host, and
the first free MAC under the locally administered `02:50:4f` prefix. Allocation order is ascending,
so identical inputs produce identical allocations. Exhaustion is a coded refusal, never wraparound.

Compatibility documents may explicitly declare `address_space: rfc1918`. That escape hatch accepts
RFC 1918 plus `198.18.0.0/15`; it is never inferred for a new document. Public, shared
(`100.64.0.0/10`), loopback, link-local and multicast ranges remain rejected.

Migrate a v0.4 file atomically in place with:

```bash
.venv/bin/polmon-topology --migrate path/to/topology.yml
```

Networks are assigned profile `/24`s in document order. Each interface keeps its host offset where
usable and its MAC unchanged; collisions fall back to the first free host. IDs, names, UUIDs,
resources and services are preserved.
