import csv

from app.core.exporter import EDGES_HEADER, NODES_HEADER, TRIPLES_HEADER, export_project_csvs
from app.db import database
from app.db.repositories import (
    ChunkRepository,
    DocumentRepository,
    EntityMappingRepository,
    ProjectRepository,
    RelationMappingRepository,
    TripleRepository,
)


def _read_csv(path):
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def test_export_project_csvs_writes_expected_headers_and_filtered_content(tmp_path) -> None:
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("导出测试项目", tmp_path)
        document_id = DocumentRepository(connection).create(
            project_id,
            "合同文档",
            filename="合同.txt",
            raw_text="公司A签署合同。公司甲签署合同。",
        )
        chunk_id = ChunkRepository(connection).create(
            document_id,
            0,
            "公司甲签署合同。",
            metadata={"page": 3},
        )
        triples = TripleRepository(connection)
        triples.create(
            project_id,
            "公司A",
            "签署",
            "合同",
            document_id=document_id,
            confidence=0.9,
            status="accepted",
            created_by="ai",
            source_text="公司A签署合同",
            metadata={"subject_type": "组织", "object_type": "文件", "page": 8},
        )
        triples.create(
            project_id,
            "公司甲",
            "签署",
            "合同",
            document_id=document_id,
            chunk_id=chunk_id,
            confidence=0.7,
            status="accepted",
            created_by="human",
            source_text="公司甲签署合同",
            metadata={"subject_type": "组织", "object_type": "文件"},
        )
        triples.create(
            project_id,
            "个人",
            "拥有",
            "公司A",
            document_id=document_id,
            status="rejected",
            source_text="个人拥有公司A",
            metadata={"subject_type": "人物", "object_type": "组织"},
        )
        RelationMappingRepository(connection).upsert(project_id, "签署", "签订")
        EntityMappingRepository(connection).upsert(project_id, "公司甲", "公司A", entity_type="组织")

    result = export_project_csvs(
        database_path,
        project_id,
        tmp_path / "exports",
        filters={"status": "accepted"},
    )

    assert result.triple_count == 2
    assert result.node_count == 2
    assert result.edge_count == 1
    for path in [result.triples_csv, result.nodes_csv, result.edges_csv]:
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")

    triples_rows = _read_csv(result.triples_csv)
    assert list(triples_rows[0].keys()) == TRIPLES_HEADER
    assert {row["subject"] for row in triples_rows} == {"公司A", "公司甲"}
    assert {row["status"] for row in triples_rows} == {"accepted"}
    assert "个人" not in {row["subject"] for row in triples_rows}
    assert {row["page"] for row in triples_rows} == {"8", "3"}
    assert triples_rows[0]["source_doc"] == "合同.txt"

    edge_rows = _read_csv(result.edges_csv)
    assert list(edge_rows[0].keys()) == EDGES_HEADER
    assert edge_rows == [
        {
            "Source": "公司A",
            "Target": "合同",
            "Label": "签订",
            "Weight": "2",
            "Type": "Directed",
            "Evidence": "公司A签署合同",
            "SourceDoc": "合同.txt",
            "Confidence": "0.8",
            "Status": "accepted",
        }
    ]

    node_rows = _read_csv(result.nodes_csv)
    assert list(node_rows[0].keys()) == NODES_HEADER
    node_by_id = {row["Id"]: row for row in node_rows}
    assert set(node_by_id) == {"公司A", "合同"}
    assert node_by_id["公司A"]["Type"] == "组织"
    assert node_by_id["合同"]["Type"] == "文件"
    assert node_by_id["公司A"]["OutDegree"] == "1"
    assert node_by_id["合同"]["InDegree"] == "1"
