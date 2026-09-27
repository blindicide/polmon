"""Design tokens, the Qt palette and the application stylesheet (docs/UI-GUIDE.md).

One accent (deep teal) on slate neutrals; semantic colours for status only, each paired with a
soft surface for banners and badges. Spacing follows a 4-px scale, type a five-step scale, and
every control is 28 px tall. Token pairs used for text are checked for ≥ 4.5:1 contrast by
``tests/unit/test_theme_contrast.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("system", "light", "dark")

# Spacing scale (px) and the type scale (px). Page, card and control metrics derive from these.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}
TYPE = {"caption": 11, "body": 13, "strong": 13, "subtitle": 15, "title": 20, "metric": 22}
CONTROL_HEIGHT = 28
RADIUS = {"control": 6, "card": 8, "pill": 10}

TOKENS: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f2f4f7",
        "surface": "#ffffff",
        "surface_alt": "#f7f9fb",
        "surface_hover": "#eef2f6",
        "border": "#dce1e8",
        "border_strong": "#c3cbd5",
        "text": "#141c26",
        "text_secondary": "#3f4b5b",
        "text_muted": "#5a6676",
        "accent": "#0b6680",
        "accent_hover": "#08546a",
        "accent_pressed": "#064456",
        "accent_soft": "#d9ecf2",
        "accent_text": "#ffffff",
        "success": "#146c36",
        "warning": "#8a4f00",
        "danger": "#b42318",
        "info": "#1d5bb8",
        "success_soft": "#e3f3e8",
        "warning_soft": "#fcf0d8",
        "danger_soft": "#fce9e7",
        "info_soft": "#e4ecfa",
        "nav_bg": "#16202b",
        "nav_hover": "#212e3c",
        "nav_active": "#0b6680",
        "nav_text": "#cdd6e0",
        "nav_text_active": "#ffffff",
        "nav_muted": "#8f9cab",
        "chart": "#0b6680",
        "focus": "#2b8fb0",
    },
    "dark": {
        "bg": "#0e131a",
        "surface": "#161d26",
        "surface_alt": "#1b232d",
        "surface_hover": "#222c38",
        "border": "#2a3542",
        "border_strong": "#3a4757",
        "text": "#e6ebf1",
        "text_secondary": "#b8c2ce",
        "text_muted": "#95a1af",
        "accent": "#2d9cbd",
        "accent_hover": "#3fb0d2",
        "accent_pressed": "#2587a4",
        "accent_soft": "#173746",
        "accent_text": "#06121a",
        "success": "#4cc37a",
        "warning": "#e3a33b",
        "danger": "#f0736a",
        "info": "#7aa7f5",
        "success_soft": "#132b1d",
        "warning_soft": "#33260f",
        "danger_soft": "#3a1716",
        "info_soft": "#152540",
        "nav_bg": "#0a0f15",
        "nav_hover": "#16202b",
        "nav_active": "#1f7f9c",
        "nav_text": "#c3cdd8",
        "nav_text_active": "#ffffff",
        "nav_muted": "#8593a3",
        "chart": "#3fb0d2",
        "focus": "#3fb0d2",
    },
}

# Older names still used by widgets and tests map onto the tokens above.
ALIASES = {
    "window": "bg",
    "base": "surface",
    "alternate": "surface_alt",
    "button": "surface_hover",
    "muted": "text_muted",
    "banner_danger": "danger_soft",
    "banner_warning": "warning_soft",
    "banner_info": "info_soft",
    "banner_success": "success_soft",
}
COLORS = {
    name: {**tokens, **{alias: tokens[target] for alias, target in ALIASES.items()}}
    for name, tokens in TOKENS.items()
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
                  "valid", "yes", "passed", "deployed", "compatible"}
INFO_STATES = {"running", "connecting", "created", "started", "loaded"}
WARNING_STATES = {"cancelled", "cancelling", "timed_out", "not_run", "interrupted", "modified",
                  "unknown", "incompatible", "stopped", "pending", "not_deployed"}
DANGER_STATES = {"failed", "error", "aborted", "lost", "unauthorized", "not_met", "triggered",
                 "invalid", "exceeds"}


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


# A glyph per tone so status never depends on colour alone (usability floor).
STATUS_GLYPHS = {"success": "✓", "info": "●", "warning": "!", "danger": "✕", "muted": "○"}


def status_glyph(status: str) -> str:
    return STATUS_GLYPHS[status_color(status)]


def _palette(values: dict[str, str]) -> QPalette:
    palette = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    assignments = {
        role.Window: values["bg"],
        role.WindowText: values["text"],
        role.Base: values["surface"],
        role.AlternateBase: values["surface_alt"],
        role.ToolTipBase: values["surface"],
        role.ToolTipText: values["text"],
        role.PlaceholderText: values["text_muted"],
        role.Text: values["text"],
        role.Button: values["surface"],
        role.ButtonText: values["text"],
        role.BrightText: values["danger"],
        role.Highlight: values["accent_soft"],
        role.HighlightedText: values["text"],
        role.Link: values["accent"],
        role.Mid: values["border"],
        role.Midlight: values["border"],
        role.Dark: values["border_strong"],
        role.Light: values["surface"],
    }
    for item, value in assignments.items():
        palette.setColor(item, QColor(value))
    for item in (role.Text, role.WindowText, role.ButtonText):
        palette.setColor(group.Disabled, item, QColor(values["text_muted"]))
    return palette


def _arrow_images(v: dict[str, str]) -> dict[str, str]:
    """Chevron images for combo and spin boxes, painted for the current palette.

    The stylesheet replaces Fusion's control drawing, which removes its arrows; the bundle has
    no image-format plugins, so the arrows are painted here and saved as PNG (built into QtGui).
    """
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPainter, QPen, QPolygonF

    folder = Path(tempfile.gettempdir()) / "polmon-ui"
    folder.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for name, tone, points in (
        ("down", "text_secondary", ((1, 2), (5, 6), (9, 2))),
        ("down_disabled", "border_strong", ((1, 2), (5, 6), (9, 2))),
        ("up", "text_secondary", ((1, 6), (5, 2), (9, 6))),
        ("up_disabled", "border_strong", ((1, 6), (5, 2), (9, 6))),
    ):
        path = folder / f"{name}-{v[tone].lstrip('#')}.png"
        if not path.is_file():
            image = QImage(20, 16, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(v[tone]), 3.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([QPointF(x * 2, y * 2) for x, y in points]))
            painter.end()
            image.save(str(path), "PNG")
        paths[name] = path.as_posix()
    return paths


def stylesheet(v: dict[str, str]) -> str:
    """The whole application stylesheet, generated from one token set."""
    s, t, h, r = SPACE, TYPE, CONTROL_HEIGHT, RADIUS
    inner = h - 2  # content height inside a 1-px border
    arrows = _arrow_images(v) if QGuiApplication.instance() is not None else {}
    return f"""
