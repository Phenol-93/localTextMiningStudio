"""Application path helpers.

The app defaults to portable mode: runtime data is stored next to the
application directory, under ``user_data``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    """Return the application directory.

    In source mode this is the project root. In PyInstaller builds this is the
    directory containing the executable, which keeps onedir builds portable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parents[2]


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_user_data_dir() -> Path:
    """Return the portable user data directory."""
    return _ensure_dir(get_app_root() / "user_data")


def get_projects_dir() -> Path:
    """Return the directory used to store local projects."""
    return _ensure_dir(get_user_data_dir() / "projects")


def get_logs_dir() -> Path:
    """Return the directory used for application logs."""
    return _ensure_dir(get_app_root() / "logs")


def get_exports_dir() -> Path:
    """Return the directory used for exported files."""
    return _ensure_dir(get_app_root() / "exports")


def get_resources_dir() -> Path:
    """Return the runtime resources directory."""
    return _ensure_dir(get_app_root() / "resources")


def get_settings_dir() -> Path:
    """Return the directory used for local settings files."""
    return _ensure_dir(get_user_data_dir() / "settings")


def ensure_app_directories() -> None:
    """Create all base runtime directories if they do not exist."""
    get_user_data_dir()
    get_projects_dir()
    get_logs_dir()
    get_exports_dir()
    get_resources_dir()
    get_settings_dir()


ensure_app_directories()
