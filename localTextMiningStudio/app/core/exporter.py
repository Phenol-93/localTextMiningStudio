"""CSV export helpers for triples and graph-ready data."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

from app.db.database import connection_scope
from app.db.repositories import EntityMappingRepository, RelationMappingRepository


TRIPLES_HEADER = [
    "triple_id",
    "subject",
    "relation",
    "object",
    "subject_type",
    "object_type",
    "evidence",
    "source_doc",
    "chunk_id",
    "page",
    "confidence",
    "status",
    "created_by",
    "created_at",
]
EDGES_HEADER = [
    "Source",
    "Target",
    "Label",
    "Weight",
    "Type",
    "Evidence",
    "SourceDoc",
    "Confidence",
    "Status",
]
NODES_HEADER = [
    "Id",
    "Label",
    "Type",
    "Degree",
    "InDegree",
    "OutDegree",
    "Betweenness",
    "Closeness",
    "PageRank",
    "Community",
]


FILTER_FIELDS = {"status", "relation", "subject_type", "object_type", "source_doc"}


@dataclass(frozen=True)
class ExportResult:
    """Paths written by a project export."""

    triples_csv: Path
    nodes_csv: Path
    edges_csv: Path
    triple_count: int
    node_count: int
    edge_count: int


def export_project_csvs(
    database_path: Path | str,
    project_id: int,
    output_dir: Path | str,
    *,
    filters: dict[str, str] | None = None,
) -> ExportResult:
    """Export triples, nodes, and edges CSV files for a project."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    triples = load_export_triples(database_path, project_id, filters=filters)
    edges = build_edges(database_path, project_id, triples)
    nodes = build_nodes(edges)

    triples_path = output_path / "triples.csv"
    nodes_path = output_path / "nodes.csv"
    edges_path = output_path / "edges.csv"

    write_csv(triples_path, TRIPLES_HEADER, triples)
    write_csv(edges_path, EDGES_HEADER, edges)
    write_csv(nodes_path, NODES_HEADER, nodes)

    return ExportResult(
        triples_csv=triples_path,
        nodes_csv=nodes_path,
        edges_csv=edges_path,
        triple_count=len(triples),
        node_count=len(nodes),
        edge_count=len(edges),
    )


