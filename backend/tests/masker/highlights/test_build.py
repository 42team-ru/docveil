"""Юниты `masker.highlights.build_regions_by_ref` и вспомогательного слоя.

Проверяем ровно то, что план feat-highlight-coords-edits обещает:
одна сущность = один union-регион на страницу, многострочная сущность —
всё равно один регион (union), перенос через страницу даёт две записи,
нормализация 0..1 честно делит на размеры страницы артефакта.

Тест изолирован: не открывает настоящий PDF, а подменяет ``read_page_dims``
на монки-фикстуру. Настоящий PDF-путь проверяется отдельным API-тестом.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from masker.highlights import build_regions_by_ref, page_dims
from masker.highlights.coords import (
    BboxRegion,
    denormalize,
    normalize,
    union_regions,
)
from masker.model import (
    Anchor,
    Entity,
    EntityType,
    MaskGroup,
    MaskPlan,
    PdfRegion,
    Replacement,
    Source,
)


def _entity(order: int = 0) -> Entity:
    return Entity(
        type=EntityType.INN,
        text="3662103003",
        segment_order=order,
        start=0,
        end=10,
        source=Source.RULE,
    )


def _anchor() -> Anchor:
    return Anchor(fmt="pdf", locator=("page", 0), label="стр. 1")


def _replacement(ref: str, regions: tuple[PdfRegion, ...] = ()) -> Replacement:
    return Replacement(
        ref=ref,
        entity=_entity(),
        marker="[ПОСТАВЩИК-ИНН]",
        group_id="G1",
        profile_id="P1",
        anchor=_anchor(),
        paint_regions=regions,
    )


def _plan(*replacements: Replacement) -> MaskPlan:
    return MaskPlan(
        replacements=tuple(replacements),
        groups=(
            MaskGroup(
                id="G1",
                key="inn:3662103003",
                type=EntityType.INN,
                marker="[ПОСТАВЩИК-ИНН]",
                profile_id="P1",
                role_label="ПОСТАВЩИК",
                number=1,
                refs=tuple(r.ref for r in replacements),
                sample="3662103003",
            ),
        ),
        skipped=(),
        requested_types=("inn",),
    )


@pytest.fixture
def _dims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяем чтение размеров: страница 0 — 600×800 pt, страница 1 — 400×500 pt."""

    def _fake(_path: Path) -> list[page_dims.PageDims]:
        return [
            page_dims.PageDims(page=0, width_pt=600.0, height_pt=800.0),
            page_dims.PageDims(page=1, width_pt=400.0, height_pt=500.0),
        ]

    monkeypatch.setattr("masker.highlights.read_page_dims", _fake)


def test_single_region_normalizes_to_page_size(_dims: None, tmp_path: Path) -> None:
    """Один прямоугольник → один регион, нормализован по размерам страницы."""
    plan = _plan(_replacement("R1", (PdfRegion(page=0, x0=60, y0=80, x1=120, y1=160),)))

    result = build_regions_by_ref(plan, tmp_path / "highlight.pdf")

    assert result == {
        "R1": [BboxRegion(page=0, x0=0.1, y0=0.1, x1=0.2, y1=0.2)],
    }


def test_multiline_regions_per_run(_dims: None, tmp_path: Path) -> None:
    """Многострочная сущность даёт отдельный регион на каждый paint_region (PDF-ран).

    Раньше здесь делался union, что давало bbox высотой в две строки. Теперь
    фронт получает отдельные прямоугольники и рисует независимый оверлей на
    каждую строку — так highlight не перекрывает чужой текст между строками.
    """
    plan = _plan(
        _replacement(
            "R1",
            (
                PdfRegion(page=0, x0=60, y0=80, x1=120, y1=120),
                PdfRegion(page=0, x0=90, y0=140, x1=180, y1=180),
            ),
        )
    )

    result = build_regions_by_ref(plan, tmp_path / "highlight.pdf")

    assert result == {
        "R1": [
            BboxRegion(page=0, x0=0.1, y0=0.1, x1=0.2, y1=0.15),
            BboxRegion(page=0, x0=0.15, y0=0.175, x1=0.3, y1=0.225),
        ],
    }