* {{ outline: 0; }}
QWidget {{ font-size: {t["body"]}px; color: {v["text"]}; }}
QMainWindow, QDialog {{ background: {v["bg"]}; }}
QToolTip {{ background: {v["surface"]}; color: {v["text"]}; border: 1px solid {v["border_strong"]};
            padding: {s["xs"]}px {s["sm"]}px; border-radius: {r["control"]}px; }}

/* -- structure: sidebar, header, pages, cards ------------------------------------------ */
QFrame#sidebar {{ background: {v["nav_bg"]}; border: none; }}
QLabel#brand {{ color: {v["nav_text_active"]}; font-size: {t["subtitle"]}px; font-weight: 700;
                padding: {s["lg"]}px {s["lg"]}px 0 {s["lg"]}px; }}
QLabel#brandVersion {{ color: {v["nav_muted"]}; font-size: {t["caption"]}px;
                       padding: 0 {s["lg"]}px {s["md"]}px {s["lg"]}px; }}
QLabel#navSection {{ color: {v["nav_muted"]}; font-size: {t["caption"]}px; font-weight: 600;
                     padding: {s["sm"]}px {s["lg"]}px {s["xs"]}px {s["lg"]}px; }}
QListWidget#navigation {{ background: {v["nav_bg"]}; border: none; color: {v["nav_text"]};
                          padding: 0 {s["sm"]}px; }}
QListWidget#navigation::item {{ padding: {s["sm"] - 1}px {s["md"]}px; margin: 1px 0;
                                border-radius: {r["control"]}px; color: {v["nav_text"]}; }}
QListWidget#navigation::item:hover:!selected {{ background: {v["nav_hover"]}; }}
QListWidget#navigation::item:selected {{ background: {v["nav_active"]};
                                         color: {v["nav_text_active"]}; }}
QLabel#sidebarFooter {{ color: {v["nav_muted"]}; font-size: {t["caption"]}px;
                        padding: {s["md"]}px {s["lg"]}px; }}

QFrame#connectionBar {{ background: {v["surface"]}; border: none;
                        border-bottom: 1px solid {v["border"]}; }}
