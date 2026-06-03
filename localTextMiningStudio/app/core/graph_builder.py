"""Build directed knowledge graphs from reviewed triples."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import networkx as nx

from app.db.database import connection_scope
from app.db.repositories import EntityMappingRepository, RelationMappingRepository


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class GraphBuildOptions:
    """Options for graph construction."""

    include_pending: bool = False


@dataclass(frozen=True)
class GraphBuildResult:
    """Constructed graph and source counts."""

    graph: nx.MultiDiGraph
    triple_count: int
    statuses: tuple[str, ...]


def build_project_graph(
    database_path: Path | str,
    project_id: int,
    *,
    options: GraphBuildOptions | None = None,
    progress_callback: ProgressCallback | None = None,
) -> GraphBuildResult:
    """Build a directed graph from accepted/edited triples.

    Entity and relation mappings are applied during graph construction, while
    the original triples table remains unchanged.
    """
    options = options or GraphBuildOptions()
    statuses = ("accepted", "edited", "pending") if options.include_pending else ("accepted", "edited")
    _progress(progress_callback, "读取三元组")
    rows = _load_rows(database_path, project_id, statuses)

    _progress(progress_callback, "读取标准化映射")
    with connection_scope(database_path) as connection:
        relation_mapping = RelationMappingRepository(connection).as_dict(project_id)
        entity_mapping = EntityMappingRepository(connection).as_dict(project_id)

    graph = nx.MultiDiGraph()
    type_counts: dict[str, Counter[str]] = {}
    _progress(progress_callback, "构建有向图")
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        subject = str(row["subject"])
        object_value = str(row["object"])
        relation = str(row["relation"])
        source = entity_mapping.get(subject, subject)
        target = entity_mapping.get(object_value, object_value)
        canonical_relation = relation_mapping.get(relation, relation)
        subject_type = str(metadata.get("subject_type") or "")
        object_type = str(metadata.get("object_type") or "")

        _add_node(graph, type_counts, source, subject_type)
        _add_node(graph, type_counts, target, object_type)
        _add_edge(graph, source, target, canonical_relation, row)

    for node, counts in type_counts.items():
        graph.nodes[node]["type"] = _most_common(counts)
    _finalize_edges(graph)
    _progress(progress_callback, "图谱构建完成")
    return GraphBuildResult(graph=graph, triple_count=len(rows), statuses=statuses)


def _load_rows(database_path: Path | str, project_id: int, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    with connection_scope(database_path) as connection:
        rows = connection.execute(
            f"""
            SELECT
                triples.id,
                triples.subject,
                triples.predicate AS relation,
                triples.object,
                triples.source_text AS evidence,
                COALESCE(NULLIF(documents.filename, ''), documents.title, '') AS source_doc,
                triples.confidence,
                triples.status,
                triples.metadata_json
            FROM triples
            LEFT JOIN documents ON documents.id = triples.document_id
            WHERE triples.project_id = ?
                AND triples.status IN ({placeholders})
                AND TRIM(triples.subject) != ''
                AND TRIM(triples.predicate) != ''
                AND TRIM(triples.object) != ''
            ORDER BY triples.id ASC
            """,
            (project_id, *statuses),
        ).fetchall()
    return [dict(row) for row in rows]


def _add_node(graph: nx.MultiDiGraph, type_counts: dict[str, Counter[str]], node_id: str, node_type: str) -> None:
    if node_id not in graph:
        graph.add_node(node_id, label=node_id, type="", source_count=0)
        type_counts[node_id] = Counter()
    graph.nodes[node_id]["source_count"] += 1
    if node_type:
        type_counts[node_id][node_type] += 1


def _add_edge(graph: nx.MultiDiGraph, source: str, target: str, relation: str, row: dict[str, Any]) -> None:
    confidence = _float_or_none(row.get("confidence"))
    if graph.has_edge(source, target, key=relation):
        edge = graph[source][target][relation]
        edge["weight"] += 1
        if not edge.get("evidence") and row.get("evidence"):
            edge["evidence"] = row["evidence"]
        if not edge.get("source_doc") and row.get("source_doc"):
            edge["source_doc"] = row["source_doc"]
        if confidence is not None:
            edge["_confidence_values"].append(confidence)
        status = str(row.get("status") or "")
        if status:
            edge["_statuses"].add(status)
        return

    status = str(row.get("status") or "")
    graph.add_edge(
        source,
        target,
        key=relation,
        relation=relation,
        weight=1,
        evidence=row.get("evidence") or "",
        source_doc=row.get("source_doc") or "",
        confidence=confidence if confidence is not None else None,
        _confidence_values=[] if confidence is None else [confidence],
        status=status,
        statuses=[status] if status else [],
        _statuses=set([status]) if status else set(),
    )


def _finalize_edges(graph: nx.MultiDiGraph) -> None:
    for _source, _target, _key, data in graph.edges(keys=True, data=True):
        values = data.pop("_confidence_values", [])
        statuses = sorted(data.pop("_statuses", set()))
        data["confidence"] = sum(values) / len(values) if values else None
        data["statuses"] = statuses
        data["status"] = ";".join(statuses)


def _metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _most_common(counter: Counter[str]) -> str:
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