def test_page_break_yields_two_regions(_dims: None, tmp_path: Path) -> None:
    """Сущность на двух страницах — две записи, каждая нормирована по своей странице."""
    plan = _plan(
        _replacement(
            "R1",
            (
                PdfRegion(page=0, x0=60, y0=80, x1=120, y1=160),
                PdfRegion(page=1, x0=40, y0=50, x1=80, y1=100),
            ),
        )
    )

    result = build_regions_by_ref(plan, tmp_path / "highlight.pdf")

    assert result["R1"] == [
        BboxRegion(page=0, x0=0.1, y0=0.1, x1=0.2, y1=0.2),
        BboxRegion(page=1, x0=0.1, y0=0.1, x1=0.2, y1=0.2),
    ]


def test_replacement_without_paint_regions_is_skipped(_dims: None, tmp_path: Path) -> None:
    """Пустой ``paint_regions`` (docx/xlsx-путь, blackbox без рендера) → нет записи."""
    plan = _plan(_replacement("R1", ()))

    result = build_regions_by_ref(plan, tmp_path / "highlight.pdf")

    assert result == {}


def test_no_artifact_gives_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если PDF-артефакта нет — результат пуст, а не ``KeyError``/``FileNotFoundError``."""
    plan = _plan(_replacement("R1", (PdfRegion(page=0, x0=1, y0=1, x1=2, y1=2),)))

    assert build_regions_by_ref(plan, None) == {}

    def _empty(_path: Path) -> list[page_dims.PageDims]:
        return []

    monkeypatch.setattr("masker.highlights.read_page_dims", _empty)
    assert build_regions_by_ref(plan, Path("/nowhere.pdf")) == {}


def test_region_on_unknown_page_is_silently_skipped(_dims: None, tmp_path: Path) -> None:
    """Регион на несуществующей странице артефакта отбрасывается молча."""
    plan = _plan(
        _replacement(
            "R1",
            (
                PdfRegion(page=0, x0=60, y0=80, x1=120, y1=160),
                PdfRegion(page=42, x0=1, y0=1, x1=2, y1=2),
            ),
        )
    )

    result = build_regions_by_ref(plan, tmp_path / "highlight.pdf")

    assert result == {
        "R1": [BboxRegion(page=0, x0=0.1, y0=0.1, x1=0.2, y1=0.2)],
    }


def test_normalize_and_denormalize_roundtrip() -> None:
    """Формулы прямой и обратной нормировки сходятся ровно."""
    region = PdfRegion(page=3, x0=100.0, y0=250.0, x1=300.0, y1=400.0)
    normalized = normalize(region, width_pt=600.0, height_pt=800.0)
    back = denormalize(
        normalized.x0,
        normalized.y0,
        normalized.x1,
        normalized.y1,
        page=region.page,
        width_pt=600.0,
        height_pt=800.0,
    )
    assert back == region


def test_union_rejects_mixed_pages() -> None:
    """Объединение через страницы — ошибка, а не молчаливое склеивание координат."""
    with pytest.raises(ValueError, match="смешаны страницы"):
        union_regions(
            [
                PdfRegion(page=0, x0=0, y0=0, x1=1, y1=1),
                PdfRegion(page=1, x0=0, y0=0, x1=1, y1=1),
            ]
        )


def test_normalize_rejects_zero_page_size() -> None:
    """Нулевая ширина/высота — валидный сбой, а не деление на ноль в отчёте."""
    with pytest.raises(ValueError, match="некорректные размеры"):
        normalize(PdfRegion(page=0, x0=0, y0=0, x1=1, y1=1), width_pt=0, height_pt=100)
