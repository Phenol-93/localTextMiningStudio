"""AI-assisted triple extraction core logic."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from jsonschema import ValidationError, validate

from app.core.prompt_templates import PromptTemplate, PromptTemplateManager
from app.db.database import connection_scope, initialize_database
from app.db.repositories import AnalysisRunRepository, TripleRepository
from app.providers import BaseLLMProvider, ProviderConfig, create_provider
from app.utils.background_tasks import TaskCancelled


TextRange = Literal["documents", "chunks"]
ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


class AIExtractionError(Exception):
    """Raised for setup errors in AI extraction."""


class AIProviderCallTimeout(AIExtractionError):
    """Raised when a provider call does not return within the configured timeout."""


@dataclass(frozen=True)
class AIExtractionOptions:
    """JSON-serializable extraction options."""

    provider_name: str
    model: str
    prompt_template_name: str
    text_range: TextRange = "documents"
    max_chars: int = 2000
    temperature: float = 0.2
    timeout: float = 60.0
    retries: int = 1
    base_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "model": self.model,
            "prompt_template_name": self.prompt_template_name,
            "text_range": self.text_range,
            "max_chars": self.max_chars,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "retries": self.retries,
            "base_url": self.base_url,
        }


@dataclass(frozen=True)
class ExtractionTextChunk:
    """A text unit sent to an LLM."""

    document_id: int
    chunk_id: int | None
    text: str
    label: str


@dataclass(frozen=True)
class ExtractionRunResult:
    """Summary for an AI extraction run."""

    analysis_run_id: int
    total_chunks: int
    processed_chunks: int
    created_triples: int
    errors: list[str] = field(default_factory=list)


def run_ai_extraction(
    database_path: Path | str,
    project_id: int,
    options: AIExtractionOptions,
    *,
    provider: BaseLLMProvider | None = None,
    prompt_manager: PromptTemplateManager | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> ExtractionRunResult:
    """Run AI triple extraction and store candidate triples."""
    initialize_database(database_path)
    prompt_manager = prompt_manager or PromptTemplateManager()
    template = prompt_manager.get_template(options.prompt_template_name)
    chunks = load_extraction_chunks(database_path, project_id, options.text_range, options.max_chars)
    if not chunks:
        raise AIExtractionError("没有可抽取的文本。请先导入并预处理文档，或创建 chunks。")

    provider = provider or create_provider(
        ProviderConfig(
            provider_name=options.provider_name,
            base_url=options.base_url,
            model=options.model,
            temperature=options.temperature,
            timeout=options.timeout,
        )
    )

    with connection_scope(database_path) as connection:
        run_id = AnalysisRunRepository(connection).create(
            project_id,
            "ai_triple_extraction",
            status="running",
            parameters=options.to_dict(),
        )

    errors: list[str] = []
    created_triples = 0
    processed = 0
    total = len(chunks)
    total_progress_units = max(1, total * 2)
    _progress(progress_callback, 0, total_progress_units, "开始抽取")

    for index, chunk in enumerate(chunks, start=1):
        try:
            if cancel_callback is not None and cancel_callback():
                raise TaskCancelled("AI 抽取任务已取消。")
            _progress(
                progress_callback,
                (index - 1) * 2 + 1,
                total_progress_units,
                f"正在请求模型 {index}/{total}",
            )
            triples = _extract_chunk_with_retries(
                provider,
                template,
                chunk.text,
                options,
                cancel_callback=cancel_callback,
                progress_callback=progress_callback,
                progress_done=(index - 1) * 2 + 1,
                progress_total=total_progress_units,
                chunk_index=index,
                total_chunks=total,
            )
            if cancel_callback is not None and cancel_callback():
                raise TaskCancelled("AI 抽取任务已取消。")
            created_triples += _save_triples(
                database_path,
                project_id,
                run_id,
                chunk,
                triples,
            )
        except TaskCancelled:
            with connection_scope(database_path) as connection:
                AnalysisRunRepository(connection).finish(run_id, "canceled", "任务已取消。")
            raise
        except Exception as error:
            errors.append(f"{chunk.label} 失败：{error}")
        processed = index
        _progress(
            progress_callback,
            index * 2,
            total_progress_units,
            f"已处理 {processed}/{total}",
        )

    status = "completed" if not errors else "completed_with_errors"
    with connection_scope(database_path) as connection:
        AnalysisRunRepository(connection).finish(run_id, status, "\n".join(errors) if errors else None)

    return ExtractionRunResult(
        analysis_run_id=run_id,
        total_chunks=total,
        processed_chunks=processed,
        created_triples=created_triples,
        errors=errors,
    )


def load_extraction_chunks(
    database_path: Path | str,
    project_id: int,
    text_range: TextRange,
    max_chars: int,
) -> list[ExtractionTextChunk]:
    """Load extraction text from chunks or documents.cleaned_text."""
    max_chars = max(1, int(max_chars))
    with connection_scope(database_path) as connection:
        if text_range == "chunks":
            rows = connection.execute(
                """
                SELECT chunks.id AS chunk_id, chunks.document_id, chunks.content, documents.filename, chunks.chunk_index
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                WHERE documents.project_id = ? AND TRIM(chunks.content) != ''
                ORDER BY documents.id, chunks.chunk_index
                """,
                (project_id,),
            ).fetchall()
            chunks: list[ExtractionTextChunk] = []
            for row in rows:
                for part_index, text in enumerate(split_text(row["content"], max_chars), start=1):
                    chunks.append(
                        ExtractionTextChunk(
                            document_id=int(row["document_id"]),
                            chunk_id=int(row["chunk_id"]),
                            text=text,
                            label=f"chunk:{row['chunk_id']}#{part_index}",
                        )
                    )
            return chunks

        rows = connection.execute(
            """
            SELECT id, filename, title, cleaned_text
            FROM documents
            WHERE project_id = ? AND TRIM(cleaned_text) != ''
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()

    chunks = []
    for row in rows:
        label_base = row["filename"] or row["title"] or f"document:{row['id']}"
        for part_index, text in enumerate(split_text(row["cleaned_text"], max_chars), start=1):
            chunks.append(
                ExtractionTextChunk(
                    document_id=int(row["id"]),
                    chunk_id=None,
                    text=text,
                    label=f"{label_base}#{part_index}",
                )
            )
    return chunks


