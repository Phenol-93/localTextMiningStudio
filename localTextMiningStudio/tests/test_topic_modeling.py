import json

from app.core.topic_modeling import (
    TopicModelingOptions,
    analyze_texts,
    export_result_table,
    run_project_topic_analysis,
)
from app.db import database
from app.db.repositories import AnalysisRunRepository, DocumentRepository, ProjectRepository


def test_word_frequency_and_tfidf_tables() -> None:
    result = analyze_texts(
        ["苹果 香蕉 苹果", "香蕉 梨"],
        document_ids=[10, 11],
        document_names=["doc-a", "doc-b"],
        options=TopicModelingOptions(algorithm="tfidf", max_features=10),
    )

    frequencies = {row["term"]: row["frequency"] for row in result.word_frequencies}

    assert frequencies["苹果"] == 2
    assert frequencies["香蕉"] == 2
    assert any(row["term"] == "苹果" and row["document_id"] == 10 for row in result.tfidf_table)


def test_lda_and_nmf_return_topics_and_document_distribution() -> None:
    texts = [
        "苹果 香蕉 水果 甜",
        "梨 香蕉 水果 新鲜",
        "合同 签署 甲方 乙方",
        "协议 甲方 履行 合同",
    ]

    lda = analyze_texts(texts, options=TopicModelingOptions(algorithm="lda", num_topics=2, max_features=20))
    nmf = analyze_texts(texts, options=TopicModelingOptions(algorithm="nmf", num_topics=2, max_features=20))

    assert {row["topic"] for row in lda.topic_keywords} == {1, 2}
    assert {row["topic"] for row in nmf.topic_keywords} == {1, 2}
    assert len(lda.document_topic_distribution) == 8
    assert len(nmf.document_topic_distribution) == 8


def test_export_result_table_writes_csv(tmp_path) -> None:
    output_path = tmp_path / "frequency.csv"

    export_result_table([{"term": "苹果", "frequency": 2}], output_path)

    content = output_path.read_text(encoding="utf-8-sig")
    assert "term,frequency" in content
    assert "苹果,2" in content


def test_project_topic_analysis_creates_analysis_run_with_parameters(tmp_path) -> None:
    database_path = database.initialize_database(tmp_path / "project.sqlite")
    with database.connection_scope(database_path) as connection:
        project_id = ProjectRepository(connection).create("分析项目", tmp_path)
        documents = DocumentRepository(connection)
        doc_id = documents.create(project_id, "doc-a", raw_text="苹果 香蕉")
        documents.save_preprocessing_result(
            doc_id,
            "苹果 香蕉 苹果",
            {"use_jieba": True},
        )
        doc_id = documents.create(project_id, "doc-b", raw_text="合同 甲方")
        documents.save_preprocessing_result(
            doc_id,
            "合同 甲方 乙方",
            {"use_jieba": True},
        )

    result = run_project_topic_analysis(
        database_path,
        project_id,
        TopicModelingOptions(algorithm="lda", num_topics=2, max_features=20),
    )

    with database.connection_scope(database_path) as connection:
        run = AnalysisRunRepository(connection).get(result.analysis_run_id)

    params = json.loads(run["parameters_json"])
    assert run["status"] == "completed"
    assert params["algorithm"] == "lda"
    assert params["num_topics"] == 2
    assert result.topic_keywords
    assert result.document_topic_distribution
