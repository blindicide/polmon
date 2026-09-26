"""Deployment: deploy, destroy and reset, with admission errors and live resource counters."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from polmon.client.formatting import format_seconds
from polmon.client.local_backend import LOCAL_FIDELITY_MESSAGE
from polmon.client.pages import Context, Page
from polmon.client.pages.dashboard import ResourceTiles
from polmon.client.tasks import CancelToken, ProgressUpdate
from polmon.client.widgets import JsonTree, fill_table, make_table, muted, primary_button
from polmon.client.yamlmap import document_id

EDITOR = "__editor__"
# Measured creation cost on the development host (RESOURCE-BUDGET.md): about 0.25 s per L1
# namespace including its veth pair, negligible per L0 endpoint, plus a fixed setup part. Used as
# the ETA until this client has observed the backend's own deployment times.
SECONDS_PER_NAMESPACE = 0.25
SECONDS_BASE = 0.2


def baseline_deploy_seconds(estimate: dict[str, object] | None) -> float | None:
    if not estimate:
        return None
    namespaces = estimate.get("l1_namespaces")
    if not isinstance(namespaces, int):
        return None
    return SECONDS_BASE + SECONDS_PER_NAMESPACE * namespaces


class DeploymentPage(Page):
    key = "deployment"
    title = "Deployment"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.editor_source = ""
        self.editor_estimate: dict[str, object] | None = None
        self.seconds_per_endpoint: float | None = None

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Topology"))
        self.target = QComboBox()
        self.target.setAccessibleName("Topology to deploy")
        self.target.setMinimumWidth(260)
        self.target.currentIndexChanged.connect(self.refresh_actions)
        controls.addWidget(self.target)
        self.deploy_button = primary_button("Deploy")
        self.deploy_button.setToolTip(
            "Admit and deploy the selected topology (Ctrl+D). Cancel rolls the deployment back."
        )
        self.destroy_button = QPushButton("Destroy")
        self.destroy_button.setObjectName("danger")
        self.destroy_button.setToolTip("Tear down the selected deployment (Ctrl+Shift+D)")
        self.reset_button = QPushButton("Reset all")
        self.reset_button.setObjectName("danger")
        self.reset_button.setToolTip(
            "Tear down every deployment; definitions and reports are kept (Ctrl+Shift+R)"
        )
        self.deploy_button.clicked.connect(self.deploy)
        self.destroy_button.clicked.connect(self.destroy)
        self.reset_button.clicked.connect(self.reset)
        controls.addWidget(self.deploy_button)
        controls.addWidget(self.destroy_button)
        controls.addStretch(1)
        controls.addWidget(self.reset_button)
        self.root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        upper = QSplitter()
        table_box = QGroupBox("Deployments")
        table_layout = QVBoxLayout(table_box)
        self.table = make_table(
            ("Topology", "State", "Backend", "Endpoints", "Namespaces", "Deploy time"), stretch=0
        )
        self.table.itemSelectionChanged.connect(self._selected)
        table_layout.addWidget(self.table)
        self.empty = muted("No deployments. Choose a topology and press Deploy.")
        table_layout.addWidget(self.empty)
        upper.addWidget(table_box)
        detail_box = QGroupBox("Selected deployment")
        detail_layout = QVBoxLayout(detail_box)
        self.owned = QListWidget()
        self.owned.setToolTip("Resources owned by this deployment (namespaces, links, endpoints)")
        self.details = JsonTree()
        detail_layout.addWidget(muted("Owned resources"))
        detail_layout.addWidget(self.owned, 1)
        detail_layout.addWidget(muted("Backend details"))
        detail_layout.addWidget(self.details, 2)
        upper.addWidget(detail_box)
        upper.setSizes([560, 420])
        splitter.addWidget(upper)
        counters = QGroupBox("Live resource counters")
        counters_layout = QVBoxLayout(counters)
        self.tiles = ResourceTiles(context)
        counters_layout.addWidget(self.tiles)
        splitter.addWidget(counters)
        splitter.setSizes([420, 260])
        self.root.addWidget(splitter, 1)

        self.session.topologies_changed.connect(self._refresh_targets)
        self.session.deployments_changed.connect(self._refresh_table)
        self._refresh_targets()
        self._refresh_table()

    # -- views --------------------------------------------------------------------------------

    def _refresh_targets(self) -> None:
        current = self.target.currentData()
        self.target.blockSignals(True)
        self.target.clear()
        editor_id = document_id(self.editor_source) if self.editor_source else None
        if editor_id:
            self.target.addItem(f"{editor_id}  (from the topology editor)", EDITOR)
        for item in self.session.backend_topologies:
            topology_id = str(item.get("topology_id"))
            state = "deployed" if item.get("deployed") else "loaded"
            estimate = item.get("resources") or {}
            endpoints = estimate.get("endpoint_count") if isinstance(estimate, dict) else "?"
            self.target.addItem(f"{topology_id}  ({state}, {endpoints} endpoints)", topology_id)
        index = self.target.findData(current)
        self.target.setCurrentIndex(max(0, index))
        self.target.blockSignals(False)
        self.refresh_actions()

    def _refresh_table(self) -> None:
        deployments = self.session.deployments
        estimates = {
            str(item.get("topology_id")): item.get("resources") or {}
            for item in self.session.backend_topologies
        }
        rows = []
        for topology_id, deployment in sorted(deployments.items()):
            estimate = estimates.get(topology_id, {})
            rows.append(
                (
                    topology_id,
                    deployment.get("state"),
                    deployment.get("backend"),
                    estimate.get("endpoint_count"),
                    estimate.get("l1_namespaces"),
                    format_seconds(deployment.get("deployment_seconds")),
                )
            )
            seconds = deployment.get("deployment_seconds")
            count = estimate.get("endpoint_count")
            if isinstance(seconds, int | float) and isinstance(count, int) and count:
                self.seconds_per_endpoint = seconds / count
        selected = self._selected_id() or self._target()[0]
        self.table.blockSignals(True)
        fill_table(self.table, rows, colors={1: "state"}, data=[row[0] for row in rows])
        self.empty.setVisible(not rows)
        ids = [values[0] for values in rows]
        if rows:
            self.table.selectRow(ids.index(selected) if selected in ids else 0)
        self.table.blockSignals(False)
        self._selected()
        self.refresh_actions()

    def _selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else None

    def _selected(self) -> None:
        topology_id = self._selected_id()
        deployment = self.session.deployments.get(topology_id or "")
        self.owned.clear()
        if deployment is None:
            self.details.clear()
            return
        for resource in deployment.get("resources") or []:
            self.owned.addItem(str(resource))
        self.details.load(deployment.get("details") or {}, expand_depth=2)
        index = self.target.findData(topology_id)
        if index >= 0:
            self.target.setCurrentIndex(index)

    def _target(self) -> tuple[str | None, str | None]:
        """(topology id, source to load first or None)."""
        data = self.target.currentData()
        if data == EDITOR:
            return document_id(self.editor_source), self.editor_source
        return (str(data) if data else None), None

    def refresh_actions(self) -> None:
        connected = self.session.connected and not self.context.busy
        topology_id, _ = self._target()
        deployed = self.session.deployed(topology_id)
        self.deploy_button.setEnabled(connected and bool(topology_id) and not deployed)
        self.destroy_button.setEnabled(connected and deployed)
        self.reset_button.setEnabled(connected and bool(self.session.deployments))

    # -- operations ---------------------------------------------------------------------------

    def deploy(self) -> None:
        topology_id, source = self._target()
        if not topology_id:
            return
        client = self.session.client()
        estimate = next(
            (
                item.get("resources")
                for item in self.session.backend_topologies
                if item.get("topology_id") == topology_id
            ),
            None,
        )
        if source is not None and self.editor_estimate is not None:
            estimate = self.editor_estimate
        if self.session.l0_only and isinstance(estimate, dict) and (
            int(estimate.get("l1_namespaces") or 0) > 0
            or int(estimate.get("l2_virtual_machines") or 0) > 0
        ):
            self.banner.show_message(
                "Local backend — L0 only",
                LOCAL_FIDELITY_MESSAGE,
                "warning",
            )
            self.session.log(f"Deployment refused — {LOCAL_FIDELITY_MESSAGE}", "warning")
            return
        endpoints = estimate.get("endpoint_count") if isinstance(estimate, dict) else None
        expected = (
            self.seconds_per_endpoint * endpoints
            if self.seconds_per_endpoint and isinstance(endpoints, int)
            else baseline_deploy_seconds(estimate if isinstance(estimate, dict) else None)
        )

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            steps = 2 if source is not None else 1
            identifier = topology_id
            if source is not None:
                report(ProgressUpdate(0, steps, "loading the definition"))
                identifier = str(client.load_topology(source)["topology_id"])
                token.raise_if_cancelled()
            report(ProgressUpdate(steps - 1, steps, f"deploying {identifier}", eta=expected))
            result = client.deploy(identifier)
            result.setdefault("topology_id", identifier)
            if token.cancelled:  # the UI has moved on: honour "cancel and roll back"
                client.destroy(identifier)
                return {"rolled_back": identifier}
            return result

        self.context.run(
            f"Deploy {topology_id}",
            work,
            on_success=self._deployed,
            banner=self.banner,
            operation=True,
        )

    def _deployed(self, result: object) -> None:
        if isinstance(result, dict) and result.get("topology_id"):
            self.session.known_topologies.add(str(result["topology_id"]))
        if isinstance(result, dict):
            seconds = format_seconds(result.get("deployment_seconds"))
            self.session.log(
                f"Deployment {result.get('topology_id')} is {result.get('state')} ({seconds})"
            )
        self.context.navigate("refresh")

    def destroy(self) -> None:
        topology_id, _ = self._target()
        if not topology_id or not self.session.deployed(topology_id):
            return
        answer = QMessageBox.question(
            self,
            "Destroy deployment",
            f"Tear down deployment '{topology_id}'? Its namespaces, links and endpoints are "
            "removed; the topology definition and reports are kept.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        client = self.session.client()
        self.context.run(
            f"Destroy {topology_id}",
            lambda token, report: client.destroy(topology_id),
            on_success=lambda result: self.context.navigate("refresh"),
            banner=self.banner,
            operation=True,
            cancellable=False,
        )

    def reset(self) -> None:
        count = len(self.session.deployments)
        answer = QMessageBox.question(
            self,
            "Reset environment",
            f"Tear down all {count} deployment(s) on the backend? Loaded definitions and "
            "reports are kept so experiments can be repeated.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.reset_now()

    def reset_now(self) -> None:
        client = self.session.client()
        self.context.run(
            "Reset environment",
            lambda token, report: client.reset_all(),
            on_success=self._reset_done,
            banner=self.banner,
            operation=True,
            cancellable=False,
        )

    def _reset_done(self, result: object) -> None:
        if isinstance(result, dict):
            self.session.log(
                f"Environment reset: {result.get('deployments_destroyed')} deployment(s) destroyed"
            )
        self.context.navigate("refresh")

    def activated(self, argument: object = None) -> None:
        if isinstance(argument, dict) and "deploy_topology" in argument:
            index = self.target.findData(argument["deploy_topology"])
            if index >= 0:
                self.target.setCurrentIndex(index)
                if self.deploy_button.isEnabled():
                    self.deploy()
            return
        if isinstance(argument, dict) and "deploy_source" in argument:
            self.editor_source = str(argument["deploy_source"])
            estimate = argument.get("resources")
            self.editor_estimate = estimate if isinstance(estimate, dict) else None
            self._refresh_targets()
            self.target.setCurrentIndex(max(0, self.target.findData(EDITOR)))
            if argument.get("start", True) and self.deploy_button.isEnabled():
                self.deploy()
