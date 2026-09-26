"""``polmon-client``: Qt console for an owned L0 or remote Linux backend."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from polmon.version import __version__

MISSING_QT = (
    "polmon-client: the Qt runtime (PySide6) is not installed. Install the GUI extra with "
    "'pip install polmon[gui]', or use the packaged Windows/Linux build."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polmon-client", description="polmon desktop client (Qt, Windows and Linux)"
    )
    parser.add_argument("--version", action="store_true", help="display the version and exit")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="verify Qt, its platform plugins, the main window and the API client off screen "
        "(never opens a window) and exit",
    )
    parser.add_argument(
        "--smoke-start",
        type=float,
        metavar="SECONDS",
        help="show the main window on the native platform for SECONDS, report, and exit",
    )
    parser.add_argument(
        "--install-desktop-entry",
        action="store_true",
        help="Linux: add polmon to the desktop menu for this user (XDG) and exit",
    )
    parser.add_argument("--url", help="backend URL to prefill (overrides the saved one)")
    parser.add_argument(
        "--backend-executable",
        help="override polmon-backend executable used by the Local backend preset",
    )
    parser.add_argument(
        "--local-backend-self-test",
        action="store_true",
        help="start the packaged backend through the client lifecycle and run a real L0 workflow",
    )
    parser.add_argument(
        "--local-backend-gui-probe",
        type=Path,
        metavar="RESULT_JSON",
        help="drive the Local preset through the real window off screen: refusal and every exit "
        "path, recording that no owned backend remains",
    )
    parser.add_argument(
        "--probe-screenshot",
        type=Path,
        metavar="PNG",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--local-backend-crash-test",
        type=Path,
        metavar="PID_JSON",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--theme", choices=("system", "light", "dark"), help="colour theme for this session"
    )
    return parser


def create_application(argv: list[str], *, theme_preference: str | None = None):  # noqa: ANN201
    """Create (or reuse) the QApplication with HiDPI policy, identity and theme applied."""
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from polmon.client import theme
    from polmon.client.icon import app_icon

    existing = QApplication.instance()
    if existing is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(argv)
    else:
        app = existing
    app.setApplicationName("polmon-client")
    app.setOrganizationName("polmon")
    app.setApplicationVersion(__version__)
    app.setApplicationDisplayName("polmon")
    app.setWindowIcon(app_icon())
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("polmon-client")  # Wayland/X11 task bars match the .desktop file
    preference = theme_preference or str(
        QSettings("polmon", "polmon-client").value("view/theme", "system")
    )
    theme.apply(app, preference if preference in theme.THEMES else "system")
    return app


def _release_owned_console() -> None:
    """Windows: a double-clicked console EXE owns a console nobody reads; release it."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    processes = (ctypes.c_uint * 4)()
    if kernel32.GetConsoleProcessList(processes, 4) == 1:  # only this process: not a terminal
        kernel32.FreeConsole()
        devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - process lifetime
        sys.stdout = sys.stderr = devnull


def run_gui(args: argparse.Namespace, qt_arguments: list[str]) -> int:
    from polmon.client.mainwindow import MainWindow

    app = create_application([sys.argv[0], *qt_arguments], theme_preference=args.theme)
    window = MainWindow(backend_executable=args.backend_executable)
    if args.url:
        window.bar.mode.setCurrentIndex(window.bar.mode.findData("remote"))
        window.bar.url.setText(args.url)
    window.show()
    code = app.exec()
    if not getattr(window, "clean_exit", True):
        # A worker is still inside a blocking request (bounded by its timeout); settings are
        # already saved, so leave now instead of hanging the desktop on exit.
        sys.stdout.flush()
        os._exit(code)
    return code


def main(argv: list[str] | None = None) -> int:
    args, qt_arguments = build_parser().parse_known_args(argv)
    if args.version:
        print(f"polmon {__version__}")
        return 0
    if args.local_backend_self_test:
        from polmon.client.local_backend import packaged_workflow_self_test

        try:
            result = packaged_workflow_self_test(args.backend_executable)
        except Exception as error:
            print(f"local-backend self-test: FAIL {type(error).__name__}: {error}")
            return 1
        print(json.dumps(result, indent=2, sort_keys=True))
        print("local-backend self-test: PASS")
        return 0
    if args.local_backend_crash_test:
        from polmon.client.local_backend import crash_cleanup_probe

        crash_cleanup_probe(args.local_backend_crash_test, args.backend_executable)
        return 77
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print(MISSING_QT, file=sys.stderr)
        return 2
    if args.local_backend_gui_probe:
        from polmon.client.localprobe import gui_lifecycle_probe

        return gui_lifecycle_probe(
            args.local_backend_gui_probe,
            args.backend_executable,
            screenshot=args.probe_screenshot,
        )
    if args.install_desktop_entry:
        if not sys.platform.startswith("linux"):
            print("polmon-client: --install-desktop-entry is for Linux desktops", file=sys.stderr)
            return 2
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # drawing the icon needs no display
        from PySide6.QtGui import QGuiApplication

        from polmon.client.desktop import install_desktop_entry

        application = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])  # noqa: F841
        for path in install_desktop_entry():
            print(f"wrote {path}")
        return 0
    if args.self_test:
        from polmon.client.selftest import self_test

        return self_test()
    if args.smoke_start is not None:
        from polmon.client.selftest import smoke_start

        return smoke_start(max(0.5, args.smoke_start), [sys.argv[0], *qt_arguments])
    _release_owned_console()
    return run_gui(args, qt_arguments)


if __name__ == "__main__":
    sys.exit(main())
