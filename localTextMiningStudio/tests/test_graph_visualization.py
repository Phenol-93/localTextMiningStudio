from app.core.graph_visualization import (
    GraphVisualizationOptions,
    export_standalone_graph_html,
    generate_graph_json,
)
from app.db import database
from app.db.repositories import (
    DocumentRepository,
    EntityMappingRepository,
    ProjectRepository,
    RelationMappingRepository,
    TripleRepository,
)


def _project(tmp_path):
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("可视化测试项目", tmp_path)
        document_id = DocumentRepository(connection).create(
            project_id,
            "doc",
            filename="doc.txt",
            raw_text="公司A签署合同。公司甲签署合同。人物拥有公司A。",
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
            source_text="公司A签署合同",
            metadata={"subject_type": "组织", "object_type": "文件"},
        )
        triples.create(
            project_id,
            "公司甲",
            "签署",
            "合同",
            document_id=document_id,
            confidence=0.7,
            status="edited",
            source_text="公司甲签署合同",
            metadata={"subject_type": "组织", "object_type": "文件"},
        )
        triples.create(
            project_id,
            "人物",
            "拥有",
            "公司A",
            document_id=document_id,
            status="pending",
            source_text="人物拥有公司A",
            metadata={"subject_type": "人物", "object_type": "组织"},
        )
        triples.create(
            project_id,
            "噪声",
            "忽略",
            "公司A",
            document_id=document_id,
            status="rejected",
            source_text="噪声忽略公司A",
        )
        RelationMappingRepository(connection).upsert(project_id, "签署", "签订")
        EntityMappingRepository(connection).upsert(project_id, "公司甲", "公司A", entity_type="组织")
    return database_path, project_id


def test_generate_graph_json_defaults_to_reviewed_mapped_graph(tmp_path) -> None:
    database_path, project_id = _project(tmp_path)

    data = generate_graph_json(
        database_path,
        project_id,
        options=GraphVisualizationOptions(top_n=1, max_nodes=10),
    )

    assert data["meta"]["node_count"] == 2
    assert data["meta"]["edge_count"] == 1
    assert data["meta"]["default_top_n"] == 1
    assert data["meta"]["truncated"] is False

    nodes = {node["data"]["id"]: node for node in data["nodes"]}
    assert set(nodes) == {"公司A", "合同"}
    assert nodes["公司A"]["data"]["type"] == "组织"
    assert sum(1 for node in data["nodes"] if node["default_visible"]) == 1

    edge = data["edges"][0]["data"]
    assert edge["source"] == "公司A"
    assert edge["target"] == "合同"
    assert edge["relation"] == "签订"
    assert edge["weight"] == 2
    assert edge["confidence"] == "0.8"
    assert edge["source_doc"] == "doc.txt"
    assert set(edge["statuses"]) == {"accepted", "edited"}
    assert data["filters"]["relations"] == ["签订"]
    assert data["filters"]["entity_types"] == ["文件", "组织"]
    assert data["filters"]["statuses"] == ["accepted", "edited"]


def test_generate_graph_json_can_include_pending_and_export_standalone_html(tmp_path) -> None:
    database_path, project_id = _project(tmp_path)

    data = generate_graph_json(
        database_path,
        project_id,
        options=GraphVisualizationOptions(include_pending=True, top_n=3, max_nodes=3),
    )
    output = export_standalone_graph_html(data, tmp_path / "graph.html")
    html = output.read_text(encoding="utf-8")

    assert data["meta"]["node_count"] == 3
    assert data["meta"]["edge_count"] == 2
    assert "pending" in data["filters"]["statuses"]
    assert "噪声" not in {node["data"]["id"] for node in data["nodes"]}
    assert "window.__GRAPH_DATA__" in html
    assert "cytoscape" in html
    assert "公司A" in html
