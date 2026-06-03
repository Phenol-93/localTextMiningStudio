"""OpenAI-compatible LLM provider."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.providers.base import (
    BaseLLMProvider,
    JSONDict,
    ProviderConfig,
    ProviderError,
    normalize_provider_name,
)


class OpenAICompatibleProvider(BaseLLMProvider):
    """Provider for OpenAI, DeepSeek, Qwen, Ollama /v1, and custom endpoints."""

    def __init__(self, config: ProviderConfig, client: Any | None = None) -> None:
        super().__init__(config)
        self._client = client

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: JSONDict,
        model: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> JSONDict:
        selected_model = self._model(model)
        client = self._client or self._create_client(timeout)
        messages = [
            {"role": "system", "content": f"{system_prompt}\n\n{self._schema_prompt(schema)}"},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = client.chat.completions.create(
                model=selected_model,
                messages=messages,
                temperature=self._temperature(temperature),
                response_format={"type": "json_object"},
                timeout=self._timeout(timeout),
            )
            content = response.choices[0].message.content
        except Exception as error:
            raise ProviderError(f"{self.config.provider_name} 调用失败：{error}") from error

        return self._parse_and_validate(content, schema)

    def _create_client(self, timeout: float | None = None) -> OpenAI:
        provider_name = normalize_provider_name(self.config.provider_name)
        api_key = self.config.resolve_api_key()
        if not api_key and provider_name not in {"ollama", "custom", "openai_compatible"}:
            raise ProviderError(f"{self.config.provider_name} API Key 为空，请在 UI 或环境变量中设置。")

        kwargs: dict[str, Any] = {
            "api_key": api_key or "not-required",
            "timeout": self._timeout(timeout),
        }
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return OpenAI(**kwargs)
