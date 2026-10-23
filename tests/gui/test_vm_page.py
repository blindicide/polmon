"""Страница виртуальных машин L1: реальные виджеты, бэкенд и поддельная команда дополнения."""

import os
import sys

from conftest import connect, wait_connected

from polmon.api import vm as vm_module
from polmon.api.vm import VMJobs

FAKE = """
import json, os, signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
action = sys.argv[1]
behavior = os.environ.get("FAKE", "ok")
if action == "readiness":
    print(json.dumps({"ready": True, "modes": {"userns": True, "netns": False}, "missing": [],
                      "version": "0.8.0", "integration_verified": False}))
elif action == "run":
    if behavior == "hang":
        time.sleep(60)
    if behavior == "fail":
        print(json.dumps({"error_code": "vm.host_memory"}), file=sys.stderr)
        sys.exit(2)
    node = {"pid": 1, "cpu_seconds": 1.5, "rss_bytes": 300 << 20,
            "overlay_allocated_bytes": 1 << 20,
            "interfaces": {"eth0": {"rx_bytes": 2048, "rx_packets": 3, "tx_bytes": 1024,
                                    "tx_packets": 2}}}
    print(json.dumps({"ready_seconds": 4.5, "probes": {"alpha": [True], "beta": [True, False]},
                      "sample": {"nodes": {"alpha": node, "beta": node},
                                 "guest_memory_mb_each": 256, "uptime_seconds": 12.0}}))
elif action == "recover":
    print(json.dumps({"recovered": True}))
"""


def install_fake(backend, tmp_path, behavior: str = "ok", image: bool = True) -> VMJobs:
    """Подменяет задания ВМ бэкенда: вместо QEMU запускается короткий скрипт."""
    script = tmp_path / "fake_addon.py"
    script.write_text(FAKE, encoding="utf-8")
    jobs = VMJobs(
        tmp_path / "vm",
        command=lambda *arguments: [sys.executable, str(script), *arguments],
        environment=lambda: {**os.environ, "FAKE": behavior},
        available=lambda: True,
        bundled=lambda: tmp_path / "no-bundled-image",
    )
    if image:
        jobs.image_path.parent.mkdir(parents=True)
        jobs.image_path.write_text("image")
    backend.plane.vm = jobs
    return jobs


def open_page(qtbot, window, backend):
    connect(qtbot, window, backend)
    wait_connected(qtbot, window)
    window.navigate("vm")
    return window.pages["vm"]


def test_page_explains_a_missing_addon(window, qtbot, live_backend, monkeypatch) -> None:
    monkeypatch.setattr(vm_module, "addon_available", lambda: False)
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    window.navigate("vm")
    page = window.pages["vm"]
    assert not page.advertised
    assert page.view.state == "empty"
    assert not page.run_button.isEnabled()


def test_page_shows_readiness_and_keeps_unavailable_mode_disabled(
    window, qtbot, live_backend, tmp_path
) -> None:
    install_fake(live_backend, tmp_path)
    page = open_page(qtbot, window, live_backend)
    qtbot.waitUntil(lambda: page.view.state == "content", timeout=10_000)
    assert page.host_badge.status == "ok"
    model = page.mode.model()
    assert model.item(0).isEnabled() and not model.item(1).isEnabled()
    assert page.mode.currentData() == "userns"
    assert page.run_button.isEnabled() and not page.cancel_button.isEnabled()


def test_run_fills_the_guest_table(window, qtbot, live_backend, tmp_path) -> None:
    install_fake(live_backend, tmp_path)
    page = open_page(qtbot, window, live_backend)
    qtbot.waitUntil(lambda: page.view.state == "content", timeout=10_000)
    page.run_button.click()
    qtbot.waitUntil(lambda: page.job_badge.status == "succeeded", timeout=30_000)
    qtbot.waitUntil(lambda: page.guests.rowCount() == 2, timeout=10_000)
    assert page.jobs.rowCount() == 1
    assert page.summary.text() and page.summary.text() != str(page.summary.toolTip())
    assert not window.context.busy


def test_failed_job_reports_the_addon_code(window, qtbot, live_backend, tmp_path) -> None:
    install_fake(live_backend, tmp_path, behavior="fail")
    page = open_page(qtbot, window, live_backend)
    qtbot.waitUntil(lambda: page.view.state == "content", timeout=10_000)
    page.run_button.click()
    qtbot.waitUntil(lambda: page.job_badge.status == "failed", timeout=30_000)
    assert "vm.host_memory" not in page.job_detail.text()
    assert page.guests_state.state == "empty"


def test_running_job_can_be_cancelled(window, qtbot, live_backend, tmp_path) -> None:
    install_fake(live_backend, tmp_path, behavior="hang")
    page = open_page(qtbot, window, live_backend)
    qtbot.waitUntil(lambda: page.view.state == "content", timeout=10_000)
    page.run_button.click()
    qtbot.waitUntil(lambda: page.cancel_button.isEnabled(), timeout=10_000)
    assert not page.run_button.isEnabled()
    page.cancel_button.click()
    qtbot.waitUntil(lambda: page.job_badge.status == "cancelled", timeout=30_000)
    qtbot.waitUntil(lambda: page.run_button.isEnabled(), timeout=10_000)
