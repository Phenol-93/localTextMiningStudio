"""Text preprocessing page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.preprocessing import PreprocessOptions, TextPreprocessor
from app.db.database import connection_scope
from app.db.repositories import DocumentRepository


class PreprocessingPage(QWidget):
    """UI for configuring, previewing, and saving cleaned document text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None
        self._document_ids: list[int] = []
        self._last_cleaned_text = ""
        self._last_options: PreprocessOptions | None = None

        title = QLabel("文本预处理")
        title.setObjectName("pageTitle")

        self.project_label = QLabel("当前项目：未打开")
        self.document_combo = QComboBox()

        self.remove_punctuation = QCheckBox("去标点")
        self.remove_punctuation.setChecked(True)
        self.remove_digits = QCheckBox("去数字")
        self.lowercase = QCheckBox("小写化")
        self.lowercase.setChecked(True)
        self.use_jieba = QCheckBox("中文分词 jieba")
        self.use_jieba.setChecked(True)
        self.use_default_stopwords = QCheckBox("使用默认中文停用词")

        self.min_word_length = QSpinBox()
        self.min_word_length.setRange(1, 50)
        self.min_word_length.setValue(1)

        self.custom_words = QTextEdit()
        self.custom_words.setPlaceholderText("每行一个自定义词")
        self.custom_words.setFixedHeight(80)

        self.custom_stopwords = QTextEdit()
        self.custom_stopwords.setPlaceholderText("每行一个自定义停用词")
        self.custom_stopwords.setFixedHeight(80)

        form = QFormLayout()
        form.addRow("选择文档", self.document_combo)
        form.addRow("最小词长", self.min_word_length)
        form.addRow("自定义词典", self.custom_words)
        form.addRow("自定义停用词", self.custom_stopwords)

        options_layout = QHBoxLayout()
        options_layout.addWidget(self.remove_punctuation)
        options_layout.addWidget(self.remove_digits)
        options_layout.addWidget(self.lowercase)
        options_layout.addWidget(self.use_jieba)
        options_layout.addWidget(self.use_default_stopwords)
        options_layout.addStretch(1)

        self.preview_button = QPushButton("预览")
        self.save_button = QPushButton("保存 cleaned_text")
        self.save_button.setEnabled(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText("预览前 100 个 token")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(self.project_label)
        layout.addLayout(form)
        layout.addLayout(options_layout)
        layout.addLayout(buttons)
        layout.addWidget(self.preview_text, stretch=1)

        self.preview_button.clicked.connect(self.preview)
        self.save_button.clicked.connect(self.save_cleaned_text)
        self.document_combo.currentIndexChanged.connect(self._clear_preview)

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")
        self.refresh_documents()

    def refresh_documents(self) -> None:
        self.document_combo.clear()
        self._document_ids = []
        self._clear_preview()
        if self.database_path is None or self.project_id is None:
            return

        with connection_scope(self.database_path) as connection:
            documents = DocumentRepository(connection).list_by_project(self.project_id)

        for document in documents:
            self._document_ids.append(int(document["id"]))
            label = document["filename"] or document["title"]
            self.document_combo.addItem(label)

    def preview(self) -> None:
        document_id = self._selected_document_id()
        if document_id is None:
            QMessageBox.information(self, "请选择文档", "请先选择一个已导入文档。")
            return

        document = self._load_document(document_id)
        if document is None:
            QMessageBox.warning(self, "文档不存在", "无法读取所选文档。")
            return

        options = self._build_options()
        result = TextPreprocessor(options).preprocess(document["raw_text"])

        self._last_cleaned_text = result.cleaned_text
        self._last_options = result.options
        self.preview_text.setPlainText(" ".join(result.tokens[:100]))
        self.save_button.setEnabled(True)

    def save_cleaned_text(self) -> None:
        document_id = self._selected_document_id()
        if document_id is None or self.database_path is None or self._last_options is None:
            QMessageBox.information(self, "请先预览", "请先预览并生成预处理结果。")
            return

        with connection_scope(self.database_path) as connection:
            DocumentRepository(connection).save_preprocessing_result(
                document_id,
                self._last_cleaned_text,
                self._last_options.to_dict(),
            )

        QMessageBox.information(self, "保存成功", "cleaned_text 已保存。")
        self.save_button.setEnabled(False)
        self.refresh_documents()

    def _selected_document_id(self) -> int | None:
        index = self.document_combo.currentIndex()
        if index < 0 or index >= len(self._document_ids):
            return None
        return self._document_ids[index]

    def _load_document(self, document_id: int):
        if self.database_path is None:
            return None
        with connection_scope(self.database_path) as connection:
            return DocumentRepository(connection).get(document_id)

    def _build_options(self) -> PreprocessOptions:
        return PreprocessOptions(
            remove_punctuation=self.remove_punctuation.isChecked(),
            remove_digits=self.remove_digits.isChecked(),
            lowercase=self.lowercase.isChecked(),
            use_jieba=self.use_jieba.isChecked(),
            use_default_stopwords=self.use_default_stopwords.isChecked(),
            min_word_length=self.min_word_length.value(),
            custom_words=_lines(self.custom_words.toPlainText()),
            custom_stopwords=_lines(self.custom_stopwords.toPlainText()),
        )

    def _clear_preview(self) -> None:
        self.preview_text.clear()
        self._last_cleaned_text = ""
        self._last_options = None
        self.save_button.setEnabled(False)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
