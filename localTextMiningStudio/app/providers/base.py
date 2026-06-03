"""Base abstractions for LLM providers."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from jsonschema import ValidationError, validate

from app.utils.logging import redact_sensitive


JSONDict = dict[str, Any]


class ProviderError(Exception):
    """Raised when an LLM provider fails without exposing secrets."""

    def __init__(self, message: str) -> None:
        super().__init__(str(redact_sensitive(message)))


@dataclass(frozen=True)
class ProviderConfig:
    """JSON-serializable configuration shared by all LLM providers."""

    provider_name: str
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float = 0.2
    timeout: float = 60.0

    def to_dict(self, *, include_api_key: bool = False) -> JSONDict:
        data = asdict(self)
        if not include_api_key:
            data["api_key"] = None
        return data

    def resolve_api_key(self) -> str | None:
        """Return UI-provided API key or a provider-specific environment value."""
        if self.api_key:
            return self.api_key

        for name in api_key_env_names(self.provider_name):
            value = os.getenv(name)
            if value:
                return value
        return None


class BaseLLMProvider(ABC):
    """Uniform JSON generation interface for all LLM providers."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: JSONDict,
        model: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> JSONDict:
        """Generate and validate a JSON object."""

    def _model(self, model: str | None) -> str:
        selected = model or self.config.model
        if not selected:
            raise ProviderError("模型名不能为空，请在 UI 中输入 model。")
        return selected

    def _temperature(self, temperature: float | None) -> float:
        return self.config.temperature if temperature is None else temperature

    def _timeout(self, timeout: float | None) -> float:
        return self.config.timeout if timeout is None else timeout

    def _parse_and_validate(self, content: Any, schema: JSONDict) -> JSONDict:
        data = parse_json_object(content)
        if schema:
            try:
                validate(instance=data, schema=schema)
            except ValidationError as error:
                raise ProviderError(f"模型返回 JSON 不符合 schema：{error.message}") from error
        return data

    def _schema_prompt(self, schema: JSONDict) -> str:
        return (
            "请只返回一个 JSON object，不要包含 Markdown 或额外说明。"
            f"\nJSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
        )


def api_key_env_names(provider_name: str) -> tuple[str, ...]:
    name = normalize_provider_name(provider_name)
    mapping = {
        "openai": ("OPENAI_API_KEY",),
        "gpt": ("OPENAI_API_KEY",),
        "deepseek": ("DEEPSEEK_API_KEY",),
        "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "ALIYUN_API_KEY"),
        "aliyun": ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "ALIYUN_API_KEY"),
        "bailian": ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "ALIYUN_API_KEY"),
        "百炼": ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "ALIYUN_API_KEY"),
        "阿里云百炼": ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "ALIYUN_API_KEY"),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "ollama": ("OLLAMA_API_KEY",),
        "custom": ("CUSTOM_LLM_API_KEY",),
        "openai_compatible": ("CUSTOM_LLM_API_KEY",),
    }
    return mapping.get(name, (f"{name.upper()}_API_KEY",))


def normalize_provider_name(provider_name: str) -> str:
    return provider_name.strip().lower().replace("-", "_").replace(" ", "_")


def parse_json_object(content: Any) -> JSONDict:
    """Parse a JSON object from provider text or already-decoded dict data."""
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ProviderError(f"模型返回值不是 JSON 文本：{type(content).__name__}")

    text = content.strip()
    candidates = [text, _strip_code_fence(text), _extract_first_json_object(text)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
        raise ProviderError("模型返回 JSON 不是 object。")

    raise ProviderError("无法从模型返回中解析 JSON object。")


def _strip_code_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1]
