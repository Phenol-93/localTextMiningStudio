"""Triple review table page."""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.db.database import connection_scope
from app.db.repositories import TripleRepository
from app.utils.paths import get_exports_dir


COLUMNS = [
    "选择",
    "subject",
    "relation",
    "object",
    "subject_type",
    "object_type",
    "evidence",
    "source_doc",
    "confidence",
    "status",
]
EDITABLE_COLUMNS = {"subject", "relation", "object", "subject_type", "object_type", "evidence", "status"}
FILTER_FIELDS = ["status", "relation", "subject_type", "object_type", "source_doc"]


class TripleReviewPage(QWidget):
    """Review, edit, filter, and export AI candidate triples."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None
        self.current_rows: list[dict[str, object]] = []
        self._loading = False

        title = QLabel("三元组审核表")
        title.setObjectName("pageTitle")
        warning = QLabel("AI 抽取结果为候选结果，建议人工确认后用于正式分析。")
        warning.setObjectName("tripleReviewWarning")
        self.project_label = QLabel("当前项目：未打开")

        self.filter_boxes: dict[str, QComboBox] = {}
        filters_layout = QHBoxLayout()
        for field in FILTER_FIELDS:
            combo = QComboBox()
            combo.addItem("全部", "")
            combo.currentIndexChanged.connect(self.refresh)
            self.filter_boxes[field] = combo
            filters_layout.addWidget(QLabel(field))
            filters_layout.addWidget(combo)
        filters_layout.addStretch(1)

        self.page_size_spin = QSpinBox()
        self.page_size_spin.setRange(20, 1000)
        self.page_size_spin.setValue(200)
        self.page_size_spin.valueChanged.connect(self.refresh)
        self.prev_button = QPushButton("上一页")
        self.next_button = QPushButton("下一页")
        self.page_label = QLabel("第 1 页")
        self.page_index = 0

        paging_layout = QHBoxLayout()
        paging_layout.addWidget(QLabel("每页"))
        paging_layout.addWidget(self.page_size_spin)
        paging_layout.addWidget(self.prev_button)
        paging_layout.addWidget(self.next_button)
        paging_layout.addWidget(self.page_label)
        paging_layout.addStretch(1)

        self.accept_button = QPushButton("接受")
        self.reject_button = QPushButton("拒绝")
        self.delete_button = QPushButton("删除")
        self.context_button = QPushButton("查看原文上下文")
        self.batch_accept_button = QPushButton("批量接受")
        self.batch_reject_button = QPushButton("批量拒绝")
        self.batch_delete_button = QPushButton("批量删除")
        self.export_button = QPushButton("导出")
        self.refresh_button = QPushButton("刷新")

        actions_layout = QHBoxLayout()
        for button in [
            self.accept_button,
            self.reject_button,
            self.delete_button,
            self.context_button,
            self.batch_accept_button,
            self.batch_reject_button,
            self.batch_delete_button,
            self.export_button,
            self.refresh_button,
        ]:
            actions_layout.addWidget(button)
        actions_layout.addStretch(1)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(warning)
        layout.addWidget(self.project_label)
        layout.addLayout(filters_layout)
        layout.addLayout(paging_layout)
        layout.addLayout(actions_layout)
        layout.addWidget(self.table, stretch=1)

        self.table.itemChanged.connect(self._item_changed)
        self.prev_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.accept_button.clicked.connect(lambda: self._single_status("accepted"))
        self.reject_button.clicked.connect(lambda: self._single_status("rejected"))
        self.delete_button.clicked.connect(self._single_delete)
        self.context_button.clicked.connect(self.show_context)
        self.batch_accept_button.clicked.connect(lambda: self._batch_status("accepted"))
        self.batch_reject_button.clicked.connect(lambda: self._batch_status("rejected"))
        self.batch_delete_button.clicked.connect(self._batch_delete)
        self.export_button.clicked.connect(self.export_csv)
        self.refresh_button.clicked.connect(self.refresh_all)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")
        self.refresh_all()

    def refresh_all(self) -> None:
        self.page_index = 0
        self.refresh_filter_values()
        self.refresh()

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

    def refresh(self) -> None:
        if self.database_path is None or self.project_id is None:
            return
        filters = self._filters()
        limit = self.page_size_spin.value()
        offset = self.page_index * limit
        with connection_scope(self.database_path) as connection:
            repository = TripleRepository(connection)
            rows = repository.list_for_review(self.project_id, filters=filters, limit=limit, offset=offset)
            total = repository.count_for_review(self.project_id, filters=filters)
        self.current_rows = [dict(row) for row in rows]
        self._fill_table()
        self.page_label.setText(f"第 {self.page_index + 1} 页 / 共 {total} 条")
        self.prev_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(offset + limit < total)

    def previous_page(self) -> None:
        if self.page_index > 0:
            self.page_index -= 1
            self.refresh()

    def next_page(self) -> None:
        self.page_index += 1
        self.refresh()

    def show_context(self) -> None:
        triple_id = self._current_triple_id()
        if triple_id is None:
            QMessageBox.information(self, "请选择三元组", "请先选择一条三元组。")
            return
        with connection_scope(self.database_path) as connection:
            context = TripleRepository(connection).get_source_context(triple_id)
        dialog = QDialog(self)
        dialog.setWindowTitle("原文上下文")
        details = QTextEdit(dialog)
        details.setReadOnly(True)
        details.setPlainText(context)
        details.setMinimumSize(760, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(details)
        dialog.exec()

    def export_csv(self) -> None:
        if self.database_path is None or self.project_id is None:
            return
        default_path = get_exports_dir() / "triples_review.csv"
        output_path, _ = QFileDialog.getSaveFileName(self, "导出三元组", str(default_path), "CSV 文件 (*.csv)")
        if not output_path:
            return

        rows = self._filtered_export_rows()
        with Path(output_path).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=[column for column in COLUMNS if column != "选择"])
            writer.writeheader()
            writer.writerows(rows)
        QMessageBox.information(self, "导出成功", output_path)

    def _filtered_export_rows(self) -> list[dict[str, object]]:
        with connection_scope(self.database_path) as connection:
            rows = TripleRepository(connection).list_for_review(
                self.project_id,
                filters=self._filters(),
                limit=1_000_000,
                offset=0,
            )
        return [
            {column: row[column] for column in COLUMNS if column != "选择"}
            for row in rows
        ]

    def _fill_table(self) -> None:
        self._loading = True
        self.table.setRowCount(len(self.current_rows))
        for row_index, row in enumerate(self.current_rows):
            checkbox = QCheckBox()
            checkbox.setProperty("triple_id", row["id"])
            self.table.setCellWidget(row_index, 0, checkbox)
            for column_index, column in enumerate(COLUMNS[1:], start=1):
                item = QTableWidgetItem("" if row.get(column) is None else str(row.get(column)))
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                if column not in EDITABLE_COLUMNS:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, column_index, item)
        self._loading = False

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self.database_path is None:
            return
        triple_id = int(item.data(Qt.ItemDataRole.UserRole))
        column = COLUMNS[item.column()]
        value = item.text().strip()
        if column not in EDITABLE_COLUMNS:
            return
        with connection_scope(self.database_path) as connection:
            repository = TripleRepository(connection)
            if column == "status":
                repository.update_status(triple_id, value)
            else:
                kwargs = {
                    "subject": None,
                    "relation": None,
                    "object_value": None,
                    "subject_type": None,
                    "object_type": None,
                    "evidence": None,
                }
                key = "object_value" if column == "object" else ("evidence" if column == "evidence" else column)
                kwargs[key] = value
                repository.update_review_fields(triple_id, **kwargs)
        self.refresh_filter_values()
        self.refresh()

    def _single_status(self, status: str) -> None:
        triple_id = self._current_triple_id()
        if triple_id is None:
            return
        with connection_scope(self.database_path) as connection:
            TripleRepository(connection).update_status(triple_id, status)
        self.refresh_all()

    def _single_delete(self) -> None:
        triple_id = self._current_triple_id()
        if triple_id is None:
            return
        with connection_scope(self.database_path) as connection:
            TripleRepository(connection).delete(triple_id)
        self.refresh_all()

    def _batch_status(self, status: str) -> None:
        ids = self._checked_triple_ids()
        if not ids:
            QMessageBox.information(self, "请选择三元组", "请先勾选要批量处理的三元组。")
            return
        with connection_scope(self.database_path) as connection:
            TripleRepository(connection).update_status_many(ids, status)
        self.refresh_all()

    def _batch_delete(self) -> None:
        ids = self._checked_triple_ids()
        if not ids:
            QMessageBox.information(self, "请选择三元组", "请先勾选要删除的三元组。")
            return
        with connection_scope(self.database_path) as connection:
            TripleRepository(connection).delete_many(ids)
        self.refresh_all()

    def _current_triple_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.current_rows):
            return None
        return int(self.current_rows[row]["id"])

    def _checked_triple_ids(self) -> list[int]:
        ids: list[int] = []
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox) and widget.isChecked():
                ids.append(int(widget.property("triple_id")))
        return ids

    def _filters(self) -> dict[str, str]:
        return {
            field: str(combo.currentData())
            for field, combo in self.filter_boxes.items()
            if combo.currentData()
        }
