"""Basic application configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.utils.paths import (
    get_exports_dir,
    get_logs_dir,
    get_projects_dir,
    get_resources_dir,
    get_user_data_dir,
)


APP_NAME = "local-text-mining-studio"
APP_TITLE = "本地文本挖掘工作台"
PORTABLE_MODE = True
LOG_FILE_NAME = "app.log"


@dataclass(frozen=True)
class AppConfig:
    """Small immutable config object for app-wide defaults."""

    app_name: str = APP_NAME
    app_title: str = APP_TITLE
    portable_mode: bool = PORTABLE_MODE
    user_data_dir: Path = field(default_factory=get_user_data_dir)
    projects_dir: Path = field(default_factory=get_projects_dir)
    logs_dir: Path = field(default_factory=get_logs_dir)
    exports_dir: Path = field(default_factory=get_exports_dir)
    resources_dir: Path = field(default_factory=get_resources_dir)


settings = AppConfig()
