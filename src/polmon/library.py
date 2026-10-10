"""Atomic, restart-safe YAML document library."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

from polmon.core.errors import ConfigurationError

Document = TypeVar("Document")


class YamlLibrary(Generic[Document]):
    """Persist validated documents under a fixed directory without path-derived input."""

    def __init__(
        self,
        directory: Path,
        *,
        parse: Callable[[str], Document],
        dump: Callable[[Document], str],
        identity: Callable[[Document], str],
    ) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._parse = parse
        self._dump = dump
        self._identity = identity
        self.errors: dict[str, str] = {}

    def load_all(self) -> dict[str, Document]:
        documents: dict[str, Document] = {}
        self.errors = {}
        for path in sorted((*self.directory.glob("*.yml"), *self.directory.glob("*.yaml"))):
            try:
                document = self._parse(path.read_text(encoding="utf-8"))
                identifier = self._identity(document)
                if identifier in documents:
                    raise ValueError(f"duplicate library identifier {identifier!r}")
                documents[identifier] = document
            except Exception as error:  # retain the file; surface it through diagnostics later
                self.errors[path.name] = f"{type(error).__name__}: {error}"
        return documents

    def put(self, identifier: str, document: Document) -> Path:
        actual = self._identity(document)
        if actual != identifier:
            raise ConfigurationError(
                f"document id '{actual}' does not match path id '{identifier}'",
                message_code="library.id_mismatch",
                params={"document_id": actual, "path_id": identifier},
            )
        destination = self.directory / f"{identifier}.yml"
        temporary = self.directory / f".{identifier}.{os.getpid()}.tmp"
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(self._dump(document))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(destination)
            if os.name == "posix":
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as error:
            raise ConfigurationError(
                "unable to persist library document",
                details={"reason": str(error)},
                message_code="library.write_failed",
            ) from error
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination

    def delete(self, identifier: str) -> bool:
        path = self.directory / f"{identifier}.yml"
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ConfigurationError(
                "unable to delete library document",
                details={"reason": str(error)},
                message_code="library.delete_failed",
            ) from error
        return True
