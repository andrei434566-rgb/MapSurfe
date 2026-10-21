"""Separate bundled read-only resources from persistent desktop app data."""
from __future__ import annotations

import os
from pathlib import Path
import sys


APP_NAME = "MapSurfe"
APP_VERSION = "1.1.0"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Return the project directory or PyInstaller's extracted data root."""
    if is_frozen() and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def app_data_dir() -> Path:
    """Keep source sessions in place and executable sessions across launches."""
    if not is_frozen():
        return resource_dir()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    directory = base / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def session_path() -> Path:
    return app_data_dir() / "paleosloy_session.json"


def error_log_path() -> Path:
    return app_data_dir() / "paleoatlas-qt-error.log"
