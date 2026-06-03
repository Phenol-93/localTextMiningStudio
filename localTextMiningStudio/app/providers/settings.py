"""AI provider settings storage.

API keys are never written to JSON settings. They are either kept in the UI
session or saved through keyring when the user explicitly opts in.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import keyring

from app.providers.base import ProviderConfig, normalize_provider_name
from app.providers.registry import with_provider_defaults
from app.utils.paths import get_settings_dir


KEYRING_SERVICE = "local-text-mining-studio"
AI_SETTINGS_FILE_NAME = "ai_settings.json"
_SESSION_API_KEYS: dict[str, str] = {}


class AISettingsError(Exception):
    """Raised when AI settings cannot be loaded, saved, or secured."""


@dataclass(frozen=True)
class AIProviderSettings:
    """JSON-serializable provider settings without API key material."""

    provider_name: str = "openai"
    base_url: str | None = None
    model: str | None = None
    temperature: float = 0.2
    timeout: float = 60.0
    save_api_key: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_provider_config(self, api_key: str | None = None) -> ProviderConfig:
        return with_provider_defaults(
            ProviderConfig(
                provider_name=self.provider_name,
                base_url=self.base_url,
                api_key=api_key,
                model=self.model,
                temperature=self.temperature,
                timeout=self.timeout,
            )
        )


def get_ai_settings_path() -> Path:
    return get_settings_dir() / AI_SETTINGS_FILE_NAME


def load_ai_settings(path: Path | None = None) -> AIProviderSettings:
    settings_path = path or get_ai_settings_path()
    if not settings_path.exists():
        return AIProviderSettings()

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data.pop("api_key", None)
    return AIProviderSettings(**data)


def save_ai_settings(settings: AIProviderSettings, path: Path | None = None) -> Path:
    settings_path = path or get_ai_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = settings.to_dict()
    data.pop("api_key", None)
    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings_path


def load_saved_api_key(provider_name: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, _keyring_account(provider_name))
    except Exception as error:
        raise AISettingsError(f"读取已保存 API Key 失败：{error}") from error


def remember_session_api_key(provider_name: str, api_key: str | None) -> None:
    """Keep an API key in memory for the current app session only."""
    account = _keyring_account(provider_name)
    value = (api_key or "").strip()
    if value:
        _SESSION_API_KEYS[account] = value
    else:
        _SESSION_API_KEYS.pop(account, None)


def load_session_api_key(provider_name: str) -> str | None:
    """Return the API key remembered for this process session."""
    return _SESSION_API_KEYS.get(_keyring_account(provider_name))


def clear_session_api_key(provider_name: str) -> None:
    """Remove the in-memory API key for a provider."""
    _SESSION_API_KEYS.pop(_keyring_account(provider_name), None)


def save_api_key(provider_name: str, api_key: str) -> None:
    if not api_key:
        raise AISettingsError("API Key 为空，无法保存。")
    try:
        keyring.set_password(KEYRING_SERVICE, _keyring_account(provider_name), api_key)
    except Exception as error:
        raise AISettingsError(f"保存 API Key 失败：{error}") from error


def clear_saved_api_key(provider_name: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, _keyring_account(provider_name))
    except keyring.errors.PasswordDeleteError:
        return
    except Exception as error:
        raise AISettingsError(f"清除已保存 API Key 失败：{error}") from error


def _keyring_account(provider_name: str) -> str:
    return f"ai-provider:{normalize_provider_name(provider_name)}"
