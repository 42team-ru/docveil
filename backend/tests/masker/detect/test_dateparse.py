"""Тесты разбора и валидации даты (план T1.15, шаг 1)."""

from __future__ import annotations

from datetime import date

import pytest

from masker.detect.dateparse import MAX_YEAR, MIN_YEAR, month_number, parse_literal


def test_parses_all_supported_formats() -> None:
    assert parse_literal("14.10.1986") == date(1986, 10, 14)
    assert parse_literal("12/02/2025") == date(2025, 2, 12)
    assert parse_literal("2025-02-12") == date(2025, 2, 12)
    assert parse_literal("10 марта 2025") == date(2025, 3, 10)
    # После снятия кавычек вызывающим (детектор) день остаётся числом.
    assert parse_literal("12 февраля 2025") == date(2025, 2, 12)


def test_month_recognizes_all_supported_word_forms() -> None:
    # Родительный падеж — форма, в которой месяц стоит в дате.
    assert month_number("января") == 1
    assert month_number("декабря") == 12
    # Именительный — на случай текстов вроде «Январь 2025».
    assert month_number("январь") == 1
    # Смешение регистров и ё/е.
    assert month_number("Декабря") == 12


def test_rejects_impossible_dates() -> None:
    assert parse_literal("32.01.2025") is None
    assert parse_literal("12.13.2025") is None
    # 2025 — не високосный.
    assert parse_literal("29.02.2025") is None
    # 2024 — високосный.
    assert parse_literal("29.02.2024") == date(2024, 2, 29)


def test_rejects_year_out_of_range() -> None:
    assert parse_literal(f"01.01.{MIN_YEAR - 1}") is None
    assert parse_literal(f"01.01.{MAX_YEAR + 1}") is None
    assert parse_literal(f"01.01.{MIN_YEAR}") == date(MIN_YEAR, 1, 1)
    assert parse_literal(f"31.12.{MAX_YEAR}") == date(MAX_YEAR, 12, 31)


def test_rejects_two_digit_year_and_period() -> None:
    """Двузначный год и «в марте 2025» — вне поддержки (план, «Не ловим»)."""
    # Двузначный год превращается в 25-й год, вне диапазона.
    assert parse_literal("12.02.25") is None
    # «в марте 2025» — 3 токена, но первый не число.
    assert parse_literal("в марте 2025") is None
    # «2025 год» — 2 токена, разбор не срабатывает.
    assert parse_literal("2025 год") is None


@pytest.mark.parametrize("text", ["", "   ", "какой-то текст без даты"])
def test_rejects_non_dates(text: str) -> None:
    assert parse_literal(text) is None
