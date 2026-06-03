"""Reusable text preprocessing utilities."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import jieba


DEFAULT_STOPWORDS_PATH = Path(__file__).resolve().parents[1] / "resources" / "stopwords" / "zh.txt"
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class PreprocessOptions:
    """JSON-serializable preprocessing options."""

    remove_punctuation: bool = True
    remove_digits: bool = False
    lowercase: bool = True
    use_jieba: bool = True
    use_default_stopwords: bool = False
    min_word_length: int = 1
    custom_words: list[str] = field(default_factory=list)
    custom_stopwords: list[str] = field(default_factory=list)
    custom_dict_path: str | None = None
    custom_stopwords_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass(frozen=True)
class PreprocessResult:
    """Preprocessing output for downstream mining modules."""

    tokens: list[str]
    cleaned_text: str
    options: PreprocessOptions


class TextPreprocessor:
    """Tokenize and normalize text for text mining workflows."""

    def __init__(self, options: PreprocessOptions | dict[str, object] | None = None) -> None:
        if isinstance(options, dict):
            options = PreprocessOptions(**options)
        self.options = options or PreprocessOptions()
        self._tokenizer = jieba.Tokenizer()
        self._load_custom_dictionary()
        self.stopwords = self._load_stopwords()

    def preprocess(self, text: str) -> PreprocessResult:
        """Return tokens and a whitespace-joined cleaned text string."""
        normalized = text or ""
        if self.options.lowercase:
            normalized = normalized.lower()
        if self.options.remove_punctuation:
            normalized = remove_punctuation(normalized)
        if self.options.remove_digits:
            normalized = remove_digits(normalized)

        tokens = self.tokenize(normalized)
        tokens = [token.strip() for token in tokens if token.strip()]
        tokens = self._filter_tokens(tokens)

        return PreprocessResult(
            tokens=tokens,
            cleaned_text=" ".join(tokens),
            options=self.options,
        )

    def tokenize(self, text: str) -> list[str]:
        """Tokenize text with jieba or whitespace splitting."""
        if self.options.use_jieba:
            return list(self._tokenizer.lcut(text))
        return [token for token in _WHITESPACE_PATTERN.split(text) if token]

    def _filter_tokens(self, tokens: Iterable[str]) -> list[str]:
        min_length = max(1, int(self.options.min_word_length))
        return [
            token
            for token in tokens
            if len(token) >= min_length and token not in self.stopwords
        ]

    def _load_custom_dictionary(self) -> None:
        for word in self.options.custom_words:
            word = word.strip()
            if word:
                self._tokenizer.add_word(word)

        if self.options.custom_dict_path:
            path = Path(self.options.custom_dict_path)
            if path.exists():
                self._tokenizer.load_userdict(str(path))

    def _load_stopwords(self) -> set[str]:
        stopwords: set[str] = set()
        if self.options.use_default_stopwords:
            stopwords.update(load_stopwords_file(DEFAULT_STOPWORDS_PATH))
        if self.options.custom_stopwords_path:
            stopwords.update(load_stopwords_file(Path(self.options.custom_stopwords_path)))
        stopwords.update(word.strip() for word in self.options.custom_stopwords if word.strip())
        return stopwords


def remove_punctuation(text: str) -> str:
    """Replace Unicode punctuation with spaces."""
    return "".join(" " if unicodedata.category(char).startswith("P") else char for char in text)


def remove_digits(text: str) -> str:
    """Replace Unicode digits with spaces."""
    return "".join(" " if char.isdigit() else char for char in text)


def load_stopwords_file(path: Path) -> set[str]:
    """Load a line-based stopword file if it exists."""
    if not path.exists():
        return set()

    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
