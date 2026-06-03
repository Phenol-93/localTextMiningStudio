from app.core.reporting import generate_project_report, redact_sensitive
from app.db import database
from app.db.repositories import (
    AnalysisRunRepository,
    DocumentRepository,
    ProjectRepository,
    RelationMappingRepository,
    TripleRepository,
)


def _report_project(tmp_path):
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("报告测试项目", tmp_path)
        documents = DocumentRepository(connection)
        first_doc = documents.create(project_id, "文档一", filename="doc1.txt", raw_text="公司A签署合同")
        second_doc = documents.create(project_id, "文档二", filename="doc2.txt", raw_text="合同属于文件")
        documents.save_preprocessing_result(
            first_doc,
            "公司A 签署 合同",
            {"use_jieba": True, "top_n_keywords": 10},
        )
        documents.save_preprocessing_result(
            second_doc,
            "合同 属于 文件",
            {"use_jieba": True, "top_n_keywords": 10},
        )
        runs = AnalysisRunRepository(connection)
        traditional_run = runs.create(
            project_id,
            "traditional_text_mining",
            status="completed",
            parameters={"algorithm": "lda", "num_topics": 2, "top_n_keywords": 10},
        )
        runs.finish(traditional_run, "completed")
        ai_run = runs.create(
            project_id,
            "ai_triple_extraction",
            status="completed",
            parameters={
                "provider_name": "custom",
                "api_key": "sk-testsecretvalue",
                "nested": {"token": "secret-token-value"},
            },
        )
        runs.finish(ai_run, "completed", "provider key sk-testsecretvalue should be hidden")
        triples = TripleRepository(connection)
        triples.create(
            project_id,
            "公司A",
            "签署",
            "合同",
            document_id=first_doc,
            status="accepted",
            source_text="公司A签署合同",
            confidence=0.9,
            metadata={"subject_type": "组织", "object_type": "文件"},
        )
        triples.create(
            project_id,
            "合同",
            "属于",
            "文件",
            document_id=second_doc,
            status="edited",
            source_text="合同属于文件",
            metadata={"subject_type": "文件", "object_type": "概念"},
        )
        triples.create(project_id, "候选", "相关", "公司A", status="pending")
        triples.create(project_id, "噪声", "错误", "公司A", status="rejected")
        RelationMappingRepository(connection).upsert(project_id, "签署", "签订")
    return database_path, project_id


def test_generate_project_report_writes_markdown_and_html_without_secrets(tmp_path) -> None:
    database_path, project_id = _report_project(tmp_path)
    output_dir = tmp_path / "exports"
    (output_dir / "triples.csv").parent.mkdir(parents=True)
    (output_dir / "triples.csv").write_text("placeholder", encoding="utf-8")

    result = generate_project_report(database_path, project_id, output_dir, include_html=True)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    html = result.html_path.read_text(encoding="utf-8")

    assert "# 本地文本挖掘分析报告" in markdown
    assert "报告测试项目" in markdown
    assert "- 文档数量：2" in markdown
    assert '"use_jieba": true' in markdown
    assert '"top_n_keywords": 10' in markdown
    assert "traditional_text_mining" in markdown
    assert '"algorithm": "lda"' in markdown
    assert "- 三元组总数：4" in markdown
    assert "- accepted：1" in markdown
    assert "- rejected：1" in markdown
    assert "- edited：1" in markdown
    assert "- pending：1" in markdown
    assert "公司A" in markdown
    assert "签订" in markdown
    assert "## 图谱指标摘要" in markdown
    assert "triples.csv" in markdown
    assert "analysis_report.md" in markdown
    assert "sk-testsecretvalue" not in markdown
    assert "secret-token-value" not in markdown
    assert "[REDACTED]" in markdown
    assert "<html" in html


def test_redact_sensitive_keeps_non_secret_keyword_parameters() -> None:
    data = {
        "api_key": "sk-realvalue",
        "top_n_keywords": 12,
        "nested": {"access_token": "abc", "model": "manual"},
    }

    redacted = redact_sensitive(data)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["top_n_keywords"] == 12
    assert redacted["nested"]["access_token"] == "[REDACTED]"
    assert redacted["nested"]["model"] == "manual"