def split_text(text: str, max_chars: int) -> list[str]:
    """Split text by max characters while keeping non-empty parts."""
    clean = (text or "").strip()
    if not clean:
        return []
    return [clean[index : index + max_chars] for index in range(0, len(clean), max_chars)]


def parse_and_validate_triples(
    response: dict[str, Any],
    template: PromptTemplate,
    source_text: str,
) -> list[dict[str, Any]]:
    """Validate model JSON and normalize triples."""
    try:
        validate(instance=response, schema=template.output_schema)
    except ValidationError as error:
        raise AIExtractionError(f"模型返回 JSON 不符合模板 schema：{error.message}") from error

    raw_triples = response.get("triples")
    if not isinstance(raw_triples, list):
        raise AIExtractionError("模型返回 JSON 缺少 triples 数组。")

    triples: list[dict[str, Any]] = []
    for index, item in enumerate(raw_triples, start=1):
        if not isinstance(item, dict):
            raise AIExtractionError(f"第 {index} 条三元组不是 object。")
        subject = str(item.get("subject", "")).strip()
        relation = str(item.get("relation", item.get("predicate", ""))).strip()
        object_value = str(item.get("object", "")).strip()
        evidence = str(item.get("evidence", item.get("source_text", ""))).strip()
        if not subject or not relation or not object_value or not evidence:
            raise AIExtractionError(f"第 {index} 条三元组缺少 subject/relation/object/evidence。")

        evidence_warning = evidence not in source_text
        triples.append(
            {
                "subject": subject,
                "relation": relation,
                "object": object_value,
                "evidence": evidence,
                "confidence": _optional_float(item.get("confidence")),
                "metadata": {
                    "created_by": "ai",
                    "evidence_warning": evidence_warning,
                    "warnings": ["evidence_not_found"] if evidence_warning else [],
                    "subject_type": item.get("subject_type"),
                    "object_type": item.get("object_type"),
                    "raw": item,
                },
            }
        )
    return triples