QLabel#fieldLabel {{ color: {v["text_secondary"]}; font-weight: 600; }}
QFrame#connectionBar QLabel#fieldLabel {{ padding-left: {s["sm"]}px; }}
QFrame#connectionBar QLabel#connectionState {{ padding-left: {s["xs"]}px; }}
QLabel#fidelity {{ border-radius: {r["pill"]}px; padding: 2px {s["sm"] + 2}px; font-weight: 600;
                   background: {v["accent_soft"]}; color: {v["accent"]}; }}

QWidget#page {{ background: {v["bg"]}; }}
QLabel#pageTitle {{ font-size: {t["title"]}px; font-weight: 600; color: {v["text"]}; }}
QLabel#pageSubtitle {{ color: {v["text_muted"]}; }}
QFrame#card {{ background: {v["surface"]}; border: 1px solid {v["border"]};
               border-radius: {r["card"]}px; }}
QLabel#cardTitle {{ font-size: {t["subtitle"]}px; font-weight: 600; color: {v["text"]}; }}
QLabel#cardHint, QLabel#muted, QLabel#caption {{ color: {v["text_muted"]}; }}
QLabel#caption {{ font-size: {t["caption"]}px; }}
QLabel#sectionLabel {{ color: {v["text_secondary"]}; font-size: {t["caption"]}px;
                       font-weight: 600; }}
QLabel#mono {{ font-family: monospace; }}

QFrame#tile {{ background: {v["surface_alt"]}; border: 1px solid {v["border"]};
               border-radius: {r["card"]}px; }}
QLabel#tileCaption {{ color: {v["text_secondary"]}; font-size: {t["caption"]}px;
                      font-weight: 600; }}
QLabel#tileValue {{ font-size: {t["metric"]}px; font-weight: 600; color: {v["text"]}; }}
QLabel#tileSecondary {{ color: {v["text_muted"]}; font-size: {t["caption"]}px; }}

/* -- controls ------------------------------------------------------------------------- */
QPushButton {{ min-height: {inner}px; padding: 0 {s["md"]}px; border-radius: {r["control"]}px;
               border: 1px solid {v["border_strong"]}; background: {v["surface"]};
               color: {v["text"]}; font-weight: 600; }}
QPushButton:hover {{ background: {v["surface_hover"]}; }}
QPushButton:pressed {{ background: {v["border"]}; }}
QPushButton:focus {{ border-color: {v["focus"]}; }}
QPushButton:disabled {{ color: {v["text_muted"]}; background: {v["surface_alt"]};
                        border-color: {v["border"]}; }}
QPushButton[role="primary"] {{ background: {v["accent"]}; color: {v["accent_text"]};
                               border-color: {v["accent"]}; }}
QPushButton[role="primary"]:hover {{ background: {v["accent_hover"]};
                                     border-color: {v["accent_hover"]}; }}
QPushButton[role="primary"]:pressed {{ background: {v["accent_pressed"]}; }}
QPushButton[role="primary"]:disabled {{ background: {v["surface_alt"]};
                                        color: {v["text_muted"]}; border-color: {v["border"]}; }}
QPushButton[role="danger"] {{ color: {v["danger"]}; border-color: {v["danger"]};
                              background: {v["surface"]}; }}
QPushButton[role="danger"]:hover {{ background: {v["danger_soft"]}; }}
QPushButton[role="danger"]:disabled {{ color: {v["text_muted"]}; border-color: {v["border"]};
                                       background: {v["surface_alt"]}; }}
QPushButton[role="quiet"] {{ border-color: transparent; background: transparent;
                             color: {v["accent"]}; }}
QPushButton[role="quiet"]:hover {{ background: {v["accent_soft"]}; }}
QPushButton[role="quiet"]:disabled {{ color: {v["text_muted"]}; }}
QToolButton {{ border: none; border-radius: {r["control"]}px; padding: 2px; }}
QToolButton:hover {{ background: {v["surface_hover"]}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    min-height: {inner}px; padding: 0 {s["sm"]}px; border: 1px solid {v["border_strong"]};
    border-radius: {r["control"]}px; background: {v["surface"]}; color: {v["text"]};
    selection-background-color: {v["accent_soft"]}; selection-color: {v["text"]}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {v["focus"]}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {v["surface_alt"]}; color: {v["text_muted"]}; border-color: {v["border"]}; }}
QComboBox {{ padding-right: 24px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
                        border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({arrows.get("down", "")}); width: 10px; height: 8px; }}
