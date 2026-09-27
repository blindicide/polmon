"""Dashboard: backend identity and capabilities, live resource counters, admission limits and
the latest experiments — every number that matters visible at once."""

from __future__ import annotations

import time

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QWidget

from polmon.client import theme
from polmon.client.formatting import format_bytes, format_datetime, format_percent, format_seconds
from polmon.client.i18n import Msg, tr
from polmon.client.pages import Context, Page
from polmon.client.state import ConnectionState
from polmon.client.widgets import (
    Card,
    CounterTile,
    KeyValueGrid,
    StateView,
    StatusBadge,
    button,
    fill_table,
    label,
    make_table,
)
from polmon.version import __version__

# Admission limits: (limits key, catalog key, renderer).
LIMIT_ROWS = (
    ("max_endpoint_count", "limit.max_endpoint_count", str),
    ("max_active_namespaces", "limit.max_active_namespaces", str),
    ("max_concurrent_experiments", "limit.max_concurrent_experiments", str),
    ("max_capture_bytes", "limit.max_capture_bytes", format_bytes),
    ("max_experiment_duration_seconds", "limit.max_experiment_duration_seconds", format_seconds),
    ("memory_safety_threshold_mb", "limit.memory_safety_threshold_mb", lambda v: f"{v} MiB"),
    ("max_data_directory_mb", "limit.max_data_directory_mb", lambda v: f"{v} MiB"),
    ("disk_free_reserve_mb", "limit.disk_free_reserve_mb", lambda v: f"{v} MiB"),
)
# Column-major: the first column holds the long values (URL, emulation level), the second the
# short ones (versions, authentication, latency).
IDENTITY_ROWS = (
    "dashboard.identity.url",
    "dashboard.identity.fidelity",
    "dashboard.identity.l1",
    "dashboard.identity.hybrid",
    "dashboard.identity.backend",
    "dashboard.identity.client",
    "dashboard.identity.auth",
    "dashboard.identity.latency",
)
RECENT_EXPERIMENTS = 6


class ResourceTiles(QWidget):
    """Live counters shared by the dashboard and the deployment page."""

    def __init__(
        self, context: Context, parent: QWidget | None = None, *, compact: bool = False
    ) -> None:
        super().__init__(parent)
        self.session = context.session
        spark = not compact  # compact tiles (deployment page) drop the sparklines
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(theme.SPACE["sm"])
        self.endpoints = CounterTile("tile.endpoints", sparkline=spark)
        self.namespaces = CounterTile("tile.namespaces", sparkline=spark)
        self.workload = CounterTile("tile.workload")
        self.rss = CounterTile("tile.rss", sparkline=spark)
        self.cpu = CounterTile("tile.cpu", sparkline=spark)
        self._cpu_sample: tuple[float, float] | None = None  # (process CPU seconds, wall time)
        self.headroom = CounterTile("tile.headroom", sparkline=spark)
        self.swap = CounterTile("tile.swap")
        self.data = CounterTile("tile.data")
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
        self.refresh()

    def _current_cpu(self, seconds: object) -> float | None:
        """CPU use since the previous poll, as a percentage of one core."""
        if not isinstance(seconds, int | float):
            return None
        now = time.monotonic()
        previous, self._cpu_sample = self._cpu_sample, (float(seconds), now)
        if previous is None or now - previous[1] < 0.5 or seconds < previous[0]:
            return None  # first sample, too close together, or the backend restarted
        return max(0.0, (float(seconds) - previous[0]) / (now - previous[1]) * 100)

    def refresh(self, *, sample: bool = True) -> None:
        resources = self.session.resources
        if not resources or self.session.state is ConnectionState.DISCONNECTED:
            self._cpu_sample = None
            for tile in self.findChildren(CounterTile):
                tile.set("—", tr("tile.no_data"))
                if tile.sparkline is not None:
                    tile.sparkline.clear()
            return
        snapshot = resources.get("snapshot") or {}
        limits = resources.get("limits") or {}
        assert isinstance(snapshot, dict) and isinstance(limits, dict)

        def point(value: object) -> float | None:
            return value if sample and isinstance(value, int | float) else None

        endpoints = snapshot.get("active_endpoints") or 0
        namespaces = snapshot.get("active_namespaces") or 0
        self.endpoints.set(
            str(endpoints),
            tr("tile.limit", limit=limits.get("max_endpoint_count", "—")),
            point(endpoints),
        )
        self.namespaces.set(
            str(namespaces),
            tr("tile.limit", limit=limits.get("max_active_namespaces", "—")),
            point(namespaces),
        )
        secondary = tr(
            "tile.workload.detail", limit=limits.get("max_concurrent_experiments", "—")
        )
        if resources.get("benchmark_running"):
            secondary += " · " + tr("tile.workload.benchmark")
        self.workload.set(
            f"{resources.get('active_deployments', 0)} / {resources.get('active_experiments', 0)}",
            secondary,
        )
        rss = snapshot.get("process_rss_bytes")
        self.rss.set(format_bytes(rss), tr("tile.rss.detail"), point(rss))
        lifetime = snapshot.get("process_cpu_percent")
        seconds = snapshot.get("process_cpu_seconds")
        current = self._current_cpu(seconds) if sample else None
        self.cpu.set(
            format_percent(current) if current is not None else "…",
            tr(
                "tile.cpu.detail",
                lifetime=format_percent(lifetime),
                time=format_seconds(seconds),
            ),
            current,
        )
        available = snapshot.get("available_memory_bytes")
        reserve = int(limits.get("memory_safety_threshold_mb") or 0) * 1_048_576
        if isinstance(available, int):
            headroom = available - reserve
            # Below zero new deployments are refused; under a quarter of the reserve is close.
            tone = "danger" if headroom <= 0 else "warning" if headroom < reserve / 4 else ""
            self.headroom.set(
                format_bytes(headroom),
                tr(
                    "tile.headroom.detail",
                    available=format_bytes(available),
                    reserve=format_bytes(reserve),
                ),
                point(headroom),
                tone,
            )
        else:
            self.headroom.set("—", tr("tile.not_reported"))
        swap = snapshot.get("swap_used_bytes")
        self.swap.set(
            format_bytes(swap),
            tr("tile.swap.detail") if isinstance(swap, int) else tr("tile.not_reported"),
        )
        used = resources.get("data_directory_bytes")
        limit_mb = limits.get("max_data_directory_mb")
        share = (
            used / (int(limit_mb) * 1_048_576)
            if isinstance(used, int) and isinstance(limit_mb, int) and limit_mb
            else 0.0
        )
        tone = "danger" if share >= 0.95 else "warning" if share >= 0.8 else ""
        self.data.set(
            format_bytes(used),
            tr("tile.data.detail", limit=limit_mb, share=f"{share:.0%}") if limit_mb else "",
            tone=tone,
        )


