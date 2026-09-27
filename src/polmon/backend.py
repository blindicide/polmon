"""Cross-platform backend entry point (Windows is explicitly L0-only)."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from polmon.api.auth import BearerTokenAuth, require_safe_binding, resolve_token
from polmon.api.control import ControlPlane
from polmon.api.limits import RequestSizeLimit
from polmon.api.routes import router
from polmon.core.diagnostics import collect_diagnostics, fidelity_readiness
from polmon.core.errors import PolmonError
from polmon.core.lifeline import onefile_launcher_pid, watch_process, watch_stream_eof
from polmon.core.logging import configure_logging
from polmon.resources import ResourceLimits
from polmon.version import __version__

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    logger.info("polmon backend %s starting", __version__, extra={"event": "startup"})
    logger.info("startup diagnostics: %s", collect_diagnostics(), extra={"event": "resources"})
    try:
        yield
    finally:
        # SIGINT/SIGTERM end here through uvicorn's graceful shutdown: never leave lab resources.
        try:
            result = application.state.control.shutdown()
            logger.info("shutdown cleanup: %s", result, extra={"event": "shutdown_cleanup"})
        except Exception as error:  # shutdown must finish and report what it could not clean
            details = getattr(error, "details", {})
            logger.error(
                "shutdown cleanup incomplete: %s %s",
                error,
                details,
                extra={"event": "shutdown_cleanup_failed"},
            )
        logger.info("polmon backend stopped", extra={"event": "shutdown"})


async def handle_polmon_error(_: Request, error: PolmonError) -> JSONResponse:
    """Return consistent safe errors without leaking traces or local state."""
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message, "details": error.details}},
    )


def root() -> dict[str, str]:
    """Return a small, stable health response."""
    return {"name": "polmon", "version": __version__, "status": "ok"}


def create_app(control: ControlPlane | None = None, *, api_token: str | None = None) -> FastAPI:
    application = FastAPI(title="polmon", version=__version__, lifespan=lifespan)
    application.state.control = control or ControlPlane()
    application.add_exception_handler(PolmonError, handle_polmon_error)
    application.add_middleware(RequestSizeLimit)
    if api_token is not None:
        # Added last, so it runs first: unauthenticated bodies are never buffered or parsed.
        application.add_middleware(BearerTokenAuth, token=api_token)
    application.add_api_route("/", root, methods=["GET"])
    application.include_router(router)
    return application


def __getattr__(name: str) -> FastAPI:
    """Build the default ``app`` (``uvicorn polmon.backend:app``) on first use only.

    Importing this module must not create ``./var`` or open its database: the packaged
    executable is often started from a read-only directory just for ``--version``.
    """
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="polmon backend (Windows: L0 only)")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--diagnostics", action="store_true", help="print diagnostics and exit")
    parser.add_argument(
        "--lab-readiness",
        action="store_true",
        help="run read-only L1/hybrid host capability probes and exit 0 when L1 is available",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="load uvicorn and the application graph and complete a rootless L0 workflow",
    )
    parser.add_argument(
        "--local-l0-only",
        action="store_true",
        help="enforce the local-client L0-only fidelity boundary (automatic on Windows)",
    )
    parser.add_argument(
        "--exit-with-stdin",
        action="store_true",
        help="shut down gracefully at EOF on stdin (used by the client that owns this process, "
        "so the backend never outlives it)",
    )
    parser.add_argument(
        "--run-benchmark",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("var"),
        help="telemetry, captures, reports and benchmark results (default: ./var in the working "
        "directory)",
    )
    parser.add_argument(
        "--api-token-file",
        "--token-file",
        type=Path,
        help="file (mode 600) holding the bearer token; POLMON_API_TOKEN is used otherwise. "
        "A token is required to listen on a non-loopback address.",
    )
    defaults = ResourceLimits()
    parser.add_argument("--max-endpoints", type=int, default=defaults.max_endpoint_count)
    parser.add_argument("--max-namespaces", type=int, default=defaults.max_active_namespaces)
    parser.add_argument(
        "--max-concurrent-experiments",
        type=int,
        default=defaults.max_concurrent_experiments,
    )
    parser.add_argument("--max-capture-bytes", type=int, default=defaults.max_capture_bytes)
    parser.add_argument(
        "--max-experiment-seconds",
        type=float,
        default=defaults.max_experiment_duration_seconds,
    )
    parser.add_argument(
        "--memory-reserve-mb",
        type=int,
        default=defaults.memory_safety_threshold_mb,
    )
    parser.add_argument(
        "--max-data-mb",
        type=int,
        default=defaults.max_data_directory_mb,
        help="refuse new experiments once telemetry/captures/reports would exceed this",
    )
    parser.add_argument(
        "--disk-reserve-mb",
        type=int,
        default=defaults.disk_free_reserve_mb,
        help="refuse new experiments that would leave less free disk than this",
    )
    return parser


def _self_test() -> int:
    """Exercise the real frozen graph without depending on a listening socket."""
    from polmon.scenarios import parse_scenario

    topology = """id: self-test