def load_export_triples(
    database_path: Path | str,
    project_id: int,
    *,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Load triples for export using review-style filters."""
    where_sql, params = _where(project_id, filters)
    with connection_scope(database_path) as connection:
        rows = connection.execute(
            f"""
            SELECT
                triples.id AS triple_id,
                triples.subject,
                triples.predicate AS relation,
                triples.object,
                json_extract(triples.metadata_json, '$.subject_type') AS subject_type,
                json_extract(triples.metadata_json, '$.object_type') AS object_type,
                triples.source_text AS evidence,
                COALESCE(NULLIF(documents.filename, ''), documents.title, '') AS source_doc,
                triples.chunk_id,
                COALESCE(
                    json_extract(triples.metadata_json, '$.page'),
                    json_extract(chunks.metadata_json, '$.page'),
                    json_extract(documents.metadata_json, '$.page'),
                    ''
                ) AS page,
                triples.confidence,
                triples.status,
                triples.created_by,
                triples.created_at
            FROM triples
            LEFT JOIN documents ON documents.id = triples.document_id
            LEFT JOIN chunks ON chunks.id = triples.chunk_id
            {where_sql}
            ORDER BY triples.created_at ASC, triples.id ASC
            """,
            params,
        ).fetchall()

    return [_csv_ready(dict(row), TRIPLES_HEADER) for row in rows]


def build_edges(
    database_path: Path | str,
    project_id: int,
    triples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build weighted graph edges with entity/relation mappings applied."""
    with connection_scope(database_path) as connection:
        relation_mapping = RelationMappingRepository(connection).as_dict(project_id)
        entity_mapping = EntityMappingRepository(connection).as_dict(project_id)

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    confidences: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    statuses: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for triple in triples:
        source = entity_mapping.get(str(triple["subject"]), str(triple["subject"]))
        target = entity_mapping.get(str(triple["object"]), str(triple["object"]))
        label = relation_mapping.get(str(triple["relation"]), str(triple["relation"]))
        key = (source, target, label)
        if key not in grouped:
            grouped[key] = {
                "Source": source,
                "Target": target,
                "Label": label,
                "Weight": 0,
                "Type": "Directed",
                "Evidence": triple.get("evidence", ""),
                "SourceDoc": triple.get("source_doc", ""),
                "Confidence": "",
                "Status": "",
                "__source_types": Counter(),
                "__target_types": Counter(),
            }
        grouped[key]["Weight"] += 1
        subject_type = str(triple.get("subject_type") or "")
        object_type = str(triple.get("object_type") or "")
        if subject_type:
            grouped[key]["__source_types"][subject_type] += 1
        if object_type:
            grouped[key]["__target_types"][object_type] += 1
        confidence = _float_or_none(triple.get("confidence"))
        if confidence is not None:
            confidences[key].append(confidence)
        status = str(triple.get("status") or "")
        if status:
            statuses[key].add(status)

    edges = list(grouped.values())
    for edge in edges:
        key = (str(edge["Source"]), str(edge["Target"]), str(edge["Label"]))
        values = confidences[key]
        if values:
            edge["Confidence"] = f"{sum(values) / len(values):.6g}"
        edge["Status"] = ";".join(sorted(statuses[key]))
    edges.sort(key=lambda row: (str(row["Source"]), str(row["Target"]), str(row["Label"])))
    return edges


def build_nodes(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build graph node metrics from exported edges."""
    graph = nx.DiGraph()
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for edge in edges:
        source = str(edge["Source"])
        target = str(edge["Target"])
        weight = int(edge.get("Weight") or 1)
        graph.add_node(source)
        graph.add_node(target)
        type_counts[source].update(edge.get("__source_types") or {})
        type_counts[target].update(edge.get("__target_types") or {})
        if graph.has_edge(source, target):
            graph[source][target]["weight"] += weight
        else:
            graph.add_edge(source, target, weight=weight)

    if not graph:
        return []

    betweenness = nx.betweenness_centrality(graph, normalized=True)
    closeness = nx.closeness_centrality(graph)
    pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_edges() else {node: 0 for node in graph.nodes}
    communities = _communities(graph)

    rows = []
    for node in sorted(graph.nodes):
        node_type = _most_common(type_counts[node])
        rows.append(
            {
                "Id": node,
                "Label": node,
                "Type": node_type,
                "Degree": graph.degree(node),
                "InDegree": graph.in_degree(node),
                "OutDegree": graph.out_degree(node),
                "Betweenness": f"{betweenness.get(node, 0):.6g}",
                "Closeness": f"{closeness.get(node, 0):.6g}",
                "PageRank": f"{pagerank.get(node, 0):.6g}",
                "Community": communities.get(node, 0),
            }
        )
    return [_csv_ready(row, NODES_HEADER) for row in rows]


def write_csv(path: Path | str, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    """Write a CSV with UTF-8 BOM for Excel-friendly Chinese display."""
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_csv_ready(row, fieldnames) for row in rows)


def _where(project_id: int, filters: dict[str, str] | None) -> tuple[str, tuple[Any, ...]]:
    clauses = ["triples.project_id = ?"]
    params: list[Any] = [project_id]
    expressions = {
        "status": "triples.status",
        "relation": "triples.predicate",
        "subject_type": "json_extract(triples.metadata_json, '$.subject_type')",
        "object_type": "json_extract(triples.metadata_json, '$.object_type')",
        "source_doc": "COALESCE(NULLIF(documents.filename, ''), documents.title, '')",
    }
    for key, value in (filters or {}).items():
        if not value or key not in FILTER_FIELDS:
            continue
        clauses.append(f"{expressions[key]} = ?")
        params.append(value)
    return "WHERE " + " AND ".join(clauses), tuple(params)


def _csv_ready(row: dict[str, Any], fieldnames: list[str]) -> dict[str, Any]:
    return {field: _cell(row.get(field)) for field in fieldnames}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _communities(graph: nx.DiGraph) -> dict[str, int]:
    undirected = graph.to_undirected()
    if not undirected:
        return {}
    try:
        groups = nx.community.louvain_communities(undirected, weight="weight", seed=0)
    except (AttributeError, ImportError):
        groups = list(nx.connected_components(undirected))
    result: dict[str, int] = {}
    for index, group in enumerate(groups):
        for node in group:
            result[str(node)] = index
    return result


def _most_common(counter: Counter[str]) -> str:
    if not counter:
        return ""
    return counter.most_common(1)[0][0]
