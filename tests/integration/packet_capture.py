"""Receive one laboratory EtherType frame inside an already selected namespace."""

import socket
import sys


def main() -> int:
    if sys.argv[1:] != ["eth0"]:
        return 2
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003)) as reader:
        reader.bind(("eth0", 0))
        reader.settimeout(3)
        print("READY", flush=True)
        while True:
            frame = reader.recv(2048)
            if frame[12:14] == b"\x88\xb5":
                print(frame.hex(), flush=True)
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
