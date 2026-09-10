"""Селектор ``masker.ocr.select_ocr``: дефолт, unknown, ленивая инициализация."""

from __future__ import annotations

import importlib.util

import pytest

from masker.ocr import OCRError, OCRProvider, select_ocr
from masker.ocr.fake import FakeOCR
from masker.ocr.tesseract import TesseractOCRProvider


def test_default_is_tesseract_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без переменной ``MASKER_OCR`` дефолт — ``TesseractOCRProvider``."""
    monkeypatch.delenv("MASKER_OCR", raising=False)
    provider = select_ocr()
    assert isinstance(provider, TesseractOCRProvider)
    # Runtime-check с Protocol — заодно проверяет, что интерфейс совместим.
    assert isinstance(provider, OCRProvider)


def test_env_var_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MASKER_OCR=fake`` явно даёт fake; регистр и пробелы нормализуются."""
    monkeypatch.setenv("MASKER_OCR", "  FAKE  ")
    assert isinstance(select_ocr(), FakeOCR)


def test_explicit_name_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASKER_OCR", "paddle")
    # Явный аргумент важнее окружения; движок не поднимается, потому что
    # для fake extra не нужна.
    assert isinstance(select_ocr("fake"), FakeOCR)


def test_unknown_provider_raises_with_available_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MASKER_OCR", raising=False)
    with pytest.raises(OCRError) as excinfo:
        select_ocr("not-a-real-engine")
    message = str(excinfo.value)
    assert "fake" in message
    assert "paddle" in message
    assert "tesseract" in message
    assert "easy" in message


@pytest.mark.parametrize(
    ("name", "pkg_name", "hint_fragment"),
    [
        ("paddle", "paddleocr", "triema-masker[ocr]"),
        ("easy", "easyocr", "easyocr>=1.7"),
    ],
)
def test_provider_without_extra_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    pkg_name: str,
    hint_fragment: str,
) -> None:
    """Пока клиентский пакет не установлен, ``select_ocr(name)`` даёт понятную ошибку.

    Как только пакет реально появится в extra ``ocr``, соответствующая ветка
    сама скажет: маркер надо перевесить на «провайдер не сумел
    инициализироваться», а не «не хватает пакета». До той поры проверка
    защищает от голого ``ModuleNotFoundError`` в лицо пользователю.
    """
    if importlib.util.find_spec(pkg_name) is not None:
        pytest.skip(f"{pkg_name} установлен — проверка ветки 'нет пакета' неприменима")
    with pytest.raises(OCRError) as excinfo:
        select_ocr(name)
    assert hint_fragment in str(excinfo.value)
