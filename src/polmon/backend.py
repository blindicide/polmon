"""Minimal Linux backend entry point."""

from __future__ import annotations

import argparse
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from polmon.api.control import ControlPlane
from polmon.api.routes import router
from polmon.core.diagnostics import collect_diagnostics
from polmon.core.errors import PolmonError
from polmon.core.logging import configure_logging
from polmon.version import __version__

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("polmon backend starting", extra={"event": "startup"})
    logger.info("startup diagnostics: %s", collect_diagnostics(), extra={"event": "resources"})
    yield
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


def create_app(control: ControlPlane | None = None) -> FastAPI:
    application = FastAPI(title="polmon", version=__version__, lifespan=lifespan)
    application.state.control = control or ControlPlane()
    application.add_exception_handler(PolmonError, handle_polmon_error)
    application.add_api_route("/", root, methods=["GET"])
    application.include_router(router)
    return application


app = create_app()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="polmon Linux backend")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--diagnostics", action="store_true", help="print diagnostics and exit")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_logging(args.log_level)
    if args.diagnostics:
        print(__import__("json").dumps(collect_diagnostics(), indent=2, sort_keys=True))
        return
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
