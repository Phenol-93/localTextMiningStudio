"""Entity and relation normalization helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.database import connection_scope
from app.db.repositories import EntityMappingRepository, RelationMappingRepository


@dataclass(frozen=True)
class RelationStat:
    source_relation: str
    count: int
    example_evidence: str
    canonical_relation: str


@dataclass(frozen=True)
class EntityStat:
    source_entity: str
    count: int
    entity_type: str
    canonical_entity: str


@dataclass(frozen=True)
class NormalizedTriple:
    triple_id: int
    subject: str
    relation: str
    object: str
    original_subject: str
    original_relation: str
    original_object: str
    subject_type: str
    object_type: str
    evidence: str
    status: str


def relation_frequency_stats(database_path: Path | str, project_id: int) -> list[RelationStat]:
    """Count relation frequency from triples without mutating source triples."""
    with connection_scope(database_path) as connection:
        mapping = RelationMappingRepository(connection).as_dict(project_id)
        rows = connection.execute(
            """
            SELECT
                predicate AS source_relation,
                COUNT(*) AS count,
                MIN(COALESCE(source_text, '')) AS example_evidence
            FROM triples
            WHERE project_id = ? AND TRIM(predicate) != ''
            GROUP BY predicate
            ORDER BY count DESC, predicate ASC
            """,
            (project_id,),
        ).fetchall()

    return [
        RelationStat(
            source_relation=row["source_relation"],
            count=int(row["count"]),
            example_evidence=row["example_evidence"] or "",
            canonical_relation=mapping.get(row["source_relation"], row["source_relation"]),
        )
        for row in rows
    ]


def entity_frequency_stats(database_path: Path | str, project_id: int) -> list[EntityStat]:
    """Count subject/object entity frequency from triples."""
    with connection_scope(database_path) as connection:
        mapping = EntityMappingRepository(connection).as_dict(project_id)
        rows = connection.execute(
            """
            WITH entities AS (
                SELECT
                    subject AS source_entity,
                    json_extract(metadata_json, '$.subject_type') AS entity_type
                FROM triples
                WHERE project_id = ? AND TRIM(subject) != ''
                UNION ALL
                SELECT
                    object AS source_entity,
                    json_extract(metadata_json, '$.object_type') AS entity_type
                FROM triples
                WHERE project_id = ? AND TRIM(object) != ''
            )
            SELECT
                source_entity,
                COALESCE(NULLIF(entity_type, ''), '') AS entity_type,
                COUNT(*) AS count
            FROM entities
            GROUP BY source_entity, COALESCE(NULLIF(entity_type, ''), '')
            ORDER BY count DESC, source_entity ASC
            """,
            (project_id, project_id),
        ).fetchall()

    return [
        EntityStat(
            source_entity=row["source_entity"],
            count=int(row["count"]),
            entity_type=row["entity_type"] or "",
            canonical_entity=mapping.get(row["source_entity"], row["source_entity"]),
        )
        for row in rows
    ]


def save_relation_mapping(
    database_path: Path | str,
    project_id: int,
    source_relation: str,
    canonical_relation: str,
    notes: str = "",
) -> int:
    with connection_scope(database_path) as connection:
        return RelationMappingRepository(connection).upsert(
            project_id,
            source_relation.strip(),
            canonical_relation.strip(),
            notes,
        )


def save_entity_mapping(
    database_path: Path | str,
    project_id: int,
    source_entity: str,
    canonical_entity: str,
    *,
    entity_type: str | None = None,
    notes: str = "",
) -> int:
    with connection_scope(database_path) as connection:
        return EntityMappingRepository(connection).upsert(
            project_id,
            source_entity.strip(),
            canonical_entity.strip(),
            entity_type=entity_type,
            notes=notes,
        )


def normalized_triples_for_graph(database_path: Path | str, project_id: int) -> list[NormalizedTriple]:
    """Return triples with mappings applied for graph construction/export.

    This function intentionally does not update the original triples table.
    """
    with connection_scope(database_path) as connection:
        relation_mapping = RelationMappingRepository(connection).as_dict(project_id)
        entity_mapping = EntityMappingRepository(connection).as_dict(project_id)
        rows = connection.execute(
            """
            SELECT id, subject, predicate, object, source_text, status, metadata_json
            FROM triples
            WHERE project_id = ?
            ORDER BY id ASC
            """,
            (project_id,),
        ).fetchall()

    normalized: list[NormalizedTriple] = []
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        subject = row["subject"]
        relation = row["predicate"]
        object_value = row["object"]
        normalized.append(
            NormalizedTriple(
                triple_id=int(row["id"]),
                subject=entity_mapping.get(subject, subject),
                relation=relation_mapping.get(relation, relation),
                object=entity_mapping.get(object_value, object_value),
                original_subject=subject,
                original_relation=relation,
                original_object=object_value,
                subject_type=metadata.get("subject_type") or "",
                object_type=metadata.get("object_type") or "",
                evidence=row["source_text"] or "",
                status=row["status"],
            )
        )
    return normalized


def _metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
