"""Interactive knowledge graph page backed by local Cytoscape.js."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.graph_visualization import (
    GraphVisualizationOptions,
    export_standalone_graph_html,
    generate_graph_json,
    graph_html_path,
)
from app.utils.paths import get_exports_dir

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_ERROR = ""
except Exception as error:  # pragma: no cover - depends on local Qt installation
    QWebEngineView = None  # type: ignore[assignment]
    WEBENGINE_ERROR = str(error)


class GraphPage(QWidget):
    """Render and export an interactive local knowledge graph."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None
        self.graph_data: dict | None = None
        self._thread: QThread | None = None
        self._worker: _GraphDataWorker | None = None
        self._html_loaded = False

        title = QLabel("知识图谱")
        title.setObjectName("pageTitle")
        self.project_label = QLabel("当前项目：未打开")

        self.include_pending_checkbox = QCheckBox("包含 pending")
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(1, 500)
        self.top_n_spin.setValue(50)
        self.max_nodes_spin = QSpinBox()
        self.max_nodes_spin.setRange(50, 5000)
        self.max_nodes_spin.setValue(500)
        self.generate_button = QPushButton("生成图谱")
        self.export_button = QPushButton("导出 graph.html")
        controls = QHBoxLayout()
        controls.addWidget(self.include_pending_checkbox)
        controls.addWidget(QLabel("Top N"))
        controls.addWidget(self.top_n_spin)
        controls.addWidget(QLabel("最多节点"))
        controls.addWidget(self.max_nodes_spin)
        controls.addWidget(self.generate_button)
        controls.addWidget(self.export_button)
        controls.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status_label = QLabel("就绪")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(self.project_label)
        layout.addLayout(controls)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)

        if QWebEngineView is None:
            hint = QLabel(f"当前环境无法加载 QWebEngineView，知识图谱可导出为 graph.html 后用浏览器打开。{WEBENGINE_ERROR}")
            hint.setWordWrap(True)
            layout.addWidget(hint, stretch=1)
            self.web_view = None
        else:
            self.web_view = QWebEngineView(self)
            self.web_view.loadFinished.connect(self._web_loaded)
            self.web_view.load(QUrl.fromLocalFile(str(graph_html_path().resolve())))
            layout.addWidget(self.web_view, stretch=1)

        self.generate_button.clicked.connect(self.generate_graph)
        self.export_button.clicked.connect(self.export_graph_html)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")

    def generate_graph(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return
        if self._thread is not None:
            return

        self.generate_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.status_label.setText("生成图谱 JSON")
        worker = _GraphDataWorker(
            self.database_path,
            self.project_id,
            options=GraphVisualizationOptions(
                include_pending=self.include_pending_checkbox.isChecked(),
                top_n=self.top_n_spin.value(),
                max_nodes=self.max_nodes_spin.value(),
            ),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._graph_ready)
        worker.failed.connect(self._graph_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._worker = worker
        self._thread = thread
        thread.start()

    def export_graph_html(self) -> None:
        if self.graph_data is None:
            self.generate_graph()
            QMessageBox.information(self, "请稍后导出", "图谱生成完成后再导出 graph.html。")
            return
        default_path = get_exports_dir() / "graph.html"
        output_path, _ = QFileDialog.getSaveFileName(self, "导出 graph.html", str(default_path), "HTML 文件 (*.html)")
        if not output_path:
            return
        try:
            export_standalone_graph_html(self.graph_data, output_path)
        except Exception as error:
            QMessageBox.critical(self, "导出失败", str(error))
            return
        QMessageBox.information(self, "导出成功", output_path)

    def _graph_ready(self, data: dict) -> None:
        self.graph_data = data
        meta = data.get("meta", {})
        self.status_label.setText(
            f"图谱已生成：节点 {meta.get('rendered_node_count', 0)}/{meta.get('node_count', 0)}，"
            f"边 {meta.get('rendered_edge_count', 0)}/{meta.get('edge_count', 0)}"
        )
        self._inject_graph_data()

    def _graph_failed(self, message: str) -> None:
        self.status_label.setText("图谱生成失败")
        QMessageBox.critical(self, "图谱生成失败", message)

    def _thread_finished(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.generate_button.setEnabled(True)
        self._thread = None
        self._worker = None

    def _web_loaded(self, ok: bool) -> None:
        self._html_loaded = bool(ok)
        if not ok:
            self.status_label.setText("本地图谱页面加载失败")
            return
        self._inject_graph_data()

    def _inject_graph_data(self) -> None:
        if self.web_view is None or not self._html_loaded or self.graph_data is None:
            return
        payload = json.dumps(self.graph_data, ensure_ascii=False)
        self.web_view.page().runJavaScript(f"window.loadGraphData({payload});")


class _GraphDataWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path: Path, project_id: int, *, options: GraphVisualizationOptions) -> None:
        super().__init__()
        self.database_path = database_path
        self.project_id = project_id
        self.options = options

    def run(self) -> None:
        try:
            data = generate_graph_json(self.database_path, self.project_id, options=self.options)
        except Exception as error:
            self.failed.emit(str(error))
            return
        self.finished.emit(data)
