"""Shared PyInstaller inputs for the Qt-free backend executables."""

from __future__ import annotations

from PyInstaller.utils.hooks import collect_submodules

# Uvicorn resolves loop/protocol/lifespan implementations by dotted name at request time. Keep
# its entire small Python graph, plus benchmark workers reached by the frozen --run-benchmark path.
# "sqlite3" is listed explicitly so the _sqlite3 C extension is always collected: the L0 store
# opens a SQLite database at startup, and its absence caused the polmon 0.4.1 Linux failure
# `ModuleNotFoundError: No module named '_sqlite3'`.
HIDDEN_IMPORTS = sorted(
    set(
        ["sqlite3"]
        + collect_submodules("uvicorn")
        + collect_submodules("polmon.api")
        + collect_submodules("polmon.backends")
        + collect_submodules("polmon.benchmarks")
        + collect_submodules("polmon.networking")
        + collect_submodules("polmon.orchestration")
        + collect_submodules("polmon.reporting")
        + collect_submodules("polmon.resources")
        + collect_submodules("polmon.scenarios")
        + collect_submodules("polmon.telemetry")
        + collect_submodules("polmon.topology")
    )
)

# The backend artifact must remain Qt-free. Client code is a separate executable and never enters
# the backend module graph.
EXCLUDED_MODULES = [
    "PySide6",
    "shiboken6",
    "polmon.client",
    "pytest",
    "pytestqt",
    "httpx",
    "unittest",
    "pydoc",
]
