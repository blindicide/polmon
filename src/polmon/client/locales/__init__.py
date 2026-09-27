"""Message catalogs of the desktop client (see docs/UI-GUIDE.md for the glossary).

Each catalog maps a stable key to a ``str.format`` template, or — for counts — to a dictionary
of plural forms (English: ``one``/``other``; Russian: ``one``/``few``/``many``/``other``).
``scripts/i18n-completeness.py`` keeps both catalogs complete and consistent.
"""

from __future__ import annotations

from polmon.client.locales import en, ru

CATALOGS: dict[str, dict[str, str | dict[str, str]]] = {"ru": ru.MESSAGES, "en": en.MESSAGES}
DEFAULT_LANGUAGE = "ru"
# Language names are shown in their own language in every UI language (never translated).
AUTONYMS = {"ru": "Русский", "en": "English"}
