"""Headless verification of the packaged Qt client (``--self-test``, ``--smoke-start``)."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from polmon.version import __version__

NATIVE_PLUGINS = {"win32": "qwindows", "linux": "qxcb", "darwin": "qcocoa"}


def _native_plugin() -> str:
    for prefix, name in NATIVE_PLUGINS.items():
        if sys.platform.startswith(prefix):
            return name
    return "qxcb"


def _plugin_names(directory: Path) -> set[str]:
    names = set()
    for path in directory.iterdir():
        stem = path.name.split(".")[0]
        names.add(stem.removeprefix("lib"))
    return names


def self_test(stream=None) -> int:  # noqa: ANN001
    """Verify Qt and the client off screen; never opens a window."""
    out = stream or sys.stdout
    previous = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"  # forced: the self-test must not show anything
    try:
        return _self_test(out)
    finally:
        if previous is None:
            os.environ.pop("QT_QPA_PLATFORM", None)
        else:
            os.environ["QT_QPA_PLATFORM"] = previous


def _self_test(out) -> int:  # noqa: ANN001
    failures = 0

    def check(name: str, function: Callable[[], str]) -> object:
        nonlocal failures
        try:
            detail = function()
        except Exception as error:  # every failure is reported, none aborts the others
            failures += 1
            print(f"FAIL {name}: {type(error).__name__}: {error}", file=out)
            return None
        print(f"PASS {name}: {detail}", file=out)
        return detail

    state: dict[str, object] = {}

    def imports() -> str:
        import PySide6
        from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401

        state["qt"] = QtCore
        return f"PySide6 {PySide6.__version__}, Qt {QtCore.qVersion()}"

    def plugins() -> str:
        from PySide6.QtCore import QCoreApplication, QLibraryInfo

        candidates = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))]
        candidates += [Path(item) for item in QCoreApplication.libraryPaths()]
        for base in candidates:
            platforms = base / "platforms"
            if platforms.is_dir():
                names = _plugin_names(platforms)
                missing = {"qoffscreen", _native_plugin()} - names
                if missing:
                    raise RuntimeError(
                        f"platform plugins missing from {platforms}: {sorted(missing)}"
                    )
                return f"{platforms} ({', '.join(sorted(names))})"
        raise RuntimeError(f"no platforms plugin directory under {candidates}")

    def application() -> str:
        from PySide6.QtWidgets import QApplication

        existing = QApplication.instance()
        app = existing or QApplication(["polmon-self-test"])
        state["app"] = app
        name = QApplication.platformName()
        if existing is not None:  # embedded use (tests): nothing may be shown on this platform
            return f"platform {name} (existing application; no window is shown)"
        if name != "offscreen":
            raise RuntimeError(f"expected the offscreen platform, got {name!r}")
        return f"platform {name}"

    def window() -> str:
        from PySide6.QtCore import QSettings

        from polmon.client import theme
        from polmon.client.mainwindow import MainWindow

        app = state["app"]
        theme.apply(app, "light")  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "self-test.ini"), QSettings.Format.IniFormat)
            main = MainWindow(settings)
            main.resize(1200, 760)
            image = main.grab()  # renders without showing the window
            if image.isNull() or image.width() < 100:
                raise RuntimeError("the main window did not render")
            pages = len(main.pages)
            main.shutdown(wait_ms=1000)
            main.deleteLater()
            app.processEvents()  # type: ignore[attr-defined]
            del settings
        size = f"{image.width()}x{image.height()}"
        return f"built, rendered {size} off screen, destroyed ({pages} pages)"

    def languages() -> str:
        from polmon.client import i18n
        from polmon.client.language import apply_language, qt_translation_file
        from polmon.client.locales import CATALOGS, DEFAULT_LANGUAGE

        reference = set(CATALOGS[DEFAULT_LANGUAGE])
        uneven = [code for code, catalog in CATALOGS.items() if set(catalog) != reference]
        if uneven:
            raise RuntimeError(f"catalogs differ from {DEFAULT_LANGUAGE}: {uneven}")
        previous = i18n.language()
        try:
            loaded = {}
            for code in CATALOGS:
                if not apply_language(state["app"], code):  # type: ignore[arg-type]
                    raise RuntimeError(f"language {code} could not be applied")
                if code != "en" and qt_translation_file(code) is None:
                    raise RuntimeError(f"Qt translation qtbase_{code}.qm is missing")
                loaded[code] = i18n.tr("page.dashboard.title")
        finally:
            apply_language(state["app"], previous)  # type: ignore[arg-type]
        if len(set(loaded.values())) != len(loaded):
            raise RuntimeError("languages render identical text")
        names = ", ".join(f"{code} ({len(CATALOGS[code])} keys)" for code in CATALOGS)
        return f"{names}; default {DEFAULT_LANGUAGE}; Qt translations present"

    def client_configuration() -> str:
        from polmon.client.api import DEFAULT_TIMEOUT, DEFAULT_URL, ApiClient, ApiClientError
        from polmon.client.errors import describe

        client = ApiClient(DEFAULT_URL)
        if client.timeout != DEFAULT_TIMEOUT or client.timeout <= 0 or client.has_token:
            raise RuntimeError("unexpected default client configuration")
        problem = describe(ApiClientError("x", status=429, code="resource_limit", details={}))
        if problem.key != "problem.admission":
            raise RuntimeError("error mapping is broken")
        return f"default {client.base_url}, timeout {client.timeout:g} s, no token"

    check("Qt imports", imports)
    if state.get("qt") is not None:
        check("platform plugins", plugins)
        if check("QApplication", application) is not None:
            check("languages", languages)
            check("main window", window)
    check("API client configuration", client_configuration)
    verdict = "PASS" if failures == 0 else f"FAIL ({failures} check(s) failed)"
    print(f"polmon {__version__} self-test: {verdict}", file=out)
    return 0 if failures == 0 else 1


def smoke_start(seconds: float, argv: list[str], stream=None) -> int:  # noqa: ANN001
    """Show the real window on the default (native) platform for ``seconds``, then exit.

    Prints ``exposed after <s>`` as soon as the window is on screen (external tools time the
    cold start from process launch to that line) and, at the end, the idle resident set size.
    """
    out = stream or sys.stdout
    from PySide6.QtCore import QEventLoop, QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    from polmon.client import i18n
    from polmon.client.app import create_application
    from polmon.client.mainwindow import MainWindow
    from polmon.core.diagnostics import resource_snapshot

    began = time.perf_counter()
    create_application(argv, theme_preference="system")  # reused when one already exists
    observed: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as directory:
        settings = QSettings(str(Path(directory) / "smoke.ini"), QSettings.Format.IniFormat)
        window = MainWindow(settings)
        window.show()

        def watch() -> None:
            handle = window.windowHandle()
            if "exposed_after" not in observed and handle is not None and handle.isExposed():
                observed["exposed_after"] = time.perf_counter() - began
                print(f"exposed after {observed['exposed_after']:.3f} s", file=out, flush=True)

        watcher = QTimer()
        watcher.timeout.connect(watch)
        watcher.start(5)

        def finish() -> None:
            watch()
            watcher.stop()
            handle = window.windowHandle()
            observed["exposed"] = bool(handle and handle.isExposed())
            observed["visible"] = window.isVisible()
            # The largest minimum size over every page, in the UI language, on this platform's
            # real fonts: the window must fit a 1440x900 screen (docs/UI-GUIDE.md).
            width = height = 0
            for key in window.pages:
                window.navigate(key)
                hint = window.minimumSizeHint().expandedTo(window.minimumSize())
                width, height = max(width, hint.width()), max(height, hint.height())
            observed["minimum"] = f"{width}x{height}"
            observed["rss"] = resource_snapshot().process_rss_bytes
            window.shutdown(wait_ms=1000)
            window.hide()
            loop.quit()

        # A local loop, not app.exec()/quit(): also correct when embedded in a running app.
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), finish)
        loop.exec()
        window.deleteLater()
        del settings
    platform = QApplication.platformName()
    ok = bool(observed.get("visible")) and bool(observed.get("exposed"))
    exposed_after = observed.get("exposed_after")
    startup = f"{exposed_after:.3f}s" if isinstance(exposed_after, float) else "never"
    rss = observed.get("rss")
    rss_text = f"{rss / 1_048_576:.1f}MiB" if isinstance(rss, int) and rss else "unknown"
    print(
        f"polmon {__version__} smoke-start: {'PASS' if ok else 'FAIL'} platform={platform} "
        f"visible={observed.get('visible')} exposed={observed.get('exposed')} "
        f"in-process-startup={startup} idle-rss-after-{seconds:g}s={rss_text} "
        f"language={i18n.language()} minimum-size={observed.get('minimum', 'unknown')}",
        file=out,
    )
    return 0 if ok else 1
