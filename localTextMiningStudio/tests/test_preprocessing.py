import json

from app.core.preprocessing import PreprocessOptions, TextPreprocessor


def test_jieba_tokenization_with_custom_dictionary() -> None:
    preprocessor = TextPreprocessor(
        PreprocessOptions(
            custom_words=["本地文本挖掘"],
            use_default_stopwords=False,
        )
    )

    result = preprocessor.preprocess("本地文本挖掘很有用")

    assert "本地文本挖掘" in result.tokens


def test_stopwords_and_min_word_length_filter_tokens() -> None:
    preprocessor = TextPreprocessor(
        PreprocessOptions(
            custom_stopwords=["是", "一个"],
            min_word_length=2,
            use_default_stopwords=False,
        )
    )

    result = preprocessor.preprocess("这是 一个 文本 挖掘 工具")

    assert "一个" not in result.tokens
    assert "文本" in result.tokens
    assert "挖掘" in result.tokens
    assert all(len(token) >= 2 for token in result.tokens)


def test_punctuation_digits_and_lowercase_are_filtered() -> None:
    preprocessor = TextPreprocessor(
        PreprocessOptions(
            remove_punctuation=True,
            remove_digits=True,
            lowercase=True,
            use_jieba=False,
        )
    )

    result = preprocessor.preprocess("Hello, WORLD! 2026 文本。")

    assert result.tokens == ["hello", "world", "文本"]
    assert "," not in result.cleaned_text
    assert "2026" not in result.cleaned_text


def test_options_are_json_serializable() -> None:
    options = PreprocessOptions(custom_words=["知识图谱"], custom_stopwords=["的"])

    payload = json.loads(options.to_json())

    assert payload["custom_words"] == ["知识图谱"]
    assert payload["custom_stopwords"] == ["的"]
