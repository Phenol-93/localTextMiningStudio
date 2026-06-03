"""Provider registry and factory helpers."""

from __future__ import annotations

from app.providers.base import BaseLLMProvider, ProviderConfig, ProviderError, normalize_provider_name
from app.providers.gemini_provider import GeminiProvider
from app.providers.ollama_provider import OLLAMA_OPENAI_BASE_URL, OllamaProvider
from app.providers.openai_compatible import OpenAICompatibleProvider


OPENAI_BASE_URL = "https://api.openai.com/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


OPENAI_COMPATIBLE_NAMES = {
    "openai",
    "gpt",
    "deepseek",
    "qwen",
    "aliyun",
    "bailian",
    "百炼",
    "阿里云百炼",
    "custom",
    "openai_compatible",
}


def create_provider(config: ProviderConfig, *, ollama_use_sdk: bool = False) -> BaseLLMProvider:
    """Create a provider implementation from a config object."""
    normalized = normalize_provider_name(config.provider_name)
    config = with_provider_defaults(config)

    if normalized in OPENAI_COMPATIBLE_NAMES:
        return OpenAICompatibleProvider(config)
    if normalized in {"gemini", "google"}:
        return GeminiProvider(config)
    if normalized == "ollama":
        return OllamaProvider(config, use_sdk=ollama_use_sdk)

    raise ProviderError(f"未知供应商：{config.provider_name}")


def with_provider_defaults(config: ProviderConfig) -> ProviderConfig:
    """Fill provider-specific default base URLs while preserving user input."""
    normalized = normalize_provider_name(config.provider_name)
    base_url = config.base_url

    if not base_url:
        if normalized in {"openai", "gpt"}:
            base_url = OPENAI_BASE_URL
        elif normalized == "deepseek":
            base_url = DEEPSEEK_BASE_URL
        elif normalized in {"qwen", "aliyun", "bailian", "百炼", "阿里云百炼"}:
            base_url = QWEN_BASE_URL
        elif normalized == "ollama":
            base_url = OLLAMA_OPENAI_BASE_URL

    return ProviderConfig(
        provider_name=config.provider_name,
        base_url=base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=config.temperature,
        timeout=config.timeout,
    )


def supported_provider_names() -> list[str]:
    """Return user-facing provider names."""
    return [
        "openai",
        "gemini",
        "deepseek",
        "qwen",
        "aliyun",
        "bailian",
        "阿里云百炼",
        "ollama",
        "custom",
        "openai_compatible",
    ]
