"""Light and dark themes: Fusion style, a full QPalette and a small stylesheet."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("system", "light", "dark")

COLORS = {
    "light": {
        "window": "#f3f4f6",
        "base": "#ffffff",
        "alternate": "#f7f8fa",
        "text": "#1c2430",
        "muted": "#5b6574",
        "border": "#d3d8df",
        "button": "#eceef2",
        "accent": "#1f6feb",
        "accent_text": "#ffffff",
        "success": "#1a7f37",
        "warning": "#9a6700",
        "danger": "#cf222e",
        "info": "#0969da",
        "banner_danger": "#ffebe9",
        "banner_warning": "#fff8c5",
        "banner_info": "#ddf4ff",
        "banner_success": "#dafbe1",
        "chart": "#1f6feb",
    },
    "dark": {
        "window": "#1b1f24",
        "base": "#0f1216",
        "alternate": "#161a1f",
        "text": "#e6edf3",
        "muted": "#8b949e",
        "border": "#30363d",
        "button": "#262c33",
        "accent": "#388bfd",
        "accent_text": "#ffffff",
        "success": "#3fb950",
        "warning": "#d29922",
        "danger": "#f85149",
        "info": "#58a6ff",
        "banner_danger": "#3d1d20",
        "banner_warning": "#3b2e10",
        "banner_info": "#12263d",
        "banner_success": "#12301b",
        "chart": "#58a6ff",
    },
}

_current = "light"


def resolve(preference: str) -> str:
    """``system`` follows the OS colour scheme (Qt ≥ 6.5); unknown schemes fall back to light."""
    if preference in {"light", "dark"}:
        return preference
    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else None
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


def current() -> str:
    return _current


def color(name: str) -> QColor:
    return QColor(COLORS[_current][name])


def hex_color(name: str) -> str:
    return COLORS[_current][name]


SUCCESS_STATES = {"succeeded", "connected", "complete", "met", "not_triggered", "ok", "done",
                  "valid", "yes"}
INFO_STATES = {"running", "connecting"}
WARNING_STATES = {"cancelled", "cancelling", "timed_out", "not_run", "interrupted", "modified",
                  "unknown", "incompatible"}
DANGER_STATES = {"failed", "error", "aborted", "lost", "unauthorized", "not_met", "triggered",
                 "invalid"}


def status_color(status: str) -> str:
    """Semantic colour name for an experiment/job/connection/action status string."""
    status = status.lower()
    if status in SUCCESS_STATES:
        return "success"
    if status in INFO_STATES:
        return "info"
    if status in WARNING_STATES:
        return "warning"
    if status in DANGER_STATES:
        return "danger"
    return "muted"


def _palette(values: dict[str, str]) -> QPalette:
    palette = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    assignments = {
        role.Window: values["window"],
        role.WindowText: values["text"],
        role.Base: values["base"],
        role.AlternateBase: values["alternate"],
        role.ToolTipBase: values["base"],
        role.ToolTipText: values["text"],
        role.PlaceholderText: values["muted"],
        role.Text: values["text"],
        role.Button: values["button"],
        role.ButtonText: values["text"],
        role.BrightText: values["danger"],
        role.Highlight: values["accent"],
        role.HighlightedText: values["accent_text"],
        role.Link: values["accent"],
        role.Mid: values["border"],
        role.Midlight: values["border"],
        role.Dark: values["border"],
    }
    for item, value in assignments.items():
        palette.setColor(item, QColor(value))
    for item in (role.Text, role.WindowText, role.ButtonText):
        palette.setColor(group.Disabled, item, QColor(values["muted"]))
    return palette


def stylesheet(values: dict[str, str]) -> str:
    return f"""
QToolBar {{ spacing: 6px; padding: 4px 6px; border: none;
           border-bottom: 1px solid {values["border"]}; }}
QStatusBar {{ border-top: 1px solid {values["border"]}; }}
QListWidget#navigation {{ border: none; background: {values["window"]}; outline: 0;
                          padding-top: 6px; }}
QListWidget#navigation::item {{ padding: 7px 12px; margin: 1px 6px; border-radius: 6px; }}
QListWidget#navigation::item:selected {{ background: {values["accent"]};
                                          color: {values["accent_text"]}; }}
QListWidget#navigation::item:hover:!selected {{ background: {values["button"]}; }}
QGroupBox {{ border: 1px solid {values["border"]}; border-radius: 6px; margin-top: 14px;
            padding: 8px 6px 6px 6px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px;
                   color: {values["muted"]}; }}
QFrame#tile {{ border: 1px solid {values["border"]}; border-radius: 6px;
              background: {values["base"]}; }}
QLabel#tileValue {{ font-size: 15pt; font-weight: 600; }}
QLabel#tileCaption, QLabel#muted {{ color: {values["muted"]}; }}
QLabel#pageTitle {{ font-size: 13pt; font-weight: 600; }}
QPlainTextEdit#yaml {{ border: 1px solid {values["border"]}; }}
QHeaderView::section {{ padding: 3px 6px; border: none;
                        border-right: 1px solid {values["border"]};
                        border-bottom: 1px solid {values["border"]};
                        background: {values["alternate"]}; }}
QTableView, QTreeView, QTreeWidget, QTableWidget {{ gridline-color: {values["border"]}; }}
QPushButton {{ padding: 4px 12px; }}
QPushButton#primary {{ background: {values["accent"]}; color: {values["accent_text"]};
                       border: 1px solid {values["accent"]}; border-radius: 4px; }}
QPushButton#primary:disabled {{ background: {values["button"]}; color: {values["muted"]};
                                border-color: {values["border"]}; }}
QPushButton#danger {{ color: {values["danger"]}; }}
"""


def apply(app: QApplication, preference: str) -> str:
    """Apply a theme preference; returns the effective theme name."""
    global _current
    effective = resolve(preference)
    _current = effective
    app.setStyle("Fusion")
    values = COLORS[effective]
    app.setPalette(_palette(values))
    app.setStyleSheet(stylesheet(values))
    return effective
