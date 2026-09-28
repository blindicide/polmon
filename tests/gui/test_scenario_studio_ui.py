"""Headless-runnable scenario step-editor coverage."""

from polmon.client.pages.scenarios import ScenarioStepEditor
from polmon.scenarios import parse_scenario

SOURCE = """id: ui-authored
required_topology: lab
initial_conditions: [topology_deployed]
permitted_actions: [ssh_exec, wait]
sequence:
  - {id: inspect, kind: ssh_exec, target: server, command: hostname}
timeout_seconds: 10
success_conditions:
  - {action: inspect, field: success, equals: true}
cleanup:
  - {id: cleanup, kind: wait, seconds: 0.1}
"""


def test_scenario_step_editor_add_duplicate_reorder_remove(qtbot) -> None:
    editor = ScenarioStepEditor()
    qtbot.addWidget(editor)
    emitted: list[str] = []
    editor.source_changed.connect(emitted.append)
    editor.set_source(SOURCE)
    assert editor.steps.count() == 1

    editor.add_step()
    assert editor.steps.count() == 2
    editor.steps.setCurrentRow(0)
    editor.duplicate_step()
    assert editor.steps.count() == 3
    editor.move_down()
    editor.remove_step()
    assert editor.steps.count() == 2
    assert emitted
    restored = parse_scenario(emitted[-1])
    assert [item.id for item in restored.sequence] == ["inspect", "step-1"]
    print("SCENARIO-UI-STEP-EDITOR-OK add duplicate reorder remove")
