"""Traditional text mining and topic modeling helpers."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from sklearn.decomposition import LatentDirichletAllocation, NMF
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

from app.db.database import connection_scope
from app.db.repositories import AnalysisRunRepository, DocumentRepository


SUPPORTED_ALGORITHMS = ("word_frequency", "tfidf", "lda", "nmf")


class TopicModelingError(Exception):
    """Raised when text mining cannot be completed."""


@dataclass(frozen=True)
class TopicModelingOptions:
    """JSON-serializable options for traditional text mining."""

    algorithm: str = "lda"
    num_topics: int = 3
    max_features: int = 1000
    top_n_keywords: int = 10
    random_state: int = 42

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TopicModelingResult:
    """Output tables for traditional text mining."""

    options: TopicModelingOptions
    document_ids: list[int]
    document_names: list[str]
    word_frequencies: list[dict[str, object]] = field(default_factory=list)
    tfidf_table: list[dict[str, object]] = field(default_factory=list)
    topic_keywords: list[dict[str, object]] = field(default_factory=list)
    document_topic_distribution: list[dict[str, object]] = field(default_factory=list)
    analysis_run_id: int | None = None


def analyze_texts(
    texts: Sequence[str | Sequence[str]],
    *,
    document_ids: Sequence[int] | None = None,
    document_names: Sequence[str] | None = None,
    options: TopicModelingOptions | dict[str, object] | None = None,
) -> TopicModelingResult:
    """Run word frequency, TF-IDF, LDA, or NMF on preprocessed text."""
    if isinstance(options, dict):
        options = TopicModelingOptions(**options)
    options = options or TopicModelingOptions()
    if options.algorithm not in SUPPORTED_ALGORITHMS:
        raise TopicModelingError(f"不支持的算法：{options.algorithm}")

    normalized_texts = [_normalize_text(text) for text in texts]
    usable = [
        (index, text)
        for index, text in enumerate(normalized_texts)
        if text.strip()
    ]
    if not usable:
        raise TopicModelingError("没有可用于分析的 cleaned_text。请先完成文本预处理。")

    used_indices = [index for index, _ in usable]
    corpus = [text for _, text in usable]
    ids = _select_by_indices(document_ids, used_indices, default_start=1)
    names = _select_names(document_names, used_indices, ids)

    vectorizer = _make_count_vectorizer(options.max_features)
    count_matrix = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()
    if len(feature_names) == 0:
        raise TopicModelingError("没有提取到有效特征。")

    word_frequencies = _build_word_frequencies(count_matrix, feature_names)
    tfidf_table = _build_tfidf_table(corpus, ids, names, options.max_features)
    topic_keywords: list[dict[str, object]] = []
    document_topic_distribution: list[dict[str, object]] = []

    if options.algorithm == "lda":
        topic_keywords, document_topic_distribution = _run_lda(
            count_matrix,
            feature_names,
            ids,
            names,
            options,
        )
    elif options.algorithm == "nmf":
        topic_keywords, document_topic_distribution = _run_nmf(
            corpus,
            ids,
            names,
            options,
        )

    return TopicModelingResult(
        options=options,
        document_ids=ids,
        document_names=names,
        word_frequencies=word_frequencies,
        tfidf_table=tfidf_table,
        topic_keywords=topic_keywords,
        document_topic_distribution=document_topic_distribution,
    )


def run_project_topic_analysis(
    database_path: Path | str,
    project_id: int,
    options: TopicModelingOptions | dict[str, object],
) -> TopicModelingResult:
    """Load cleaned documents, create an analysis run, and execute analysis."""
    if isinstance(options, dict):
        options = TopicModelingOptions(**options)

    with connection_scope(database_path) as connection:
        runs = AnalysisRunRepository(connection)
        run_id = runs.create(
            project_id,
            "traditional_text_mining",
            status="running",
            parameters=options.to_dict(),
        )
        documents = DocumentRepository(connection).list_preprocessed_by_project(project_id)

    texts = [document["cleaned_text"] for document in documents]
    document_ids = [int(document["id"]) for document in documents]
    document_names = [document["filename"] or document["title"] for document in documents]

    try:
        result = analyze_texts(
            texts,
            document_ids=document_ids,
            document_names=document_names,
            options=options,
        )
    except Exception as error:
        with connection_scope(database_path) as connection:
            AnalysisRunRepository(connection).finish(run_id, "failed", str(error))
        raise

    with connection_scope(database_path) as connection:
        AnalysisRunRepository(connection).finish(run_id, "completed")

    return TopicModelingResult(
        options=result.options,
        document_ids=result.document_ids,
        document_names=result.document_names,
        word_frequencies=result.word_frequencies,
        tfidf_table=result.tfidf_table,
        topic_keywords=result.topic_keywords,
        document_topic_distribution=result.document_topic_distribution,
        analysis_run_id=run_id,
    )


def export_result_table(rows: Iterable[dict[str, object]], output_path: Path | str) -> Path:
    """Export one result table to CSV."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fieldnames = _collect_fieldnames(rows)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _normalize_text(text: str | Sequence[str]) -> str:
    if isinstance(text, str):
        return text
    return " ".join(str(token) for token in text)


