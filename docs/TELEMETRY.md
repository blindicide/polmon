# Telemetry

Each experiment has one SQLite metadata row containing its ID, project version, topology, scenario,
timestamps, and status. Ordered event rows cover scenario activity, node lifecycle, network
observations, execution errors, and resource snapshots. Payloads are compact UTF-8 JSON; keys that
look credential-, token-, secret-, password-, or API-key-related are recursively redacted.

Packet data uses classic Ethernet PCAP, readable by tcpdump and Wireshark. Both the total capture
bytes and per-frame snap length are hard limits. Once the total limit would be exceeded, packets are
dropped and counted rather than allowing unbounded storage. Capture metadata records path, frame and
byte counts, drops, and truncations under the same experiment foreign key. Experiment identifiers are
path-safe and captures use exclusive creation to prevent accidental overwrite.

