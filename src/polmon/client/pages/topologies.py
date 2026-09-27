"""Topologies: library, YAML editor, backend validation and structural inspection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from polmon.client import i18n, theme
from polmon.client.api import ApiClientError
from polmon.client.errors import error_message, yaml_problem
from polmon.client.i18n import Msg, bind_fn, bind_tip, tr
from polmon.client.pages import Context, Page, default_folder, write_document
from polmon.client.widgets import (
    RAW_ROLE,
    Card,
    StateView,
    StatusBadge,
    YamlEditor,
    button,
    danger_button,
    fill_table,
    make_table,
    monospace_font,
    muted,
    primary_button,
    tint,
)
from polmon.client.yamlmap import document_id, locate, reason_line

MAX_DOCUMENT_BYTES = 2_000_000


def problem_rows(source: str, error: ApiClientError) -> list[tuple[object, object, object]]:
    """(line, location, message) for each validation problem of a 422 answer."""
    details = error.details if isinstance(error.details, dict) else {}
    rows: list[tuple[object, object, object]] = []
    errors = details.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                location = str(item.get("location") or "")
                rows.append(
                    (locate(source, location), location or Msg("validation.document"),
                     error_message(item))
                )
    elif "problem_code" in details or isinstance(details.get("reason"), str):
        line = details.get("line")
        if not isinstance(line, int) and isinstance(details.get("reason"), str):
            line = reason_line(str(details["reason"]))
        rows.append((line, Msg("validation.yaml_syntax"), yaml_problem(details)))
    else:
        from polmon.client.errors import backend_message

        rows.append(
            (None, Msg("validation.document"),
             backend_message(error.message_code, error.params, str(error).split(": ", 1)[-1]))
        )
    return rows


class DocumentLibrary(Card):
    """YAML files of one folder; double-click (or Enter) opens one."""

    def __init__(self, title: str, key: str, page: Page) -> None:
        super().__init__(title, name=f"{key}Library")
        self.key = key
        self.page = page
        self.folder_label = muted()
        self.folder_label.setObjectName("caption")
        self.list = QListWidget()
        self.list.setObjectName(f"{key}Files")
        self.list.setFont(monospace_font())
        self.list.itemActivated.connect(
            lambda item: page.open_path(Path(item.data(Qt.ItemDataRole.UserRole)))
        )
        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE["sm"])
        self.open_button = button("library.open", tip="library.open.tip", name="openFile")
        self.folder_button = button("library.folder", "quiet", tip="library.folder.tip",
                                    name="chooseFolder")
        self.open_button.clicked.connect(page.open_dialog)
        self.folder_button.clicked.connect(self.choose_folder)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch(1)
        self.add(self.folder_label)
        self.add(self.list, 1)
        self.body.addLayout(buttons)
        stored = page.context.settings.value(f"folders/{key}", "")
        self.set_folder(Path(str(stored)) if stored else default_folder(key))

    def choose_folder(self) -> None:
        folder = self.page.context.ask_folder(self, "library.folder.dialog", self.key)
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

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.path: Path | None = None
        self.saved_source = ""
        self.result: dict[str, object] | None = None
        self.validated_source: str | None = None
        self.problem_rows: list[tuple[object, object, object]] = []
        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.setInterval(700)
        self._auto.timeout.connect(lambda: self.validate(quiet=True))

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        # -- left: library and backend-loaded topologies
        left = QSplitter(Qt.Orientation.Vertical)
        left.setChildrenCollapsible(False)
        self.library = DocumentLibrary("library.title", "topologies", self)
        left.addWidget(self.library)
        loaded_card = Card("topologies.loaded", name="loaded")
        self.loaded = QListWidget()
        self.loaded.setObjectName("loadedTopologies")
        self.loaded.setFont(monospace_font())
        bind_tip(self.loaded, "topologies.loaded.tip")
        self.loaded.itemActivated.connect(self.open_loaded)
        self.loaded_state = StateView(self.loaded)
        loaded_card.add(self.loaded_state, 1)
        self.unload_button = danger_button(
            "topologies.unload", tip="topologies.unload.tip", name="unloadButton"
        )
        self.unload_button.clicked.connect(self.unload_selected)
        self.loaded.itemSelectionChanged.connect(self.refresh_actions)
        loaded_card.add_action(self.unload_button)
        left.addWidget(loaded_card)
        left.setSizes([420, 260])
        splitter.addWidget(left)

        # -- centre: editor
        editor_card = Card(name="editor")
        header = QHBoxLayout()
        self.document_label = QLabel()
        self.document_label.setObjectName("cardTitle")
        self.document_name: str | None = None
        self.badge = StatusBadge()
        header.addWidget(self.document_label, 1)
        self.save_button = button("editor.save_as", "quiet", tip="editor.save_as.tip",
                                  name="saveAs")
        header.addWidget(self.save_button)  # document commands sit with the document name
        header.addWidget(self.badge)
        editor_card.body.addLayout(header)
        self.editor = YamlEditor()
        self.editor.setObjectName("topologyEditor")
        editor_card.add(self.editor, 1)
        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE["sm"])
        self.validate_button = button(
            "editor.validate", tip="topologies.validate.tip", name="validateButton"
        )
        self.load_button = button("topologies.load", tip="topologies.load.tip", name="loadButton")
        self.deploy_button = primary_button(
            "topologies.deploy", tip="topologies.deploy.tip", name="deployTopology"
        )
        self.validate_button.clicked.connect(lambda: self.validate(quiet=False))
        self.load_button.clicked.connect(self.load_to_backend)
        self.deploy_button.clicked.connect(self.deploy)
        self.save_button.clicked.connect(self.save_as)
        for widget in (self.deploy_button, self.load_button, self.validate_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        editor_card.body.addLayout(actions)
        splitter.addWidget(editor_card)

        # -- right: inspection
        inspect_card = Card("topologies.inspection", name="inspection")
        self.tabs = QTabWidget()
        self.tabs.setObjectName("topologyTabs")
        self.summary = make_table(
            ("column.property", "column.value", "column.admission"), stretch=1, sortable=False,
            name="topologySummary",
        )
        self.nodes = QTreeWidget()
        self.nodes.setObjectName("topologyNodes")
        bind_fn(
            self.nodes,
            lambda tree: tree.setHeaderLabels(
                [tr(key) for key in (
                    "column.node_interface", "column.class", "column.network", "column.mac",
                    "column.ipv4", "column.notes",
                )]
            ),
            tag="headers",
        )
        self.nodes.setAlternatingRowColors(True)
        self.networks = make_table(
            ("column.network", "column.subnet", "column.interfaces", "column.members"),
            stretch=3, mono=(0, 1), name="topologyNetworks",
        )
        self.problems = make_table(
            ("column.line", "column.location", "column.problem"), stretch=2, mono=(1,),
            name="topologyProblems",
        )
        self.problems.setWordWrap(True)
        self.problems.itemActivated.connect(self._goto_problem)
        for widget in (self.summary, self.nodes, self.networks, self.problems):
            self.tabs.addTab(widget, "")
        self.summary_state = StateView(self.tabs)
        inspect_card.add(self.summary_state, 1)
        splitter.addWidget(inspect_card)
        splitter.setSizes([220, 420, 600])
        for index, factor in enumerate((0, 2, 3)):  # growth goes to the editor and inspection
            splitter.setStretchFactor(index, factor)
        self.root.addWidget(splitter, 1)

        QShortcut(QKeySequence("Ctrl+Shift+V"), self, lambda: self.validate(quiet=False))
        self.session.topologies_changed.connect(self._refresh_loaded)
        self.session.resources_changed.connect(self._refresh_summary)
        self.retranslate()
        self.refresh_actions()
        # Connected last: the editor signals while the page is still being built.
        self.editor.textChanged.connect(self._edited)

    def retranslate(self) -> None:
        count = len(self.problem_rows)
        titles = (
            tr("topologies.tab.summary"),
            tr("topologies.tab.nodes"),
            tr("topologies.tab.networks"),
            tr("editor.tab.problems_count", count=count) if count else tr("editor.tab.problems"),
        )
        for index, title in enumerate(titles):
            self.tabs.setTabText(index, title)
        self._update_label()
        self._refresh_summary()
        self._refresh_loaded()
        if self.problem_rows:
            fill_table(self.problems, self.problem_rows)
        self._update_state()

    def _update_state(self) -> None:
        if self.result or self.problem_rows:
            self.summary_state.show_content()
        elif self.source().strip():
            self.summary_state.show_empty(Msg("topologies.not_validated"),
                                          Msg("topologies.not_validated_hint"))
        else:
            self.summary_state.show_empty(Msg("topologies.no_document"),
                                          Msg("topologies.no_document_hint"))

    # -- documents ----------------------------------------------------------------------------

    def open_dialog(self) -> None:
        path = self.context.ask_open(self, "topologies.open.dialog", "topologies")
        if path is not None:
            self.open_path(path)

    def open_path(self, path: Path) -> None:
        try:
            if path.stat().st_size > MAX_DOCUMENT_BYTES:
                self.banner.show_message(
                    Msg("problem.too_large.title"),
                    Msg("editor.too_large", name=path.name),
                    "danger",
                )
                return
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.path = path
        self.saved_source = text
        self.set_source(text, path.name)
        self.session.log(Msg("log.opened", kind=Msg("document.topology"), path=path))

    def set_source(self, text: str, name: str | None) -> None:
        self.document_name = name
        self.editor.setPlainText(text)
        self._update_label()
        self.validate(quiet=True)

    def source(self) -> str:
        return self.editor.toPlainText()

    def open_loaded(self, item: QListWidgetItem) -> None:
        topology_id = str(item.data(Qt.ItemDataRole.UserRole))
        client = self.session.client()
        self.context.run(
            Msg("operation.fetch_topology", topology=topology_id),
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
            Msg("operation.unload", topology=topology_id),
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
            str(result.get("normalized_yaml") or ""),
            tr("topologies.backend_copy", topology=result["topology_id"]),
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
        path = self.context.ask_save(self, "topologies.save.dialog", suggested, "yaml")
        if path is not None and write_document(self, path, self.source(), "topology"):
            self.path = path
            self.document_name = path.name
            self.saved_source = self.source()
            self._update_label()

    def _update_label(self) -> None:
        name = self.path.name if self.path else self.document_name
        dirty = self.path is not None and self.source() != self.saved_source
        text = name or tr("topologies.untitled")
        self.document_label.setText(f"{text} •" if dirty else text)
        self.document_label.setToolTip(
            tr("editor.unsaved") if dirty else str(self.path or text)
        )

    def _edited(self) -> None:
        self.editor.set_error_line(None)
        if self.path is not None:
            self._update_label()
        if self.validated_source is not None and self.source() != self.validated_source:
            self.badge.set_status("modified")
        if self.session.connected and self.source().strip():
            self._auto.start()
        self._update_state()
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
                    Msg("common.not_connected"), Msg("topologies.validate.offline"), "warning"
                )
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.validate_topology"),
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
            Msg("operation.load_topology"),
            lambda token, report: client.load_topology(source),
            on_success=lambda result: self._loaded(source, result),  # type: ignore[arg-type]
            on_failure=lambda error: self._show_failure(source, error),
            banner=self.banner,
        )

    def _loaded(self, source: str, result: dict[str, object]) -> None:
        self.session.known_topologies.add(str(result.get("topology_id")))
        self._show_result(source, result)
        self.session.log(Msg("log.topology_loaded", topology=result.get("topology_id")))
        self.context.navigate("refresh")

    def deploy(self) -> None:
        self.context.navigate(
            "deployment",
            {
                "deploy_source": self.source(),
                "resources": (self.result or {}).get("resources"),
            },
        )

    # -- results ------------------------------------------------------------------------------

    def _show_failure(self, source: str, error: BaseException) -> None:
        if source != self.source():
            return
        if not isinstance(error, ApiClientError) or error.status != 422:
            return
        rows = problem_rows(source, error)
        self.result = None
        self.validated_source = source
        self.problem_rows = rows
        fill_table(self.problems, rows)
        self.problems.resizeRowsToContents()
        self.problems.setProperty("count", len(rows))
        self.retranslate()
        self.tabs.setCurrentWidget(self.problems)
        self.badge.set_status("invalid")
        first = next((line for line, _, _ in rows if isinstance(line, int)), None)
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
        self.problem_rows = []
        self.problems.setRowCount(0)
        self.nodes.clear()
        self.networks.setRowCount(0)
        if result:
            self._fill_structure(result)
            if self.tabs.currentWidget() is self.problems:
                self.tabs.setCurrentWidget(self.summary)
        self.retranslate()
        self.refresh_actions()

    def _fill_structure(self, result: dict[str, object]) -> None:
        topology = result.get("topology") or {}
        assert isinstance(topology, dict)
        members: dict[str, list[str]] = {}
        mono = monospace_font()
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
            parent.setFont(0, mono)
            tint(parent, "info" if node["class"] == "l0" else "success", 1)
            for interface in node.get("interfaces") or []:
                child = QTreeWidgetItem(
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
                for column in (0, 2, 3, 4):
                    child.setFont(column, mono)
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

        def fit(requested: int, limit_key: str, active_key: str) -> tuple[str, str]:
            if limit_key not in limits:
                return "—", ""
            limit = int(limits[limit_key])  # type: ignore[arg-type]
            active = 0 if deployed_here else int(snapshot.get(active_key) or 0)
            free = limit - active
            verdict = "fits" if requested <= free else "exceeds"
            return tr(f"topologies.fit.{verdict}", free=free), verdict

        memory = int(estimate.get("memory_mb") or 0)
        available = snapshot.get("available_memory_bytes")
        reserve = int(limits.get("memory_safety_threshold_mb") or 0)
        memory_fit: tuple[str, str] = ("—", "")
        if isinstance(available, int) and limits:
            spare = available // 1_048_576 - reserve
            verdict = "fits" if memory <= spare else "exceeds"
            memory_fit = (tr(f"topologies.fit.memory_{verdict}", spare=spare), verdict)
        l2 = estimate.get("l2_virtual_machines")
        rows = [
            ("summary.topology", result.get("topology_id"), ("", "")),
            ("summary.networks", len(topology.get("networks") or []), ("", "")),
            (
                "summary.endpoints",
                estimate.get("endpoint_count"),
                fit(int(estimate.get("endpoint_count") or 0), "max_endpoint_count",
                    "active_endpoints"),
            ),
            ("summary.l0", estimate.get("l0_endpoints"), ("", "")),
            (
                "summary.l1",
                estimate.get("l1_namespaces"),
                fit(int(estimate.get("l1_namespaces") or 0), "max_active_namespaces",
                    "active_namespaces"),
            ),
            (
                "summary.l2",
                l2,
                (tr("topologies.fit.unsupported"), "exceeds") if l2 else ("", ""),
            ),
            ("summary.memory", f"{memory} MiB", memory_fit),
            ("summary.cpu", f"{estimate.get('cpu_millicores')} mCPU", ("", "")),
            ("summary.disk", f"{estimate.get('disk_mb')} MiB", ("", "")),
            (
                "summary.deployed",
                tr("common.yes") if deployed_here else tr("common.no"),
                ("", ""),
            ),
        ]
        fill_table(self.summary, [(tr(key), value, verdict[0]) for key, value, verdict in rows])
        for row, (key, _, (_, verdict)) in enumerate(rows):
            item = self.summary.item(row, 2)
            first = self.summary.item(row, 0)
            if first is not None:
                first.setData(Qt.ItemDataRole.UserRole, key)
            if item is not None:
                item.setData(RAW_ROLE, verdict or None)
            if item is not None and verdict:
                bad = verdict == "exceeds"
                tint(item, "danger" if bad else "success")
                item.setText(f"{theme.STATUS_GLYPHS['danger' if bad else 'success']} "
                             f"{item.text()}")

    def _refresh_loaded(self) -> None:
        self.loaded.clear()
        for item in self.session.backend_topologies:
            topology_id = str(item.get("topology_id"))
            marker = f"   ● {tr('status.deployed')}" if item.get("deployed") else ""
            entry = QListWidgetItem(f"{topology_id}{marker}")
            entry.setData(Qt.ItemDataRole.UserRole, topology_id)
            entry.setToolTip(
                tr(
                    "topologies.loaded.summary",
                    nodes=i18n.tr_n("count.nodes", int(item.get("node_count") or 0)),
                    networks=i18n.tr_n("count.networks", int(item.get("network_count") or 0)),
                )
            )
            if item.get("deployed"):
                tint(entry, "success")
            self.loaded.addItem(entry)
        if self.session.backend_topologies:
            self.loaded_state.show_content()
        elif self.session.connected:
            self.loaded_state.show_empty(Msg("topologies.loaded.empty"),
                                         Msg("topologies.loaded.empty_hint"))
        else:
            self.loaded_state.show_empty(Msg("common.offline"), Msg("common.offline_hint"))
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
