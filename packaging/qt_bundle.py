"""Shared PyInstaller settings for the Qt client bundles (imported by the .spec files).

PyInstaller's PySide6 hooks collect the platform plugins automatically. These helpers keep the
bundle lean and deterministic: Qt modules the client never imports are excluded, and plugins and
translations it cannot use are pruned after analysis. The self-test verifies that the offscreen
and the native platform plugin are still present in the built bundle.
"""

from __future__ import annotations

# Qt modules the client does not use (it needs QtCore, QtGui and QtWidgets only).
EXCLUDED_MODULES = [
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtXml",
    "PySide6.QtDBus",
    "PySide6.QtConcurrent",
    "PySide6.QtHelp",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtPrintSupport",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "unittest",
    "pydoc",
]

# Platform plugins kept per OS; every other platform plugin is removed.
PLATFORMS = {
    "windows": {"qwindows", "qoffscreen", "qminimal"},
    "linux": {"qxcb", "qwayland", "qoffscreen", "qminimal"},
}
# Plugin groups this client cannot use: it loads no images or icons from files, renders with the
# raster engine (no OpenGL), uses Qt's own dialogs and style, and needs no network backends.
UNUSED_PLUGIN_GROUPS = (
    "/iconengines/",
    "/imageformats/",
    "/generic/",
    "/platformthemes/",
    "/xcbglintegrations/",
    "/egldeviceintegrations/",
    "/wayland-graphics-integration-client/",
    "/tls/",
    "/networkinformation/",
    "/platforminputcontexts/libibus",
    "/platforminputcontexts/qtvirtualkeyboard",
)
# Host libraries that only the pruned GTK platform theme pulled in; bundling a host GTK stack
# would also be non-portable.
UNUSED_HOST_LIBRARIES = (
    "libgtk-3",
    "libgdk-3",
    "libgdk_pixbuf",
    "libatk-1.0",
    "libatk-bridge",
    "libatspi",
    "libcairo",
    "libpango",
    "libepoxy",
    "libthai",
    "libdatrie",
    "libfribidi",
    "libpixman",
    "libXcomposite",
    "libXdamage",
    "libXinerama",
    "libXrandr",
    "libXcursor",
    "libXi.so",
)


def _plugin_name(path: str) -> str:
    stem = path.replace("\\", "/").rsplit("/", 1)[-1].split(".")[0]
    return stem.removeprefix("lib")


def keep(dest: str, os_name: str) -> bool:
    """Whether a collected file (by its destination path) belongs in the bundle."""
    normalized = "/" + dest.replace("\\", "/")
    if "/translations/" in normalized:
        return False  # the UI is English only
    if os_name == "linux" and normalized.rsplit("/", 1)[-1].startswith(UNUSED_HOST_LIBRARIES):
        return False
    if "/plugins/platforms/" in normalized:
        return _plugin_name(normalized) in PLATFORMS[os_name]
    return not any(group in normalized for group in UNUSED_PLUGIN_GROUPS)


def prune(entries, os_name: str):  # noqa: ANN001, ANN201 - PyInstaller TOC entries
    return [entry for entry in entries if keep(entry[0], os_name)]
