"""Application settings page."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.prompt_templates import (
    PromptTemplate,
    PromptTemplateError,
    PromptTemplateManager,
)
from app.providers import ProviderError, create_provider
from app.providers.base import normalize_provider_name
from app.providers.registry import with_provider_defaults
from app.providers.settings import (
    AIProviderSettings,
    AISettingsError,
    clear_session_api_key,
    clear_saved_api_key,
    load_ai_settings,
    load_saved_api_key,
    load_session_api_key,
    remember_session_api_key,
    save_ai_settings,
    save_api_key,
)
from app.utils.logging import redact_sensitive


PROVIDER_ITEMS = [
    ("GPT / OpenAI", "openai"),
    ("Gemini", "gemini"),
    ("DeepSeek", "deepseek"),
    ("Qwen / 阿里云百炼", "qwen"),
    ("本地 Ollama", "ollama"),
    ("自定义 OpenAI-compatible", "custom"),
]


class SettingsPage(QWidget):
    """Settings page with AI provider configuration."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_provider_name = "openai"
        self._worker_thread: QThread | None = None
        self._worker: _ConnectionTestWorker | None = None
        self.prompt_manager = PromptTemplateManager()

        title = QLabel("设置")
        title.setObjectName("pageTitle")

        ai_group = QGroupBox("AI 设置")
        self.provider_combo = QComboBox()
        for label, provider_name in PROVIDER_ITEMS:
            self.provider_combo.addItem(label, provider_name)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("默认仅保存在当前会话")

        self.base_url_edit = QLineEdit()
        self.model_edit = QLineEdit()

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(2)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setSuffix(" 秒")

        self.save_api_key_checkbox = QCheckBox("保存 API Key")
        self.saved_key_label = QLabel("未检查保存状态")

        self.save_button = QPushButton("保存设置")
        self.clear_key_button = QPushButton("清除已保存 Key")
        self.test_button = QPushButton("测试连接")

        form = QFormLayout(ai_group)
        form.addRow("供应商", self.provider_combo)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("模型名", self.model_edit)
        form.addRow("temperature", self.temperature_spin)
        form.addRow("timeout", self.timeout_spin)
        form.addRow("", self.save_api_key_checkbox)
        form.addRow("Key 状态", self.saved_key_label)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.clear_key_button)
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        form.addRow(buttons)

        advanced_group = QGroupBox("高级设置")
        self.template_combo = QComboBox()
        self.copy_template_button = QPushButton("复制模板")
        self.edit_template_button = QPushButton("编辑模板")
        self.restore_templates_button = QPushButton("恢复默认模板")
        self.import_template_button = QPushButton("导入模板")
        self.export_template_button = QPushButton("导出模板")

        template_buttons = QHBoxLayout()
        template_buttons.addWidget(self.copy_template_button)
        template_buttons.addWidget(self.edit_template_button)
        template_buttons.addWidget(self.restore_templates_button)
        template_buttons.addWidget(self.import_template_button)
        template_buttons.addWidget(self.export_template_button)
        template_buttons.addStretch(1)

        advanced_form = QFormLayout(advanced_group)
        advanced_form.addRow("抽取规则模板", self.template_combo)
        advanced_form.addRow(template_buttons)
        form.addRow(advanced_group)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addWidget(ai_group)
        layout.addStretch(1)

        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.save_button.clicked.connect(self.save_settings)
        self.clear_key_button.clicked.connect(self.clear_saved_key)
        self.test_button.clicked.connect(self.test_connection)
        self.copy_template_button.clicked.connect(self.copy_template)
        self.edit_template_button.clicked.connect(self.edit_template)
        self.restore_templates_button.clicked.connect(self.restore_templates)
        self.import_template_button.clicked.connect(self.import_template)
        self.export_template_button.clicked.connect(self.export_template)

        self._load_settings()
        self.refresh_templates()

    def save_settings(self) -> None:
        provider_name = self._provider_name()
        self._remember_session_key(provider_name)
        settings = self._build_settings()

        try:
            save_ai_settings(settings)
            if settings.save_api_key:
                api_key = self._current_api_key()
                if not api_key:
                    QMessageBox.warning(self, "API Key 为空", "请先输入 API Key，再勾选保存。")
                    return
                save_api_key(provider_name, api_key)
        except AISettingsError as error:
            QMessageBox.warning(self, "保存失败", str(error))
            return
        except Exception as error:
            QMessageBox.warning(self, "保存失败", str(error))
            return

        self._refresh_saved_key_status()
        QMessageBox.information(self, "保存成功", "AI 设置已保存。")

    def clear_saved_key(self) -> None:
        provider_name = self._provider_name()
        try:
            clear_saved_api_key(provider_name)
        except AISettingsError as error:
            QMessageBox.warning(self, "清除失败", str(error))
            return

        clear_session_api_key(provider_name)
        self.api_key_edit.clear()
        self.save_api_key_checkbox.setChecked(False)
        self._refresh_saved_key_status()
        QMessageBox.information(self, "已清除", "已清除当前供应商保存的 API Key。")

    def test_connection(self) -> None:
        provider_name = self._provider_name()
        self._remember_session_key(provider_name)
        settings = self._build_settings()
        api_key = self._current_api_key()

        if not settings.model:
            QMessageBox.warning(self, "模型名为空", "请先输入模型名。")
            return
        if normalize_provider_name(settings.provider_name) == "custom" and not settings.base_url:
            QMessageBox.warning(self, "Base URL 为空", "自定义供应商需要输入 Base URL。")
            return
        if _requires_api_key(settings.provider_name) and not settings.to_provider_config(api_key).resolve_api_key():
            QMessageBox.warning(self, "API Key 为空", "请先输入 API Key，或设置对应环境变量。")
            return

        config = settings.to_provider_config(api_key)
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中...")

        self._worker_thread = QThread(self)
        self._worker = _ConnectionTestWorker(config)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._connection_test_succeeded)
        self._worker.failed.connect(self._connection_test_failed)
        self._worker.succeeded.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.finished.connect(self._clear_worker)
        self._worker_thread.start()

    def refresh_templates(self) -> None:
        current_name = self.template_combo.currentText()
        self.template_combo.clear()
        try:
            templates = self.prompt_manager.list_templates()
        except PromptTemplateError as error:
            QMessageBox.warning(self, "模板加载失败", str(error))
            return

        for template in templates:
            self.template_combo.addItem(template.name)

        if current_name:
            index = self.template_combo.findText(current_name)
            if index >= 0:
                self.template_combo.setCurrentIndex(index)

    def copy_template(self) -> None:
        source_name = self.template_combo.currentText()
        if not source_name:
            QMessageBox.information(self, "请选择模板", "请先选择一个模板。")
            return

        new_name, accepted = QInputDialog.getText(self, "复制模板", "新模板名称")
        if not accepted or not new_name.strip():
            return

        try:
            self.prompt_manager.copy_template(source_name, new_name.strip())
        except PromptTemplateError as error:
            QMessageBox.warning(self, "复制失败", str(error))
            return

        self.refresh_templates()
        self.template_combo.setCurrentText(new_name.strip())

    def edit_template(self) -> None:
        template_name = self.template_combo.currentText()
        if not template_name:
            QMessageBox.information(self, "请选择模板", "请先选择一个模板。")
            return

        try:
            template = self.prompt_manager.get_template(template_name)
        except PromptTemplateError as error:
            QMessageBox.warning(self, "读取模板失败", str(error))
            return

        dialog = PromptTemplateDialog(template, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self.prompt_manager.save_template(dialog.template())
        except PromptTemplateError as error:
            QMessageBox.warning(self, "保存模板失败", str(error))
            return

        self.refresh_templates()
        self.template_combo.setCurrentText(dialog.template().name)

    def restore_templates(self) -> None:
        reply = QMessageBox.question(
            self,
            "恢复默认模板",
            "将删除用户自定义模板并恢复默认模板，是否继续？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.prompt_manager.restore_defaults()
        self.refresh_templates()

    def import_template(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入模板",
            "",
            "JSON 模板 (*.json)",
        )
        if not file_path:
            return

        try:
            template = self.prompt_manager.import_template(file_path)
        except PromptTemplateError as error:
            QMessageBox.warning(self, "导入失败", str(error))
            return

        self.refresh_templates()
        self.template_combo.setCurrentText(template.name)

    def export_template(self) -> None:
        template_name = self.template_combo.currentText()
        if not template_name:
            QMessageBox.information(self, "请选择模板", "请先选择一个模板。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出模板",
            f"{template_name}.json",
            "JSON 模板 (*.json)",
        )
        if not file_path:
            return

        try:
            self.prompt_manager.export_template(template_name, file_path)
        except PromptTemplateError as error:
            QMessageBox.warning(self, "导出失败", str(error))
            return

        QMessageBox.information(self, "导出成功", file_path)

    @Slot()
    def _connection_test_succeeded(self) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")
        QMessageBox.information(self, "连接成功", "AI Provider 连接测试通过。")

    @Slot(str)
    def _connection_test_failed(self, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")
        QMessageBox.warning(self, "连接失败", message)

    @Slot()
    def _clear_worker(self) -> None:
        self._worker_thread = None
        self._worker = None

    def _load_settings(self) -> None:
        settings = load_ai_settings()
        provider_index = self.provider_combo.findData(settings.provider_name)
        if provider_index < 0:
            provider_index = 0
        self.provider_combo.setCurrentIndex(provider_index)
        self._current_provider_name = self._provider_name()
        self._apply_settings(settings)
        self._refresh_saved_key_status()

    def _apply_settings(self, settings: AIProviderSettings) -> None:
        config = with_provider_defaults(settings.to_provider_config())
        self.base_url_edit.setText(config.base_url or "")
        self.model_edit.setText(config.model or "")
        self.temperature_spin.setValue(float(config.temperature))
        self.timeout_spin.setValue(int(config.timeout))
        self.save_api_key_checkbox.setChecked(settings.save_api_key)
        self.api_key_edit.setText(load_session_api_key(settings.provider_name) or "")

    def _provider_changed(self) -> None:
        self._remember_session_key(self._current_provider_name)
        provider_name = self._provider_name()
        self._current_provider_name = provider_name
        defaults = with_provider_defaults(
            AIProviderSettings(provider_name=provider_name).to_provider_config()
        )
        self.base_url_edit.setText(defaults.base_url or "")
        self.api_key_edit.setText(load_session_api_key(provider_name) or "")
        self.save_api_key_checkbox.setChecked(False)
        self._refresh_saved_key_status()

    def _build_settings(self) -> AIProviderSettings:
        return AIProviderSettings(
            provider_name=self._provider_name(),
            base_url=self.base_url_edit.text().strip() or None,
            model=self.model_edit.text().strip() or None,
            temperature=float(self.temperature_spin.value()),
            timeout=float(self.timeout_spin.value()),
            save_api_key=self.save_api_key_checkbox.isChecked(),
        )

    def _provider_name(self) -> str:
        return str(self.provider_combo.currentData())

    def _current_api_key(self) -> str:
        return self.api_key_edit.text().strip()

    def _remember_session_key(self, provider_name: str) -> None:
        remember_session_api_key(provider_name, self._current_api_key())

    def _refresh_saved_key_status(self) -> None:
        provider_name = self._provider_name()
        try:
            saved = load_saved_api_key(provider_name)
        except AISettingsError:
            self.saved_key_label.setText("无法读取保存状态")
            return

        self.saved_key_label.setText("已保存" if saved else "未保存")


class _ConnectionTestWorker(QObject):
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config

    @Slot()
    def run(self) -> None:
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        try:
            provider = create_provider(self.config)
            provider.generate_json(
                "Return only JSON.",
                'Return {"ok": true}.',
                schema,
                self.config.model,
                self.config.temperature,
                self.config.timeout,
            )
        except ProviderError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(str(redact_sensitive(str(error))))
        else:
            self.succeeded.emit()


def _requires_api_key(provider_name: str) -> bool:
    return normalize_provider_name(provider_name) != "ollama"


class PromptTemplateDialog(QDialog):
    """Prompt template editor dialog."""

    def __init__(self, template: PromptTemplate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("抽取规则模板")
        self.resize(860, 720)

        self.name_edit = QLineEdit(template.name)
        self.description_edit = QTextEdit(template.description)
        self.description_edit.setFixedHeight(70)
        self.system_prompt_edit = QTextEdit(template.system_prompt)
        self.user_prompt_edit = QTextEdit(template.user_prompt_template)
        self.entity_types_edit = QTextEdit("\n".join(template.allowed_entity_types))
        self.entity_types_edit.setFixedHeight(90)
        self.relations_edit = QTextEdit("\n".join(template.recommended_relations))
        self.relations_edit.setFixedHeight(90)
        self.output_schema_edit = QTextEdit(
            json_dumps(template.output_schema)
        )

        form = QFormLayout()
        form.addRow("name", self.name_edit)
        form.addRow("description", self.description_edit)
        form.addRow("system_prompt", self.system_prompt_edit)
        form.addRow("user_prompt_template", self.user_prompt_edit)
        form.addRow("allowed_entity_types", self.entity_types_edit)
        form.addRow("recommended_relations", self.relations_edit)
        form.addRow("output_schema", self.output_schema_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def template(self) -> PromptTemplate:
        try:
            output_schema = json_loads(self.output_schema_edit.toPlainText())
        except ValueError as error:
            raise PromptTemplateError(str(error)) from error

        return PromptTemplate.from_dict(
            {
                "name": self.name_edit.text().strip(),
                "description": self.description_edit.toPlainText().strip(),
                "system_prompt": self.system_prompt_edit.toPlainText().strip(),
                "user_prompt_template": self.user_prompt_edit.toPlainText().strip(),
                "allowed_entity_types": _lines(self.entity_types_edit.toPlainText()),
                "recommended_relations": _lines(self.relations_edit.toPlainText()),
                "output_schema": output_schema,
            }
        )

    def _accept_if_valid(self) -> None:
        try:
            self.template()
        except PromptTemplateError as error:
            QMessageBox.warning(self, "模板错误", str(error))
            return
        self.accept()


def json_dumps(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


def json_loads(value: str):
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"output_schema 不是合法 JSON：{error.msg}") from error


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
