"""The desktop client depends on the HTTP contract only, never on backend implementation code."""

import json
import subprocess
import sys

FORBIDDEN = (
    "polmon.api",
    "polmon.backend",
    "polmon.backends",
    "polmon.benchmarks",
    "polmon.networking",
    "polmon.orchestration",
    "polmon.reporting",
    "polmon.resources",
    "polmon.scenarios",
    "polmon.telemetry",
    "polmon.topology",
    "fastapi",
    "uvicorn",
    "pydantic",
)


def test_client_imports_no_backend_modules() -> None:
    script = (
        "import json, sys\n"
        "import polmon.client.app, polmon.client.mainwindow, polmon.client.selftest\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    loaded = json.loads(
        subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        ).stdout
    )
    leaked = [name for name in loaded if name.startswith(FORBIDDEN)]
    assert not leaked, leaked
