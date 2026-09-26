# L0 networking

The supported synthetic protocol surface is deliberately small: Ethernet II, Ethernet/IPv4 ARP,
IPv4 without options or fragmentation, and ICMP echo request/reply. Codecs validate packet length,
supported formats, and IPv4/ICMP checksums. TCP, UDP application behavior, IPv6, fragmentation,
multicast, and routing are not advertised.

ARP and ICMP exchanges use deterministic endpoint ordering and virtual sequence numbers. Frames are
copied through bounded endpoint queues and retained in a bounded in-memory capture for diagnostics.
The first ping emits ARP request/reply and ICMP request/reply; subsequent pings use the ARP cache.

