"""Deployment: deploy, destroy and reset, with admission errors and live resource counters."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QListWidget, QSplitter, QWidget

from polmon.client import theme
from polmon.client.errors import Problem
from polmon.client.formatting import format_seconds
from polmon.client.i18n import Msg, bind_tip, status_msg, tr
from polmon.client.pages import Context, Page
from polmon.client.pages.dashboard import ResourceTiles
from polmon.client.tasks import CancelToken, ProgressUpdate
from polmon.client.widgets import (
    Card,
    JsonTree,
    StateView,
    accessible,
    confirm,
    danger_button,
    fill_table,
    label,
    make_table,
    monospace_font,
    primary_button,
    section_label,
)
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


def fidelity_refusal() -> Problem:
    """The client-side L1/L2 refusal against an L0-only backend (same code as the backend's)."""
    return Problem(
        "problem.l0_only", Msg("backend.fidelity.l0_only"), message_code="fidelity.l0_only"
    )


class DeploymentPage(Page):
    key = "deployment"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.editor_source = ""
        self.editor_estimate: dict[str, object] | None = None
        self.seconds_per_endpoint: float | None = None

        target = Card("deployment.target", name="target")
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["sm"])
        row.addWidget(label("deployment.topology", name="fieldLabel"))
        self.target = QComboBox()
        self.target.setObjectName("deployTarget")
        accessible(self.target, "a11y.deploy_target")
        self.target.setMinimumWidth(280)
        self.target.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.target.setMinimumContentsLength(24)
        self.target.currentIndexChanged.connect(self.refresh_actions)
        row.addWidget(self.target, 2)
        self.deploy_button = primary_button(
            "deployment.deploy", tip="deployment.deploy.tip", name="deployButton"
        )
        self.destroy_button = danger_button(
            "deployment.destroy", tip="deployment.destroy.tip", name="destroyButton"
        )
        self.reset_button = danger_button(
            "deployment.reset", tip="deployment.reset.tip", name="resetButton"
        )
        self.deploy_button.clicked.connect(self.deploy)
        self.destroy_button.clicked.connect(self.destroy)
        self.reset_button.clicked.connect(self.reset)
        row.addWidget(self.deploy_button)
        row.addStretch(1)
        row.addWidget(self.destroy_button)
        row.addSpacing(theme.SPACE["lg"])
        row.addWidget(self.reset_button)
        target.body.addLayout(row)
        self.estimate = label(name="muted", wrap=True)
        target.add(self.estimate)
        self.root.addWidget(target)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        upper = QSplitter()
        upper.setChildrenCollapsible(False)
        table_card = Card("deployment.list", name="deployments")
        self.table = make_table(
            (
                "column.topology",
                "column.state",
                "column.backend",
                "column.endpoints",
                "column.namespaces",
                "column.deploy_time",
            ),
            stretch=None,
            mono=(0,),
            name="deploymentsTable",
        )
        self.table.itemSelectionChanged.connect(self._selected)
        self.table_state = StateView(self.table)
        table_card.add(self.table_state, 1)
        upper.addWidget(table_card)
        detail_card = Card("deployment.selected", name="selected")
        self.owned = QListWidget()
        self.owned.setObjectName("ownedResources")
        self.owned.setFont(monospace_font())
        bind_tip(self.owned, "deployment.owned.tip")
        self.details = JsonTree()
        self.details.setObjectName("deploymentDetails")
        detail_card.add(section_label("deployment.owned"))
        detail_card.add(self.owned, 1)
        detail_card.add(section_label("deployment.details"))
        detail_card.add(self.details, 2)
        upper.addWidget(detail_card)
        upper.setSizes([920, 360])
        splitter.addWidget(upper)
        counters = Card("deployment.counters", name="counters")
        self.tiles = ResourceTiles(context, compact=True)
        counters.add(self.tiles)
        splitter.addWidget(counters)
        splitter.setSizes([420, 250])
        self.root.addWidget(splitter, 1)

        self.session.topologies_changed.connect(self._refresh_targets)
        self.session.deployments_changed.connect(self._refresh_table)
        self._refresh_targets()
        self._refresh_table()

    def retranslate(self) -> None:
        self._refresh_targets()
        self._refresh_table()
        self.tiles.refresh(sample=False)

    # -- views --------------------------------------------------------------------------------

    def _refresh_targets(self) -> None:
        current = self.target.currentData()
        self.target.blockSignals(True)
        self.target.clear()
        editor_id = document_id(self.editor_source) if self.editor_source else None
        if editor_id:
            self.target.addItem(tr("deployment.target.editor", topology=editor_id), EDITOR)
        for item in self.session.backend_topologies:
            topology_id = str(item.get("topology_id"))
            estimate = item.get("resources") or {}
            endpoints = estimate.get("endpoint_count") if isinstance(estimate, dict) else "?"
            state = "deployed" if item.get("deployed") else "loaded"
            self.target.addItem(
                tr(f"deployment.target.{state}", topology=topology_id, endpoints=endpoints),
                topology_id,
            )
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
        if rows:
            self.table_state.show_content()
        elif self.session.connected:
            self.table_state.show_empty(
                Msg("deployment.empty"), Msg("deployment.empty_hint")
            )
        else:
            self.table_state.show_empty(Msg("common.offline"), Msg("common.offline_hint"))
        ids = [self._row_id(row) for row in range(self.table.rowCount())]
        if rows:
            self.table.selectRow(ids.index(selected) if selected in ids else 0)
        self.table.blockSignals(False)
        self._selected()
        self.refresh_actions()

    def _row_id(self, row: int) -> str | None:
        item = self.table.item(row, 0)
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def _selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self._row_id(rows[0].row()) if rows else None

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

    def _estimate(self, topology_id: str | None, source: str | None) -> dict[str, object] | None:
        if source is not None and self.editor_estimate is not None:
            return self.editor_estimate
        estimate = next(
            (
                item.get("resources")
                for item in self.session.backend_topologies
                if item.get("topology_id") == topology_id
            ),
            None,
        )
        return estimate if isinstance(estimate, dict) else None

    def refresh_actions(self) -> None:
        connected = self.session.connected and not self.context.busy
        topology_id, source = self._target()
        deployed = self.session.deployed(topology_id)
        self.deploy_button.setEnabled(connected and bool(topology_id) and not deployed)
        self.destroy_button.setEnabled(connected and deployed)
        self.reset_button.setEnabled(connected and bool(self.session.deployments))
        estimate = self._estimate(topology_id, source)
        if estimate:
            self.estimate.setText(
                tr(
                    "deployment.estimate",
                    endpoints=estimate.get("endpoint_count", "—"),
                    l0=estimate.get("l0_endpoints", "—"),
                    namespaces=estimate.get("l1_namespaces", "—"),
                    memory=estimate.get("memory_mb", "—"),
                )
            )
        elif not self.session.connected:
            self.estimate.setText(tr("deployment.hint_offline"))
        else:
            self.estimate.setText(tr("deployment.hint_choose"))

    # -- operations ---------------------------------------------------------------------------

    def deploy(self) -> None:
        topology_id, source = self._target()
        if not topology_id:
            return
        client = self.session.client()
        estimate = self._estimate(topology_id, source)
        if self.session.l0_only and isinstance(estimate, dict) and (
            int(estimate.get("l1_namespaces") or 0) > 0
            or int(estimate.get("l2_virtual_machines") or 0) > 0
        ):
            problem = fidelity_refusal()
            self.banner.show_problem(problem, "warning")
            self.session.log(Msg("log.refused", problem=problem.text()), "warning")
            return
        endpoints = estimate.get("endpoint_count") if isinstance(estimate, dict) else None
        expected = (
            self.seconds_per_endpoint * endpoints
            if self.seconds_per_endpoint and isinstance(endpoints, int)
            else baseline_deploy_seconds(estimate)
        )

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            steps = 2 if source is not None else 1
            identifier = topology_id
            if source is not None:
                report(ProgressUpdate(0, steps, tr("deployment.progress.loading")))
                identifier = str(client.load_topology(source)["topology_id"])
                token.raise_if_cancelled()
            report(
                ProgressUpdate(
                    steps - 1, steps, tr("deployment.progress.deploying", topology=identifier),
                    eta=expected,
                )
            )
            result = client.deploy(identifier)
            result.setdefault("topology_id", identifier)
            if token.cancelled:  # the UI has moved on: honour "cancel and roll back"
                client.destroy(identifier)
                return {"rolled_back": identifier}
            return result

        self.context.run(
            Msg("operation.deploy", topology=topology_id),
            work,
            on_success=self._deployed,
            banner=self.banner,
            operation=True,
            kind="deploy",
        )

    def _deployed(self, result: object) -> None:
        if isinstance(result, dict) and result.get("topology_id"):
            self.session.known_topologies.add(str(result["topology_id"]))
        if isinstance(result, dict) and result.get("rolled_back"):
            self.session.log(Msg("log.deploy.rolled_back", topology=result["rolled_back"]))
        elif isinstance(result, dict):
            self.session.log(
                Msg(
                    "log.deploy.done",
                    topology=result.get("topology_id"),
                    state=status_msg(result.get("state")),
                    duration=format_seconds(result.get("deployment_seconds")),
                )
            )
        self.context.navigate("refresh")

    def destroy(self) -> None:
        topology_id, _ = self._target()
        if not topology_id or not self.session.deployed(topology_id):
            return
        if not confirm(
            self,
            "deployment.destroy.confirm_title",
            Msg("deployment.destroy.confirm", topology=topology_id),
            "deployment.destroy.confirm_accept",
        ):
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.destroy", topology=topology_id),
            lambda token, report: client.destroy(topology_id),
            on_success=lambda result: self.context.navigate("refresh"),
            banner=self.banner,
            operation=True,
            cancellable=False,
            kind="destroy",
        )

    def reset(self) -> None:
        count = len(self.session.deployments)
        if not confirm(
            self,
            "deployment.reset.confirm_title",
            Msg("deployment.reset.confirm", count=count),
            "deployment.reset.confirm_accept",
        ):
            return
        self.reset_now()

    def reset_now(self) -> None:
        client = self.session.client()
        self.context.run(
            Msg("operation.reset"),
            lambda token, report: client.reset_all(),
            on_success=self._reset_done,
            banner=self.banner,
            operation=True,
            cancellable=False,
            kind="reset",
        )

    def _reset_done(self, result: object) -> None:
        if isinstance(result, dict):
            self.session.log(
                Msg(
                    "log.reset.done",
                    deployments=Msg(
                        "count.deployments", count=int(result.get("deployments_destroyed") or 0)
                    ),
                )
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
