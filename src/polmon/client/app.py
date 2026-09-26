"""Responsive Tkinter control client for a remote Linux backend."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tkinter as tk
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from polmon.client.api import ApiClient
from polmon.version import __version__


def self_test() -> int:
    """Validate packaged imports and configuration without opening a window."""
    required = ("json", "tkinter", "urllib.request", "polmon.client.api", "polmon.version")
    for module_name in required:
        importlib.import_module(module_name)
    ApiClient("http://127.0.0.1:8080")
    if not __version__ or not isinstance(__version__, str):
        return 1
    print(f"polmon {__version__} self-test: PASS")
    return 0


class PolmonApp:
    """Asynchronous GUI for topology and experiment workflows."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="polmon-client")
        self.future: Future[object] | None = None
        self.topology_source = ""
        self.scenario_source = ""
        self.topology_id = ""
        root.title(f"polmon {__version__}")
        root.minsize(700, 500)
        frame = ttk.Frame(root, padding=16)
        frame.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)
        ttk.Label(
            frame, text=f"polmon {__version__}", font=("TkDefaultFont", 16, "bold")
        ).grid(row=0, column=0, columnspan=4, pady=(0, 10))
        ttk.Label(frame, text="Backend URL").grid(row=1, column=0, sticky="w")
        self.server_url = tk.StringVar(value="http://127.0.0.1:8080")
        ttk.Entry(frame, textvariable=self.server_url).grid(row=1, column=1, sticky="ew")
        ttk.Button(frame, text="Connect", command=self.connect).grid(row=1, column=2, padx=4)
        self.status = tk.StringVar(value="Disconnected")
        ttk.Label(frame, textvariable=self.status).grid(row=1, column=3, sticky="w")
        ttk.Label(frame, text="API token").grid(row=2, column=0, sticky="w")
        # Held in memory only; never written to disk, logs, or the output pane.
        self.api_token = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.api_token, show="*").grid(
            row=2, column=1, sticky="ew", pady=(4, 4)
        )
        ttk.Button(frame, text="Load topology", command=self.load_topology_file).grid(
            row=3, column=0
        )
        ttk.Button(frame, text="Validate", command=self.validate_topology).grid(
            row=3, column=1, sticky="w"
        )
        ttk.Button(frame, text="Deploy", command=self.deploy).grid(row=3, column=2)
        ttk.Button(frame, text="Reset", command=self.reset).grid(row=3, column=3)
        ttk.Button(frame, text="Load scenario", command=self.load_scenario_file).grid(
            row=4, column=0
        )
        ttk.Button(frame, text="Run experiment", command=self.run_experiment).grid(
            row=4, column=1, sticky="w"
        )
        self.selection = tk.StringVar(value="No topology or scenario selected")
        ttk.Label(frame, textvariable=self.selection).grid(
            row=5, column=0, columnspan=4, sticky="w"
        )
        self.output = tk.Text(frame, wrap="word", height=18)
        self.output.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _client(self) -> ApiClient:
        return ApiClient(
            self.server_url.get(), timeout=5, token=self.api_token.get().strip() or None
        )

    def _submit(self, label: str, function) -> None:
        if self.future is not None and not self.future.done():
            messagebox.showinfo("polmon", "Another operation is still running.")
            return
        self.status.set(label)
        self.future = self.executor.submit(function)
        self.root.after(50, self._poll)

    def _poll(self) -> None:
        if self.future is None:
            return
        if not self.future.done():
            self.root.after(50, self._poll)
            return
        try:
            result = self.future.result()
            self.output.insert("end", json.dumps(result, indent=2, default=str) + "\n")
            self.output.see("end")
            self.status.set("Ready")
        except Exception as error:
            self.status.set("Error")
            messagebox.showerror("polmon", str(error))

    def connect(self) -> None:
        self._submit("Connecting…", self._client().health)

    def load_topology_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yml *.yaml"), ("All", "*")])
        if path:
            self.topology_source = Path(path).read_text(encoding="utf-8")
            self.selection.set(f"Topology: {Path(path).name}")

    def validate_topology(self) -> None:
        source = self.topology_source
        client = self._client()  # Tk variables are read on the UI thread only

        def work() -> dict[str, object]:
            result = client.validate_topology(source)
            self.topology_id = str(result["topology_id"])
            return result

        self._submit("Validating…", work)

    def deploy(self) -> None:
        source = self.topology_source
        client = self._client()

        def work() -> dict[str, object]:
            loaded = client.load_topology(source)
            self.topology_id = str(loaded["topology_id"])
            return client.deploy(self.topology_id)

        self._submit("Deploying…", work)

    def load_scenario_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yml *.yaml"), ("All", "*")])
        if path:
            self.scenario_source = Path(path).read_text(encoding="utf-8")
            self.selection.set(f"Scenario: {Path(path).name}")

    def run_experiment(self) -> None:
        experiment_id = f"gui-{uuid.uuid4().hex[:12]}"
        topology_id = self.topology_id
        scenario = self.scenario_source
        client = self._client()

        def work() -> dict[str, object]:
            result = client.run_experiment(experiment_id, topology_id, scenario)
            result["telemetry"] = client.telemetry(experiment_id)
            result["report"] = client.report(experiment_id)
            return result

        self._submit("Running experiment…", work)

    def reset(self) -> None:
        self._submit("Resetting…", self._client().reset_all)

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


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