networks:
  - id: lab
    ipv4_subnet: 198.18.0.0/24
nodes:
  - id: probe
    class: l0
    interfaces:
      - {id: eth0, network: lab, mac: '02:00:00:00:00:01', ipv4: 198.18.0.2}
  - id: target
    class: l0
    interfaces:
      - {id: eth0, network: lab, mac: '02:00:00:00:00:02', ipv4: 198.18.0.3}
"""
    scenario = """id: self-test
required_topology: self-test
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
  - {id: ping, kind: icmp_probe, source: probe, target: target}
timeout_seconds: 5
success_conditions:
  - {action: ping, field: success, equals: true}
cleanup_policy: never
"""
    try:
        with tempfile.TemporaryDirectory(prefix="polmon-backend-selftest-") as work:
            plane = ControlPlane(work, l0_only=True)
            try:
                application = create_app(plane)
                config = uvicorn.Config(application, host="127.0.0.1", port=0, log_level="error")
                assert config.app is application
                parsed = parse_scenario(scenario)
                assert parsed.required_topology == "self-test"
                plane.load_topology(topology)
                deployed = plane.deploy("self-test")
                result = plane.run_experiment("backend-self-test", "self-test", scenario)
                telemetry = plane.experiment_telemetry("backend-self-test")
                report = plane.experiment_report("backend-self-test")
                reset = plane.reset_all()
                assert deployed["backend"] == "synthetic"
                assert result["status"] == "succeeded"
                assert telemetry and report["status"] == "succeeded"
                assert reset["deployments_destroyed"] == 1
                plane.shutdown()
            finally:
                # The directory is removed on exit; Windows refuses while SQLite holds it open.
                plane.close()
    except Exception as error:
        print(f"polmon {__version__} backend self-test: FAIL {type(error).__name__}: {error}")
        return 1
    print("PASS uvicorn application graph")
    print("PASS L0 deploy -> scenario -> telemetry -> report -> reset")
    print(f"polmon {__version__} backend self-test: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    if args.run_benchmark is not None:
        from polmon.benchmarks.cli import main as benchmark_main

        return benchmark_main(args.run_benchmark)
    if args.self_test:
        return _self_test()
    if args.diagnostics:
        print(json.dumps(collect_diagnostics(), indent=2, sort_keys=True))
        return 0
    if args.lab_readiness:
        readiness = fidelity_readiness()
        print(json.dumps(readiness, indent=2, sort_keys=True))
        return 0 if readiness["l1_ready"] else 2
    limits = ResourceLimits(
        max_endpoint_count=args.max_endpoints,
        max_active_namespaces=args.max_namespaces,
        max_concurrent_experiments=args.max_concurrent_experiments,
        max_capture_bytes=args.max_capture_bytes,
        max_experiment_duration_seconds=args.max_experiment_seconds,
        memory_safety_threshold_mb=args.memory_reserve_mb,
        max_data_directory_mb=args.max_data_mb,
        disk_free_reserve_mb=args.disk_reserve_mb,
    )
    try:
        token = resolve_token(args.api_token_file)
        require_safe_binding(args.host, token)
    except (PolmonError, OSError) as error:
        raise SystemExit(f"polmon-backend: {getattr(error, 'message', error)}") from None
    logger.info(
        "API authentication %s",
        "enabled" if token else "disabled (loopback only)",
        extra={"event": "api_auth"},
    )
    l0_only = args.local_l0_only or sys.platform == "win32"
    try:
        control = ControlPlane(args.data_dir, limits=limits, l0_only=l0_only)
    except (OSError, sqlite3.Error) as error:
        raise SystemExit(
            f"polmon-backend: cannot use data directory {args.data_dir.absolute()}: {error}; "
            "pass --data-dir with a writable directory"
        ) from None
    server = uvicorn.Server(
        uvicorn.Config(create_app(control, api_token=token), host=args.host, port=args.port)
    )
    def request_exit() -> None:
        server.should_exit = True

    launcher = onefile_launcher_pid()
    if launcher is not None:
        watch_process(launcher, request_exit)
    if args.exit_with_stdin and sys.stdin is not None:
        watch_stream_eof(sys.stdin.buffer, request_exit)
    try:
        server.run()
    finally:
        control.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
