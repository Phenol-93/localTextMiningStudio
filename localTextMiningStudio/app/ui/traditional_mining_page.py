"""Traditional text mining page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.topic_modeling import (
    TopicModelingOptions,
    TopicModelingResult,
    export_result_table,
    run_project_topic_analysis,
)
from app.utils.background_tasks import BackgroundTaskWorker, TaskContext
from app.utils.paths import get_exports_dir


class TraditionalMiningPage(QWidget):
    """UI for word frequency, TF-IDF, LDA, and NMF analysis."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None
        self.current_result: TopicModelingResult | None = None
        self._worker_thread: QThread | None = None
        self._worker: BackgroundTaskWorker | None = None

        title = QLabel("传统文本挖掘")
        title.setObjectName("pageTitle")

        self.project_label = QLabel("当前项目：未打开")

        self.algorithm_combo = QComboBox()
        self.algorithm_combo.addItem("词频统计", "word_frequency")
        self.algorithm_combo.addItem("TF-IDF", "tfidf")
        self.algorithm_combo.addItem("LDA 主题模型", "lda")
        self.algorithm_combo.addItem("NMF 主题模型", "nmf")

        self.topic_count = QSpinBox()
        self.topic_count.setRange(1, 50)
        self.topic_count.setValue(3)

        self.max_features = QSpinBox()
        self.max_features.setRange(10, 50000)
        self.max_features.setSingleStep(100)
        self.max_features.setValue(1000)

        form = QFormLayout()
        form.addRow("算法", self.algorithm_combo)
        form.addRow("主题数", self.topic_count)
        form.addRow("最大特征数", self.max_features)

        self.run_button = QPushButton("运行分析")
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        self.export_button = QPushButton("导出当前表格 CSV")
        self.export_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel("未开始")
        self.error_text = QTextEdit()
        self.error_text.setReadOnly(True)
        self.error_text.setMaximumHeight(90)
        self.error_text.setPlaceholderText("错误信息")

        self.tabs = QTabWidget()
        self.topic_table = _table()
        self.document_topic_table = _table()
        self.frequency_table = _table()
        self.tfidf_table = _table()
        self.tabs.addTab(self.topic_table, "主题关键词")
        self.tabs.addTab(self.document_topic_table, "文档-主题分布")
        self.tabs.addTab(self.frequency_table, "词频表")
        self.tabs.addTab(self.tfidf_table, "TF-IDF 表")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(self.project_label)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.error_text)
        layout.addWidget(self.tabs, stretch=1)

        self.run_button.clicked.connect(self.run_analysis)
        self.cancel_button.clicked.connect(self.cancel_task)
        self.export_button.clicked.connect(self.export_current_table)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")

    def run_analysis(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return

        options = TopicModelingOptions(
            algorithm=str(self.algorithm_combo.currentData()),
            num_topics=self.topic_count.value(),
            max_features=self.max_features.value(),
        )

        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.export_button.setEnabled(False)
        self.error_text.clear()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText("准备分析")

        database_path = self.database_path
        project_id = self.project_id

        def task(context: TaskContext) -> TopicModelingResult:
            context.report(0, 3, "读取预处理文档")
            context.check_cancelled()
            context.report(1, 3, "运行文本挖掘分析")
            result = run_project_topic_analysis(database_path, project_id, options)
            context.check_cancelled()
            context.report(3, 3, "分析完成")
            return result

        self._start_worker("traditional_text_mining", task)

    def cancel_task(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("正在取消...")

    @Slot(int, int, str)
    def _update_progress(self, done: int, total: int, message: str) -> None:
        self.progress_bar.setValue(int(done / max(1, total) * 100))
        self.status_label.setText(message)

    @Slot(object)
    def _analysis_finished(self, result: TopicModelingResult) -> None:
        self.current_result = result
        self._show_result(result)
        self.export_button.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("分析完成")
        QMessageBox.information(self, "分析完成", f"分析运行 ID：{result.analysis_run_id}")

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        self.status_label.setText("分析失败")
        self.error_text.setPlainText(message)
        QMessageBox.warning(self, "分析失败", message)

    @Slot(str)
    def _analysis_canceled(self, message: str) -> None:
        self.status_label.setText(message)
        self.error_text.setPlainText(message)

    @Slot()
    def _clear_worker(self) -> None:
        self._worker_thread = None
        self._worker = None
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def _start_worker(self, task_name: str, task) -> None:
        self._worker_thread = QThread(self)
        self._worker = BackgroundTaskWorker(task_name, task)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.finished.connect(self._analysis_finished)
        self._worker.failed.connect(self._analysis_failed)
        self._worker.canceled.connect(self._analysis_canceled)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker.canceled.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.finished.connect(self._clear_worker)
        self._worker_thread.start()

    def export_current_table(self) -> None:
        rows = self._current_rows()
        if not rows:
            QMessageBox.information(self, "没有可导出数据", "当前表格没有数据。")
            return

        default_path = get_exports_dir() / f"{self.tabs.tabText(self.tabs.currentIndex())}.csv"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 CSV",
            str(default_path),
            "CSV 文件 (*.csv)",
        )
        if not output_path:
            return

        try:
            export_result_table(rows, output_path)
        except Exception as error:
            QMessageBox.warning(self, "导出失败", str(error))
            return

        QMessageBox.information(self, "导出成功", output_path)

    def _show_result(self, result: TopicModelingResult) -> None:
        _fill_table(self.topic_table, result.topic_keywords)
        _fill_table(self.document_topic_table, result.document_topic_distribution)
        _fill_table(self.frequency_table, result.word_frequencies)
        _fill_table(self.tfidf_table, result.tfidf_table)

    def _current_rows(self) -> list[dict[str, object]]:
        if self.current_result is None:
            return []
        index = self.tabs.currentIndex()
        if index == 0:
            return self.current_result.topic_keywords
        if index == 1:
            return self.current_result.document_topic_distribution
        if index == 2:
            return self.current_result.word_frequencies
        return self.current_result.tfidf_table


def _table() -> QTableWidget:
    table = QTableWidget()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill_table(table: QTableWidget, rows: list[dict[str, object]]) -> None:
    table.clear()
    if not rows:
        table.setRowCount(0)
        table.setColumnCount(0)
        return

    headers = list(rows[0].keys())
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, key in enumerate(headers):
            table.setItem(row_index, column_index, QTableWidgetItem(str(row.get(key, ""))))
