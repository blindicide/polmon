"""Topologies: library, YAML editor, backend validation and structural inspection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from polmon.client import theme
from polmon.client.api import ApiClientError
from polmon.client.pages import Context, Page, default_folder, write_document
from polmon.client.widgets import (
    StatusBadge,
    YamlEditor,
    fill_table,
    make_table,
    muted,
    primary_button,
)
from polmon.client.yamlmap import document_id, locate, reason_line

MAX_DOCUMENT_BYTES = 2_000_000


class DocumentLibrary(QGroupBox):
    """YAML files of one folder; double-click (or Enter) opens one."""

    def __init__(self, title: str, key: str, page: Page) -> None:
        super().__init__(title)
        self.key = key
        self.page = page
        layout = QVBoxLayout(self)
        self.folder_label = muted()
        self.list = QListWidget()
        self.list.itemActivated.connect(
            lambda item: page.open_path(Path(item.data(Qt.ItemDataRole.UserRole)))
        )
        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open file…")
        self.folder_button = QPushButton("Folder…")
        self.open_button.clicked.connect(page.open_dialog)
        self.folder_button.clicked.connect(self.choose_folder)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.folder_button)
        layout.addWidget(self.folder_label)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        stored = page.context.settings.value(f"folders/{key}", "")
        self.set_folder(Path(str(stored)) if stored else default_folder(key))

    def choose_folder(self) -> None:
        folder = self.page.context.ask_folder(self, "Choose a folder of YAML documents", self.key)
        if folder is not None:
            self.set_folder(folder)

    def set_folder(self, folder: Path) -> None:
        self.folder = folder
        self.folder_label.setText(str(folder))
        self.folder_label.setToolTip(str(folder))
        self.list.clear()
        try:
            paths = sorted(path for path in folder.iterdir() if path.suffix in {".yml", ".yaml"})
        except OSError:
            paths = []
        for path in paths[:500]:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.list.addItem(item)


class TopologiesPage(Page):
    key = "topologies"
    title = "Topologies"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.path: Path | None = None
        self.saved_source = ""
        self.result: dict[str, object] | None = None
        self.validated_source: str | None = None
        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.setInterval(700)
        self._auto.timeout.connect(lambda: self.validate(quiet=True))

        splitter = QSplitter()
        # -- left: library and backend-loaded topologies
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.library = DocumentLibrary("Library", "topologies", self)
        left_layout.addWidget(self.library, 3)
        loaded_box = QGroupBox("Loaded on backend")
        loaded_layout = QVBoxLayout(loaded_box)
        self.loaded = QListWidget()
        self.loaded.setToolTip("Double-click to open the backend's normalized copy")
        self.loaded.itemActivated.connect(self.open_loaded)
        loaded_layout.addWidget(self.loaded)
        self.unload_button = QPushButton("Unload")
        self.unload_button.setToolTip(
            "Remove the selected definition from the backend (it must not be deployed)"
        )
        self.unload_button.clicked.connect(self.unload_selected)
        self.loaded.itemSelectionChanged.connect(self.refresh_actions)
        loaded_layout.addWidget(self.unload_button)
        left_layout.addWidget(loaded_box, 2)
        splitter.addWidget(left)

        # -- centre: editor
        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.document_label = QLabel("Untitled topology")
        self.badge = StatusBadge()
        header.addWidget(self.document_label, 1)
        header.addWidget(self.badge)
        centre_layout.addLayout(header)
        self.editor = YamlEditor()
        self.editor.setAccessibleName("Topology YAML editor")
        self.editor.textChanged.connect(self._edited)
        centre_layout.addWidget(self.editor, 1)
        actions = QHBoxLayout()
        self.validate_button = QPushButton("Validate")
        self.validate_button.setToolTip("Validate on the backend (Ctrl+Shift+V)")
        self.load_button = QPushButton("Load to backend")
        self.load_button.setToolTip("Store this definition on the backend without deploying")
        self.deploy_button = primary_button("Deploy…")
        self.deploy_button.setToolTip("Load and deploy this topology (Ctrl+D)")
        self.save_button = QPushButton("Save as…")
        self.validate_button.clicked.connect(lambda: self.validate(quiet=False))
        self.load_button.clicked.connect(self.load_to_backend)
        self.deploy_button.clicked.connect(self.deploy)
        self.save_button.clicked.connect(self.save_as)
        for button in (self.validate_button, self.load_button, self.deploy_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        centre_layout.addLayout(actions)
        splitter.addWidget(centre)

        # -- right: inspection
        self.tabs = QTabWidget()
        self.summary = make_table(("Property", "Value", "Admission"), stretch=1)
        self.nodes = QTreeWidget()
        self.nodes.setHeaderLabels(["Node / interface", "Class", "Network", "MAC", "IPv4", "Notes"])
        self.nodes.setAlternatingRowColors(True)
        self.networks = make_table(("Network", "IPv4 subnet", "Interfaces", "Members"), stretch=3)
        self.problems = make_table(("Line", "Location", "Problem"), stretch=2)
        self.problems.setWordWrap(True)
        self.problems.itemActivated.connect(self._goto_problem)
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.nodes, "Nodes")
        self.tabs.addTab(self.networks, "Networks")
        self.tabs.addTab(self.problems, "Problems")
        splitter.addWidget(self.tabs)
        splitter.setSizes([210, 430, 470])
        splitter.setStretchFactor(1, 1)
        self.root.addWidget(splitter, 1)

        QShortcut(QKeySequence("Ctrl+Shift+V"), self, lambda: self.validate(quiet=False))
        self.session.topologies_changed.connect(self._refresh_loaded)
        self.session.resources_changed.connect(self._refresh_summary)
        self.refresh_actions()

    # -- documents ----------------------------------------------------------------------------

    def open_dialog(self) -> None:
        path = self.context.ask_open(self, "Open topology", "topologies")
        if path is not None:
            self.open_path(path)

    def open_path(self, path: Path) -> None:
        try:
            if path.stat().st_size > MAX_DOCUMENT_BYTES:
                self.banner.show_message(
                    "Document too large", f"{path.name} exceeds the 2 MB document limit.", "danger"
                )
                return
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.path = path
        self.saved_source = text
        self.set_source(text, path.name)
        self.session.log(f"Opened topology {path}")

    def set_source(self, text: str, label: str) -> None:
        self.editor.setPlainText(text)
        self.document_label.setText(label)
        self.document_label.setToolTip(str(self.path or label))
        self.validate(quiet=True)

    def source(self) -> str:
        return self.editor.toPlainText()

    def open_loaded(self, item: QListWidgetItem) -> None:
        topology_id = str(item.data(Qt.ItemDataRole.UserRole))
        client = self.session.client()
        self.context.run(
            f"Fetch topology {topology_id}",
            lambda token, report: client.topology(topology_id),
            on_success=lambda result: self._opened_loaded(result),  # type: ignore[arg-type]
            banner=self.banner,
        )

    def unload_selected(self) -> None:
        item = self.loaded.currentItem()
        if item is None:
            return
        topology_id = str(item.data(Qt.ItemDataRole.UserRole))
        client = self.session.client()
        self.context.run(
            f"Unload topology {topology_id}",
            lambda token, report: client.unload_topology(topology_id),
            on_success=lambda result: self._unloaded(topology_id),
            banner=self.banner,
        )

    def _unloaded(self, topology_id: str) -> None:
        self.session.known_topologies.discard(topology_id)
        self.context.navigate("refresh")

    def _opened_loaded(self, result: dict[str, object]) -> None:
        self.path = None
        self.set_source(
            str(result.get("normalized_yaml") or ""), f"{result['topology_id']} " "(backend copy)"
        )

    def save(self) -> None:
        """Save to the opened file (Ctrl+S); ask for a path when there is none."""
        if self.path is None:
            self.save_as()
        elif write_document(self, self.path, self.source(), "topology"):
            self.saved_source = self.source()
            self._update_label()

    def save_as(self) -> None:
        suggested = (
            self.path.name if self.path else f"{document_id(self.source()) or 'topology'}.yml"
        )
        path = self.context.ask_save(self, "Save topology", suggested, "YAML (*.yml *.yaml)")
        if path is not None and write_document(self, path, self.source(), "topology"):
            self.path = path
            self.saved_source = self.source()
            self._update_label()

    def _update_label(self) -> None:
        name = self.path.name if self.path else self.document_label.text().rstrip(" •")
        dirty = self.path is not None and self.source() != self.saved_source
        self.document_label.setText(f"{name} •" if dirty else name)
        self.document_label.setToolTip("Unsaved changes" if dirty else str(self.path or name))

    def _edited(self) -> None:
        self.editor.set_error_line(None)
        if self.path is not None:
            self._update_label()
        if self.validated_source is not None and self.source() != self.validated_source:
            self.badge.set_status("modified")
        if self.session.connected and self.source().strip():
            self._auto.start()
        self.refresh_actions()

    # -- backend actions ----------------------------------------------------------------------

    def validate(self, *, quiet: bool) -> None:
        source = self.source()
        if not source.strip():
            self._show_result(None, None)
            return
        if not self.session.connected:
            if not quiet:
                self.banner.show_message(
                    "Not connected", "Connect to a backend to validate topologies.", "warning"
                )
            return
        client = self.session.client()
        self.context.run(
            "Validate topology",
            lambda token, report: client.validate_topology(source),
            on_success=lambda result: self._show_result(source, result),  # type: ignore[arg-type]
            on_failure=lambda error: self._show_failure(source, error),
            banner=None if quiet else self.banner,
            quiet=quiet,
        )

    def load_to_backend(self) -> None:
        source = self.source()
        client = self.session.client()
        self.context.run(
            "Load topology",
            lambda token, report: client.load_topology(source),
            on_success=lambda result: self._loaded(source, result),  # type: ignore[arg-type]
            on_failure=lambda error: self._show_failure(source, error),
            banner=self.banner,
        )

    def _loaded(self, source: str, result: dict[str, object]) -> None:
        self.session.known_topologies.add(str(result.get("topology_id")))
        self._show_result(source, result)
        self.session.log(f"Topology {result.get('topology_id')} loaded on the backend")
        self.context.navigate("refresh")

    def deploy(self) -> None:
        self.context.navigate("deployment", {"deploy_source": self.source()})

    # -- results ------------------------------------------------------------------------------

    def _show_failure(self, source: str, error: BaseException) -> None:
        if source != self.source():
            return
        if not isinstance(error, ApiClientError) or error.status != 422:
            return
        details = error.details if isinstance(error.details, dict) else {}
        rows = []
        errors = details.get("errors")
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict):
                    location = str(item.get("location") or "")
                    rows.append(
                        (locate(source, location), location or "document", item.get("message"))
                    )
        elif isinstance(details.get("reason"), str):
            reason = str(details["reason"])
            rows.append((reason_line(reason), "YAML syntax", reason.splitlines()[0]))
        else:
            message = str(error).split(": ", 1)[-1]
            rows.append((None, "document", message))
        self.result = None
        self.validated_source = source
        fill_table(self.problems, rows)
        self.problems.resizeRowsToContents()
        self.problems.setProperty("count", len(rows))
        self.tabs.setTabText(3, f"Problems ({len(rows)})")
        self.tabs.setCurrentWidget(self.problems)
        self.badge.set_status("invalid")
        first = next((line for line, _, _ in rows if line), None)
        self.editor.set_error_line(first)
        self.refresh_actions()

    def _goto_problem(self, item) -> None:  # noqa: ANN001
        line_item = self.problems.item(item.row(), 0)
        if line_item is not None and line_item.text().isdigit():
            line = int(line_item.text())
            self.editor.goto_line(line)
            self.editor.set_error_line(line)

    def _show_result(self, source: str | None, result: dict[str, object] | None) -> None:
        if source is not None and source != self.source():
            return  # stale: the document changed while validating
        self.result = result
        self.validated_source = source
        self.badge.set_status("valid" if result else "")
        self.problems.setRowCount(0)
        self.tabs.setTabText(3, "Problems")
        self.nodes.clear()
        self.networks.setRowCount(0)
        if result:
            self._fill_structure(result)
            if self.tabs.currentWidget() is self.problems:
                self.tabs.setCurrentWidget(self.summary)
        self._refresh_summary()
        self.refresh_actions()

    def _fill_structure(self, result: dict[str, object]) -> None:
        topology = result.get("topology") or {}
        assert isinstance(topology, dict)
        members: dict[str, list[str]] = {}
        for node in topology.get("nodes") or []:
            services = ", ".join(
                f"{item['id']} {item['protocol']}/{item['port']} ({item['implementation']})"
                for item in node.get("services") or []
            )
            resources = node.get("resources")
            notes = services or (
                f"{resources['memory_mb']} MiB, {resources['cpu_millicores']} mCPU"
                if isinstance(resources, dict)
                else ""
            )
            parent = QTreeWidgetItem(
                self.nodes, [node["id"], node["class"].upper(), "", "", "", notes]
            )
            parent.setForeground(1, theme.color("info" if node["class"] == "l0" else "success"))
            for interface in node.get("interfaces") or []:
                QTreeWidgetItem(
                    parent,
                    [
                        interface["id"],
                        "",
                        interface["network"],
                        interface["mac"],
                        str(interface["ipv4"]),
                        "",
                    ],
                )
                members.setdefault(interface["network"], []).append(node["id"])
        self.nodes.expandAll()
        for column in range(5):
            self.nodes.resizeColumnToContents(column)
        fill_table(
            self.networks,
            [
                (
                    network["id"],
                    network["ipv4_subnet"],
                    len(members.get(network["id"], [])),
                    ", ".join(members.get(network["id"], [])),
                )
                for network in topology.get("networks") or []
            ],
        )

    def _refresh_summary(self) -> None:
        result = self.result
        if not result:
            self.summary.setRowCount(0)
            return
        estimate = result.get("resources") or {}
        topology = result.get("topology") or {}
        assert isinstance(estimate, dict) and isinstance(topology, dict)
        limits = self.session.limits()
        snapshot = (self.session.resources or {}).get("snapshot") or {}
        assert isinstance(snapshot, dict)
        deployed_here = self.session.deployed(str(result.get("topology_id")))

        def fit(requested: int, limit_key: str, active_key: str) -> str:
            if limit_key not in limits:
                return "—"
            limit = int(limits[limit_key])  # type: ignore[arg-type]
            active = 0 if deployed_here else int(snapshot.get(active_key) or 0)
            free = limit - active
            return f"fits ({free} free)" if requested <= free else f"exceeds ({free} free)"

        memory = int(estimate.get("memory_mb") or 0)
        available = snapshot.get("available_memory_bytes")
        reserve = int(limits.get("memory_safety_threshold_mb") or 0)
        memory_fit = "—"
        if isinstance(available, int) and limits:
            spare = available // 1_048_576 - reserve
            memory_fit = (
                f"fits ({spare} MiB spare)" if memory <= spare else (f"exceeds ({spare} MiB spare)")
            )
        rows = [
            ("Topology", result.get("topology_id"), ""),
            ("Networks", len(topology.get("networks") or []), ""),
            (
                "Endpoints",
                estimate.get("endpoint_count"),
                fit(
                    int(estimate.get("endpoint_count") or 0),
                    "max_endpoint_count",
                    "active_endpoints",
                ),
            ),
            ("L0 synthetic endpoints", estimate.get("l0_endpoints"), ""),
            (
                "L1 namespaces",
                estimate.get("l1_namespaces"),
                fit(
                    int(estimate.get("l1_namespaces") or 0),
                    "max_active_namespaces",
                    "active_namespaces",
                ),
            ),
            (
                "L2 virtual machines",
                estimate.get("l2_virtual_machines"),
                "unsupported" if estimate.get("l2_virtual_machines") else "",
            ),
            ("Estimated memory", f"{memory} MiB", memory_fit),
            ("Estimated CPU", f"{estimate.get('cpu_millicores')} mCPU", ""),
            ("Estimated disk", f"{estimate.get('disk_mb')} MiB", ""),
            ("Deployed", "yes" if deployed_here else "no", ""),
        ]
        fill_table(self.summary, rows)
        for row, (_, _, verdict) in enumerate(rows):
            item = self.summary.item(row, 2)
            if item is not None and verdict:
                bad = verdict.startswith(("exceeds", "unsupported"))
                item.setForeground(theme.color("danger" if bad else "success"))

    def _refresh_loaded(self) -> None:
        self.loaded.clear()
        for item in self.session.backend_topologies:
            topology_id = str(item.get("topology_id"))
            marker = "  ● deployed" if item.get("deployed") else ""
            entry = QListWidgetItem(f"{topology_id}{marker}")
            entry.setData(Qt.ItemDataRole.UserRole, topology_id)
            entry.setToolTip(
                f"{item.get('node_count')} nodes, {item.get('network_count')} networks"
            )
            if item.get("deployed"):
                entry.setForeground(theme.color("success"))
            self.loaded.addItem(entry)
        self._refresh_summary()

    def refresh_actions(self) -> None:
        connected = self.session.connected
        has_text = bool(self.source().strip())
        self.validate_button.setEnabled(connected and has_text)
        self.load_button.setEnabled(connected and has_text)
        self.deploy_button.setEnabled(connected and has_text and not self.context.busy)
        self.save_button.setEnabled(has_text)
        self.loaded.setEnabled(connected)
        current = self.loaded.currentItem()
        deployed = current is not None and self.session.deployed(
            str(current.data(Qt.ItemDataRole.UserRole))
        )
        self.unload_button.setEnabled(connected and current is not None and not deployed)

    def activated(self, argument: object = None) -> None:
        if isinstance(argument, Path):
            self.open_path(argument)
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
