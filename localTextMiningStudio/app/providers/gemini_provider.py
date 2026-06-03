"""Gemini provider using google-genai."""

from __future__ import annotations

from typing import Any

from google import genai

from app.providers.base import BaseLLMProvider, JSONDict, ProviderConfig, ProviderError


class GeminiProvider(BaseLLMProvider):
    """Provider for Gemini models through google-genai."""

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
        prompt = f"{system_prompt}\n\n{self._schema_prompt(schema)}\n\n用户输入：\n{user_prompt}"
        config = {
            "temperature": self._temperature(temperature),
            "response_mime_type": "application/json",
        }

        try:
            response = client.models.generate_content(
                model=selected_model,
                contents=prompt,
                config=config,
            )
            content = getattr(response, "text", None) or _extract_gemini_text(response)
        except Exception as error:
            raise ProviderError(f"Gemini 调用失败：{error}") from error

        return self._parse_and_validate(content, schema)

    def _create_client(self, timeout: float | None = None):
        api_key = self.config.resolve_api_key()
        if not api_key:
            raise ProviderError("Gemini API Key 为空，请在 UI 或 GEMINI_API_KEY/GOOGLE_API_KEY 中设置。")

        http_options = {"timeout": int(self._timeout(timeout) * 1000)}
        return genai.Client(api_key=api_key, http_options=http_options)


def _extract_gemini_text(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            continue
        texts = [getattr(part, "text", "") for part in parts if getattr(part, "text", "")]
        if texts:
            return "\n".join(texts)
    return ""
