"""Командная строка дополнения: планирование, проверка образа, запуск гостей, восстановление."""

from __future__ import annotations

import argparse
import contextlib
import http.client
import ipaddress
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from threading import Event, Thread

from polmon.topology import load_topology
from polmon.version import __version__
from polmon_l1_vm.backend import VMBackend, readiness
from polmon_l1_vm.host import alive
from polmon_l1_vm.images import ImageManifest, VMError, acquire_image, verify_image
from polmon_l1_vm.lab import MODES
from polmon_l1_vm.recovery import inspect_run, recover

MAX_HOLD_SECONDS = 600


@contextlib.contextmanager
def _parent_guard(pid: int | None, start: str | None):
    """An API backend killed without shutdown must not orphan its VM command."""
    if pid is None and start is None:
        yield
        return
    if pid is None or pid <= 0 or start is None or not start.isdigit():
        raise VMError("vm.state_invalid")
    stopped = Event()

    def watch() -> None:
        while not stopped.is_set():
            if not alive((pid, start)):
                # The dead supervisor may also have closed our stderr pipe.
                with contextlib.suppress(OSError):
                    print(
                        json.dumps({"error_code": "vm.parent_exited"}),
                        file=sys.stderr, flush=True,
                    )
                os.kill(os.getpid(), signal.SIGTERM)
                return
            stopped.wait(0.25)

    watcher = Thread(target=watch, name="polmon-vm-parent", daemon=True)
    watcher.start()
    try:
        yield
    finally:
        stopped.set()
        watcher.join(timeout=1)


def _manifest(path: Path) -> ImageManifest:
    if path.stat().st_size > 16384:
        raise VMError("vm.manifest_size")
    return ImageManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _backend(args: argparse.Namespace) -> VMBackend:
    backend, extra = VMBackend, {}
    if args.vm_node:
        from polmon_l1_vm.mixed import MixedBackend

        backend, extra = MixedBackend, {"vm_nodes": args.vm_node}
    return backend(
        base=args.image,
        manifest=_manifest(args.manifest),
        directory=args.directory,
        mode=getattr(args, "mode", "userns"),
        **extra,
    )


def _run(args: argparse.Namespace) -> dict:
    """Создаёт гостей, ждёт готовности, снимает измерения и всегда всё удаляет."""
    topology = load_topology(args.topology)
    vm = _backend(args)
    started = time.monotonic()
    try:
        vm.create(topology)
        vm.start()
        vm.wait_ready()
        report = {
            "ready_seconds": round(time.monotonic() - started, 1),
            "probes": {
                node.id: [
                    vm.probe_http(str(node.interfaces[0].ipv4), service.port, node.id)
                    for service in node.services
                ]
                for node in topology.nodes
            },
            "sample": vm.sample(),
        }
        if args.hold_seconds:
            time.sleep(args.hold_seconds)
        return report
    finally:
        vm.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Дополнение: узлы L1 на виртуальных машинах KVM")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("readiness")
    sub.add_parser("bundle-check")
    helper = sub.add_parser("mixed-helper")
    helper.add_argument("arguments", nargs=argparse.REMAINDER)
    probe = sub.add_parser("probe-http")
    probe.add_argument("address")
    probe.add_argument("port", type=int, choices=range(1, 65536), metavar="PORT")
    probe.add_argument("path")
    commands = {}
    for name in ("plan", "run", "verify-image", "acquire-image", "recover", "inspect"):
        commands[name] = sub.add_parser(name)
    for name in ("plan", "run"):
        commands[name].add_argument("--topology", type=Path, required=True)
        commands[name].add_argument("--directory", type=Path, required=True)
        commands[name].add_argument("--vm-node", action="append", default=[])
    for name in ("plan", "run", "verify-image", "acquire-image"):
        commands[name].add_argument("--manifest", type=Path, required=True)
        commands[name].add_argument("--image", type=Path, required=True)
    for name in ("recover", "inspect"):
        commands[name].add_argument("--directory", type=Path, required=True)
    commands["run"].add_argument("--mode", choices=MODES, default="userns")
    commands["run"].add_argument("--parent-pid", type=int)
    commands["run"].add_argument("--parent-start")
    commands["run"].add_argument(
        "--hold-seconds", type=int, default=0, choices=range(MAX_HOLD_SECONDS + 1), metavar="N"
    )
    args = parser.parse_args(argv)
    # SIGTERM проходит через блоки finally: иначе остались бы гости, пространство, частичный образ.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        if args.action == "mixed-helper":
            from polmon_l1_vm.mixed import helper_main

            return helper_main(args.arguments)
        if args.action == "probe-http":
            address = str(ipaddress.IPv4Address(args.address))
            if not re.fullmatch(r"/[A-Za-z0-9._/-]{0,64}", args.path):
                raise VMError("vm.path_invalid")
            connection = http.client.HTTPConnection(address, args.port, timeout=3)
            try:
                connection.request("GET", args.path)
                response = connection.getresponse()
                print(
                    str(response.status) + " " + response.read(512).decode("utf-8", "replace"),
                    end="",
                )
            finally:
                connection.close()
            return 0
        if args.action == "bundle-check":
            import stat

            from polmon.api.vm import MANIFEST, bundled_image
            from polmon_l1_vm.images import digest

            image = bundled_image()
            manifest = ImageManifest.model_validate(MANIFEST)
            if image.is_symlink() or not image.is_file() or image.stat().st_mode & 0o222:
                raise VMError("vm.base_not_readonly")
            if not stat.S_ISREG(image.stat().st_mode):
                raise VMError("vm.image_missing")
            if digest(image, limit=manifest.max_file_bytes) != manifest.sha256:
                raise VMError("vm.image_checksum")
            result = {
                "version": __version__,
                "sha256": manifest.sha256,
                "image_bytes": image.stat().st_size,
                "integration_verified": False,
            }
        elif args.action == "readiness":
            result = readiness()
            print(json.dumps(result))
            return 0 if result["ready"] else 2
        elif args.action == "verify-image":
            from polmon.backends.namespace.runner import CommandRunner

            result = verify_image(args.image, _manifest(args.manifest), CommandRunner())
        elif args.action == "acquire-image":
            result = acquire_image(args.image, _manifest(args.manifest))
        elif args.action == "recover":
            result = recover(args.directory)
        elif args.action == "inspect":
            result = inspect_run(args.directory)
        elif args.action == "run":
            with _parent_guard(args.parent_pid, args.parent_start):
                result = _run(args)
        else:
            backend = _backend(args)
            result = backend.plan(load_topology(args.topology))
        print(json.dumps(result, default=list))
        return 0
    except Exception as error:
        code = error.code if isinstance(error, VMError) else type(error).__name__
        print(json.dumps({"error_code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
