import json
import threading

from app.core.ai_extraction import AIExtractionOptions, run_ai_extraction
from app.db import database
from app.db.repositories import DocumentRepository, ProjectRepository, TripleRepository
from app.utils.background_tasks import TaskCancelled


class FakeProvider:
    def __init__(self, responses=None, fail_on_text=None):
        self.responses = list(responses or [])
        self.fail_on_text = fail_on_text or set()
        self.calls = []

    def generate_json(self, system_prompt, user_prompt, schema, model, temperature, timeout):
        self.calls.append(user_prompt)
        for marker in self.fail_on_text:
            if marker in user_prompt:
                raise RuntimeError("fake provider failure")
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {
            "triples": [
                {
                    "subject": "苹果",
                    "relation": "属于",
                    "object": "水果",
                    "evidence": "苹果 属于 水果",
                    "confidence": 0.9,
                }
            ]
        }


class HangingProvider:
    def __init__(self, wait_seconds=30):
        self.started = threading.Event()
        self.wait_seconds = wait_seconds

    def generate_json(self, system_prompt, user_prompt, schema, model, temperature, timeout):
        self.started.set()
        threading.Event().wait(self.wait_seconds)
        return {"triples": []}


def _project_with_document(tmp_path, cleaned_text="苹果 属于 水果。香蕉 属于 水果。"):
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("AI 抽取测试", tmp_path)
        document_id = DocumentRepository(connection).create(
            project_id,
            "doc",
            filename="doc.txt",
            raw_text=cleaned_text,
        )
        DocumentRepository(connection).save_preprocessing_result(
            document_id,
            cleaned_text,
            {"use_jieba": True},
        )
    return database_path, project_id, document_id


def _options(**kwargs):
    data = {
        "provider_name": "fake",
        "model": "fake-model",
        "prompt_template_name": "通用三元组抽取",
        "text_range": "documents",
        "max_chars": 2000,
        "retries": 1,
    }
    data.update(kwargs)
    return AIExtractionOptions(**data)


def test_ai_extraction_writes_pending_ai_triples(tmp_path) -> None:
    database_path, project_id, _ = _project_with_document(tmp_path)

    result = run_ai_extraction(database_path, project_id, _options(), provider=FakeProvider())

    with database.connection_scope(database_path) as connection:
        triples = TripleRepository(connection).list_by_project(project_id)

    assert result.created_triples == 1
    assert triples[0]["subject"] == "苹果"
    assert triples[0]["predicate"] == "属于"
    assert triples[0]["object"] == "水果"
    assert triples[0]["status"] == "pending"
    assert triples[0]["created_by"] == "ai"
    assert triples[0]["source_text"] == "苹果 属于 水果"


def test_ai_extraction_marks_evidence_warning_without_dropping(tmp_path) -> None:
    database_path, project_id, _ = _project_with_document(tmp_path)
    provider = FakeProvider(
        responses=[
            {
                "triples": [
                    {
                        "subject": "苹果",
                        "relation": "属于",
                        "object": "水果",
                        "evidence": "原文里没有的证据",
                    }
                ]
            }
        ]
    )

    run_ai_extraction(database_path, project_id, _options(), provider=provider)

    with database.connection_scope(database_path) as connection:
        triple = TripleRepository(connection).list_by_project(project_id)[0]

    metadata = json.loads(triple["metadata_json"])
    assert metadata["evidence_warning"] is True
    assert "evidence_not_found" in metadata["warnings"]


def test_ai_extraction_retries_failed_provider_call(tmp_path) -> None:
    database_path, project_id, _ = _project_with_document(tmp_path)
    provider = FakeProvider(responses=[RuntimeError("first failure")])

    result = run_ai_extraction(database_path, project_id, _options(retries=1), provider=provider)

    assert len(provider.calls) == 2
    assert result.created_triples == 1
    assert result.errors == []


def test_ai_extraction_reports_progress_before_provider_returns(tmp_path) -> None:
    database_path, project_id, _ = _project_with_document(tmp_path)
    events = []

    run_ai_extraction(
        database_path,
        project_id,
        _options(),
        provider=FakeProvider(),
        progress_callback=lambda done, total, message: events.append((done, total, message)),
    )

    assert events[0][0] == 0
    assert any(done > 0 and "请求模型" in message for done, _, message in events)
    assert events[-1][0] == events[-1][1]


def test_ai_extraction_times_out_hanging_provider_call(tmp_path) -> None:
    database_path, project_id, _ = _project_with_document(tmp_path)

    result = run_ai_extraction(
        database_path,
        project_id,
        _options(timeout=1, retries=0),
        provider=HangingProvider(),
    )

    assert result.created_triples == 0
    assert result.errors
    assert "超过 1 秒" in result.errors[0]


def test_ai_extraction_can_cancel_during_provider_call(tmp_path) -> None:
    database_path, project_id, _ = _project_with_document(tmp_path)
    provider = HangingProvider()

    try:
        run_ai_extraction(
            database_path,
            project_id,
            _options(timeout=30, retries=0),
            provider=provider,
            cancel_callback=lambda: provider.started.is_set(),
        )
    except TaskCancelled:
        pass
    else:
        raise AssertionError("Expected TaskCancelled")

    with database.connection_scope(database_path) as connection:
        run = connection.execute("SELECT status FROM analysis_runs WHERE project_id = ?", (project_id,)).fetchone()

    assert run["status"] == "canceled"


def test_ai_extraction_chunk_failure_does_not_stop_task(tmp_path) -> None:
    database_path, project_id, document_id = _project_with_document(tmp_path)
    with database.connection_scope(database_path) as connection:
        chunks = connection.execute(
            """
            INSERT INTO chunks (document_id, chunk_index, content)
            VALUES (?, ?, ?), (?, ?, ?)
            """,
            (document_id, 0, "坏文本", document_id, 1, "苹果 属于 水果"),
        )
        assert chunks.rowcount == 2

    result = run_ai_extraction(
        database_path,
        project_id,
        _options(text_range="chunks"),
        provider=FakeProvider(fail_on_text={"坏文本"}),
    )

    with database.connection_scope(database_path) as connection:
        triples = TripleRepository(connection).list_by_project(project_id)
        run = connection.execute("SELECT status FROM analysis_runs WHERE id = ?", (result.analysis_run_id,)).fetchone()

    assert result.created_triples == 1
    assert len(result.errors) == 1
    assert run["status"] == "completed_with_errors"
    assert len(triples) == 1


def test_ai_extraction_can_be_canceled_between_chunks(tmp_path) -> None:
    database_path, project_id, _ = _project_with_document(tmp_path)

    try:
        run_ai_extraction(
            database_path,
            project_id,
            _options(),
            provider=FakeProvider(),
            cancel_callback=lambda: True,
        )
    except TaskCancelled:
        pass
    else:
        raise AssertionError("Expected TaskCancelled")

    with database.connection_scope(database_path) as connection:
        run = connection.execute("SELECT status FROM analysis_runs WHERE project_id = ?", (project_id,)).fetchone()
        triples = TripleRepository(connection).list_by_project(project_id)

    assert run["status"] == "canceled"
    assert triples == []
