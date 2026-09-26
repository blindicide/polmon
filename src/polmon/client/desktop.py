"""Per-user desktop integration on Linux: a menu entry and icon following the XDG layout."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

APP_ID = "polmon-client"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def launcher() -> list[str]:
    """The command that starts this client: the bundle executable or the installed script."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    script = Path(sys.argv[0]).resolve()
    if script.name == APP_ID and script.is_file():
        return [str(script)]
    return [str(Path(sys.executable).resolve()), "-m", "polmon.client"]


def install_desktop_entry() -> list[Path]:
    """Write ``applications/polmon-client.desktop`` and the icon; returns the files written."""
    from polmon.client.icon import draw_icon

    root = data_home()
    icon = root / "icons/hicolor/256x256/apps" / f"{APP_ID}.png"
    entry = root / "applications" / f"{APP_ID}.desktop"
    icon.parent.mkdir(parents=True, exist_ok=True)
    entry.parent.mkdir(parents=True, exist_ok=True)
    if not draw_icon(256).save(str(icon)):
        raise OSError(f"could not write {icon}")
    command = " ".join(shlex.quote(part) for part in launcher())
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=polmon\n"
        "GenericName=Network laboratory console\n"
        "Comment=Operator console for isolated network-security experiments\n"
        f"Exec={command}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Network;Monitor;\n"
        f"StartupWMClass={APP_ID}\n",
        encoding="utf-8",
    )
    return [entry, icon]
