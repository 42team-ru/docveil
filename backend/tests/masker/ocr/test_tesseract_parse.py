"""Юнит-тесты _parse_results: группировка слов в строки и фикс омоглифов."""

from __future__ import annotations

from masker.ocr.tesseract import _fix_homoglyphs, _parse_results


def _make_data(words: list[tuple[int, int, int, str, int, int, int, int, int]]) -> dict:
    """Построить data-словарь в формате pytesseract image_to_data.

    Каждый элемент words: (block_num, par_num, line_num, text, conf, left, top, w, h).
    level=5 (слово) выставляется автоматически.
    """
    n = len(words)
    return {
        "level": [5] * n,
        "block_num": [w[0] for w in words],
        "par_num": [w[1] for w in words],
        "line_num": [w[2] for w in words],
        "text": [w[3] for w in words],
        "conf": [w[4] for w in words],
        "left": [w[5] for w in words],
        "top": [w[6] for w in words],
        "width": [w[7] for w in words],
        "height": [w[8] for w in words],
    }


def test_single_word_single_line() -> None:
    data = _make_data([(1, 1, 1, "Иванов", 90, 10, 20, 50, 15)])
    result = _parse_results(data)
    assert len(result) == 1
    assert result[0].text == "Иванов"


def test_two_words_same_line_merged() -> None:
    """Два слова одной строки должны слиться в один OCRLine."""
    data = _make_data(
        [
            (1, 1, 1, "Пеков", 88, 10, 20, 40, 15),
            (1, 1, 1, "Е.В.", 85, 55, 20, 25, 15),
        ]
    )
    result = _parse_results(data)
    assert len(result) == 1
    assert result[0].text == "Пеков Е.В."


def test_two_lines_produce_two_segments() -> None:
    data = _make_data(
        [
            (1, 1, 1, "Иванов", 90, 10, 10, 50, 15),
            (1, 1, 2, "Петров", 90, 10, 30, 50, 15),
        ]
    )
    result = _parse_results(data)
    assert len(result) == 2
    assert result[0].text == "Иванов"
    assert result[1].text == "Петров"


def test_bbox_is_union_of_word_bboxes() -> None:
    data = _make_data(
        [
            (1, 1, 1, "А", 90, 10, 20, 30, 15),
            (1, 1, 1, "Б", 90, 50, 22, 20, 12),
        ]
    )
    result = _parse_results(data)
    # Word1: x1=10+30=40, y1=20+15=35; Word2: x1=50+20=70, y1=22+12=34 → union y1=35
    assert result[0].bbox == (10.0, 20.0, 70.0, 35.0)


def test_confidence_is_min_of_words() -> None:
    data = _make_data(
        [
            (1, 1, 1, "слово", 95, 0, 0, 30, 10),
            (1, 1, 1, "ещё", 70, 35, 0, 20, 10),
        ]
    )
    result = _parse_results(data)
    assert abs(result[0].confidence - 0.70) < 0.01


def test_negative_conf_word_skipped() -> None:
    """Слова с conf < 0 (Tesseract ставит -1 для мусора) пропускаются."""
    data = _make_data(
        [
            (1, 1, 1, "ОК", 80, 10, 10, 20, 10),
            (1, 1, 1, "??", -1, 40, 10, 20, 10),
        ]
    )
    result = _parse_results(data)
    assert result[0].text == "ОК"


def test_empty_text_word_skipped() -> None:
    data = _make_data(
        [
            (1, 1, 1, "хорошо", 90, 10, 10, 40, 10),
            (1, 1, 1, "  ", 90, 55, 10, 10, 10),
        ]
    )
    result = _parse_results(data)
    assert result[0].text == "хорошо"


def test_empty_data_returns_empty_tuple() -> None:
    data = _make_data([])
    assert _parse_results(data) == ()


def test_fix_homoglyphs_uppercase_always() -> None:
    assert _fix_homoglyphs("ABC") == "АВС"


def test_fix_homoglyphs_uppercase_in_cyrillic_context_replaced() -> None:
    # Uppercase E→Е, B→В regardless of context
    assert _fix_homoglyphs("Иванов E.B.") == "Иванов Е.В."


def test_fix_homoglyphs_lowercase_replaced_when_cyrillic_present() -> None:
    # Latin 'e' inside a Cyrillic word → Cyrillic 'е'
    assert "e" not in _fix_homoglyphs("Пeков")


def test_fix_homoglyphs_latin_word_unchanged_lowercase() -> None:
    assert _fix_homoglyphs("hello") == "hello"
