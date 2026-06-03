from app.db import database
from app.db.repositories import (
    AnalysisRunRepository,
    ChunkRepository,
    DocumentRepository,
    EntityMappingRepository,
    ProjectRepository,
    RelationMappingRepository,
    TripleRepository,
)


def test_initialize_database_creates_expected_tables(tmp_path) -> None:
    database_path = tmp_path / "project.sqlite"

    database.initialize_database(database_path)

    with database.connection_scope(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = ? AND name NOT LIKE ?
            ORDER BY name
            """,
            ("table", "sqlite_%"),
        ).fetchall()

    table_names = {row["name"] for row in rows}

    assert {
        "projects",
        "documents",
        "chunks",
        "analysis_runs",
        "triples",
        "relation_mappings",
        "entity_mappings",
    } <= table_names

    with database.connection_scope(database_path) as connection:
        document_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(documents)")
        }
        triple_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(triples)")
        }

    assert {"cleaned_text", "preprocessing_params_json"} <= document_columns
    assert "created_by" in triple_columns


def test_get_schema_sql_loads_project_schema() -> None:
    schema_sql = database.get_schema_sql()

    assert "CREATE TABLE IF NOT EXISTS projects" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS triples" in schema_sql


def test_create_project_database_uses_projects_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "get_projects_dir", lambda: tmp_path)

    database_path = database.create_project_database("中文 项目")

    assert database_path.parent.parent == tmp_path
    assert database_path.name == "project.sqlite"
    assert database_path.exists()


def test_repositories_create_and_read_core_records(tmp_path) -> None:
    database_path = database.initialize_database(tmp_path / "project.sqlite")

    with database.connection_scope(database_path) as connection:
        projects = ProjectRepository(connection)
        project_id = projects.create("测试项目", tmp_path)

        documents = DocumentRepository(connection)
        document_id = documents.create(project_id, "文档 A", file_type="txt")
        documents.save_preprocessing_result(
            document_id,
            "甲方 签署 合同",
            {"use_jieba": True, "min_word_length": 1},
        )

        chunks = ChunkRepository(connection)
        chunk_id = chunks.create(document_id, 0, "甲方 签署 合同", token_count=3)

        runs = AnalysisRunRepository(connection)
        run_id = runs.create(project_id, "triples", status="running")

        triples = TripleRepository(connection)
        triple_id = triples.create(
            project_id,
            "甲方",
            "签署",
            "合同",
            document_id=document_id,
            chunk_id=chunk_id,
            analysis_run_id=run_id,
            confidence=0.95,
        )

        relations = RelationMappingRepository(connection)
        relation_mapping_id = relations.upsert(project_id, "签署", "签订")

        entities = EntityMappingRepository(connection)
        entity_mapping_id = entities.upsert(project_id, "甲方", "甲方公司", entity_type="组织")

        assert projects.get(project_id)["name"] == "测试项目"
        assert documents.get(document_id)["title"] == "文档 A"
        assert documents.get(document_id)["cleaned_text"] == "甲方 签署 合同"
        assert chunks.get(chunk_id)["content"] == "甲方 签署 合同"
        assert runs.get(run_id)["run_type"] == "triples"
        assert triples.get(triple_id)["predicate"] == "签署"
        assert triples.get(triple_id)["created_by"] == "ai"
        assert relations.get(relation_mapping_id)["canonical_relation"] == "签订"
        assert entities.get(entity_mapping_id)["canonical_entity"] == "甲方公司"
