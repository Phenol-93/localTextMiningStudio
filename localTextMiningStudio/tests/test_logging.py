import logging

from app.utils import logging as app_logging
from app.utils import paths


def test_setup_logging_writes_redacted_log_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(app_logging, "get_logs_dir", lambda: tmp_path)

    logger = logging.getLogger("local_text_mining_studio")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    configured = app_logging.setup_logging()
    configured.info("openai_api_key=%s", "placeholder-value")
    configured.info('{"api_key": "json-secret"}')
    configured.info("Authorization: Bearer bearer-secret")
    configured.info({"api_key": "abc123", "safe": "visible"})

    for handler in configured.handlers:
        handler.flush()

    log_text = (tmp_path / "app.log").read_text(encoding="utf-8")

    assert "placeholder-value" not in log_text
    assert "json-secret" not in log_text
    assert "bearer-secret" not in log_text
    assert "abc123" not in log_text
    assert "[REDACTED]" in log_text
    assert "visible" in log_text
