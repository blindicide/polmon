from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.namespace.runner import CommandResult
from polmon.scenarios.executors import HybridScenarioExecutor
from polmon.scenarios.models import ActionKind, ScenarioAction
from polmon.topology import parse_topology


class FakeProcess:
    pid = 1

    def poll(self):
        return 0


class FakeRunner:
    def run(self, command, *, privileged=False, check=True, timeout=10, input=None):
        return CommandResult("", "", 0)

    def start(self, command, *, privileged=False):
        return FakeProcess()


class FakeTap:
    def __init__(self, name: str) -> None:
        self.name = name

    def write(self, frame: bytes) -> None:
        pass

    def read(self, timeout: float):
        return None

    def close(self) -> None:
        pass


TOPOLOGY = parse_topology(
    """id: mixed
networks:
  - id: lab
    ipv4_subnet: 10.90.0.0/24
nodes:
  - id: sensor-a
    class: l0
    interfaces: [{id: eth0, network: lab, mac: "02:00:00:90:00:01", ipv4: 10.90.0.1}]
  - id: sensor-b
    class: l0
    interfaces: [{id: eth0, network: lab, mac: "02:00:00:90:00:02", ipv4: 10.90.0.2}]
  - id: server-a
    class: l1
    interfaces: [{id: eth0, network: lab, mac: "02:00:00:90:00:11", ipv4: 10.90.0.11}]
    services: [{id: web, protocol: tcp, port: 8080, implementation: static_http}]
  - id: server-b
    class: l1
    interfaces: [{id: eth0, network: lab, mac: "02:00:00:90:00:12", ipv4: 10.90.0.12}]
"""
)


def deployed_executor() -> tuple[HybridBackend, HybridScenarioExecutor]:
    backend = HybridBackend(
        runner=FakeRunner(),
        tap_factory=FakeTap,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1000,
        bridge_port_states=lambda bridge: {name: "3" for name in backend.tap_names.values()},
    )
    backend.validate(TOPOLOGY)
    backend.create(TOPOLOGY)
    backend.capture.append(b"frame from before the experiment")
    return backend, HybridScenarioExecutor(backend)


def action(kind: ActionKind, source: str, target: str, service: str | None = None):
    return ScenarioAction(id="a", kind=kind, source=source, target=target, service=service)


def test_hybrid_executor_routes_each_path_to_its_real_transport() -> None:
    backend, executor = deployed_executor()
    assert not backend.capture  # the experiment owns the boundary capture window
    calls = []
    backend.ping_l1 = lambda source, address, timeout: calls.append(("tap", source, str(address)))
    backend.namespace.ping = lambda source, address: calls.append(("kernel", source, address))

    l0_l0 = executor.execute(action(ActionKind.ICMP_PROBE, "sensor-a", "sensor-b"), TOPOLOGY, 5)
    assert l0_l0.success and l0_l0.data["path"] == "l0->l0"
    assert executor.captured_frames()  # synthetic ARP/ICMP frames are captured

    executor.execute(action(ActionKind.ICMP_PROBE, "sensor-a", "server-a"), TOPOLOGY, 5)
    executor.execute(action(ActionKind.ICMP_PROBE, "server-a", "server-b"), TOPOLOGY, 5)
    assert calls == [
        ("tap", "sensor-a", "10.90.0.11"),
        ("kernel", "server-a", "10.90.0.12"),
    ]
    backend.destroy()


def test_hybrid_executor_reports_unsupported_paths_instead_of_emulating() -> None:
    backend, executor = deployed_executor()
    calls = []
    backend.namespace.ping = lambda source, address: calls.append((source, address)) or True
    reverse = executor.execute(action(ActionKind.ICMP_PROBE, "server-a", "sensor-a"), TOPOLOGY, 5)
    assert (reverse.success, reverse.data["path"]) == (True, "l1->l0")
    assert calls == [("server-a", "10.90.0.1")]  # the kernel pings; the TAP responder answers
    for source, target in (("sensor-a", "server-a"), ("server-a", "sensor-a")):
        tcp = executor.execute(action(ActionKind.TCP_PROBE, source, target, "web"), TOPOLOGY, 5)
        assert (tcp.success, tcp.detail, tcp.data["protocol"]) == (
            False,
            "unsupported",
            "tcp_probe",
        )
    backend.destroy()


def test_hybrid_executor_reports_unreachable_when_the_tap_stays_silent() -> None:
    backend, executor = deployed_executor()  # FakeTap never answers
    result = executor.execute(action(ActionKind.ICMP_PROBE, "sensor-b", "server-b"), TOPOLOGY, 0.2)
    assert (result.success, result.detail) == (False, "unreachable")
    backend.destroy()
