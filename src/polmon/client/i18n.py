"""Runtime translation: message catalogs, plurals, live widget bindings (Qt-free core).

Every user-visible string of the desktop client comes from ``polmon.client.locales`` through
:func:`tr` / :func:`tr_n`, or through a :func:`bind`-ing that re-applies the text whenever the
language changes. Keys are stable identifiers (``deploy.action.deploy``) that tests may assert
on; display text is never asserted. Switching language re-renders bound texts and calls every
registered ``retranslate`` hook — no restart, no lost session state.
"""

from __future__ import annotations

import itertools
import logging
import os
import weakref
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from polmon.client.locales import CATALOGS, DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)
T = TypeVar("T")

LANGUAGE_ENVIRONMENT_VARIABLE = "POLMON_LANGUAGE"

_language = DEFAULT_LANGUAGE
# Keys looked up but absent from the current catalog (tests require this to stay empty).
missing: set[tuple[str, str]] = set()


def languages() -> tuple[str, ...]:
    return tuple(CATALOGS)


def language() -> str:
    return _language


def initial_language(stored: object = None) -> str:
    """Environment override, then the stored preference, then the default (Russian)."""
    for candidate in (os.environ.get(LANGUAGE_ENVIRONMENT_VARIABLE), stored):
        if isinstance(candidate, str) and candidate in CATALOGS:
            return candidate
    return DEFAULT_LANGUAGE


def _plural_form(language_code: str, count: float) -> str:
    if language_code == "ru":
        if count != int(count):
            return "other"
        number = abs(int(count))
        if number % 10 == 1 and number % 100 != 11:
            return "one"
        if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
            return "few"
        return "many"
    return "one" if count == 1 else "other"


def _lookup(key: str) -> str | Mapping[str, str]:
    catalog = CATALOGS[_language]
    if key in catalog:
        return catalog[key]
    missing.add((_language, key))
    logger.warning("missing %s translation for %r", _language, key)
    fallback = CATALOGS[DEFAULT_LANGUAGE].get(key) or CATALOGS["en"].get(key)
    return fallback if fallback is not None else key


def _render(template: str, key: str, params: Mapping[str, object]) -> str:
    if not params:
        return template
    try:
        return template.format(**{name: str(value) for name, value in params.items()})
    except (KeyError, IndexError, ValueError):
        missing.add((_language, f"{key} (placeholders)"))
        logger.warning("placeholder mismatch in %s translation for %r", _language, key)
        return template


def tr(key: str, **params: object) -> str:
    """The current-language text for ``key`` with ``params`` substituted (values via ``str``)."""
    value = _lookup(key)
    if isinstance(value, Mapping):  # a plural entry used without a count: take the plain form
        value = value.get("other") or next(iter(value.values()))
    return _render(value, key, params)


def tr_n(key: str, count: float, **params: object) -> str:
    """Plural-aware text; ``{count}`` is available to the template."""
    value = _lookup(key)
    if isinstance(value, Mapping):
        form = _plural_form(_language, count)
        value = value.get(form) or value.get("other") or next(iter(value.values()))
    count_text = f"{count:g}" if isinstance(count, float) else str(count)
    return _render(value, key, {"count": count_text, **params})


class Msg:
    """A message rendered when displayed, so it follows later language switches.

    ``Msg("deploy.done", topology="lab")`` renders ``tr("deploy.done", topology="lab")``;
    ``Msg.raw(text)`` carries data (file names, identifiers, OS text) that is never translated.
    Parameters may themselves be :class:`Msg` values.
    """

    __slots__ = ("count", "key", "literal", "params")

    def __init__(self, key: str = "", /, *, count: float | None = None, **params: object) -> None:
        self.key = key
        self.params: dict[str, object] = params
        self.count = count
        self.literal: str | None = None

    @classmethod
    def raw(cls, text: str) -> Msg:
        message = cls()
        message.literal = text
        return message

    def __str__(self) -> str:
        if self.literal is not None:
            return self.literal
        if self.count is not None:
            return tr_n(self.key, self.count, **self.params)
        return tr(self.key, **self.params)

    def __repr__(self) -> str:
        if self.literal is not None:
            return f"Msg.raw({self.literal!r})"
        return f"Msg({self.key!r}, count={self.count!r}, **{self.params!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Msg) and (self.key, self.params, self.count, self.literal) == (
            other.key,
            other.params,
            other.count,
            other.literal,
        )

    __hash__ = None  # type: ignore[assignment]


