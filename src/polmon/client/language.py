"""Apply a UI language to the running application: catalogs and Qt's own translations."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication

from polmon.client import i18n

_qt_translator: QTranslator | None = None


def _translation_directories() -> list[Path]:
    directories = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:  # PyInstaller bundles keep PySide6's layout under the extraction directory
        directories.append(Path(bundle) / "PySide6" / "Qt" / "translations")
        directories.append(Path(bundle) / "PySide6" / "translations")
    return directories


def qt_translation_file(language: str) -> Path | None:
    """``qtbase_<language>.qm`` (Qt's standard dialogs, context menus, buttons) if present."""
    for directory in _translation_directories():
        candidate = directory / f"qtbase_{language}.qm"
        if candidate.is_file():
            return candidate
    return None


def apply_language(app: QApplication, language: str) -> bool:
    """Switch catalogs and Qt's own strings; bound widgets re-render immediately."""
    global _qt_translator
    if language not in i18n.languages():
        return False
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    path = qt_translation_file(language) if language != "en" else None
    if path is not None:
        translator = QTranslator(app)
        if translator.load(str(path)):
            app.installTranslator(translator)
            _qt_translator = translator
    i18n.set_language(language)
    return True


def qt_translation_loaded() -> bool:
    return _qt_translator is not None
