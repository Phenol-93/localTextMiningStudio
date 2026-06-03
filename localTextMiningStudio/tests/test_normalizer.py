from app.core.normalizer import (
    entity_frequency_stats,
    normalized_triples_for_graph,
    relation_frequency_stats,
    save_entity_mapping,
    save_relation_mapping,
)
from app.db import database
from app.db.repositories import DocumentRepository, ProjectRepository, TripleRepository


def _project_with_normalization_triples(tmp_path):
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("标准化测试项目", tmp_path)
        document_id = DocumentRepository(connection).create(
            project_id,
            "doc",
            filename="doc.txt",
            raw_text="苹果属于水果。苹果是一种水果。香蕉属于水果。",
        )
        triples = TripleRepository(connection)
        triples.create(
            project_id,
            "苹果",
            "属于",
            "水果",
            document_id=document_id,
            source_text="苹果属于水果",
            metadata={"subject_type": "概念", "object_type": "概念"},
        )
        triples.create(
            project_id,
            "苹果",
            "是一种",
            "水果",
            document_id=document_id,
            source_text="苹果是一种水果",
            metadata={"subject_type": "概念", "object_type": "概念"},
        )
        triples.create(
            project_id,
            "香蕉",
            "属于",
            "水果",
            document_id=document_id,
            source_text="香蕉属于水果",
            metadata={"subject_type": "概念", "object_type": "概念"},
        )
    return database_path, project_id


def test_relation_and_entity_frequency_stats(tmp_path) -> None:
    database_path, project_id = _project_with_normalization_triples(tmp_path)

    relation_stats = relation_frequency_stats(database_path, project_id)
    entity_stats = entity_frequency_stats(database_path, project_id)

    relation_counts = {row.source_relation: row.count for row in relation_stats}
    entity_counts = {row.source_entity: row.count for row in entity_stats}

    assert relation_counts["属于"] == 2
    assert relation_counts["是一种"] == 1
    assert entity_counts["水果"] == 3
    assert entity_counts["苹果"] == 2


def test_mappings_are_saved_and_applied_without_overwriting_triples(tmp_path) -> None:
    database_path, project_id = _project_with_normalization_triples(tmp_path)

    save_relation_mapping(database_path, project_id, "属于", "类型")
    save_relation_mapping(database_path, project_id, "是一种", "类型")
    save_entity_mapping(database_path, project_id, "苹果", "苹果实体", entity_type="概念")

    normalized = normalized_triples_for_graph(database_path, project_id)

    with database.connection_scope(database_path) as connection:
        original = TripleRepository(connection).list_by_project(project_id)

    normalized_relations = {row.relation for row in normalized}
    normalized_subjects = {row.subject for row in normalized}

    assert normalized_relations == {"类型"}
    assert "苹果实体" in normalized_subjects
    assert {row["predicate"] for row in original} == {"属于", "是一种"}
    assert {row["subject"] for row in original} >= {"苹果", "香蕉"}


def test_frequency_stats_show_existing_canonical_mapping(tmp_path) -> None:
    database_path, project_id = _project_with_normalization_triples(tmp_path)

    save_relation_mapping(database_path, project_id, "属于", "类型")
    save_entity_mapping(database_path, project_id, "水果", "水果概念", entity_type="概念")

    relation_stat = next(row for row in relation_frequency_stats(database_path, project_id) if row.source_relation == "属于")
    entity_stat = next(row for row in entity_frequency_stats(database_path, project_id) if row.source_entity == "水果")

    assert relation_stat.canonical_relation == "类型"
    assert entity_stat.canonical_entity == "水果概念"
