"""Bbox-координаты сущностей для подсветки в UI (план feat/highlight-coords-edits).

Два потребителя:
1. Отчёт (``masker.graph.nodes._build_report_dict``): ``regions`` на каждую
   сущность и общий ``pages`` — фронт умножает 0..1 на физический размер
   canvas без пересчёта.
2. Правки оператора (``masker.graph.review.parse_review_edits``): фронт
   присылает bbox 0..1, сервер денормализует его в pt артефакта и собирает
   искусственный сегмент с ``origin="user"``.

Всё, что здесь есть, — чистые функции над уже готовыми артефактами. Ни один
файл здесь не пишет и рендер не запускает.
"""

from __future__ import annotations

from pathlib import Path

from masker.highlights.coords import (
    BboxRegion,
    denormalize,
    normalize,
    union_regions,
)
from masker.highlights.page_dims import PageDims, read_page_dims
from masker.model import MaskPlan, PdfRegion

__all__ = [
    "BboxRegion",
    "PageDims",
    "build_regions_by_ref",
    "denormalize",
    "normalize",
    "page_infos_for_report",
    "read_page_dims",
    "union_regions",
]


def build_regions_by_ref(
    plan: MaskPlan, artifact_pdf_path: Path | None
) -> dict[str, list[BboxRegion]]:
    """Собрать ``{ref: [BboxRegion, ...]}`` по готовому PDF-артефакту.

    Логика:
    - на каждую замену объединяем ``paint_regions`` в описывающий
      прямоугольник **по странице** (перенос на две страницы → две записи);
    - нормализуем по размерам соответствующей страницы артефакта.

    Пустой ответ для замен без геометрии (docx/xlsx до появления
    PDF-preview) или если ``artifact_pdf_path`` — ``None``/не существует.
    """
    if artifact_pdf_path is None:
        return {}
    dims = read_page_dims(artifact_pdf_path)
    if not dims:
        return {}
    dims_by_page = {page.page: page for page in dims}

    result: dict[str, list[BboxRegion]] = {}
    for replacement in plan.replacements:
        if not replacement.paint_regions:
            continue
        # Одна сущность — один union-регион на страницу; перенос через
        # страницу даёт две записи с разными ``page``.
        regions_by_page: dict[int, list[PdfRegion]] = {}
        for region in replacement.paint_regions:
            regions_by_page.setdefault(region.page, []).append(region)

        bboxes: list[BboxRegion] = []
        for page in sorted(regions_by_page):
            page_regions = regions_by_page[page]
            union = union_regions(page_regions)
            if union is None:
                continue
            dims_for_page = dims_by_page.get(page)
            if dims_for_page is None:
                # Регион ссылается на страницу, которой нет в артефакте —
                # молча пропускаем, не выдумываем координаты.
                continue
            bboxes.append(
                normalize(
                    union,
                    width_pt=dims_for_page.width_pt,
                    height_pt=dims_for_page.height_pt,
                )
            )
        if bboxes:
            result[replacement.ref] = bboxes
    return result


def page_infos_for_report(artifact_pdf_path: Path | None) -> list[dict[str, float | int]]:
    """Секция ``report["pages"]`` — размеры страниц готового артефакта.

    Возвращает список словарей формы ``{"page", "width_pt", "height_pt"}``;
    именно словарей, потому что ``report`` — JSON-совместимый dict, а
    ``PageDims`` — датакласс для внутренней геометрии.
    """
    if artifact_pdf_path is None:
        return []
    return [
        {"page": item.page, "width_pt": item.width_pt, "height_pt": item.height_pt}
        for item in read_page_dims(artifact_pdf_path)
    ]
