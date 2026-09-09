"""Селектор ``masker.ocr.select_ocr``: дефолт, unknown, ленивая инициализация."""

from __future__ import annotations

from pathlib import Path

import pytest

from masker.ocr import OCRError, OCRProvider, select_ocr
from masker.ocr.fake import FakeOCR


def test_default_is_fake_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без переменной ``MASKER_OCR`` дефолт — ``FakeOCR``, а не реальный движок."""
    monkeypatch.delenv("MASKER_OCR", raising=False)
    provider = select_ocr()
    assert isinstance(provider, FakeOCR)
    # Runtime-check с Protocol — заодно проверяет, что интерфейс совместим.
    assert isinstance(provider, OCRProvider)


def test_env_var_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MASKER_OCR=fake`` явно даёт fake; регистр и пробелы нормализуются."""
    monkeypatch.setenv("MASKER_OCR", "  FAKE  ")
    assert isinstance(select_ocr(), FakeOCR)


def test_yaml_provider_is_used_and_environment_has_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "masker.yaml"
    path.write_text("ocr:\n  provider: fake\n", encoding="utf-8")
    monkeypatch.setenv("MASKER_CONFIG", str(path))
    monkeypatch.delenv("MASKER_OCR", raising=False)
    assert isinstance(select_ocr(), FakeOCR)

    monkeypatch.setenv("MASKER_OCR", "not-a-real-engine")
    with pytest.raises(OCRError, match="not-a-real-engine"):
        select_ocr()


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


def test_paddle_without_extra_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пока ``paddleocr`` не установлен, ``select_ocr('paddle')`` даёт понятную ошибку.

    Как только пакет реально появится в extra ``ocr``, этот тест сам скажет:
    маркер надо перевесить на "провайдер не сумел инициализироваться", а не
    "не хватает пакета". До той поры проверка защищает от голого
    ``ModuleNotFoundError`` в лицо пользователю.
    """
    import importlib.util

    if importlib.util.find_spec("paddleocr") is not None:
        pytest.skip("paddleocr установлен — проверка ветки 'нет пакета' неприменима")
    with pytest.raises(OCRError) as excinfo:
        select_ocr("paddle")
    assert "triema-masker[ocr]" in str(excinfo.value)
