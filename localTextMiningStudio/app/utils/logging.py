"""Logging helpers with basic secret redaction."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config import APP_NAME, LOG_FILE_NAME
from app.utils.paths import get_logs_dir


_LOGGER_NAME = "local_text_mining_studio"
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(['\"]?)([\w.-]*(?:api[_-]?key|secret|access[_-]?token|refresh[_-]?token|token))"
    r"(\1\s*[:=]\s*)(['\"]?)([^'\"\s,;&}]+)(['\"]?)"
)
_AUTH_PATTERN = re.compile(
    r"(?i)(['\"]?)(authorization)(\1\s*[:=]\s*)(['\"]?)(bearer\s+)?([^'\"\s,;&}]+)(['\"]?)"
)


def redact_sensitive(value: Any) -> Any:
    """Return a value with API keys and similar secrets redacted."""
    if isinstance(value, str):
        value = _SENSITIVE_KEY_PATTERN.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}{match.group(3)}"
                f"{match.group(4)}{_REDACTED}{match.group(6)}"
            ),
            value,
        )
        return _AUTH_PATTERN.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}"
                f"{match.group(5) or ''}{_REDACTED}{match.group(7)}"
            ),
            value,
        )

    if isinstance(value, dict):
        return {
            key: _REDACTED if _is_sensitive_key(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }

    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)

    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]

    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in ("api_key", "apikey", "secret", "access_token", "refresh_token", "token")
    )


class RedactingFilter(logging.Filter):
    """Filter log records so secrets are not written to log files."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive(record.msg)
        record.args = redact_sensitive(record.args)
        return True


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the application logger."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    if not any(getattr(handler, "_local_text_mining_handler", False) for handler in logger.handlers):
        log_file = get_logs_dir() / LOG_FILE_NAME
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RedactingFilter())
        file_handler._local_text_mining_handler = True  # type: ignore[attr-defined]
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(RedactingFilter())
        console_handler._local_text_mining_handler = True  # type: ignore[attr-defined]
        logger.addHandler(console_handler)

    logger.debug("%s logging configured", APP_NAME)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return an application logger."""
    setup_logging()
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)
