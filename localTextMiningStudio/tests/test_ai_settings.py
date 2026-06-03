import json

from app.providers.base import ProviderConfig
from app.providers.registry import QWEN_BASE_URL, with_provider_defaults
from app.providers.settings import (
    AIProviderSettings,
    clear_session_api_key,
    clear_saved_api_key,
    load_ai_settings,
    load_saved_api_key,
    load_session_api_key,
    remember_session_api_key,
    save_ai_settings,
    save_api_key,
)
from app.ui.settings_page import _ConnectionTestWorker


def test_ai_settings_json_does_not_store_api_key(tmp_path) -> None:
    settings_path = tmp_path / "ai_settings.json"
    settings = AIProviderSettings(
        provider_name="custom",
        base_url="http://example.test/v1",
        model="manual-model",
        temperature=0.3,
        timeout=12,
        save_api_key=True,
    )

    save_ai_settings(settings, settings_path)
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    loaded = load_ai_settings(settings_path)

    assert "api_key" not in raw
    assert loaded.provider_name == "custom"
    assert loaded.model == "manual-model"
    assert loaded.save_api_key is True


def test_keyring_save_load_and_clear_are_used(monkeypatch) -> None:
    storage = {}

    def fake_set_password(service, account, password):
        storage[(service, account)] = password

    def fake_get_password(service, account):
        return storage.get((service, account))

    def fake_delete_password(service, account):
        storage.pop((service, account), None)

    monkeypatch.setattr("app.providers.settings.keyring.set_password", fake_set_password)
    monkeypatch.setattr("app.providers.settings.keyring.get_password", fake_get_password)
    monkeypatch.setattr("app.providers.settings.keyring.delete_password", fake_delete_password)

    save_api_key("openai", "placeholder-value")
    assert load_saved_api_key("openai") == "placeholder-value"

    clear_saved_api_key("openai")
    assert load_saved_api_key("openai") is None


def test_session_api_key_is_process_local_and_clearable() -> None:
    remember_session_api_key("openai", "session-placeholder")
    assert load_session_api_key("openai") == "session-placeholder"

    remember_session_api_key("openai", "")
    assert load_session_api_key("openai") is None

    remember_session_api_key("openai", "session-placeholder")
    clear_session_api_key("openai")
    assert load_session_api_key("openai") is None


def test_provider_defaults_for_settings() -> None:
    qwen = with_provider_defaults(ProviderConfig(provider_name="qwen", model="manual-model"))
    custom = with_provider_defaults(
        ProviderConfig(provider_name="custom", base_url="http://custom.test/v1", model="custom-model")
    )
    ollama = AIProviderSettings(provider_name="ollama", model="local-model").to_provider_config()

    assert qwen.base_url == QWEN_BASE_URL
    assert custom.base_url == "http://custom.test/v1"
    assert custom.model == "custom-model"
    assert ollama.base_url == "http://localhost:11434/v1"


def test_connection_worker_can_be_mocked_without_real_api(monkeypatch) -> None:
    calls = {}

    class FakeProvider:
        def generate_json(self, system_prompt, user_prompt, schema, model, temperature, timeout):
            calls["system_prompt"] = system_prompt
            calls["user_prompt"] = user_prompt
            calls["schema"] = schema
            calls["model"] = model
            return {"ok": True}

    monkeypatch.setattr("app.ui.settings_page.create_provider", lambda config: FakeProvider())
    worker = _ConnectionTestWorker(ProviderConfig(provider_name="custom", base_url="http://x", model="m"))

    worker.run()

    assert calls["schema"]["required"] == ["ok"]
    assert calls["model"] == "m"
    assert "文档" not in calls["user_prompt"]
