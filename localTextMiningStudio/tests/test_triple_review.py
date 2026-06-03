import json

from app.db import database
from app.db.repositories import DocumentRepository, ProjectRepository, TripleRepository


def _project_with_triples(tmp_path):
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("审核测试项目", tmp_path)
        document_id = DocumentRepository(connection).create(
            project_id,
            "source-doc",
            filename="source.txt",
            raw_text="苹果属于水果。香蕉属于水果。",
        )
        triples = TripleRepository(connection)
        first_id = triples.create(
            project_id,
            "苹果",
            "属于",
            "水果",
            document_id=document_id,
            confidence=0.9,
            status="pending",
            source_text="苹果属于水果",
            metadata={"subject_type": "概念", "object_type": "概念"},
        )
        second_id = triples.create(
            project_id,
            "香蕉",
            "属于",
            "水果",
            document_id=document_id,
            confidence=0.8,
            status="pending",
            source_text="香蕉属于水果",
            metadata={"subject_type": "概念", "object_type": "概念"},
        )
    return database_path, project_id, first_id, second_id


def test_triple_review_list_filters_and_context(tmp_path) -> None:
    database_path, project_id, first_id, _ = _project_with_triples(tmp_path)

    with database.connection_scope(database_path) as connection:
        repository = TripleRepository(connection)
        rows = repository.list_for_review(
            project_id,
            filters={"status": "pending", "relation": "属于", "source_doc": "source.txt"},
            limit=20,
        )
        context = repository.get_source_context(first_id)
        statuses = repository.list_filter_values(project_id, "status")

    assert len(rows) == 2
    assert rows[0]["source_doc"] == "source.txt"
    assert rows[0]["subject_type"] == "概念"
    assert "苹果属于水果" in context
    assert "pending" in statuses


def test_triple_review_edit_marks_status_edited(tmp_path) -> None:
    database_path, _, first_id, _ = _project_with_triples(tmp_path)

    with database.connection_scope(database_path) as connection:
        repository = TripleRepository(connection)
        repository.update_review_fields(
            first_id,
            subject="红苹果",
            relation="是一种",
            object_value="水果",
            subject_type="实体",
            evidence="苹果属于水果",
        )
        triple = repository.get(first_id)

    metadata = json.loads(triple["metadata_json"])
    assert triple["subject"] == "红苹果"
    assert triple["predicate"] == "是一种"
    assert triple["status"] == "edited"
    assert metadata["subject_type"] == "实体"


def test_triple_review_batch_status_and_delete(tmp_path) -> None:
    database_path, project_id, first_id, second_id = _project_with_triples(tmp_path)

    with database.connection_scope(database_path) as connection:
        repository = TripleRepository(connection)
        repository.update_status_many([first_id, second_id], "accepted")
        accepted = repository.list_for_review(project_id, filters={"status": "accepted"})
        repository.delete_many([first_id])
        remaining = repository.list_for_review(project_id)

    assert len(accepted) == 2
    assert len(remaining) == 1
    assert remaining[0]["id"] == second_id
