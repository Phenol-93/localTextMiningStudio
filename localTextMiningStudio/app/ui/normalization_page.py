"""Entity and relation normalization page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.normalizer import (
    entity_frequency_stats,
    relation_frequency_stats,
    save_entity_mapping,
    save_relation_mapping,
)


class NormalizationPage(QWidget):
    """Page for relation and entity standardization mappings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None

        title = QLabel("实体/关系标准化")
        title.setObjectName("pageTitle")
        self.project_label = QLabel("当前项目：未打开")

        self.tabs = QTabWidget()
        self.relation_table = _table(["原始关系", "出现次数", "示例证据", "标准关系", "操作"])
        self.entity_table = _table(["原始实体", "出现次数", "实体类型", "标准实体", "操作"])
        self.tabs.addTab(self.relation_table, "关系标准化")
        self.tabs.addTab(self.entity_table, "实体标准化")

        self.refresh_button = QPushButton("刷新")
        self.save_button = QPushButton("保存当前行映射")
        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(self.project_label)
        layout.addLayout(buttons)
        layout.addWidget(self.tabs, stretch=1)

        self.refresh_button.clicked.connect(self.refresh)
        self.save_button.clicked.connect(self.save_current_mapping)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")
        self.refresh()

    def refresh(self) -> None:
        if self.database_path is None or self.project_id is None:
            return
        self._fill_relations()
        self._fill_entities()

    def save_current_mapping(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return

        if self.tabs.currentWidget() is self.relation_table:
            self._save_relation_row()
        else:
            self._save_entity_row()

    def _fill_relations(self) -> None:
        rows = relation_frequency_stats(self.database_path, self.project_id)
        self.relation_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.source_relation,
                str(row.count),
                row.example_evidence,
                row.canonical_relation,
                "",
            ]
            _set_row(self.relation_table, row_index, values, editable_columns={3})
            button = QPushButton("保存")
            button.clicked.connect(lambda _checked=False, current_row=row_index: self._save_relation_row(current_row))
            self.relation_table.setCellWidget(row_index, 4, button)

    def _fill_entities(self) -> None:
        rows = entity_frequency_stats(self.database_path, self.project_id)
        self.entity_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.source_entity,
                str(row.count),
                row.entity_type,
                row.canonical_entity,
                "",
            ]
            _set_row(self.entity_table, row_index, values, editable_columns={3})
            button = QPushButton("保存")
            button.clicked.connect(lambda _checked=False, current_row=row_index: self._save_entity_row(current_row))
            self.entity_table.setCellWidget(row_index, 4, button)

    def _save_relation_row(self, row: int | None = None) -> None:
        if row is None:
            row = self.relation_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择行", "请先选择要保存的关系映射。")
            return
        source = self.relation_table.item(row, 0).text().strip()
        canonical = self.relation_table.item(row, 3).text().strip()
        if not canonical:
            QMessageBox.warning(self, "标准关系为空", "请输入标准关系。")
            return
        save_relation_mapping(self.database_path, self.project_id, source, canonical)
        QMessageBox.information(self, "保存成功", "关系映射已保存。")
        self.refresh()

    def _save_entity_row(self, row: int | None = None) -> None:
        if row is None:
            row = self.entity_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择行", "请先选择要保存的实体映射。")
            return
        source = self.entity_table.item(row, 0).text().strip()
        entity_type = self.entity_table.item(row, 2).text().strip()
        canonical = self.entity_table.item(row, 3).text().strip()
        if not canonical:
            QMessageBox.warning(self, "标准实体为空", "请输入标准实体。")
            return
        save_entity_mapping(
            self.database_path,
            self.project_id,
            source,
            canonical,
            entity_type=entity_type or None,
        )
        QMessageBox.information(self, "保存成功", "实体映射已保存。")
        self.refresh()


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
    return table


def _set_row(table: QTableWidget, row_index: int, values: list[str], editable_columns: set[int]) -> None:
    for column_index, value in enumerate(values):
        item = QTableWidgetItem(value)
        if column_index not in editable_columns:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row_index, column_index, item)
