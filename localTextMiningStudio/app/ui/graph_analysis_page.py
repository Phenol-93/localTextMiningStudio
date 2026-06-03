"""Knowledge graph analysis page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.graph_builder import GraphBuildOptions, build_project_graph
from app.core.graph_metrics import GraphMetricsResult, analyze_graph
from app.utils.background_tasks import BackgroundTaskWorker, TaskContext


NODE_COLUMNS = [
    "节点",
    "类型",
    "来源次数",
    "degree",
    "in_degree",
    "out_degree",
    "degree_centrality",
    "betweenness",
    "closeness",
    "pagerank",
    "community",
]
RELATION_COLUMNS = ["关系", "次数"]


class GraphAnalysisPage(QWidget):
    """Display graph summary metrics and ranking tables."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None
        self._thread: QThread | None = None
        self._worker: BackgroundTaskWorker | None = None

        title = QLabel("图谱分析")
        title.setObjectName("pageTitle")
        self.project_label = QLabel("当前项目：未打开")

        self.include_pending_checkbox = QCheckBox("包含 pending")
        self.community_checkbox = QCheckBox("计算社区")
        self.run_button = QPushButton("运行分析")
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        controls = QHBoxLayout()
        controls.addWidget(self.include_pending_checkbox)
        controls.addWidget(self.community_checkbox)
        controls.addWidget(self.run_button)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status_label = QLabel("就绪")
        self.error_text = QTextEdit()
        self.error_text.setReadOnly(True)
        self.error_text.setMaximumHeight(90)
        self.error_text.setPlaceholderText("错误信息")

        summary = QHBoxLayout()
        self.node_count_label = QLabel("节点数：0")
        self.edge_count_label = QLabel("边数：0")
        self.density_label = QLabel("密度：0")
        summary.addWidget(self.node_count_label)
        summary.addWidget(self.edge_count_label)
        summary.addWidget(self.density_label)
        summary.addStretch(1)

        self.node_table = _table(NODE_COLUMNS)
        self.relation_table = _table(RELATION_COLUMNS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(self.project_label)
        layout.addLayout(controls)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        layout.addWidget(self.error_text)
        layout.addLayout(summary)
        layout.addWidget(QLabel("Top 20 节点中心性"))
        layout.addWidget(self.node_table, stretch=2)
        layout.addWidget(QLabel("高频关系 Top 20"))
        layout.addWidget(self.relation_table, stretch=1)

        self.run_button.clicked.connect(self.run_analysis)
        self.cancel_button.clicked.connect(self.cancel_task)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")

    def run_analysis(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return
        if self._thread is not None:
            return

        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.error_text.clear()
        self.status_label.setText("开始分析")
        database_path = self.database_path
        project_id = self.project_id
        include_pending = self.include_pending_checkbox.isChecked()
        compute_communities = self.community_checkbox.isChecked()

        def task(context: TaskContext) -> GraphMetricsResult:
            graph_result = build_project_graph(
                database_path,
                project_id,
                options=GraphBuildOptions(include_pending=include_pending),
                progress_callback=lambda message: context.report(0, 2, message),
            )
            context.check_cancelled()
            result = analyze_graph(
                graph_result.graph,
                top_n=20,
                compute_communities=compute_communities,
                progress_callback=lambda message: context.report(1, 2, message),
            )
            context.report(2, 2, "图谱指标计算完成")
            return result

        self._start_worker("graph_metrics", task)

    def cancel_task(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("正在取消...")

    def _start_worker(self, task_name: str, task) -> None:
        worker = BackgroundTaskWorker(task_name, task)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._update_progress)
        worker.finished.connect(self._analysis_finished)
        worker.failed.connect(self._analysis_failed)
        worker.canceled.connect(self._analysis_canceled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._worker = worker
        self._thread = thread
        thread.start()

    @Slot(int, int, str)
    def _update_progress(self, done: int, total: int, message: str) -> None:
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(int(done / max(1, total) * 100))
        self.status_label.setText(message)

    def _analysis_finished(self, result: GraphMetricsResult) -> None:
        self.node_count_label.setText(f"节点数：{result.node_count}")
        self.edge_count_label.setText(f"边数：{result.edge_count}")
        self.density_label.setText(f"密度：{result.density:.6g}")
        self._fill_node_table(result)
        self._fill_relation_table(result)
        self.status_label.setText("分析完成")

    def _analysis_failed(self, message: str) -> None:
        self.status_label.setText("分析失败")
        self.error_text.setPlainText(message)
        QMessageBox.critical(self, "分析失败", message)

    @Slot(str)
    def _analysis_canceled(self, message: str) -> None:
        self.status_label.setText(message)
        self.error_text.setPlainText(message)

    def _thread_finished(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._thread = None
        self._worker = None

    def _fill_node_table(self, result: GraphMetricsResult) -> None:
        self.node_table.setRowCount(len(result.top_nodes))
        for row_index, metric in enumerate(result.top_nodes):
            values = [
                metric.label,
                metric.node_type,
                str(metric.source_count),
                str(metric.degree),
                str(metric.in_degree),
                str(metric.out_degree),
                f"{metric.degree_centrality:.6g}",
                f"{metric.betweenness_centrality:.6g}",
                f"{metric.closeness_centrality:.6g}",
                f"{metric.pagerank:.6g}",
                "" if metric.community is None else str(metric.community),
            ]
            _set_row(self.node_table, row_index, values)

    def _fill_relation_table(self, result: GraphMetricsResult) -> None:
        self.relation_table.setRowCount(len(result.relation_frequencies))
        for row_index, relation in enumerate(result.relation_frequencies):
            _set_row(self.relation_table, row_index, [relation.relation, str(relation.count)])


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return table


def _set_row(table: QTableWidget, row_index: int, values: list[str]) -> None:
    for column_index, value in enumerate(values):
        table.setItem(row_index, column_index, QTableWidgetItem(value))
