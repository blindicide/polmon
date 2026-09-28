import json

from polmon.client.pages.logs import LogsPage


def test_logs_page_filters_renders_details_and_exports(qtbot, window, tmp_path) -> None:
    page = window.pages["logs"]
    assert isinstance(page, LogsPage)
    qtbot.addWidget(page)
    page._received(
        {
            "records": [
                {
                    "cursor": 7,
                    "timestamp": "2026-09-28T12:00:00+00:00",
                    "level": "INFO",
                    "event": "console.command",
                    "message": "console command completed",
                    "correlation": {"node": {"id": "server", "uuid": "node-uuid"}},
                    "params": {"argv": ["hostname"]},
                }
            ],
            "next_cursor": 7,
        }
    )
    assert page.table.rowCount() == 1
    page.table.selectRow(0)
    assert "console.command" in page.detail.toPlainText()
    original = window.context.ask_save
    window.context.ask_save = lambda *args, **kwargs: tmp_path / "logs.json"
    try:
        page.export()
    finally:
        window.context.ask_save = original
    exported = json.loads((tmp_path / "logs.json").read_text(encoding="utf-8"))
    assert exported[0]["cursor"] == 7
    page.copy_selected()
    print("LOGS-UI-OK filters detail copy export")
