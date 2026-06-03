"""Export center page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.exporter import export_project_csvs
from app.core.reporting import generate_project_report
from app.db.database import connection_scope
from app.db.repositories import TripleRepository
from app.utils.paths import get_exports_dir


FILTER_FIELDS = ["status", "relation", "subject_type", "object_type", "source_doc"]


class ExportPage(QWidget):
    """Page for exporting triples and graph CSV files."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None

        title = QLabel("导出中心")
        title.setObjectName("pageTitle")
        self.project_label = QLabel("当前项目：未打开")

        self.output_dir_edit = QLineEdit(str(get_exports_dir()))
        self.output_dir_edit.setReadOnly(True)
        self.choose_dir_button = QPushButton("选择目录")
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.output_dir_edit, stretch=1)
        dir_layout.addWidget(self.choose_dir_button)

        self.filter_boxes: dict[str, QComboBox] = {}
        filters_layout = QHBoxLayout()
        for field in FILTER_FIELDS:
            combo = QComboBox()
            combo.addItem("全部", "")
            self.filter_boxes[field] = combo
            filters_layout.addWidget(QLabel(field))
            filters_layout.addWidget(combo)
        filters_layout.addStretch(1)

        self.export_button = QPushButton("导出 CSV")
        self.report_button = QPushButton("生成报告")
        self.html_report_checkbox = QCheckBox("同时生成 HTML")
        self.refresh_button = QPushButton("刷新筛选")
        self.result_label = QLabel("")
        actions = QHBoxLayout()
        actions.addWidget(self.export_button)
        actions.addWidget(self.report_button)
        actions.addWidget(self.html_report_checkbox)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)

        form = QFormLayout()
        form.addRow("导出目录", dir_layout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(self.project_label)
        layout.addLayout(form)
        layout.addLayout(filters_layout)
        layout.addLayout(actions)
        layout.addWidget(self.result_label)
        layout.addStretch(1)

        self.choose_dir_button.clicked.connect(self.choose_output_dir)
        self.export_button.clicked.connect(self.export_csvs)
        self.report_button.clicked.connect(self.generate_report)
        self.refresh_button.clicked.connect(self.refresh_filter_values)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")
        self.refresh_filter_values()

    def choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录", self.output_dir_edit.text())
        if directory:
            self.output_dir_edit.setText(directory)

    def refresh_filter_values(self) -> None:
        if self.database_path is None or self.project_id is None:
            return
        current = {field: box.currentData() or "" for field, box in self.filter_boxes.items()}
        with connection_scope(self.database_path) as connection:
            repository = TripleRepository(connection)
            for field, combo in self.filter_boxes.items():
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("全部", "")
                for value in repository.list_filter_values(self.project_id, field):
                    combo.addItem(value, value)
                index = combo.findData(current[field])
                combo.setCurrentIndex(index if index >= 0 else 0)
                combo.blockSignals(False)

    def export_csvs(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return
        output_dir = Path(self.output_dir_edit.text())
        try:
            result = export_project_csvs(
                self.database_path,
                self.project_id,
                output_dir,
                filters=self._filters(),
            )
        except Exception as error:
            QMessageBox.critical(self, "导出失败", str(error))
            return

        message = (
            f"已导出 {result.triple_count} 条三元组、"
            f"{result.node_count} 个节点、{result.edge_count} 条边：{output_dir}"
        )
        self.result_label.setText(message)
        QMessageBox.information(self, "导出成功", message)

    def generate_report(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return
        output_dir = Path(self.output_dir_edit.text())
        try:
            result = generate_project_report(
                self.database_path,
                self.project_id,
                output_dir,
                include_html=self.html_report_checkbox.isChecked(),
            )
        except Exception as error:
            QMessageBox.critical(self, "生成报告失败", str(error))
            return

        paths = [str(result.markdown_path)]
        if result.html_path is not None:
            paths.append(str(result.html_path))
        message = "报告已生成：" + "；".join(paths)
        self.result_label.setText(message)
        QMessageBox.information(self, "生成报告成功", message)

    def _filters(self) -> dict[str, str]:
        return {
            field: str(combo.currentData())
            for field, combo in self.filter_boxes.items()
            if combo.currentData()
        }
