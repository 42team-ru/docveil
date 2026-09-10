"""Логотип DocVeil в терминале (branding.py)."""

from __future__ import annotations

import io
from itertools import pairwise

from masker import branding


def test_banner_without_colour_has_no_ansi() -> None:
    """В пайп и в CI логотип обязан уходить без escape-кодов.

    Вывод прогонов читают глазами и грепают; тринадцать строк ANSI в начале
    лога делают и то, и другое невозможным.
    """
    for columns in (60, 100):
        plain = branding.banner(colour=False, width=columns)

        assert "\033[" not in plain
        assert branding.TAGLINE in plain


def test_banner_with_colour_uses_truecolor_from_the_logo() -> None:
    """Цвета берутся с исходного логотипа, а не назначаются на глаз."""
    coloured = branding.banner(colour=True)

    assert "\033[38;2;{};{};{}m".format(*branding.NAVY) in coloured
    assert "\033[38;2;{};{};{}m".format(*branding.PAPER) in coloured


def test_no_color_environment_disables_colour(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`NO_COLOR` — устоявшееся соглашение, его обязаны уважать."""
    monkeypatch.setenv("NO_COLOR", "1")

    assert branding._use_colour() is False


def test_colour_is_off_when_output_is_not_a_terminal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert branding._use_colour(io.StringIO()) is False


def test_logo_silhouette_narrows_to_a_point() -> None:
    """Щит обязан читаться как щит: низ уже верха и сходится в остриё."""
    lines = branding.logo_lines(colour=False)
    width = [len(line.strip()) for line in lines]

    assert width[0] > width[-1]
    assert width[-1] > 0
    # Монотонное сужение начиная с плеч — иначе силуэт «дребезжит».
    tail = width[len(width) // 2 :]
    assert all(later <= earlier for earlier, later in pairwise(tail))


def test_wordmark_spells_the_product_name() -> None:
    """Крупное начертание — это имя продукта, а не абстрактный узор."""
    lines = branding.wordmark_lines(colour=False)

    assert len(lines) == 5
    assert max(len(line) for line in lines) == branding.WORDMARK_WIDTH
    # Заглавная «D» начинается с самой первой колонки, строчные — ниже
    # базовой линии заглавных: слово обязано стоять на одной строке.
    assert lines[0].startswith("█")
    assert lines[0][8:14].strip() == ""


def test_narrow_terminal_falls_back_to_plain_name() -> None:
    """Крупные буквы, переносящиеся на следующую строку, хуже их отсутствия."""
    narrow = branding.banner(colour=False, width=60)
    wide = branding.banner(colour=False, width=100)

    assert branding.PRODUCT in narrow
    assert branding.PRODUCT not in wide  # там имя нарисовано, а не написано
    assert branding.TAGLINE in narrow and branding.TAGLINE in wide
