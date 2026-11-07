"""Подставной qemu-system-x86_64: разбирает настоящую командную строку и отвечает по QMP.

Гостя нет — проверяется только то, что жизненный цикл ВМ делает с процессом QEMU.
Поведение задаёт POLMON_FAKE_QEMU: ok, ignore-quit, ignore-term, exit-early, bad-args.
"""

import json
import os
import signal
import socket
import sys

REQUIRED = ("-nodefaults", "-no-user-config", "-no-reboot")


def fail(message: str) -> None:
    print(f"fake-qemu: {message}", file=sys.stderr, flush=True)
    sys.exit(2)


def parse(argv: list[str]) -> dict:
    options: dict[str, list[str]] = {}
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag in REQUIRED:
            options.setdefault(flag, []).append("")
            index += 1
        elif flag.startswith("-"):
            if index + 1 >= len(argv):
                fail(f"{flag} needs a value")
            options.setdefault(flag, []).append(argv[index + 1])
            index += 2
        else:
            fail(f"unexpected argument {flag}")
    for flag in REQUIRED:
        if flag not in options:
            fail(f"missing {flag}")
    if options.get("-machine") != ["pc,accel=kvm"]:
        fail("only accel=kvm is allowed")
    sandbox = options.get("-sandbox", [""])[0]
    if "spawn=deny" not in sandbox or "elevateprivileges=deny" not in sandbox:
        fail("sandbox must deny spawn and privilege elevation")
    if len(options.get("-drive", [])) != 2 or "readonly=on" not in options["-drive"][1]:
        fail("expected an overlay and a read-only seed drive")
    if any(value.startswith("user") for value in options.get("-netdev", [])):
        fail("user-mode networking is forbidden")
    for flag in ("-name", "-uuid", "-qmp", "-pidfile", "-m"):
        if len(options.get(flag, [])) != 1:
            fail(f"exactly one {flag} expected")
    return options


def main() -> None:
    mode = os.environ.get("POLMON_FAKE_QEMU", "ok")
    if mode == "bad-args":
        fail("simulated rejection")
    options = parse(sys.argv[1:])
    if mode == "exit-early":
        sys.exit(1)
    if mode == "ignore-term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    path = options["-qmp"][0].removeprefix("unix:").split(",")[0]
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(1)
    with open(options["-pidfile"][0], "w") as stream:
        stream.write(f"{os.getpid()}\n")
    print("fake-qemu: serial console ready", flush=True)
    while True:
        connection, _ = listener.accept()
        with connection, connection.makefile("rwb") as stream:
            stream.write(b'{"QMP":{"version":{},"capabilities":[]}}\n')
            stream.flush()
            for line in stream:
                name = json.loads(line)["execute"]
                stream.write(b'{"return":{}}\n')
                stream.flush()
                if name == "quit" and mode != "ignore-quit":
                    sys.exit(0)


if __name__ == "__main__":
    main()
