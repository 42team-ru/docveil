"""Нормализация/денормализация bbox: pt артефакта ↔ 0..1 для фронта.

Отдельный модуль, потому что арифметика одинаковая и в оба конца:
- **К1** (координаты в отчёте): объединяем ``paint_regions`` одной сущности
  на одной странице в один прямоугольник (union) и делим на размеры
  страницы артефакта.
- **К2** (bbox-based ``manual``): фронт присылает 0..1, сервер умножает на
  размеры страницы артефакта и получает pt для якоря.

Одинаковые формулы в двух местах — общий источник правды: любое расхождение
знака или порядка деления сразу проявится в обоих направлениях, а не только
в одном.
"""

from __future__ import annotations

from dataclasses import dataclass

from masker.model import PdfRegion


@dataclass(frozen=True, slots=True)
class BboxRegion:
    """Прямоугольник сущности на странице PDF-артефакта, координаты 0..1.

    Отдельный тип, а не ``PdfRegion``: у ``PdfRegion`` координаты в pt по
    исходной геометрии страницы, у ``BboxRegion`` — нормализованные по
    размерам страницы артефакта. Смешивать их в одном контейнере — прямой
    путь к молчаливой ошибке умножения.
    """

    page: int  # 0-based
    x0: float  # 0..1
    y0: float
    x1: float
    y1: float


def union_regions(regions: list[PdfRegion]) -> PdfRegion | None:
    """Объединить прямоугольники одной страницы в описывающий прямоугольник.

    Регионы разных страниц отклоняются с ``ValueError``: страница — часть
    адреса, объединять «через страницы» нельзя. Пустой вход → ``None``.
    """
    if not regions:
        return None
    page = regions[0].page
    for region in regions[1:]:
        if region.page != page:
            raise ValueError(
                f"union_regions: смешаны страницы {page} и {region.page} — "
                "объединение возможно только в пределах одной страницы"
            )
    x0 = min(region.x0 for region in regions)
    y0 = min(region.y0 for region in regions)
    x1 = max(region.x1 for region in regions)
    y1 = max(region.y1 for region in regions)
    return PdfRegion(page=page, x0=x0, y0=y0, x1=x1, y1=y1)


def normalize(region: PdfRegion, *, width_pt: float, height_pt: float) -> BboxRegion:
    """pt → 0..1 по размерам страницы артефакта.

    Деление на ноль — валидный сбой, а не ``0.0``: страница без размера
    невозможна для настоящего PDF, молчание здесь скроет ошибку выбора
    артефакта (в state положили не PDF).
    """
    if width_pt <= 0 or height_pt <= 0:
        raise ValueError(f"normalize: некорректные размеры страницы {width_pt}x{height_pt}")
    return BboxRegion(
        page=region.page,
        x0=region.x0 / width_pt,
        y0=region.y0 / height_pt,
        x1=region.x1 / width_pt,
        y1=region.y1 / height_pt,
    )


def denormalize(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    page: int,
    width_pt: float,
    height_pt: float,
) -> PdfRegion:
    """0..1 → pt по размерам страницы артефакта. Обратная к ``normalize``."""
    if width_pt <= 0 or height_pt <= 0:
        raise ValueError(f"denormalize: некорректные размеры страницы {width_pt}x{height_pt}")
    return PdfRegion(
        page=page,
        x0=x0 * width_pt,
        y0=y0 * height_pt,
        x1=x1 * width_pt,
        y1=y1 * height_pt,
    )
