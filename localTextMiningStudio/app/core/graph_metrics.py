"""Graph metric calculations for knowledge graphs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable

import networkx as nx


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class NodeMetric:
    """Metrics for one graph node."""

    node_id: str
    label: str
    node_type: str
    source_count: int
    degree: int
    in_degree: int
    out_degree: int
    degree_centrality: float
    betweenness_centrality: float
    closeness_centrality: float
    pagerank: float
    community: int | None = None


@dataclass(frozen=True)
class RelationFrequency:
    """Weighted relation frequency."""

    relation: str
    count: int


@dataclass(frozen=True)
class GraphMetricsResult:
    """Summary metrics and top ranking tables."""

    node_count: int
    edge_count: int
    density: float
    top_nodes: list[NodeMetric]
    relation_frequencies: list[RelationFrequency]


def analyze_graph(
    graph: nx.MultiDiGraph,
    *,
    top_n: int = 20,
    compute_communities: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> GraphMetricsResult:
    """Calculate graph-level summary, node centrality, and relation frequencies."""
    _progress(progress_callback, "准备图谱指标")
    projected = project_to_weighted_digraph(graph)
    if projected.number_of_nodes() == 0:
        return GraphMetricsResult(
            node_count=0,
            edge_count=0,
            density=0.0,
            top_nodes=[],
            relation_frequencies=[],
        )

    _progress(progress_callback, "计算度和中心性")
    degree_centrality = nx.degree_centrality(projected)
    betweenness = nx.betweenness_centrality(projected, normalized=True)
    closeness = nx.closeness_centrality(projected)
    pagerank = nx.pagerank(projected, weight="weight") if projected.number_of_edges() else {node: 0 for node in projected.nodes}
    communities = _communities(projected) if compute_communities else {}

    metrics = []
    for node in projected.nodes:
        data = graph.nodes[node]
        metric = NodeMetric(
            node_id=str(node),
            label=str(data.get("label") or node),
            node_type=str(data.get("type") or ""),
            source_count=int(data.get("source_count") or 0),
            degree=int(projected.degree(node)),
            in_degree=int(projected.in_degree(node)),
            out_degree=int(projected.out_degree(node)),
            degree_centrality=float(degree_centrality.get(node, 0.0)),
            betweenness_centrality=float(betweenness.get(node, 0.0)),
            closeness_centrality=float(closeness.get(node, 0.0)),
            pagerank=float(pagerank.get(node, 0.0)),
            community=communities.get(str(node)),
        )
        metrics.append(metric)
        graph.nodes[node].update(
            {
                "degree": metric.degree,
                "in_degree": metric.in_degree,
                "out_degree": metric.out_degree,
                "degree_centrality": metric.degree_centrality,
                "betweenness_centrality": metric.betweenness_centrality,
                "closeness_centrality": metric.closeness_centrality,
                "pagerank": metric.pagerank,
                "community": metric.community,
            }
        )

    _progress(progress_callback, "统计高频关系")
    top_nodes = sorted(
        metrics,
        key=lambda item: (
            item.pagerank,
            item.degree_centrality,
            item.source_count,
            item.label,
        ),
        reverse=True,
    )[: max(1, top_n)]
    relation_frequencies = relation_frequency(graph, top_n=top_n)

    _progress(progress_callback, "图谱指标计算完成")
    return GraphMetricsResult(
        node_count=projected.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        density=float(nx.density(projected)),
        top_nodes=top_nodes,
        relation_frequencies=relation_frequencies,
    )


def project_to_weighted_digraph(graph: nx.MultiDiGraph) -> nx.DiGraph:
    """Collapse relation-specific parallel edges for centrality algorithms."""
    projected = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        projected.add_node(node, **data)
    for source, target, data in graph.edges(data=True):
        weight = int(data.get("weight") or 1)
        if projected.has_edge(source, target):
            projected[source][target]["weight"] += weight
        else:
            projected.add_edge(source, target, weight=weight)
    return projected


def relation_frequency(graph: nx.MultiDiGraph, *, top_n: int = 20) -> list[RelationFrequency]:
    counter: Counter[str] = Counter()
    for _source, _target, data in graph.edges(data=True):
        counter[str(data.get("relation") or "")] += int(data.get("weight") or 1)
    return [
        RelationFrequency(relation=relation, count=count)
        for relation, count in counter.most_common(max(1, top_n))
        if relation
    ]


def _communities(graph: nx.DiGraph) -> dict[str, int]:
    undirected = graph.to_undirected()
    if undirected.number_of_nodes() == 0:
        return {}
    try:
        communities = nx.community.louvain_communities(undirected, weight="weight", seed=0)
    except (AttributeError, ImportError):
        communities = list(nx.connected_components(undirected))
    result: dict[str, int] = {}
    for index, community in enumerate(communities):
        for node in community:
            result[str(node)] = index
    return result


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
