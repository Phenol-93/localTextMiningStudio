from app.core.graph_builder import GraphBuildOptions, build_project_graph
from app.core.graph_metrics import analyze_graph, project_to_weighted_digraph
from app.db import database
from app.db.repositories import (
    DocumentRepository,
    EntityMappingRepository,
    ProjectRepository,
    RelationMappingRepository,
    TripleRepository,
)


def _graph_project(tmp_path):
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("图谱测试项目", tmp_path)
        document_id = DocumentRepository(connection).create(
            project_id,
            "doc",
            filename="doc.txt",
            raw_text="公司A签署合同。公司甲签署合同。合同属于文件。",
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
            status="accepted",
            source_text="公司甲签署合同",
            metadata={"subject_type": "组织", "object_type": "文件"},
        )
        triples.create(
            project_id,
            "合同",
            "属于",
            "文件",
            document_id=document_id,
            status="edited",
            source_text="合同属于文件",
            metadata={"subject_type": "文件", "object_type": "概念"},
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
        RelationMappingRepository(connection).upsert(project_id, "属于", "类型")
        EntityMappingRepository(connection).upsert(project_id, "公司甲", "公司A", entity_type="组织")
    return database_path, project_id


def test_build_project_graph_applies_mappings_and_merges_edges(tmp_path) -> None:
    database_path, project_id = _graph_project(tmp_path)

    result = build_project_graph(database_path, project_id)
    graph = result.graph

    assert result.statuses == ("accepted", "edited")
    assert result.triple_count == 3
    assert set(graph.nodes) == {"公司A", "合同", "文件"}
    assert graph.nodes["公司A"]["label"] == "公司A"
    assert graph.nodes["公司A"]["type"] == "组织"
    assert graph.nodes["公司A"]["source_count"] == 2
    assert graph.has_edge("公司A", "合同", key="签订")
    assert graph["公司A"]["合同"]["签订"]["relation"] == "签订"
    assert graph["公司A"]["合同"]["签订"]["weight"] == 2
    assert graph["公司A"]["合同"]["签订"]["confidence"] == 0.8
    assert graph["公司A"]["合同"]["签订"]["source_doc"] == "doc.txt"
    assert graph.has_edge("合同", "文件", key="类型")
    assert "人物" not in graph.nodes


def test_build_project_graph_can_include_pending(tmp_path) -> None:
    database_path, project_id = _graph_project(tmp_path)

    result = build_project_graph(
        database_path,
        project_id,
        options=GraphBuildOptions(include_pending=True),
    )

    assert result.triple_count == 4
    assert "人物" in result.graph.nodes
    assert result.graph.has_edge("人物", "公司A", key="拥有")
    assert result.graph.nodes["公司A"]["source_count"] == 3
    assert not result.graph.has_edge("噪声", "公司A", key="忽略")


def test_analyze_graph_computes_metrics_and_relation_frequency(tmp_path) -> None:
    database_path, project_id = _graph_project(tmp_path)
    graph = build_project_graph(database_path, project_id).graph

    result = analyze_graph(graph, compute_communities=True)
    projected = project_to_weighted_digraph(graph)

    assert result.node_count == 3
    assert result.edge_count == 2
    assert result.density == projected.number_of_edges() / (projected.number_of_nodes() * (projected.number_of_nodes() - 1))
    assert [(row.relation, row.count) for row in result.relation_frequencies] == [("签订", 2), ("类型", 1)]

    metrics_by_id = {row.node_id: row for row in result.top_nodes}
    assert metrics_by_id["合同"].degree == 2
    assert metrics_by_id["合同"].in_degree == 1
    assert metrics_by_id["合同"].out_degree == 1
    assert metrics_by_id["合同"].degree_centrality > 0
    assert metrics_by_id["合同"].community is not None
    assert graph.nodes["合同"]["pagerank"] == metrics_by_id["合同"].pagerank
