"""AI triple extraction page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.ai_extraction import AIExtractionOptions, ExtractionRunResult, run_ai_extraction
from app.core.prompt_templates import PromptTemplateError, PromptTemplateManager
from app.providers.base import ProviderConfig, normalize_provider_name
from app.providers.registry import with_provider_defaults
from app.providers.settings import (
    AISettingsError,
    load_ai_settings,
    load_saved_api_key,
    load_session_api_key,
)
from app.utils.background_tasks import BackgroundTaskWorker, TaskContext


PROVIDER_ITEMS = [
    ("GPT / OpenAI", "openai"),
    ("Gemini", "gemini"),
    ("DeepSeek", "deepseek"),
    ("Qwen / 阿里云百炼", "qwen"),
    ("本地 Ollama", "ollama"),
    ("自定义 OpenAI-compatible", "custom"),
]


class AIExtractionPage(QWidget):
    """UI for AI candidate triple extraction."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path: Path | None = None
        self.project_id: int | None = None
        self.prompt_manager = PromptTemplateManager()
        self._worker_thread: QThread | None = None
        self._worker: BackgroundTaskWorker | None = None

        title = QLabel("AI 三元组抽取")
        title.setObjectName("pageTitle")
        warning = QLabel("AI 抽取结果为候选结果，建议人工确认后用于正式分析。")
        warning.setObjectName("aiExtractionWarning")

        self.project_label = QLabel("当前项目：未打开")

        self.provider_combo = QComboBox()
        for label, provider_name in PROVIDER_ITEMS:
            self.provider_combo.addItem(label, provider_name)

        self.model_edit = QLineEdit()
        self.template_combo = QComboBox()
        self.text_range_combo = QComboBox()
        self.text_range_combo.addItem("documents.cleaned_text", "documents")
        self.text_range_combo.addItem("chunks.content", "chunks")

        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(100, 50000)
        self.chunk_size_spin.setSingleStep(500)
        self.chunk_size_spin.setValue(2000)

        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 5)
        self.retry_spin.setValue(1)

        form = QFormLayout()
        form.addRow("供应商", self.provider_combo)
        form.addRow("模型", self.model_edit)
        form.addRow("抽取模板", self.template_combo)
        form.addRow("文本范围", self.text_range_combo)
        form.addRow("分块大小", self.chunk_size_spin)
        form.addRow("失败重试", self.retry_spin)

        self.start_button = QPushButton("开始抽取")
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel("未开始")
        self.error_text = QTextEdit()
        self.error_text.setReadOnly(True)
        self.error_text.setPlaceholderText("错误信息")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(warning)
        layout.addWidget(self.project_label)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.error_text, stretch=1)

        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.start_button.clicked.connect(self.start_extraction)
        self.cancel_button.clicked.connect(self.cancel_task)

        self.refresh_templates()
        self._load_ai_defaults()

    def set_current_project(self, database_path: Path | str, project_id: int) -> None:
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.project_label.setText(f"当前项目：{self.database_path}")

    def refresh_templates(self) -> None:
        current = self.template_combo.currentText()
        self.template_combo.clear()
        try:
            templates = self.prompt_manager.list_templates()
        except PromptTemplateError as error:
            QMessageBox.warning(self, "模板加载失败", str(error))
            return
        for template in templates:
            self.template_combo.addItem(template.name)
        if current:
            index = self.template_combo.findText(current)
            if index >= 0:
                self.template_combo.setCurrentIndex(index)

    def start_extraction(self) -> None:
        if self.database_path is None or self.project_id is None:
            QMessageBox.information(self, "请先打开项目", "请先新建或打开一个项目。")
            return
        if not self.model_edit.text().strip():
            QMessageBox.warning(self, "模型为空", "请先输入模型名。")
            return
        if not self.template_combo.currentText():
            QMessageBox.warning(self, "模板为空", "请先选择抽取模板。")
            return

        provider_name = str(self.provider_combo.currentData())
        config = self._provider_config(provider_name)
        if normalize_provider_name(provider_name) == "custom" and not config.base_url:
            QMessageBox.warning(self, "Base URL 为空", "请先在设置页为自定义供应商配置 Base URL。")
            return
        if _requires_api_key(provider_name) and not config.resolve_api_key():
            QMessageBox.warning(self, "API Key 为空", "请先在设置页输入 API Key、保存 Key，或设置环境变量。")
            return

        options = AIExtractionOptions(
            provider_name=provider_name,
            model=self.model_edit.text().strip(),
            prompt_template_name=self.template_combo.currentText(),
            text_range=str(self.text_range_combo.currentData()),
            max_chars=self.chunk_size_spin.value(),
            temperature=config.temperature,
            timeout=config.timeout,
            retries=self.retry_spin.value(),
            base_url=config.base_url,
        )

        self.error_text.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("开始抽取")
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        database_path = self.database_path
        project_id = self.project_id
        api_key = config.api_key

        def task(context: TaskContext) -> ExtractionRunResult:
            provider_config = ProviderConfig(
                provider_name=options.provider_name,
                base_url=options.base_url,
                api_key=api_key,
                model=options.model,
                temperature=options.temperature,
                timeout=options.timeout,
            )
            from app.providers import create_provider

            provider = create_provider(provider_config)
            return run_ai_extraction(
                database_path,
                project_id,
                options,
                provider=provider,
                progress_callback=lambda done, total, message: context.report(done, total, message),
                cancel_callback=context.is_cancelled,
            )

        self._start_worker("ai_triple_extraction", task)

    def cancel_task(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("正在取消，当前模型请求会在返回或超时后停止...")

    @Slot(int, int, str)
    def _update_progress(self, done: int, total: int, message: str) -> None:
        self.progress_bar.setValue(int(done / max(1, total) * 100))
        self.status_label.setText(message)

    @Slot(object)
    def _extraction_finished(self, result: ExtractionRunResult) -> None:
        self.start_button.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"完成：写入 {result.created_triples} 条候选三元组")
        if result.errors:
            self.error_text.setPlainText("\n".join(result.errors))
        QMessageBox.information(self, "抽取完成", f"候选三元组：{result.created_triples} 条")

    @Slot(str)
    def _extraction_failed(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self.status_label.setText("抽取失败")
        self.error_text.setPlainText(message)
        QMessageBox.warning(self, "抽取失败", message)

    @Slot(str)
    def _extraction_canceled(self, message: str) -> None:
        self.status_label.setText(message)
        self.error_text.setPlainText(message)

    @Slot()
    def _clear_worker(self) -> None:
        self._worker_thread = None
        self._worker = None
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def _start_worker(self, task_name: str, task) -> None:
        self._worker_thread = QThread(self)
        self._worker = BackgroundTaskWorker(task_name, task)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.finished.connect(self._extraction_finished)
        self._worker.failed.connect(self._extraction_failed)
        self._worker.canceled.connect(self._extraction_canceled)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker.canceled.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.finished.connect(self._clear_worker)
        self._worker_thread.start()

    def _provider_changed(self) -> None:
        self._load_ai_defaults()

    def _load_ai_defaults(self) -> None:
        try:
            settings = load_ai_settings()
        except Exception:
            settings = None
        provider_name = str(self.provider_combo.currentData())
        if settings and settings.provider_name == provider_name and settings.model:
            self.model_edit.setText(settings.model)

    def _provider_config(self, provider_name: str) -> ProviderConfig:
        try:
            settings = load_ai_settings()
        except Exception:
            settings = None
        api_key = _load_api_key_safely(provider_name)

        if settings and settings.provider_name == provider_name:
            return settings.to_provider_config(api_key)

        return with_provider_defaults(
            ProviderConfig(
                provider_name=provider_name,
                api_key=api_key,
                model=self.model_edit.text().strip() or None,
            )
        )


def _load_api_key_safely(provider_name: str) -> str | None:
    session_key = load_session_api_key(provider_name)
    if session_key:
        return session_key
    try:
        return load_saved_api_key(provider_name)
    except AISettingsError:
        return None


def _requires_api_key(provider_name: str) -> bool:
    return normalize_provider_name(provider_name) != "ollama"
