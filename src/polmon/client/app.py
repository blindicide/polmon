"""``polmon-client``: Qt desktop client for a remote polmon Linux backend."""

from __future__ import annotations

import argparse
import os
import sys

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
    parser.add_argument("--url", help="backend URL to prefill (overrides the saved one)")
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
    window = MainWindow()
    if args.url:
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
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print(MISSING_QT, file=sys.stderr)
        return 2
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
