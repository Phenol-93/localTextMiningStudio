"""Ollama provider adapters."""

from __future__ import annotations

from typing import Any

import ollama

from app.providers.base import BaseLLMProvider, JSONDict, ProviderConfig, ProviderError
from app.providers.openai_compatible import OpenAICompatibleProvider


OLLAMA_OPENAI_BASE_URL = "http://localhost:11434/v1"
OLLAMA_SDK_HOST = "http://localhost:11434"


class OllamaProvider(BaseLLMProvider):
    """Provider for local Ollama models.

    By default this uses Ollama's OpenAI-compatible endpoint. Set
    ``use_sdk=True`` to use the ollama Python SDK adapter.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        use_sdk: bool = False,
        client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self.use_sdk = use_sdk
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
        if not self.use_sdk:
            config = ProviderConfig(
                provider_name="ollama",
                base_url=self.config.base_url or OLLAMA_OPENAI_BASE_URL,
                api_key=self.config.api_key or "ollama",
                model=self.config.model,
                temperature=self.config.temperature,
                timeout=self.config.timeout,
            )
            return OpenAICompatibleProvider(config, client=self._client).generate_json(
                system_prompt,
                user_prompt,
                schema,
                model,
                temperature,
                timeout,
            )

        selected_model = self._model(model)
        client = self._client or self._create_client()
        messages = [
            {"role": "system", "content": f"{system_prompt}\n\n{self._schema_prompt(schema)}"},
            {"role": "user", "content": user_prompt},
        ]
        try:
            response = client.chat(
                model=selected_model,
                messages=messages,
                format=schema or "json",
                options={"temperature": self._temperature(temperature)},
            )
            content = _extract_ollama_content(response)
        except Exception as error:
            raise ProviderError(f"Ollama 调用失败：{error}") from error

        return self._parse_and_validate(content, schema)

    def _create_client(self):
        return ollama.Client(host=self.config.base_url or OLLAMA_SDK_HOST)


def _extract_ollama_content(response: Any) -> str:
    if isinstance(response, dict):
        message = response.get("message", {})
        return str(message.get("content", ""))
    message = getattr(response, "message", None)
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))
