"""Dashboard: backend identity, live resource counters and the configured limits."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QVBoxLayout, QWidget

from polmon.client.formatting import format_bytes, format_percent, format_seconds
from polmon.client.pages import Context, Page
from polmon.client.state import ConnectionState
from polmon.client.widgets import CounterTile, StatusBadge, fill_table, make_table, muted
from polmon.version import __version__

LIMIT_ROWS = (
    ("max_endpoint_count", "Maximum endpoints", str),
    ("max_active_namespaces", "Maximum active namespaces", str),
    ("max_concurrent_experiments", "Maximum concurrent experiments", str),
    ("max_capture_bytes", "Maximum capture size", format_bytes),
    ("max_experiment_duration_seconds", "Maximum experiment duration", format_seconds),
    ("memory_safety_threshold_mb", "Memory safety reserve", lambda v: f"{v} MiB"),
    ("max_data_directory_mb", "Data directory limit", lambda v: f"{v} MiB"),
    ("disk_free_reserve_mb", "Free-disk reserve", lambda v: f"{v} MiB"),
)


class ResourceTiles(QWidget):
    """Live counters shared by the dashboard and the deployment page."""

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = context.session
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self.endpoints = CounterTile("Active endpoints", sparkline=True)
        self.namespaces = CounterTile("Active namespaces", sparkline=True)
        self.workload = CounterTile("Deployments / experiments")
        self.rss = CounterTile("Backend RSS", sparkline=True)
        self.cpu = CounterTile("Backend CPU (lifetime avg)", sparkline=True)
        self.headroom = CounterTile("Memory headroom", sparkline=True)
        self.swap = CounterTile("Swap used")
        self.data = CounterTile("Data directory")
        tiles = (
            self.endpoints,
            self.namespaces,
            self.workload,
            self.rss,
            self.cpu,
            self.headroom,
            self.swap,
            self.data,
        )
        for index, tile in enumerate(tiles):
            grid.addWidget(tile, index // 4, index % 4)
        self.session.resources_changed.connect(self.refresh)
        self.session.connection_changed.connect(self.refresh)

    def refresh(self) -> None:
        resources = self.session.resources
        if not resources or self.session.state is ConnectionState.DISCONNECTED:
            for tile in self.findChildren(CounterTile):
                tile.set("—")
                if tile.sparkline is not None:
                    tile.sparkline.clear()
            return
        snapshot = resources.get("snapshot") or {}
        limits = resources.get("limits") or {}
        assert isinstance(snapshot, dict) and isinstance(limits, dict)
        endpoints = snapshot.get("active_endpoints") or 0
        namespaces = snapshot.get("active_namespaces") or 0
        self.endpoints.set(
            str(endpoints), f"limit {limits.get('max_endpoint_count', '—')}", endpoints
        )
        self.namespaces.set(
            str(namespaces), f"limit {limits.get('max_active_namespaces', '—')}", namespaces
        )
        benchmark = " · benchmark running" if resources.get("benchmark_running") else ""
        self.workload.set(
            f"{resources.get('active_deployments', 0)} / {resources.get('active_experiments', 0)}",
            f"max {limits.get('max_concurrent_experiments', '—')} concurrent experiments"
            + benchmark,
        )
        rss = snapshot.get("process_rss_bytes")
        self.rss.set(format_bytes(rss), "resident set size", rss if isinstance(rss, int) else None)
        cpu = snapshot.get("process_cpu_percent")
        seconds = snapshot.get("process_cpu_seconds")
        self.cpu.set(format_percent(cpu), f"{format_seconds(seconds)} CPU time", cpu)
        available = snapshot.get("available_memory_bytes")
        reserve = int(limits.get("memory_safety_threshold_mb") or 0) * 1_048_576
        if isinstance(available, int):
            headroom = available - reserve
            self.headroom.set(
                format_bytes(headroom),
                f"{format_bytes(available)} available − {format_bytes(reserve)} reserve",
                headroom,
            )
        else:
            self.headroom.set("—", "not reported by this host")
        swap = snapshot.get("swap_used_bytes")
        self.swap.set(format_bytes(swap), "host swap in use")
        used = resources.get("data_directory_bytes")
        limit_mb = limits.get("max_data_directory_mb")
        self.data.set(format_bytes(used), f"limit {limit_mb} MiB" if limit_mb else "")


class DashboardPage(Page):
    key = "dashboard"
    title = "Dashboard"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        identity = QGroupBox("Backend")
        identity_layout = QHBoxLayout(identity)
        self.badge = StatusBadge("disconnected")
        self.identity = muted()
        identity_layout.addWidget(self.badge)
        identity_layout.addWidget(self.identity, 1)
        self.root.addWidget(identity)

        counters = QGroupBox("Live resources")
        counters_layout = QVBoxLayout(counters)
        self.tiles = ResourceTiles(context)
        counters_layout.addWidget(self.tiles)
        self.root.addWidget(counters)

        limits = QGroupBox("Admission limits (configured on the backend)")
        limits_layout = QVBoxLayout(limits)
        self.limits = make_table(("Limit", "Value"), stretch=1)
        limits_layout.addWidget(self.limits)
        self.root.addWidget(limits, 1)

        self.session.connection_changed.connect(self.refresh)
        self.session.resources_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        session = self.session
        self.badge.set_status(session.state.value)
        if session.state is ConnectionState.DISCONNECTED:
            self.identity.setText(
                f"Client {__version__}. Not connected — enter the backend URL (and token, if the "
                "backend requires one) in the toolbar and press Connect (Ctrl+Return)."
            )
        else:
            latency = format_seconds(session.latency) if session.latency is not None else "—"
            auth = "token set" if session.token else "no token"
            problem = f" — {session.problem.title}" if session.problem else ""
            self.identity.setText(
                f"{session.url} · backend {session.backend_version or '—'} · client "
                f"{__version__} · {auth} · last round trip {latency}{problem}"
            )
        limits = session.limits()
        fill_table(
            self.limits,
            [
                (label, render(limits[key]) if key in limits else "—")
                for key, label, render in LIMIT_ROWS
            ],
        )