class DashboardPage(Page):
    key = "dashboard"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE["md"])
        identity = Card("dashboard.backend", name="backend")
        self.badge = StatusBadge("disconnected")
        identity.add_action(self.badge)
        self.identity = KeyValueGrid(IDENTITY_ROWS, columns=2, wrap_values=True)
        identity.add(self.identity)
        self.hint = label(wrap=True, name="muted")
        identity.add(self.hint)
        top.addWidget(identity, 3)

        limits = Card("dashboard.limits", hint="dashboard.limits.hint", name="limits")
        self.limits = KeyValueGrid([key for _, key, _ in LIMIT_ROWS], columns=2)
        limits.add(self.limits)
        top.addWidget(limits, 2)
        self.root.addLayout(top)

        counters = Card("dashboard.resources", hint="dashboard.resources.hint", name="resources")
        self.tiles = ResourceTiles(context)
        counters.add(self.tiles)
        self.root.addWidget(counters)

        recent = Card("dashboard.recent", name="recent")
        self.open_reports = button("dashboard.recent.open", "quiet", name="openReports")
        self.open_reports.clicked.connect(lambda: self.context.navigate("reports"))
        recent.add_action(self.open_reports)
        self.recent = make_table(
            (
                "column.experiment",
                "column.scenario",
                "column.topology",
                "column.status",
                "column.started",
            ),
            stretch=None,
            mono=(0, 2),
            name="recentExperiments",
        )
        self.recent_state = StateView(self.recent)
        recent.add(self.recent_state, 1)
        self.root.addWidget(recent, 1)

        self.session.connection_changed.connect(self.refresh)
        self.session.resources_changed.connect(self.refresh)
        self.session.experiments_changed.connect(self._fill_recent)
        # An empty list does not change on connect, but its empty state does (offline → none yet).
        self.session.connection_changed.connect(lambda *_: self._fill_recent())
        self.refresh()
        self._fill_recent()

    def retranslate(self) -> None:
        self.refresh()
        self.tiles.refresh(sample=False)
        self._fill_recent()

    def refresh(self) -> None:
        session = self.session
        self.badge.set_status(session.state.value)
        connected = session.state is not ConnectionState.DISCONNECTED
        grid = self.identity
        grid.set("dashboard.identity.url", session.url if connected else "—", mono=True)
        grid.set("dashboard.identity.backend", session.backend_version or "—")
        grid.set("dashboard.identity.client", __version__)
        grid.set(
            "dashboard.identity.auth",
            tr("dashboard.auth.token") if session.token else tr("dashboard.auth.none"),
        )
        latency = format_seconds(session.latency) if session.latency is not None else "—"
        grid.set("dashboard.identity.latency", latency)
        capabilities = session.capabilities
        fidelity = capabilities.get("fidelity")
        grid.set(
            "dashboard.identity.fidelity",
            tr(f"fidelity.{fidelity}") if fidelity in {"l0_only", "linux_lab"} else "—",
        )
        for key, capability in (("l1", "l1"), ("hybrid", "hybrid_tap")):
            value = capabilities.get(capability)
            if value is None:
                grid.set(f"dashboard.identity.{key}", "—")
            else:
                grid.set(
                    f"dashboard.identity.{key}",
                    tr("common.available") if value else tr("common.unavailable"),
                    tone="success" if value else "muted",
                )
        if not connected:
            self.hint.setText(tr("dashboard.disconnected_hint", version=__version__))
        elif session.problem is not None:
            self.hint.setText(f"{session.problem.title}: {session.problem.detail}")
        else:
            self.hint.setText("")
        self.hint.setVisible(bool(self.hint.text()))
        limits = session.limits()
        for key, catalog_key, render in LIMIT_ROWS:
            self.limits.set(catalog_key, render(limits[key]) if key in limits else "—")
            self.limits.values[catalog_key].setProperty("raw", limits.get(key))

    def _fill_recent(self) -> None:
        experiments = self.session.experiments[:RECENT_EXPERIMENTS]
        fill_table(
            self.recent,
            [
                (
                    item.get("experiment_id"),
                    item.get("scenario_id"),
                    item.get("topology_id"),
                    item.get("status"),
                    format_datetime(item.get("started_at")),
                )
                for item in experiments
            ],
            colors={3: "status"},
        )
        if experiments:
            self.recent_state.show_content()
        elif self.session.connected:
            self.recent_state.show_empty(
                Msg("dashboard.recent.empty"), Msg("dashboard.recent.empty_hint")
            )
        else:
            self.recent_state.show_empty(
                Msg("dashboard.recent.offline"), Msg("dashboard.recent.offline_hint")
            )
