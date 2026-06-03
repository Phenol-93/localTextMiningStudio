"""Document import page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QComboBox,
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

from app.core.importer import DocumentImportError, get_csv_columns, parse_document
from app.db.database import connection_scope, initialize_database
from app.db.repositories import DocumentRepository
from app.utils.background_tasks import BackgroundTaskWorker, TaskContext


class ImportPage(QWidget):
    """UI for importing supported document files into the current project."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None
        self.selected_file: Path | None = None
        self._worker_thread: QThread | None = None
        self._worker: BackgroundTaskWorker | None = None

        title = QLabel("文档导入")
        title.setObjectName("pageTitle")

        self.project_label = QLabel("当前项目：未打开")
        self.project_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.file_label = QLabel("未选择文件")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.text_column_combo = QComboBox()
        self.text_column_combo.setVisible(False)

        self.select_file_button = QPushButton("选择文件")
        self.import_button = QPushButton("导入")
        self.import_button.setEnabled(False)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.select_file_button)
        toolbar.addWidget(self.text_column_combo)
        toolbar.addWidget(self.import_button)
        toolbar.addWidget(self.cancel_button)
        toolbar.addStretch(1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel("未开始")
        self.error_text = QTextEdit()
        self.error_text.setReadOnly(True)
        self.error_text.setMaximumHeight(90)
        self.error_text.setPlaceholderText("错误信息")

        self.documents_table = QTableWidget(0, 4)
        self.documents_table.setHorizontalHeaderLabels(["文件名", "类型", "创建时间", "路径"])
        self.documents_table.horizontalHeader().setStretchLastSection(True)
        self.documents_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.documents_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(self.project_label)
        layout.addWidget(self.file_label)
        layout.addLayout(toolbar)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.error_text)
        layout.addWidget(self.documents_table, stretch=1)

        self.select_file_button.clicked.connect(self.select_file)
        self.import_button.clicked.connect(self.import_selected_file)
        self.cancel_button.clicked.connect(self.cancel_task)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")
        self.import_button.setEnabled(self.selected_file is not None)
        self.refresh_documents()

    def select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文档",
            "",
            "支持的文档 (*.txt *.csv *.docx);;文本文件 (*.txt);;CSV 文件 (*.csv);;Word 文档 (*.docx)",
        )
        if not file_path:
            return

        self.selected_file = Path(file_path)
        self.file_label.setText(f"已选择：{self.selected_file}")
        self.import_button.setEnabled(self.database_path is not None and self.project_id is not None)
        self._refresh_csv_columns()

    def import_selected_file(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return
        if self.selected_file is None:
            QMessageBox.information(self, "请选择文件", "请先选择要导入的文档。")
            return

        if self._worker_thread is not None:
            return

        text_column = self.text_column_combo.currentText() if self.text_column_combo.isVisible() else None
        file_path = self.selected_file
        database_path = self.database_path
        project_id = self.project_id

        def task(context: TaskContext) -> int:
            context.report(0, 3, "开始导入")
            context.check_cancelled()
            parsed = parse_document(file_path, text_column=text_column or None)
            context.report(1, 3, "文档解析完成")
            context.check_cancelled()
            initialize_database(database_path)
            with connection_scope(database_path) as connection:
                repository = DocumentRepository(connection)
                document_id = repository.create(
                    project_id,
                    parsed.filename,
                    filename=parsed.filename,
                    file_path=parsed.file_path,
                    file_type=parsed.file_type,
                    raw_text=parsed.raw_text,
                    metadata=parsed.metadata,
                    status="imported",
                )
            context.report(3, 3, "导入完成")
            return document_id

        self.error_text.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("开始导入")
        self.import_button.setEnabled(False)
        self.select_file_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._start_worker("document_import", task)

    def cancel_task(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("正在取消...")

    @Slot(int, int, str)
    def _update_progress(self, done: int, total: int, message: str) -> None:
        self.progress_bar.setValue(int(done / max(1, total) * 100))
        self.status_label.setText(message)

    @Slot(object)
    def _task_finished(self, _result: object) -> None:
        self.progress_bar.setValue(100)
        self.status_label.setText("导入完成")
        self.refresh_documents()
        QMessageBox.information(self, "导入成功", "文档已导入。")

    @Slot(str)
    def _task_failed(self, message: str) -> None:
        self.status_label.setText("导入失败")
        self.error_text.setPlainText(message)
        QMessageBox.warning(self, "导入失败", message)

    @Slot(str)
    def _task_canceled(self, message: str) -> None:
        self.status_label.setText(message)
        self.error_text.setPlainText(message)

    @Slot()
    def _clear_worker(self) -> None:
        self._worker_thread = None
        self._worker = None
        self.import_button.setEnabled(self.database_path is not None and self.project_id is not None and self.selected_file is not None)
        self.select_file_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def _start_worker(self, task_name: str, task) -> None:
        self._worker_thread = QThread(self)
        self._worker = BackgroundTaskWorker(task_name, task)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.finished.connect(self._task_finished)
        self._worker.failed.connect(self._task_failed)
        self._worker.canceled.connect(self._task_canceled)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker.canceled.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.finished.connect(self._clear_worker)
        self._worker_thread.start()

    def refresh_documents(self) -> None:
        self.documents_table.setRowCount(0)
        if self.database_path is None or self.project_id is None:
            return

        with connection_scope(self.database_path) as connection:
            documents = DocumentRepository(connection).list_by_project(self.project_id)

        self.documents_table.setRowCount(len(documents))
        for row_index, document in enumerate(documents):
            values = [
                document["filename"] or document["title"],
                document["file_type"] or "",
                document["created_at"],
                document["file_path"] or "",
            ]
            for column_index, value in enumerate(values):
                self.documents_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))

    def _refresh_csv_columns(self) -> None:
        self.text_column_combo.clear()
        if self.selected_file is None or self.selected_file.suffix.lower() != ".csv":
            self.text_column_combo.setVisible(False)
            return

        try:
            columns = get_csv_columns(self.selected_file)
        except DocumentImportError as error:
            self.text_column_combo.setVisible(False)
            QMessageBox.warning(self, "读取 CSV 失败", str(error))
            return

        self.text_column_combo.addItems(columns)
        self.text_column_combo.setVisible(bool(columns))