QComboBox::down-arrow:disabled {{ image: url({arrows.get("down_disabled", "")}); }}
QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 20px; border: none; background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: {v["surface_hover"]}; }}
QAbstractSpinBox::up-arrow {{ image: url({arrows.get("up", "")}); width: 9px; height: 7px; }}
QAbstractSpinBox::down-arrow {{ image: url({arrows.get("down", "")}); width: 9px; height: 7px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{
    image: url({arrows.get("up_disabled", "")}); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{
    image: url({arrows.get("down_disabled", "")}); }}
QComboBox QAbstractItemView {{ background: {v["surface"]}; border: 1px solid {v["border_strong"]};
                              selection-background-color: {v["accent_soft"]};
                              selection-color: {v["text"]}; padding: {s["xs"]}px; }}
QCheckBox {{ spacing: {s["sm"]}px; }}
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: {v["surface"]};
    border: 1px solid {v["border"]}; border-radius: {r["control"]}px;
    selection-background-color: {v["accent_soft"]}; selection-color: {v["text"]}; }}
QPlainTextEdit#yaml {{ border-color: {v["border_strong"]}; }}
QPlainTextEdit#activityLog {{ border: none; border-radius: 0; }}

/* -- tables, lists, trees -------------------------------------------------------------- */
QTableView, QTreeView, QListView, QTableWidget, QTreeWidget, QListWidget {{
    background: {v["surface"]}; alternate-background-color: {v["surface_alt"]};
    border: 1px solid {v["border"]}; border-radius: {r["control"]}px;
    gridline-color: {v["border"]}; selection-background-color: {v["accent_soft"]};
    selection-color: {v["text"]}; }}
QTableView::item, QTreeView::item, QListView::item {{ padding: 0 {s["sm"] - 2}px; }}
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {{
    background: {v["surface_hover"]}; }}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background: {v["accent_soft"]}; color: {v["text"]}; }}
QHeaderView {{ background: {v["surface_alt"]}; border: none; }}
QHeaderView::section {{ background: {v["surface_alt"]}; color: {v["text_secondary"]};
                        font-weight: 600; font-size: {t["caption"]}px; border: none;
                        border-bottom: 1px solid {v["border"]};
                        border-right: 1px solid {v["border"]};
                        padding: {s["xs"] + 1}px {s["sm"]}px; }}
QHeaderView::section:hover {{ background: {v["surface_hover"]}; }}

QTabWidget::pane {{ border: 1px solid {v["border"]}; border-radius: {r["control"]}px;
                    background: {v["surface"]}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {v["text_muted"]}; font-weight: 600;
                padding: {s["sm"] - 2}px {s["md"]}px; margin-right: 2px;
                border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {v["text"]}; border-bottom-color: {v["accent"]}; }}
QTabBar::tab:hover:!selected {{ color: {v["text"]}; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: {s["md"]}px; }}
QSplitter::handle:vertical {{ height: {s["md"]}px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {v["border_strong"]}; border-radius: 4px; min-height: 24px;
                      min-width: 24px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {v["text_muted"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ border: 1px solid {v["border"]}; border-radius: 4px; background: {v["surface_alt"]};
                text-align: center; height: 14px; font-size: {t["caption"]}px; }}
QProgressBar::chunk {{ background: {v["accent"]}; border-radius: 3px; }}

QStatusBar {{ background: {v["surface"]}; border-top: 1px solid {v["border"]};
              color: {v["text_secondary"]}; }}
QStatusBar::item {{ border: none; }}
QDockWidget {{ titlebar-close-icon: none; font-weight: 600; }}
QDockWidget::title {{ background: {v["surface_alt"]}; padding: {s["xs"] + 1}px {s["md"]}px;
                      border-top: 1px solid {v["border"]}; text-align: left; }}
QMenuBar {{ background: {v["surface"]}; border-bottom: 1px solid {v["border"]}; }}
QMenuBar::item {{ padding: {s["xs"]}px {s["sm"] + 2}px; background: transparent; }}
QMenuBar::item:selected {{ background: {v["surface_hover"]}; border-radius: 4px; }}
QMenu {{ background: {v["surface"]}; border: 1px solid {v["border_strong"]};
         padding: {s["xs"]}px; }}
QMenu::item {{ padding: {s["xs"] + 1}px {s["xl"]}px {s["xs"] + 1}px {s["md"]}px;
               border-radius: 4px; }}
QMenu::item:selected {{ background: {v["accent_soft"]}; color: {v["text"]}; }}
QMenu::separator {{ height: 1px; background: {v["border"]}; margin: {s["xs"]}px {s["sm"]}px; }}
QMessageBox QLabel {{ min-width: 360px; }}
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
