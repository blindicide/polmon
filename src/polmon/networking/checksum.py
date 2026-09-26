"""Internet checksum shared by IPv4 and ICMP."""


def internet_checksum(data: bytes) -> int:
    """Return the RFC 1071 one's-complement checksum."""
    if len(data) % 2:
        data += b"\x00"
    total = sum((data[index] << 8) | data[index + 1] for index in range(0, len(data), 2))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF

