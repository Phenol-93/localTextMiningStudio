"""Repository helpers for project SQLite databases."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _to_json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _from_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class ProjectRepository:
    """CRUD operations for project metadata."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(self, name: str, project_path: Path | str, description: str = "") -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO projects (name, description, project_path)
            VALUES (?, ?, ?)
            """,
            (name, description, str(project_path)),
        )
        return int(cursor.lastrowid)

    def get(self, project_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()

    def get_current(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM projects ORDER BY id LIMIT 1",
        ).fetchone()

    def list_all(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, id DESC",
            )
        )

    def update(self, project_id: int, *, name: str, description: str) -> None:
        self.connection.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, description, project_id),
        )

    def delete(self, project_id: int) -> None:
        self.connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))


class DocumentRepository:
    """CRUD operations for imported documents."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        project_id: int,
        title: str,
        *,
        filename: str | None = None,
        file_path: Path | str | None = None,
        file_type: str | None = None,
        raw_text: str = "",
        content_hash: str | None = None,
        status: str = "new",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO documents (
                project_id, title, filename, file_path, file_type,
                raw_text, content_hash, status, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                title,
                filename or title,
                str(file_path) if file_path is not None else None,
                file_type,
                raw_text,
                content_hash,
                status,
                _to_json(metadata),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, document_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()

    def list_by_project(self, project_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at DESC, id DESC",
                (project_id,),
            )
        )

    def list_preprocessed_by_project(self, project_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT * FROM documents
                WHERE project_id = ? AND TRIM(cleaned_text) != ''
                ORDER BY created_at DESC, id DESC
                """,
                (project_id,),
            )
        )

    def update_status(self, document_id: int, status: str) -> None:
        self.connection.execute(
            """
            UPDATE documents
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, document_id),
        )

    def save_preprocessing_result(
        self,
        document_id: int,
        cleaned_text: str,
        preprocessing_params: dict[str, Any],
    ) -> None:
        self.connection.execute(
            """
            UPDATE documents
            SET cleaned_text = ?,
                preprocessing_params_json = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (cleaned_text, _to_json(preprocessing_params), "preprocessed", document_id),
        )

    def delete(self, document_id: int) -> None:
        self.connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))


class ChunkRepository:
    """CRUD operations for document chunks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        document_id: int,
        chunk_index: int,
        content: str,
        *,
        start_offset: int | None = None,
        end_offset: int | None = None,
        token_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO chunks (
                document_id, chunk_index, content, start_offset, end_offset, token_count, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                chunk_index,
                content,
                start_offset,
                end_offset,
                token_count,
                _to_json(metadata),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, chunk_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()

    def list_by_document(self, document_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index ASC",
                (document_id,),
            )
        )

    def delete(self, chunk_id: int) -> None:
        self.connection.execute("DELETE FROM chunks WHERE id = ?", (chunk_id,))


class AnalysisRunRepository:
    """CRUD operations for analysis runs."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        project_id: int,
        run_type: str,
        *,
        status: str = "pending",
        parameters: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_runs (project_id, run_type, status, parameters_json)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, run_type, status, _to_json(parameters)),
        )
        return int(cursor.lastrowid)

    def get(self, run_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM analysis_runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    def list_by_project(self, project_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM analysis_runs WHERE project_id = ? ORDER BY started_at DESC, id DESC",
                (project_id,),
            )
        )

    def finish(self, run_id: int, status: str, error_message: str | None = None) -> None:
        self.connection.execute(
            """
            UPDATE analysis_runs
            SET status = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, error_message, run_id),
        )

    def delete(self, run_id: int) -> None:
        self.connection.execute("DELETE FROM analysis_runs WHERE id = ?", (run_id,))