def text(value: Msg | str | None) -> str:
    return "" if value is None else str(value)


# -- live bindings ----------------------------------------------------------------------------
#
# A binding is (weak reference to a target, function applied to the target). The function
# receives the target as its argument, so closures never keep a widget alive; bindings of
# destroyed widgets are dropped on the next language change.

_bindings: dict[tuple[int, str], tuple[weakref.ReferenceType[Any], Callable[[Any], None]]] = {}
_counter = itertools.count()
PRUNE_THRESHOLD = 4000


def _run(target: object, apply: Callable[[Any], None]) -> bool:
    try:
        apply(target)
    except RuntimeError:  # the C++ object is gone while its wrapper lingers
        return False
    return True


def _prune() -> None:
    for identity, (reference, _) in list(_bindings.items()):
        if reference() is None:
            _bindings.pop(identity, None)


def bind_fn(target: T, apply: Callable[[T], None], tag: str | None = None) -> T:
    """Run ``apply(target)`` now and after every language change while ``target`` lives.

    A binding with the same ``tag`` on the same target replaces the previous one.
    """
    if len(_bindings) > PRUNE_THRESHOLD:
        _prune()
    key = (id(target), tag or f"fn{next(_counter)}")
    _bindings[key] = (weakref.ref(target), apply)  # type: ignore[arg-type]
    _run(target, apply)  # type: ignore[arg-type]
    return target


def bind(target: T, setter: str, key: str | Msg, **params: object) -> T:
    """``target.<setter>(tr(key, **params))`` now and after every language change.

    Returns ``target`` so widgets can be built inline:
    ``layout.addWidget(bind(QLabel(), "setText", "dashboard.title"))``.
    """
    message = key if isinstance(key, Msg) else Msg(key, **params)
    return bind_fn(target, lambda widget: getattr(widget, setter)(str(message)), tag=setter)


def bind_text(target: T, key: str | Msg, **params: object) -> T:
    return bind(target, "setText", key, **params)


def bind_tip(target: T, key: str | Msg, **params: object) -> T:
    return bind(target, "setToolTip", key, **params)


def on_language_changed(owner: object, method: str = "retranslate") -> None:
    """Call ``owner.<method>()`` after each language change while ``owner`` is alive."""
    _bindings[(id(owner), f"hook:{method}")] = (
        weakref.ref(owner),
        lambda target: getattr(target, method)(),
    )


def set_language(code: str) -> bool:
    """Switch language; returns False (and changes nothing) for an unknown code."""
    global _language
    if code not in CATALOGS:
        return False
    changed = code != _language
    _language = code
    if changed:
        retranslate_all()
    return True


def retranslate_all() -> None:
    """Re-apply every live binding (plain bindings first, then page-level hooks)."""
    ordered = sorted(_bindings.items(), key=lambda item: item[0][1].startswith("hook:"))
    for identity, (reference, apply) in ordered:
        target = reference()
        if target is None or not _run(target, apply):
            _bindings.pop(identity, None)


def binding_count() -> int:
    return len(_bindings)


def has(key: str) -> bool:
    return key in CATALOGS[_language] or key in CATALOGS[DEFAULT_LANGUAGE]


def status_label(status: object) -> str:
    """Localized label of a machine status (``succeeded``, ``running`` …); unknown ones verbatim."""
    value = str(status or "")
    key = f"status.{value.lower()}"
    return tr(key) if has(key) else value.replace("_", " ")


def status_msg(status: object) -> Msg | str:
    """Like :func:`status_label`, but rendered on display (for message parameters)."""
    value = str(status or "")
    key = f"status.{value.lower()}"
    return Msg(key) if has(key) else value.replace("_", " ")


class Joined:
    """Several messages shown as one ``a · b · c`` line, rendered on display."""

    __slots__ = ("parts",)

    def __init__(self, parts: list[object]) -> None:
        self.parts = parts

    def __str__(self) -> str:
        return " · ".join(str(part) for part in self.parts)
