"""Generate project analysis reports."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.graph_builder import build_project_graph
from app.core.graph_metrics import GraphMetricsResult, analyze_graph
from app.db.database import connection_scope


SENSITIVE_KEYWORDS = ("api_key", "apikey", "token", "secret", "password")
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{8,}"),
]


@dataclass(frozen=True)
class ReportResult:
    """Generated report paths."""

    markdown_path: Path
    html_path: Path | None = None


def generate_project_report(
    database_path: Path | str,
    project_id: int,
    output_dir: Path | str,
    *,
    include_html: bool = False,
) -> ReportResult:
    """Generate a Markdown report and optionally an HTML report."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    data = collect_report_data(database_path, project_id, output_path)
    markdown = render_markdown_report(data)
    markdown_path = output_path / "analysis_report.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    html_path = None
    if include_html:
        html_path = output_path / "analysis_report.html"
        html_path.write_text(render_html_report(markdown), encoding="utf-8")
    return ReportResult(markdown_path=markdown_path, html_path=html_path)


def collect_report_data(database_path: Path | str, project_id: int, output_dir: Path | str) -> dict[str, Any]:
    """Collect report data from the project database."""
    with connection_scope(database_path) as connection:
        project = connection.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        document_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM documents WHERE project_id = ?",
                (project_id,),
            ).fetchone()["count"]
        )
        preprocessing_rows = connection.execute(
            """
            SELECT preprocessing_params_json AS params, COUNT(*) AS count
            FROM documents
            WHERE project_id = ? AND TRIM(preprocessing_params_json) != ''
            GROUP BY preprocessing_params_json
            ORDER BY count DESC
            """,
            (project_id,),
        ).fetchall()
        analysis_rows = connection.execute(
            """
            SELECT run_type, status, parameters_json, started_at, finished_at, error_message
            FROM analysis_runs
            WHERE project_id = ?
            ORDER BY started_at DESC, id DESC
            """,
            (project_id,),
        ).fetchall()
        triple_status_rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM triples
            WHERE project_id = ?
            GROUP BY status
            """,
            (project_id,),
        ).fetchall()
        triple_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM triples WHERE project_id = ?",
                (project_id,),
            ).fetchone()["count"]
        )

    graph_metrics = _graph_metrics(database_path, project_id)
    exported_files = _exported_files(output_dir)
    markdown_name = "analysis_report.md"
    if markdown_name not in exported_files:
        exported_files.append(markdown_name)

    return {
        "project": dict(project) if project is not None else {},
        "document_count": document_count,
        "preprocessing_params": _preprocessing_params(preprocessing_rows),
        "analysis_runs": _analysis_runs(analysis_rows),
        "traditional_runs": _traditional_runs(analysis_rows),
        "triple_count": triple_count,
        "triple_status_counts": _status_counts(triple_status_rows),
        "graph_metrics": graph_metrics,
        "exported_files": sorted(exported_files),
    }


def render_markdown_report(data: dict[str, Any]) -> str:
    """Render report data as Markdown."""
    project = data["project"]
    graph: GraphMetricsResult = data["graph_metrics"]
    status_counts = data["triple_status_counts"]
    lines: list[str] = [
        "# 本地文本挖掘分析报告",
        "",
        "## 项目信息",
        f"- 项目名称：{_md(project.get('name', ''))}",
        f"- 项目路径：{_md(project.get('project_path', ''))}",
        f"- 创建时间：{_md(project.get('created_at', ''))}",
        f"- 更新时间：{_md(project.get('updated_at', ''))}",
        "",
        "## 文档概览",
        f"- 文档数量：{data['document_count']}",
        "",
        "## 文本预处理参数",
    ]
    lines.extend(_parameter_block(data["preprocessing_params"], empty="未记录预处理参数。"))
    lines.extend(
        [
            "",
            "## 传统文本挖掘结果摘要",
        ]
    )
    lines.extend(_analysis_run_block(data["traditional_runs"], empty="未记录传统文本挖掘运行。"))
    lines.extend(
        [
            "",
            "## 分析参数记录",
        ]
    )
    lines.extend(_analysis_run_block(data["analysis_runs"], empty="未记录分析运行。"))
    lines.extend(
        [
            "",
            "## 三元组统计",
            f"- 三元组总数：{data['triple_count']}",
            f"- accepted：{status_counts.get('accepted', 0)}",
            f"- rejected：{status_counts.get('rejected', 0)}",
            f"- edited：{status_counts.get('edited', 0)}",
            f"- pending：{status_counts.get('pending', 0)}",
            "",
            "## 核心实体 Top 20",
            "| 排名 | 实体 | 类型 | PageRank | Degree | 来源次数 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    if graph.top_nodes:
        for index, node in enumerate(graph.top_nodes, start=1):
            lines.append(
                f"| {index} | {_md(node.label)} | {_md(node.node_type)} | {node.pagerank:.6g} | "
                f"{node.degree} | {node.source_count} |"
            )
    else:
        lines.append("| - | 无 |  |  |  |  |")
    lines.extend(
        [
            "",
            "## 高频关系 Top 20",
            "| 排名 | 关系 | 次数 |",
            "| --- | --- | --- |",
        ]
    )
    if graph.relation_frequencies:
        for index, relation in enumerate(graph.relation_frequencies, start=1):
            lines.append(f"| {index} | {_md(relation.relation)} | {relation.count} |")
    else:
        lines.append("| - | 无 | 0 |")
    lines.extend(
        [
            "",
            "## 图谱指标摘要",
            f"- 节点数：{graph.node_count}",
            f"- 边数：{graph.edge_count}",
            f"- 密度：{graph.density:.6g}",
            "",
            "## 导出文件列表",
        ]
    )
    lines.extend(f"- {_md(name)}" for name in data["exported_files"])
    return "\n".join(lines) + "\n"


def render_html_report(markdown: str) -> str:
    """Render a lightweight HTML report from Markdown text."""
    escaped = html.escape(markdown)
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head><meta charset=\"utf-8\"><title>分析报告</title>"
        "<style>body{font-family:Segoe UI,Microsoft YaHei,sans-serif;line-height:1.6;margin:32px;}"
        "pre{white-space:pre-wrap;} table{border-collapse:collapse;} td,th{border:1px solid #ddd;padding:4px 8px;}</style>"
        "</head>\n"
        f"<body><pre>{escaped}</pre></body>\n"
        "</html>\n"
    )


def _graph_metrics(database_path: Path | str, project_id: int) -> GraphMetricsResult:
    try:
        graph = build_project_graph(database_path, project_id).graph
        return analyze_graph(graph, top_n=20, compute_communities=True)
    except Exception:
        return GraphMetricsResult(node_count=0, edge_count=0, density=0.0, top_nodes=[], relation_frequencies=[])


def _preprocessing_params(rows) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        params = _safe_json(row["params"])
        if params == {}:
            continue
        result.append({"count": int(row["count"]), "parameters": redact_sensitive(params)})
    return result


def _analysis_runs(rows) -> list[dict[str, Any]]:
    runs = []
    for row in rows:
        params = redact_sensitive(_safe_json(row["parameters_json"]))
        error_message = redact_sensitive(row["error_message"] or "")
        runs.append(
            {
                "run_type": row["run_type"],
                "status": row["status"],
                "parameters": params,
                "started_at": row["started_at"] or "",
                "finished_at": row["finished_at"] or "",
                "error_message": error_message,
            }
        )
    return runs


def _traditional_runs(rows) -> list[dict[str, Any]]:
    return [
        run for run in _analysis_runs(rows)
        if run["run_type"] == "traditional_text_mining"
    ]


def _status_counts(rows) -> dict[str, int]:
    counts = Counter({status: 0 for status in ("accepted", "rejected", "edited", "pending")})
    for row in rows:
        counts[str(row["status"] or "")] = int(row["count"])
    return dict(counts)


def _exported_files(output_dir: Path | str) -> list[str]:
    path = Path(output_dir)
    if not path.exists():
        return []
    return sorted(item.name for item in path.iterdir() if item.is_file())


def _parameter_block(items: list[dict[str, Any]], *, empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    lines = []
    for index, item in enumerate(items, start=1):
        lines.append(f"- 参数组 {index}，文档数：{item.get('count', 0)}")
        lines.append("```json")
        lines.append(json.dumps(item.get("parameters", {}), ensure_ascii=False, indent=2))
        lines.append("```")
    return lines


def _analysis_run_block(runs: list[dict[str, Any]], *, empty: str) -> list[str]:
    if not runs:
        return [f"- {empty}"]
    lines = []
    for index, run in enumerate(runs, start=1):
        lines.append(
            f"- 运行 {index}：{_md(run['run_type'])}，状态：{_md(run['status'])}，"
            f"开始：{_md(run['started_at'])}，结束：{_md(run['finished_at'])}"
        )
        if run["error_message"]:
            lines.append(f"  - 错误：{_md(run['error_message'])}")
        lines.append("```json")
        lines.append(json.dumps(run["parameters"], ensure_ascii=False, indent=2))
        lines.append("```")
    return lines


def redact_sensitive(value: Any) -> Any:
    """Recursively redact API keys, tokens, and similar secrets."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive(item)
        return result
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized == "key" or normalized.endswith("_key"):
        return True
    return any(keyword in normalized for keyword in SENSITIVE_KEYWORDS)


def _safe_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")
