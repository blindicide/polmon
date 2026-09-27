"""Turn any client-side failure into a short, actionable operator message (never a traceback).

A :class:`Problem` holds catalog keys and parameters, not text: it renders in the current
language whenever it is displayed, so a banner shown before a language switch follows it.
Backend refusals carry ``message_code`` + ``params`` (see docs/API.md) and are rendered from
``backend.<message_code>``; tests assert on ``Problem.key`` and ``Problem.message_code``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from polmon.client.api import ApiClientError
from polmon.client.formatting import duration, format_duration, format_mebibytes, quantity_for, size
from polmon.client.i18n import Msg, has, tr

# Parameters of admission-control violations (``details`` of HTTP 429 responses).
LIMIT_FIELDS = (
    "projected",
    "limit",
    "active",
    "requested",
    "minimum",
    "required_mb_including_reserve",
    "available_mb",
    "used_mb",
    "free_mb",
)
# Fields whose unit is that of the limit they belong to (``max_run_seconds``: a duration).
AMOUNT_FIELDS = {"projected", "limit", "requested", "minimum"}
MIB_FIELD = re.compile(r"_mb(?:_|$)")  # available_mb, required_mb_including_reserve

Text = Msg | str


def _render(value: Text | None) -> str:
    return "" if value is None else str(value)


class Problem:
    """What went wrong (``key`` → title), the specifics (``detail``/``items``) and what to do.

    ``key`` names catalog entries: ``<key>.title`` and, unless a hint is given, ``<key>.hint``
    when it exists. ``detail``, ``hint`` and ``items`` are :class:`Msg` values (or verbatim data)
    rendered on access.
    """

    __slots__ = ("_detail", "_hint", "_items", "_title", "code", "key", "message_code", "status")

    def __init__(
        self,
        key: str,
        detail: Text = "",
        hint: Text | None = None,
        items: Sequence[Text] = (),
        *,
        status: int | None = None,
        code: str | None = None,
        message_code: str | None = None,
        title: Text | None = None,
    ) -> None:
        self.key = key
        self._title = title if title is not None else Msg(f"{key}.title")
        self._detail = detail
        if hint is None and has(f"{key}.hint"):
            hint = Msg(f"{key}.hint")
        self._hint = hint
        self._items = tuple(items)
        self.status = status
        self.code = code
        self.message_code = message_code

    @classmethod
    def message(cls, title: Text, detail: Text) -> Problem:
        """A plain titled message (banners that are not failures)."""
        return cls("problem.message", detail, title=title)

    @property
    def title(self) -> str:
        return _render(self._title)

    @property
    def detail(self) -> str:
        return _render(self._detail)

    @property
    def hint(self) -> str | None:
        return _render(self._hint) if self._hint is not None else None

    @property
    def items(self) -> tuple[str, ...]:
        return tuple(_render(item) for item in self._items)

    @property
    def item_messages(self) -> tuple[object, ...]:
        """The unrendered items (``Msg`` / limit / located values) for identifier-based checks."""
        return self._items

    @property
    def detail_message(self) -> Text:
        return self._detail

    def text(self) -> str:
        lines = [f"{self.title}: {self.detail}"]
        lines += [f"  • {item}" for item in self.items]
        if self.hint:
            lines.append(self.hint)
        return "\n".join(lines)

    def __str__(self) -> str:  # rendered on display: a logged problem follows a language switch
        return self.text()

    def __repr__(self) -> str:
        return f"Problem({self.key!r}, message_code={self.message_code!r}, status={self.status})"


def backend_message(message_code: object, params: object, fallback: str = "") -> Text:
    """The client rendering of a backend ``message_code``; older backends send no code, so their
    English text is quoted inside a localized sentence rather than shown bare."""
    if isinstance(message_code, str) and has(f"backend.{message_code}"):
        values = params if isinstance(params, dict) else {}
        return Msg(
            f"backend.{message_code}",
            **{str(k): quantity_for(str(k), v) for k, v in values.items()},
        )
    if isinstance(message_code, str) and message_code.startswith("pydantic."):
        return Msg("backend.pydantic.other", check=message_code.removeprefix("pydantic."))
    if fallback:
        return Msg("backend.uncoded", message=fallback)
    return Msg("backend.unknown", code=str(message_code or "—"))


def _limit_field(name: str) -> str:
    key = f"limit.field.{name}"
    return tr(key) if has(key) else name.replace("_", " ")


def _limit_label(name: str) -> str:
    key = f"limit.{name}"
    return tr(key) if has(key) else name.replace("_", " ")


class _LimitItem:
    """``Endpoints: projected 300, limit 250`` in the current language."""

    __slots__ = ("name", "value")

    def __init__(self, name: str, value: object) -> None:
        self.name, self.value = name, value

    def _value(self, field: str, value: object) -> str:
        """Values carry the unit of their field (``*_mb``) or of the limit (``*_seconds``,
        ``*_mb``); counts stay plain numbers."""
        amount = field in AMOUNT_FIELDS
        if MIB_FIELD.search(field) or (amount and self.name.endswith("_mb")):
            return format_mebibytes(value)
        if amount and self.name.endswith("_seconds"):
            return format_duration(value)
        if field.endswith("_bytes"):
            return str(size(value))
        return str(value)

    def __str__(self) -> str:
        if isinstance(self.value, dict):
            pairs = ", ".join(
                f"{_limit_field(k)} {self._value(k, v)}" for k, v in self.value.items()
            )
        else:
            pairs = str(self.value)
        return f"{_limit_label(self.name)}: {pairs}"


def limit_items(details: object) -> tuple[Text, ...]:
    """One line per violated limit, e.g. ``Endpoints: projected 300, limit 250``."""
    if not isinstance(details, dict):
        return ()
    return tuple(_LimitItem(key, value) for key, value in details.items())  # type: ignore[misc]


class _LocatedItem:
    __slots__ = ("location", "message")

    def __init__(self, location: str, message: Text) -> None:
        self.location, self.message = location, message

    def __str__(self) -> str:
        where = self.location or tr("validation.document")
        return f"{where}: {self.message}"


def error_message(item: dict[str, object]) -> Text:
    """One validation error item (``details.errors[]``) as a localized message."""
    return backend_message(item.get("message_code"), item.get("params"), str(item.get("message")))


def yaml_problem(details: dict[str, object]) -> Text:
    code = details.get("problem_code")
    if isinstance(code, str) and has(f"backend.yaml.{code}"):
        return Msg(f"backend.yaml.{code}", key=details.get("key") or "")
    return Msg("backend.yaml.syntax")


def validation_items(details: object) -> tuple[Text, ...]:
    if not isinstance(details, dict):
        return ()
    errors = details.get("errors")
    if isinstance(errors, list):
        return tuple(
            _LocatedItem(str(error.get("location") or ""), error_message(error))  # type: ignore[misc]
            for error in errors
            if isinstance(error, dict)
        )
    if "problem_code" in details:
        return (yaml_problem(details),)
    reason = details.get("reason")
    if isinstance(reason, str):  # an older backend: its parser's own words
        return tuple(Msg.raw(line.strip()) for line in reason.splitlines()[:2] if line.strip())
    return ()


# Substrings of operating-system and HTTP-library error text (never shown).
TRANSPORT_PATTERNS = (
    (("timed out", "timeout"), "problem.timeout"),  # i18n: allow
    (("refused", "10061"), "problem.refused"),
    # i18n: allow
    (("name or service not known", "getaddrinfo", "11001", "nodename nor servname"), "problem.dns"),
    (("reset", "aborted", "closed", "10054"), "problem.dropped"),
)


def _transport(error: ApiClientError, url: str | None, timeout: float | None) -> Problem:
    lowered = str(error).lower()
    where = url or "—"
    for needles, key in TRANSPORT_PATTERNS:
        if any(needle in lowered for needle in needles):
            if key == "problem.timeout":
                return Problem(key, Msg(f"{key}.detail", url=where, timeout=duration(timeout or 0)))
            return Problem(key, Msg(f"{key}.detail", url=where))
    reason = str(error).removeprefix("unable to reach backend: ").strip()
    return Problem(
        "problem.unreachable", Msg("problem.unreachable.detail", url=where, reason=reason)
    )


STATUS_KEYS = {
    401: "problem.unauthorized",
    404: "problem.unsupported",
    405: "problem.unsupported",
    409: "problem.conflict",
    413: "problem.too_large",
    429: "problem.admission",
    422: "problem.rejected",
}


def describe(
    error: BaseException, *, url: str | None = None, timeout: float | None = None
) -> Problem:
    """Map ``error`` to a :class:`Problem`; unknown errors keep only their type and message."""
    if isinstance(error, ApiClientError):
        status, code, details = error.status, error.code, error.details
        if code == "download_too_large":
            limit = size(error.params.get("limit"))
            return Problem("problem.download", Msg("problem.download.detail", limit=limit))
        if code == "malformed_response":
            return Problem("problem.malformed", Msg("problem.malformed.detail"), code=code)
        if status is None:
            return _transport(error, url, timeout)
        common = {"status": status, "code": code, "message_code": error.message_code}
        if status >= 500:
            return Problem("problem.server", Msg("problem.server.detail", status=status), **common)
        key = STATUS_KEYS.get(status, "problem.request")
        if status == 401:
            return Problem(key, Msg("problem.unauthorized.detail"), **common)
        if status in {404, 405}:
            return Problem(key, Msg("problem.unsupported.detail", status=status), **common)
        fallback = re.sub(r"^server returned HTTP \d+(?: \S+)?: ", "", str(error))
        detail = backend_message(error.message_code, error.params, fallback)
        items = limit_items(details) if status == 429 else validation_items(details)
        if error.message_code == "fidelity.l0_only":
            key = "problem.l0_only"
        elif error.message_code == "fidelity.linux_lab_unavailable":
            key = "problem.linux_lab"
            items = ()
        title = Msg("problem.request.title", status=status) if key == "problem.request" else None
        return Problem(key, detail, items=items, title=title, **common)
    if isinstance(error, ValueError):
        return Problem("problem.settings", Msg("problem.settings.detail"))
    if isinstance(error, UnicodeDecodeError):
        return Problem("problem.unreadable", Msg("problem.unreadable.detail"))
    if isinstance(error, OSError):
        filename = getattr(error, "filename", None)
        return Problem(
            "problem.file",
            Msg("problem.file.detail", reason=error.strerror or str(error)),
            Msg("problem.file.hint", path=filename) if filename else Msg.raw(""),
        )
    local = getattr(error, "problem", None)
    if isinstance(local, Problem):  # client-side errors that already know their message
        return local
    return Problem(
        "problem.unexpected", Msg("problem.unexpected.detail", kind=type(error).__name__)
    )
