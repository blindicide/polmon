"""Изолированная лабораторная сеть ВМ: одно сетевое пространство с мостами и TAP-устройствами.

Все мосты и TAP живут внутри отдельного сетевого пространства без внешнего интерфейса,
маршрута по умолчанию и NAT. Пространство бывает двух видов:

* ``userns`` — непривилегированное: пользовательское + сетевое пространство имён, sudo не нужен;
* ``netns`` — именованное ``ip netns`` через sudo, процессы затем понижают права через setpriv.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from polmon.backends.namespace.runner import CommandRunner, stop_process_group
from polmon.topology.models import Topology
from polmon_l1_vm.host import alive, process_start, terminate
from polmon_l1_vm.images import VMError

MODES = ("userns", "netns")


def _name(value: str, suffix: str) -> str:
    digest = hashlib.blake2s(value.encode("utf-8"), digest_size=4).hexdigest()
    name = f"polmon{digest}{suffix}"
    if len(name) > 15:
        raise VMError("vm.name_invalid")
    return name


@dataclass(frozen=True, slots=True)
class LabNames:
    namespace: str
    bridges: dict[str, str]
    taps: dict[tuple[str, str], str]
    probes: dict[str, ipaddress.IPv4Interface]


def probe_address(topology: Topology, network_id: str) -> ipaddress.IPv4Interface:
    """Старший свободный адрес подсети: с него хост лаборатории опрашивает гостей."""
    network = next(item for item in topology.networks if item.id == network_id)
    used = {
        interface.ipv4
        for node in topology.nodes
        for interface in node.interfaces
        if interface.network == network_id
    }
    candidate = network.ipv4_subnet.broadcast_address - 1
    for _ in range(len(used) + 1):
        if candidate not in used and candidate > network.ipv4_subnet.network_address:
            return ipaddress.IPv4Interface(f"{candidate}/{network.ipv4_subnet.prefixlen}")
        candidate -= 1
    raise VMError("vm.probe_address")


def lab_names(topology: Topology) -> LabNames:
    return LabNames(
        namespace=_name(f"vm:{topology.id}", "n"),
        bridges={item.id: _name(f"vm:{topology.id}:{item.id}", "b") for item in topology.networks},
        taps={
            (node.id, interface.id): _name(f"vm:{topology.id}:{node.id}:{interface.id}", "t")
            for node in topology.nodes
            for interface in node.interfaces
        },
        probes={item.id: probe_address(topology, item.id) for item in topology.networks},
    )


class Lab:
    """Сетевое пространство ВМ и всё, что в него входит; владеет только созданным им самим."""

    def __init__(
        self,
        topology: Topology,
        runner: CommandRunner,
        *,
        mode: str = "userns",
        owner_uid: int | None = None,
        owner_gid: int | None = None,
    ):
        if mode not in MODES:
            raise VMError("vm.mode_invalid")
        self.topology, self.runner, self.mode = topology, runner, mode
        self.owner_uid = os.getuid() if owner_uid is None else owner_uid
        self.owner_gid = os.getgid() if owner_gid is None else owner_gid
        self.names = lab_names(topology)
        self.holder: subprocess.Popen[bytes] | None = None
        self.holder_identity: tuple[int, str] | None = None
        self.created = False

    # -- команды внутри пространства ------------------------------------------------------

    def wrap(self, argv: list[str], *, as_owner: bool = False, harden: bool = False) -> list[str]:
        """Команда, выполняющая ``argv`` внутри пространства; sudo добавляет сам ``runner``."""
        if self.mode == "userns":
            if self.holder is None:
                raise VMError("vm.lab_missing")
            return [
                "nsenter",
                "--target",
                str(self.holder.pid),
                "--user",
                "--net",
                "--preserve-credentials",
                "--",
                *argv,
            ]
        prefix = ["ip", "netns", "exec", self.names.namespace]
        if as_owner:
            prefix += [
                "setpriv",
                "--reuid",
                str(self.owner_uid),
                "--regid",
                str(self.owner_gid),
                "--clear-groups",
            ]
            if harden:
                prefix.append("--no-new-privs")
        return [*prefix, *argv]

    @property
    def privileged(self) -> bool:
        return self.mode == "netns"

    def run(
        self,
        argv: list[str],
        *,
        as_owner: bool = False,
        check: bool = True,
        timeout: float = 10,
        input: str | None = None,
    ):
        return self.runner.run(
            self.wrap(argv, as_owner=as_owner),
            privileged=self.privileged,
            check=check,
            timeout=timeout,
            input=input,
        )

    def start(self, argv: list[str], *, log_path: Path, max_output_bytes: int = 262_144):
        """Запускает долгоживущий процесс гостевой машины от имени владельца."""
        return self.runner.start(
            self.wrap(argv, as_owner=True, harden=True),
            privileged=self.privileged,
            log_path=log_path,
            max_output_bytes=max_output_bytes,
        )

    # -- жизненный цикл -------------------------------------------------------------------

    def _existing(self) -> bool:
        listing = self.runner.run(["ip", "netns", "list"], check=False).stdout
        return any(line.split()[:1] == [self.names.namespace] for line in listing.splitlines())

    def create(self) -> None:
        """Создаёт пространство, мосты и TAP; при любой ошибке откатывает уже созданное."""
        if self.created:
            raise VMError("vm.lab_exists")
        if self.mode == "netns":
            if self._existing():
                # Чужое пространство с тем же именем не усыновляется: откат удалил бы его.
                raise VMError("vm.lab_exists")
            self.created = True
            self.runner.run(["ip", "netns", "add", self.names.namespace], privileged=True)
        else:
            self.created = True
            self._spawn_holder()
        try:
            self.run(
                ["ip", "-batch", "-"],
                timeout=10 + len(self._lines()),
                input="".join(f"{line}\n" for line in self._lines()),
            )
            self.verify_isolated()
        except BaseException:
            self.destroy()
            raise

    def _lines(self) -> list[str]:
        """Строки ``ip -batch``: только проверенные идентификаторы и сгенерированные имена."""
        lines = ["link set lo up"]
        for network in self.topology.networks:
            bridge = self.names.bridges[network.id]
            probe = self.names.probes[network.id]
            lines += [
                f"link add name {bridge} type bridge",
                f"addr add {probe} dev {bridge}",
                f"link set dev {bridge} up",
            ]
        owner = f" user {self.owner_uid} group {self.owner_gid}" if self.mode == "netns" else ""
        for node in self.topology.nodes:
            for interface in node.interfaces:
                tap = self.names.taps[(node.id, interface.id)]
                bridge = self.names.bridges[interface.network]
                lines += [
                    f"tuntap add dev {tap} mode tap{owner}",
                    f"link set dev {tap} master {bridge}",
                    f"link set dev {tap} up",
                ]
        return lines

    def _spawn_holder(self) -> None:
        self.holder = self.runner.start(
            ["unshare", "--user", "--map-root-user", "--net", "sleep", "infinity"]
        )
        deadline = time.monotonic() + 5
        host = os.readlink("/proc/self/ns/net")
        while time.monotonic() < deadline:
            try:
                if (
                    self.holder.poll() is None
                    and os.readlink(f"/proc/{self.holder.pid}/ns/net") != host
                    and Path(f"/proc/{self.holder.pid}/comm").read_text().strip() == "sleep"
                ):
                    start = process_start(self.holder.pid)
                    if start is not None:
                        self.holder_identity = (self.holder.pid, start)
                        return
            except OSError:
                pass
            time.sleep(0.02)
        stop_process_group(self.holder, grace=1)
        self.holder = None
        raise VMError("vm.userns_unavailable")

    def verify_isolated(self) -> dict:
        """Отказывает при чужих устройствах или маршруте по умолчанию в пространстве."""
        owned = {
            "lo",
            *self.names.bridges.values(),
            *self.names.taps.values(),
        }
        links = self.run(["ip", "-o", "link", "show"]).stdout
        found = {
            line.split(": ", 1)[1].split(":", 1)[0].split("@", 1)[0]
            for line in links.splitlines()
            if ": " in line
        }
        if not found <= owned:
            raise VMError("vm.lab_foreign_link")
        for family in ("-4", "-6"):
            routes = self.run(["ip", family, "route", "show"]).stdout
            if any(line.startswith("default") for line in routes.splitlines()):
                raise VMError("vm.lab_default_route")
        return {"namespace": self.names.namespace, "links": sorted(found)}

    def members(self) -> list[int]:
        """Процессы пользователя в сетевом пространстве (только режим ``userns``)."""
        if self.mode != "userns" or self.holder is None:
            return []
        try:
            target = os.readlink(f"/proc/{self.holder.pid}/ns/net")
        except OSError:
            return []
        found = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == self.holder.pid:
                continue
            try:
                if os.readlink(entry / "ns" / "net") == target:
                    found.append(int(entry.name))
            except OSError:
                continue
        return found

    def destroy(self) -> None:
        """Идемпотентно удаляет пространство; устройства внутри исчезают вместе с ним."""
        if self.mode == "netns":
            if self.created:
                self.runner.run(
                    ["ip", "netns", "del", self.names.namespace], privileged=True, check=False
                )
        elif self.holder is not None:
            for pid in self.members():
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
            stop_process_group(self.holder, grace=1)
        self.holder = None
        self.holder_identity = None
        self.created = False

    def resources(self) -> frozenset[str]:
        if not self.created:
            return frozenset()
        if self.mode == "netns":
            return frozenset({f"netns:{self.names.namespace}"})
        if self.holder_identity is None:
            return frozenset()
        return frozenset({f"userns:{self.holder_identity[0]}"})

    def state(self) -> dict:
        """Запись о владении для восстановления после аварии."""
        return {
            "mode": self.mode,
            "namespace": self.names.namespace,
            "holder": list(self.holder_identity) if self.holder_identity else None,
        }


def release(state: dict, runner: CommandRunner) -> list[str]:
    """Освобождает пространство по записи о владении (после аварии); возвращает снятые ресурсы."""
    released = []
    if state.get("mode") == "netns" and state.get("namespace"):
        name = state["namespace"]
        if not name.startswith("polmon") or not name.endswith("n"):
            raise VMError("vm.state_invalid")
        runner.run(["ip", "netns", "del", name], privileged=True, check=False)
        released.append(f"netns:{name}")
    elif state.get("mode") == "userns" and state.get("holder"):
        holder = state["holder"]
        if alive(holder):
            target = os.readlink(f"/proc/{holder[0]}/ns/net")
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit() or int(entry.name) == holder[0]:
                    continue
                with contextlib.suppress(OSError):
                    if os.readlink(entry / "ns" / "net") == target:
                        os.kill(int(entry.name), signal.SIGKILL)
            terminate(holder, grace=1)
            released.append(f"userns:{holder[0]}")
    return released