def _extract_chunk_with_retries(
    provider: BaseLLMProvider,
    template: PromptTemplate,
    text: str,
    options: AIExtractionOptions,
    *,
    cancel_callback: CancelCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_done: int = 0,
    progress_total: int = 1,
    chunk_index: int = 1,
    total_chunks: int = 1,
) -> list[dict[str, Any]]:
    attempts = max(0, options.retries) + 1
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            if cancel_callback is not None and cancel_callback():
                raise TaskCancelled("AI 抽取任务已取消。")
            response = _call_provider_json_with_guard(
                provider,
                template.system_prompt,
                _render_user_prompt(template, text),
                template.output_schema,
                options.model,
                options.temperature,
                options.timeout,
                cancel_callback=cancel_callback,
                progress_callback=progress_callback,
                progress_done=progress_done,
                progress_total=progress_total,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
            )
            return parse_and_validate_triples(response, template, text)
        except TaskCancelled:
            raise
        except AIProviderCallTimeout:
            raise
        except Exception as error:
            last_error = error
    raise AIExtractionError(str(last_error) if last_error else "模型调用失败。")


def _call_provider_json_with_guard(
    provider: BaseLLMProvider,
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    model: str,
    temperature: float,
    timeout: float,
    *,
    cancel_callback: CancelCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_done: int = 0,
    progress_total: int = 1,
    chunk_index: int = 1,
    total_chunks: int = 1,
) -> dict[str, Any]:
    """Call the provider while keeping cancellation and timeout responsive."""
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    timeout_seconds = max(1.0, float(timeout or 60.0))

    def target() -> None:
        try:
            result = provider.generate_json(
                system_prompt,
                user_prompt,
                schema,
                model,
                temperature,
                timeout_seconds,
            )
        except BaseException as error:
            result_queue.put(("error", error))
        else:
            result_queue.put(("ok", result))

    thread = threading.Thread(target=target, name="ai-provider-json-call", daemon=True)
    thread.start()

    started_at = time.monotonic()
    next_heartbeat_at = started_at + 5.0
    while True:
        try:
            status, payload = result_queue.get(timeout=0.2)
        except queue.Empty:
            elapsed = time.monotonic() - started_at
            if cancel_callback is not None and cancel_callback():
                raise TaskCancelled("AI 抽取任务已取消。")
            if elapsed >= timeout_seconds:
                raise AIProviderCallTimeout(
                    f"模型请求超过 {int(timeout_seconds)} 秒未返回，已停止等待。"
                )
            if progress_callback is not None and elapsed >= next_heartbeat_at:
                _progress(
                    progress_callback,
                    progress_done,
                    progress_total,
                    f"正在请求模型 {chunk_index}/{total_chunks}，已等待 {int(elapsed)} 秒",
                )
                next_heartbeat_at += 5.0
            continue

        if status == "ok":
            return payload
        raise payload


def _render_user_prompt(template: PromptTemplate, text: str) -> str:
    return template.user_prompt_template.format(
        text=text,
        allowed_entity_types=", ".join(template.allowed_entity_types),
        recommended_relations=", ".join(template.recommended_relations),
    )


def _save_triples(
    database_path: Path | str,
    project_id: int,
    run_id: int,
    chunk: ExtractionTextChunk,
    triples: list[dict[str, Any]],
) -> int:
    with connection_scope(database_path) as connection:
        repository = TripleRepository(connection)
        for triple in triples:
            repository.create(
                project_id,
                triple["subject"],
                triple["relation"],
                triple["object"],
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                analysis_run_id=run_id,
                confidence=triple["confidence"],
                status="pending",
                created_by="ai",
                source_text=triple["evidence"],
                metadata=triple["metadata"],
            )
    return len(triples)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _progress(callback: ProgressCallback | None, done: int, total: int, message: str) -> None:
    if callback is not None:
        callback(done, total, message)
