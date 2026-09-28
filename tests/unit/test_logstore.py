import json

from polmon.core.logstore import StructuredLogStore


def test_structured_logs_are_bounded_filterable_redacted_and_rotated(tmp_path) -> None:
    store = StructuredLogStore(tmp_path, max_records=20, max_file_bytes=400, max_files=3)
    for index in range(30):
        store.emit(
            "INFO" if index % 2 else "ERROR",
            "lab.event",
            "record",
            params={"index": index, "access_token": "do-not-store"},
            deployment="lab",
            topology="lab",
            node={"id": "server", "name": "Server", "uuid": "node-uuid"},
        )
    result = store.query(level="ERROR", node="node-uuid", limit=5)
    assert len(result["records"]) == 5
    assert all(item["level"] == "ERROR" for item in result["records"])
    assert "do-not-store" not in json.dumps(store.files())
    paths = store.files()["files"]
    assert any(str(item["path"]).endswith(".1") for item in paths)
    assert all(int(item["size"]) <= 400 for item in paths)


def test_structured_logs_reload_and_wait_for_cursor(tmp_path) -> None:
    store = StructuredLogStore(tmp_path)
    first = store.emit("INFO", "one", "first")
    restarted = StructuredLogStore(tmp_path)
    assert restarted.query(since=0)["records"][0]["cursor"] == first["cursor"]
    second = restarted.emit("INFO", "two", "second")
    assert restarted.wait_for(first["cursor"])["next_cursor"] == second["cursor"]
