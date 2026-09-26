import json
import socket

from polmon import demo


def test_demo_fails_loudly_when_the_backend_is_unreachable(tmp_path, capsys) -> None:
    with socket.socket() as listener:  # a port nobody listens on
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    code = demo.main(
        [
            "--url",
            f"http://127.0.0.1:{port}",
            "--experiment-id",
            "unreachable",
            "--output-dir",
            str(tmp_path),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    record = json.loads(captured.out)
    assert record["status"] == "failed" and "ApiClientError" in record["error"]
    assert json.loads((tmp_path / "unreachable.json").read_text(encoding="utf-8"))["status"] == (
        "failed"
    )
    assert "[demo] 100.0% step 9/9" in captured.err  # progress never touches stdout


def test_demo_defaults_point_at_the_mvp_examples() -> None:
    assert demo.DEFAULT_TOPOLOGY.is_file() and demo.DEFAULT_SCENARIO.is_file()
    assert "mvp-demo" in demo.DEFAULT_SCENARIO.read_text(encoding="utf-8")
