"""Tkinter client that remains useful before a backend is available."""

from __future__ import annotations

import argparse
import importlib
import sys
import tkinter as tk
from tkinter import ttk

from polmon.version import __version__


def self_test() -> int:
    """Validate imports and static configuration without opening a window."""
    required = ("json", "tkinter", "urllib.request", "polmon.version")
    for module_name in required:
        importlib.import_module(module_name)
    if not __version__ or not isinstance(__version__, str):
        return 1
    print(f"polmon {__version__} self-test: PASS")
    return 0


class PolmonApp:
    """Small connection configuration window for the initial release."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"polmon {__version__}")
        root.minsize(480, 240)
        frame = ttk.Frame(root, padding=20)
        frame.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="polmon", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 8)
        )
        ttk.Label(frame, text=f"Version {__version__}").grid(row=1, column=0, columnspan=2)
        ttk.Label(frame, text="Backend URL").grid(row=2, column=0, sticky="w", pady=(20, 4))
        self.server_url = tk.StringVar(value="http://127.0.0.1:8080")
        ttk.Entry(frame, textvariable=self.server_url).grid(
            row=2, column=1, sticky="ew", pady=(20, 4)
        )
        ttk.Label(
            frame,
            text="The client can be configured without a running backend.",
        ).grid(row=3, column=0, columnspan=2, pady=(14, 0))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="polmon Windows client")
    parser.add_argument("--version", action="store_true", help="display the version and exit")
    parser.add_argument(
        "--self-test", action="store_true", help="run headless packaged-application checks"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"polmon {__version__}")
        return 0
    if args.self_test:
        return self_test()
    root = tk.Tk()
    PolmonApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

