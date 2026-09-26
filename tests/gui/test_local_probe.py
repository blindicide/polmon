"""The packaged Local-backend GUI probe, run from the source checkout (backend via -m)."""

import io
import json
import os

import pytest

from polmon.client.local_backend import LOCAL_FIDELITY_MESSAGE, LOCAL_LABEL


def test_gui_probe_proves_refusal_and_reaps_the_backend_on_every_exit_path(
    qapp, tmp_path, monkeypatch
) -> None:
    from polmon.client.localprobe import gui_lifecycle_probe

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")  # the probe forces it; restore afterwards
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    output = tmp_path / "probe.json"
    screenshot = tmp_path / "refusal.png"
    stream = io.StringIO()

    assert gui_lifecycle_probe(output, screenshot=screenshot, stream=stream) == 0, stream.getvalue()
    assert stream.getvalue().rstrip().endswith("local-backend GUI probe: PASS")
    record = json.loads(output.read_text(encoding="utf-8"))

    assert record["connected"]["state_label"] == LOCAL_LABEL
    assert record["connected"]["l0_only"] is True
    assert record["ui_refusal"] == {"title": LOCAL_LABEL, "detail": LOCAL_FIDELITY_MESSAGE}
    assert record["backend_refusal"]["http_status"] == 422
    assert record["backend_refusal"]["message"] == LOCAL_FIDELITY_MESSAGE
    assert record["backend_killed"]["ui_title"] == "Local backend stopped"
    assert record["connected"]["backend_rss_bytes"] > 10_000_000
    assert len(record["seconds_to_connected"]) == 3
    assert screenshot.stat().st_size > 10_000

    paths = ("disconnect", "backend_killed", "window_closed")
    pids = {record[path]["backend_pid"] for path in paths}
    assert len(pids) == 3, "each exit path must own a fresh backend"
    for path in paths:
        assert record[path]["exit_code"] is not None
        if os.name == "posix":
            with pytest.raises(ProcessLookupError):
                os.kill(record[path]["backend_pid"], 0)