def _make_count_vectorizer(max_features: int) -> CountVectorizer:
    return CountVectorizer(
        tokenizer=str.split,
        preprocessor=None,
        token_pattern=None,
        lowercase=False,
        max_features=max(1, max_features),
    )


def _make_tfidf_vectorizer(max_features: int) -> TfidfVectorizer:
    return TfidfVectorizer(
        tokenizer=str.split,
        preprocessor=None,
        token_pattern=None,
        lowercase=False,
        max_features=max(1, max_features),
    )


def _build_word_frequencies(count_matrix, feature_names) -> list[dict[str, object]]:
    counts = count_matrix.sum(axis=0).A1
    rows = [
        {"term": feature_names[index], "frequency": int(count)}
        for index, count in enumerate(counts)
        if count > 0
    ]
    return sorted(rows, key=lambda row: (-int(row["frequency"]), str(row["term"])))


def _build_tfidf_table(
    corpus: Sequence[str],
    document_ids: Sequence[int],
    document_names: Sequence[str],
    max_features: int,
) -> list[dict[str, object]]:
    vectorizer = _make_tfidf_vectorizer(max_features)
    matrix = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()
    rows: list[dict[str, object]] = []
    coo = matrix.tocoo()
    for doc_index, term_index, value in zip(coo.row, coo.col, coo.data):
        rows.append(
            {
                "document_id": int(document_ids[doc_index]),
                "document": document_names[doc_index],
                "term": feature_names[term_index],
                "tfidf": round(float(value), 6),
            }
        )
    return sorted(rows, key=lambda row: (-float(row["tfidf"]), str(row["document"]), str(row["term"])))


def _run_lda(count_matrix, feature_names, document_ids, document_names, options):
    num_topics = _effective_num_topics(options.num_topics, len(feature_names))
    model = LatentDirichletAllocation(
        n_components=num_topics,
        random_state=options.random_state,
        learning_method="batch",
    )
    distribution = model.fit_transform(count_matrix)
    return (
        _topic_keywords(model.components_, feature_names, options.top_n_keywords),
        _document_topics(distribution, document_ids, document_names),
    )


def _run_nmf(corpus, document_ids, document_names, options):
    vectorizer = _make_tfidf_vectorizer(options.max_features)
    matrix = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()
    num_topics = _effective_num_topics(options.num_topics, len(feature_names))
    model = NMF(
        n_components=num_topics,
        init="nndsvda" if min(matrix.shape) >= num_topics else "random",
        random_state=options.random_state,
        max_iter=400,
    )
    distribution = model.fit_transform(matrix)
    distribution = _normalize_rows(distribution)
    return (
        _topic_keywords(model.components_, feature_names, options.top_n_keywords),
        _document_topics(distribution, document_ids, document_names),
    )


def _topic_keywords(components, feature_names, top_n: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    limit = max(1, top_n)
    for topic_index, component in enumerate(components, start=1):
        top_indices = component.argsort()[::-1][:limit]
        for rank, term_index in enumerate(top_indices, start=1):
            rows.append(
                {
                    "topic": topic_index,
                    "rank": rank,
                    "term": feature_names[term_index],
                    "weight": round(float(component[term_index]), 6),
                }
            )
    return rows


def _document_topics(distribution, document_ids, document_names) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for doc_index, weights in enumerate(distribution):
        for topic_index, value in enumerate(weights, start=1):
            rows.append(
                {
                    "document_id": int(document_ids[doc_index]),
                    "document": document_names[doc_index],
                    "topic": topic_index,
                    "weight": round(float(value), 6),
                }
            )
    return rows


def _effective_num_topics(requested: int, feature_count: int) -> int:
    return max(1, min(max(1, requested), max(1, feature_count)))


def _normalize_rows(matrix):
    row_sums = matrix.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return matrix / row_sums


def _select_by_indices(values: Sequence[int] | None, indices: Sequence[int], default_start: int) -> list[int]:
    if values is None:
        return [index + default_start for index in indices]
    return [int(values[index]) for index in indices]


def _select_names(values: Sequence[str] | None, indices: Sequence[int], document_ids: Sequence[int]) -> list[str]:
    if values is None:
        return [f"document-{document_id}" for document_id in document_ids]
    return [str(values[index]) for index in indices]


def _collect_fieldnames(rows: Sequence[dict[str, object]]) -> list[str]:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    return fieldnames or ["empty"]
