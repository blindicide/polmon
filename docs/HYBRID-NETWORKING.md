# Hybrid L0/L1 boundary

Each topology network containing synthetic nodes gets one shared TAP—not one interface per L0 node.
The TAP is owned by the invoking user, attached to the backend-created isolated bridge, and accessed
through a non-blocking file descriptor. Synthetic Ethernet frames enter the bridge through that TAP;
Linux ARP and ICMP replies return through the same boundary. All frames observed by the boundary are
retained only in a bounded in-memory deque.

Standard tools can inspect traffic on the generated `polmon*` TAP or bridge, for example with a
bounded `tcpdump -i <tap> -c <count>`. Measured overhead should include a bridge, one TAP/file
descriptor per participating network, and ordinary L0 state. Supported cross-boundary behavior is
Ethernet/ARP/IPv4/ICMP echo only. TCP, synthetic services, routing, IPv6, and fragmented IP are not
claimed. Teardown closes TAP descriptors and deletes TAPs before namespaces and bridges.

