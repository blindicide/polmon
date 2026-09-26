"""Minimal Linux backend entry point."""

from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI

from polmon.version import __version__

app = FastAPI(title="polmon", version=__version__)


@app.get("/")
def root() -> dict[str, str]:
    """Return a small, stable health response."""
    return {"name": "polmon", "version": __version__, "status": "ok"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="polmon Linux backend")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

