"""Prepare graph data for local Cytoscape.js visualization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.graph_builder import GraphBuildOptions, build_project_graph
from app.core.graph_metrics import project_to_weighted_digraph


WEBVIEW_RESOURCE_DIR = Path(__file__).resolve().parents[1] / "resources" / "webview"


@dataclass(frozen=True)
class GraphVisualizationOptions:
    """Options controlling graph JSON size and default visibility."""

    include_pending: bool = False
    top_n: int = 50
    max_nodes: int = 500


def generate_graph_json(
    database_path: Path | str,
    project_id: int,
    *,
    options: GraphVisualizationOptions | None = None,
) -> dict[str, Any]:
    """Generate local Cytoscape-compatible graph JSON."""
    options = options or GraphVisualizationOptions()
    build_result = build_project_graph(
        database_path,
        project_id,
        options=GraphBuildOptions(include_pending=options.include_pending),
    )
    graph = build_result.graph
    projected = project_to_weighted_digraph(graph)

    ranked_nodes = sorted(
        projected.nodes,
        key=lambda node: (
            int(graph.nodes[node].get("source_count") or 0),
            int(projected.degree(node)),
            str(graph.nodes[node].get("label") or node),
        ),
        reverse=True,
    )
    max_nodes = max(1, int(options.max_nodes))
    top_n = max(1, int(options.top_n))
    retained_nodes = set(ranked_nodes[:max_nodes])
    default_nodes = set(ranked_nodes[: min(top_n, len(ranked_nodes), max_nodes)])

    node_payload = []
    for node in ranked_nodes:
        if node not in retained_nodes:
            continue
        data = graph.nodes[node]
        node_payload.append(
            {
                "data": {
                    "id": str(node),
                    "label": str(data.get("label") or node),
                    "type": str(data.get("type") or ""),
                    "source_count": int(data.get("source_count") or 0),
                    "degree": int(projected.degree(node)),
                    "in_degree": int(projected.in_degree(node)),
                    "out_degree": int(projected.out_degree(node)),
                },
                "default_visible": node in default_nodes,
            }
        )

    edge_payload = []
    relation_values: set[str] = set()
    status_values: set[str] = set()
    for index, (source, target, key, data) in enumerate(graph.edges(keys=True, data=True), start=1):
        if source not in retained_nodes or target not in retained_nodes:
            continue
        statuses = [str(status) for status in data.get("statuses") or [] if status]
        relation = str(data.get("relation") or key)
        relation_values.add(relation)
        status_values.update(statuses)
        edge_payload.append(
            {
                "data": {
                    "id": f"e{index}",
                    "source": str(source),
                    "target": str(target),
                    "label": relation,
                    "relation": relation,
                    "weight": int(data.get("weight") or 1),
                    "evidence": str(data.get("evidence") or ""),
                    "source_doc": str(data.get("source_doc") or ""),
                    "confidence": _confidence(data.get("confidence")),
                    "status": str(data.get("status") or ""),
                    "statuses": statuses,
                }
            }
        )

    entity_types = sorted({str(node["data"]["type"]) for node in node_payload if node["data"]["type"]})
    return {
        "meta": {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "triple_count": build_result.triple_count,
            "rendered_node_count": len(node_payload),
            "rendered_edge_count": len(edge_payload),
            "default_top_n": min(top_n, len(node_payload)),
            "max_nodes": max_nodes,
            "include_pending": options.include_pending,
            "truncated": graph.number_of_nodes() > len(node_payload),
        },
        "nodes": node_payload,
        "edges": edge_payload,
        "filters": {
            "relations": sorted(relation_values),
            "entity_types": entity_types,
            "statuses": sorted(status_values),
        },
    }


def export_standalone_graph_html(graph_data: dict[str, Any], output_path: Path | str) -> Path:
    """Export a standalone offline graph.html file."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    html = _resource("graph.html")
    css = _resource("graph.css")
    cytoscape = _resource("cytoscape.min.js")
    js = _resource("graph.js")
    payload = json.dumps(graph_data, ensure_ascii=False)
    standalone = html.replace(
        '<link rel="stylesheet" href="graph.css" />',
        f"<style>\n{css}\n</style>",
    )
    standalone = standalone.replace(
        '<script src="cytoscape.min.js"></script>',
        f"<script>\n{cytoscape}\n</script>",
    )
    standalone = standalone.replace(
        '<script src="graph.js"></script>',
        f'<script>window.__GRAPH_DATA__ = {payload};</script>\n<script>\n{js}\n</script>',
    )
    destination.write_text(standalone, encoding="utf-8")
    return destination


def graph_html_path() -> Path:
    return WEBVIEW_RESOURCE_DIR / "graph.html"


def _resource(name: str) -> str:
    return (WEBVIEW_RESOURCE_DIR / name).read_text(encoding="utf-8")


def _confidence(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return str(value)