class TripleRepository:
    """CRUD operations for extracted triples."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        project_id: int,
        subject: str,
        predicate: str,
        object_value: str,
        *,
        document_id: int | None = None,
        chunk_id: int | None = None,
        analysis_run_id: int | None = None,
        confidence: float | None = None,
        status: str = "pending",
        created_by: str = "ai",
        source_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO triples (
                project_id, document_id, chunk_id, analysis_run_id,
                subject, predicate, object, confidence, status, created_by, source_text, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                document_id,
                chunk_id,
                analysis_run_id,
                subject,
                predicate,
                object_value,
                confidence,
                status,
                created_by,
                source_text,
                _to_json(metadata),
            ),
        )
        return int(cursor.lastrowid)

    def get(self, triple_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM triples WHERE id = ?",
            (triple_id,),
        ).fetchone()

    def list_by_project(self, project_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM triples WHERE project_id = ? ORDER BY created_at DESC, id DESC",
                (project_id,),
            )
        )

    def list_for_review(
        self,
        project_id: int,
        *,
        filters: dict[str, str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        where_sql, params = self._review_where(project_id, filters)
        return list(
            self.connection.execute(
                f"""
                SELECT
                    triples.id,
                    triples.subject,
                    triples.predicate AS relation,
                    triples.object,
                    json_extract(triples.metadata_json, '$.subject_type') AS subject_type,
                    json_extract(triples.metadata_json, '$.object_type') AS object_type,
                    triples.source_text AS evidence,
                    COALESCE(NULLIF(documents.filename, ''), documents.title, '') AS source_doc,
                    triples.confidence,
                    triples.status,
                    triples.document_id,
                    triples.chunk_id,
                    triples.metadata_json
                FROM triples
                LEFT JOIN documents ON documents.id = triples.document_id
                {where_sql}
                ORDER BY triples.updated_at DESC, triples.id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, max(1, limit), max(0, offset)),
            )
        )

    def count_for_review(self, project_id: int, filters: dict[str, str] | None = None) -> int:
        where_sql, params = self._review_where(project_id, filters)
        row = self.connection.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM triples
            LEFT JOIN documents ON documents.id = triples.document_id
            {where_sql}
            """,
            params,
        ).fetchone()
        return int(row["total"])

    def list_filter_values(self, project_id: int, field: str) -> list[str]:
        expressions = {
            "status": "triples.status",
            "relation": "triples.predicate",
            "subject_type": "json_extract(triples.metadata_json, '$.subject_type')",
            "object_type": "json_extract(triples.metadata_json, '$.object_type')",
            "source_doc": "COALESCE(NULLIF(documents.filename, ''), documents.title, '')",
        }
        if field not in expressions:
            raise ValueError(f"Unsupported filter field: {field}")

        rows = self.connection.execute(
            f"""
            SELECT DISTINCT {expressions[field]} AS value
            FROM triples
            LEFT JOIN documents ON documents.id = triples.document_id
            WHERE triples.project_id = ?
                AND {expressions[field]} IS NOT NULL
                AND TRIM({expressions[field]}) != ''
            ORDER BY value
            """,
            (project_id,),
        ).fetchall()
        return [str(row["value"]) for row in rows]

    def update_review_fields(
        self,
        triple_id: int,
        *,
        subject: str | None = None,
        relation: str | None = None,
        object_value: str | None = None,
        subject_type: str | None = None,
        object_type: str | None = None,
        evidence: str | None = None,
    ) -> None:
        current = self.get(triple_id)
        if current is None:
            return

        metadata = _from_json(current["metadata_json"])
        if subject_type is not None:
            metadata["subject_type"] = subject_type
        if object_type is not None:
            metadata["object_type"] = object_type

        self.connection.execute(
            """
            UPDATE triples
            SET subject = ?,
                predicate = ?,
                object = ?,
                source_text = ?,
                metadata_json = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                current["subject"] if subject is None else subject,
                current["predicate"] if relation is None else relation,
                current["object"] if object_value is None else object_value,
                current["source_text"] if evidence is None else evidence,
                _to_json(metadata),
                "edited",
                triple_id,
            ),
        )

    def update_status(self, triple_id: int, status: str) -> None:
        self.connection.execute(
            """
            UPDATE triples
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, triple_id),
        )

    def update_status_many(self, triple_ids: Sequence[int], status: str) -> None:
        ids = [int(triple_id) for triple_id in triple_ids]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self.connection.execute(
            f"""
            UPDATE triples
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            (status, *ids),
        )

    def delete(self, triple_id: int) -> None:
        self.connection.execute("DELETE FROM triples WHERE id = ?", (triple_id,))

    def delete_many(self, triple_ids: Sequence[int]) -> None:
        ids = [int(triple_id) for triple_id in triple_ids]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self.connection.execute(
            f"DELETE FROM triples WHERE id IN ({placeholders})",
            ids,
        )

    def get_source_context(self, triple_id: int, window_chars: int = 300) -> str:
        row = self.connection.execute(
            """
            SELECT
                triples.source_text,
                documents.raw_text,
                documents.cleaned_text,
                chunks.content AS chunk_text
            FROM triples
            LEFT JOIN documents ON documents.id = triples.document_id
            LEFT JOIN chunks ON chunks.id = triples.chunk_id
            WHERE triples.id = ?
            """,
            (triple_id,),
        ).fetchone()
        if row is None:
            return ""

        text = row["chunk_text"] or row["raw_text"] or row["cleaned_text"] or ""
        evidence = row["source_text"] or ""
        if not evidence or evidence not in text:
            return text[: max(1, window_chars * 2)]

        index = text.find(evidence)
        start = max(0, index - window_chars)
        end = min(len(text), index + len(evidence) + window_chars)
        return text[start:end]

    def _review_where(
        self,
        project_id: int,
        filters: dict[str, str] | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        clauses = ["triples.project_id = ?"]
        params: list[Any] = [project_id]
        filters = {key: value for key, value in (filters or {}).items() if value}
        mapping = {
            "status": "triples.status",
            "relation": "triples.predicate",
            "subject_type": "json_extract(triples.metadata_json, '$.subject_type')",
            "object_type": "json_extract(triples.metadata_json, '$.object_type')",
            "source_doc": "COALESCE(NULLIF(documents.filename, ''), documents.title, '')",
        }
        for key, value in filters.items():
            if key not in mapping:
                continue
            clauses.append(f"{mapping[key]} = ?")
            params.append(value)
        return "WHERE " + " AND ".join(clauses), tuple(params)


class RelationMappingRepository:
    """CRUD operations for relation standardization mappings."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert(self, project_id: int, source_relation: str, canonical_relation: str, notes: str = "") -> int:
        self.connection.execute(
            """
            INSERT INTO relation_mappings (project_id, source_relation, canonical_relation, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id, source_relation)
            DO UPDATE SET
                canonical_relation = excluded.canonical_relation,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (project_id, source_relation, canonical_relation, notes),
        )
        row = self.connection.execute(
            """
            SELECT id FROM relation_mappings
            WHERE project_id = ? AND source_relation = ?
            """,
            (project_id, source_relation),
        ).fetchone()
        return int(row["id"])

    def get(self, mapping_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM relation_mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()

    def list_by_project(self, project_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM relation_mappings WHERE project_id = ? ORDER BY source_relation ASC",
                (project_id,),
            )
        )

    def as_dict(self, project_id: int) -> dict[str, str]:
        return {
            row["source_relation"]: row["canonical_relation"]
            for row in self.list_by_project(project_id)
        }

    def delete(self, mapping_id: int) -> None:
        self.connection.execute("DELETE FROM relation_mappings WHERE id = ?", (mapping_id,))


