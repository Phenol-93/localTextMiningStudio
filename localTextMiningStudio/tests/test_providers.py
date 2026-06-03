import pytest

from app.providers import ProviderConfig, create_provider
from app.providers.base import ProviderError, parse_json_object
from app.providers.gemini_provider import GeminiProvider
from app.providers.ollama_provider import OLLAMA_OPENAI_BASE_URL, OllamaProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.registry import DEEPSEEK_BASE_URL, QWEN_BASE_URL, with_provider_defaults


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


class _FakeOpenAIClient:
    def __init__(self, content='{"answer": "ok"}', error=None) -> None:
        self.chat = _FakeChat(content, error)


class _FakeChat:
    def __init__(self, content, error) -> None:
        self.completions = _FakeCompletions(content, error)


class _FakeCompletions:
    def __init__(self, content, error) -> None:
        self.content = content
        self.error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return _Response(self.content)


class _Response:
    def __init__(self, content) -> None:
        self.choices = [_Choice(content)]


class _Choice:
    def __init__(self, content) -> None:
        self.message = _Message(content)


class _Message:
    def __init__(self, content) -> None:
        self.content = content


class _FakeGeminiClient:
    def __init__(self) -> None:
        self.models = _FakeGeminiModels()


class _FakeGeminiModels:
    def __init__(self) -> None:
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return type("GeminiResponse", (), {"text": '{"answer": "gemini"}'})()


class _FakeOllamaClient:
    def __init__(self) -> None:
        self.kwargs = None

    def chat(self, **kwargs):
        self.kwargs = kwargs
        return {"message": {"content": '{"answer": "ollama"}'}}


def test_openai_compatible_generate_json_uses_uniform_interface() -> None:
    client = _FakeOpenAIClient()
    provider = OpenAICompatibleProvider(
        ProviderConfig(provider_name="custom", base_url="http://example.test/v1", api_key="test", model="manual"),
        client=client,
    )

    data = provider.generate_json("system", "user", SCHEMA, model="override", temperature=0.1, timeout=5)

    assert data == {"answer": "ok"}
    assert client.chat.completions.kwargs["model"] == "override"
    assert client.chat.completions.kwargs["response_format"] == {"type": "json_object"}


def test_gemini_provider_generate_json_with_mock_client() -> None:
    client = _FakeGeminiClient()
    provider = GeminiProvider(
        ProviderConfig(provider_name="gemini", api_key="test", model="manual"),
        client=client,
    )

    data = provider.generate_json("system", "user", SCHEMA)

    assert data == {"answer": "gemini"}
    assert client.models.kwargs["model"] == "manual"
    assert client.models.kwargs["config"]["response_mime_type"] == "application/json"


def test_ollama_sdk_provider_generate_json_with_mock_client() -> None:
    client = _FakeOllamaClient()
    provider = OllamaProvider(
        ProviderConfig(provider_name="ollama", model="llama"),
        use_sdk=True,
        client=client,
    )

    data = provider.generate_json("system", "user", SCHEMA)

    assert data == {"answer": "ollama"}
    assert client.kwargs["format"] == SCHEMA


def test_registry_routes_supported_providers() -> None:
    assert isinstance(create_provider(ProviderConfig(provider_name="deepseek", model="x")), OpenAICompatibleProvider)
    assert isinstance(create_provider(ProviderConfig(provider_name="qwen", model="x")), OpenAICompatibleProvider)
    assert isinstance(create_provider(ProviderConfig(provider_name="gemini", model="x")), GeminiProvider)
    assert isinstance(create_provider(ProviderConfig(provider_name="ollama", model="x")), OllamaProvider)


def test_provider_defaults_allow_custom_models_and_urls() -> None:
    deepseek = with_provider_defaults(ProviderConfig(provider_name="deepseek", model="user-model"))
    qwen = with_provider_defaults(ProviderConfig(provider_name="qwen", model="user-model"))
    bailian = with_provider_defaults(ProviderConfig(provider_name="阿里云百炼", model="user-model"))
    ollama = with_provider_defaults(ProviderConfig(provider_name="ollama", model="user-model"))
    custom = with_provider_defaults(
        ProviderConfig(provider_name="custom", base_url="http://custom.test/v1", api_key="ui-key", model="m")
    )

    assert deepseek.base_url == DEEPSEEK_BASE_URL
    assert qwen.base_url == QWEN_BASE_URL
    assert bailian.base_url == QWEN_BASE_URL
    assert ollama.base_url == OLLAMA_OPENAI_BASE_URL
    assert custom.base_url == "http://custom.test/v1"
    assert custom.model == "m"


def test_config_resolves_api_key_from_environment_without_serializing_it(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")

    config = ProviderConfig(provider_name="openai", model="manual")

    assert config.resolve_api_key() == "env-secret"
    assert config.to_dict()["api_key"] is None
    assert config.to_dict(include_api_key=True)["api_key"] is None


def test_error_messages_redact_api_keys() -> None:
    provider = OpenAICompatibleProvider(
        ProviderConfig(provider_name="custom", api_key="placeholder-value", model="manual"),
        client=_FakeOpenAIClient(error=RuntimeError("api_key=placeholder-value failed")),
    )

    with pytest.raises(ProviderError) as error:
        provider.generate_json("system", "user", SCHEMA)

    message = str(error.value)
    assert "placeholder-value" not in message
    assert "[REDACTED]" in message


def test_parse_json_object_handles_markdown_fences() -> None:
    assert parse_json_object('```json\n{"answer": "ok"}\n```') == {"answer": "ok"}
