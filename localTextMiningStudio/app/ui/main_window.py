"""Main window for the local text mining studio."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_TITLE
from app.db.database import (
    PROJECT_DATABASE_NAME,
    connection_scope,
    create_project_database,
    initialize_database,
)
from app.db.repositories import ProjectRepository
from app.ui.ai_extraction_page import AIExtractionPage
from app.ui.export_page import ExportPage
from app.ui.graph_analysis_page import GraphAnalysisPage
from app.ui.graph_page import GraphPage
from app.ui.import_page import ImportPage
from app.ui.normalization_page import NormalizationPage
from app.ui.preprocessing_page import PreprocessingPage
from app.ui.settings_page import SettingsPage
from app.ui.traditional_mining_page import TraditionalMiningPage
from app.ui.triple_review_page import TripleReviewPage
from app.utils.paths import get_projects_dir


PAGE_TITLES = (
    "项目首页",
    "文档导入",
    "文本预处理",
    "传统文本挖掘",
    "AI 三元组抽取",
    "三元组审核表",
    "实体/关系标准化",
    "知识图谱",
    "图谱分析",
    "导出中心",
    "设置",
)


class ProjectHomePage(QWidget):
    """Home page for creating and opening local projects."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.current_project_path_label = QLabel("未打开项目")
        self.current_project_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.new_project_button = QPushButton("新建项目")
        self.open_project_button = QPushButton("打开项目")

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.new_project_button)
        button_layout.addWidget(self.open_project_button)
        button_layout.addStretch(1)

        form_layout = QFormLayout()
        form_layout.addRow("当前项目路径", self.current_project_path_label)

        title = QLabel("项目首页")
        title.setObjectName("pageTitle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(title)
        layout.addLayout(button_layout)
        layout.addLayout(form_layout)
        layout.addStretch(1)

    def set_current_project_path(self, project_path: str) -> None:
        self.current_project_path_label.setText(project_path)


class PlaceholderPage(QWidget):
    """Simple placeholder page used before business logic is added."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("pageTitle")

        layout = QVBoxLayout(self)
        layout.addWidget(label)


class MainWindow(QMainWindow):
    """Primary application window with navigation, pages, and status bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 760)

        self.navigation = QListWidget()
        self.navigation.setFixedWidth(220)
        self.navigation.setObjectName("projectNavigation")

        self.pages = QStackedWidget()
        self.pages.setObjectName("pageArea")

        self.current_database_path = None
        self.current_project_id = None
        self.project_home_page = ProjectHomePage()
        self.project_home_page.new_project_button.clicked.connect(self.create_project)
        self.project_home_page.open_project_button.clicked.connect(self.open_project)
        self.import_page = ImportPage()
        self.preprocessing_page = PreprocessingPage()
        self.traditional_mining_page = TraditionalMiningPage()
        self.ai_extraction_page = AIExtractionPage()
        self.triple_review_page = TripleReviewPage()
        self.normalization_page = NormalizationPage()
        self.graph_page = GraphPage()
        self.graph_analysis_page = GraphAnalysisPage()
        self.export_page = ExportPage()
        self.settings_page = SettingsPage()

        for title in PAGE_TITLES:
            self.navigation.addItem(QListWidgetItem(title))
            if title == "项目首页":
                self.pages.addWidget(self.project_home_page)
            elif title == "文档导入":
                self.pages.addWidget(self.import_page)
            elif title == "文本预处理":
                self.pages.addWidget(self.preprocessing_page)
            elif title == "传统文本挖掘":
                self.pages.addWidget(self.traditional_mining_page)
            elif title == "AI 三元组抽取":
                self.pages.addWidget(self.ai_extraction_page)
            elif title == "三元组审核表":
                self.pages.addWidget(self.triple_review_page)
            elif title == "实体/关系标准化":
                self.pages.addWidget(self.normalization_page)
            elif title == "知识图谱":
                self.pages.addWidget(self.graph_page)
            elif title == "图谱分析":
                self.pages.addWidget(self.graph_analysis_page)
            elif title == "导出中心":
                self.pages.addWidget(self.export_page)
            elif title == "设置":
                self.pages.addWidget(self.settings_page)
            else:
                self.pages.addWidget(PlaceholderPage(title))

        self.navigation.currentRowChanged.connect(self.change_page)

        central_widget = QWidget()
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.navigation)
        main_layout.addWidget(self.pages, stretch=1)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        status_bar = QStatusBar()
        status_bar.showMessage("就绪")
        author_label = QLabel("作者：Phenol93")
        author_label.setObjectName("authorLabel")
        status_bar.addPermanentWidget(author_label)
        self.setStatusBar(status_bar)

        self.navigation.setCurrentRow(0)

    def create_project(self) -> None:
        project_name, accepted = QInputDialog.getText(self, "新建项目", "项目名称")
        project_name = project_name.strip()
        if not accepted or not project_name:
            return

        try:
            database_path = create_project_database(project_name)
            with connection_scope(database_path) as connection:
                repository = ProjectRepository(connection)
                project_id = repository.create(project_name, database_path.parent)
        except Exception as error:
            QMessageBox.critical(self, "新建项目失败", str(error))
            return

        self._set_current_project(database_path, project_id)
        self.statusBar().showMessage(f"已新建项目：{project_name}")

    def open_project(self) -> None:
        database_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开项目",
            str(get_projects_dir()),
            f"项目数据库 ({PROJECT_DATABASE_NAME});;SQLite 数据库 (*.sqlite *.db);;所有文件 (*)",
        )
        if not database_path:
            return

        try:
            project_id = self._open_project_database(database_path)
        except Exception as error:
            QMessageBox.critical(self, "打开项目失败", str(error))
            return

        self._set_current_project(database_path, project_id)
        self.statusBar().showMessage("已打开项目")

    def _open_project_database(self, database_path: str) -> int:
        initialize_database(database_path)
        with connection_scope(database_path) as connection:
            repository = ProjectRepository(connection)
            project = repository.get_current()
            if project is not None:
                return int(project["id"])

            project_dir = str(Path(database_path).resolve().parent)
            return repository.create(Path(project_dir).name, project_dir)

    def _set_current_project(self, database_path: str | Path, project_id: int) -> None:
        path = Path(database_path).resolve()
        self.current_database_path = path
        self.current_project_id = project_id
        self.project_home_page.set_current_project_path(str(path))
        self.import_page.set_current_project(path, project_id)
        self.preprocessing_page.set_current_project(path, project_id)
        self.traditional_mining_page.set_current_project(path, project_id)
        self.ai_extraction_page.set_current_project(path, project_id)
        self.triple_review_page.set_current_project(path, project_id)
        self.normalization_page.set_current_project(path, project_id)
        self.graph_page.set_current_project(path, project_id)
        self.graph_analysis_page.set_current_project(path, project_id)
        self.export_page.set_current_project(path, project_id)

    def change_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if self.pages.widget(index) is self.preprocessing_page:
            self.preprocessing_page.refresh_documents()
        if self.pages.widget(index) is self.ai_extraction_page:
            self.ai_extraction_page.refresh_templates()
        if self.pages.widget(index) is self.triple_review_page:
            self.triple_review_page.refresh_all()
        if self.pages.widget(index) is self.normalization_page:
            self.normalization_page.refresh()
        if self.pages.widget(index) is self.export_page:
            self.export_page.refresh_filter_values()