class EntityMappingRepository:
    """CRUD operations for entity standardization mappings."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert(
        self,
        project_id: int,
        source_entity: str,
        canonical_entity: str,
        *,
        entity_type: str | None = None,
        notes: str = "",
    ) -> int:
        self.connection.execute(
            """
            INSERT INTO entity_mappings (
                project_id, source_entity, canonical_entity, entity_type, notes
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id, source_entity)
            DO UPDATE SET
                canonical_entity = excluded.canonical_entity,
                entity_type = excluded.entity_type,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (project_id, source_entity, canonical_entity, entity_type, notes),
        )
        row = self.connection.execute(
            """
            SELECT id FROM entity_mappings
            WHERE project_id = ? AND source_entity = ?
            """,
            (project_id, source_entity),
        ).fetchone()
        return int(row["id"])

    def get(self, mapping_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM entity_mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()

    def list_by_project(self, project_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM entity_mappings WHERE project_id = ? ORDER BY source_entity ASC",
                (project_id,),
            )
        )

    def as_dict(self, project_id: int) -> dict[str, str]:
        return {
            row["source_entity"]: row["canonical_entity"]
            for row in self.list_by_project(project_id)
        }

    def delete(self, mapping_id: int) -> None:
        self.connection.execute("DELETE FROM entity_mappings WHERE id = ?", (mapping_id,))
