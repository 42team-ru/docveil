"""Тесты `layout_diff` — сохранность текстового слоя PDF вне замен (план T2.2.2, шаг 4).

Это единственное доказательство, что обрезка прямоугольника по соседней
строке (шаг 3, Д10) действительно чинит дефект, а не просто выглядит
правдоподобно: ``test_layout_diff_catches_collateral_removal`` красная на
искусственно раздутом прямоугольнике независимо от состояния шага 3 — она
проверяет саму метрику, а не факт починки (факт починки на реальном
документе показан в отчёте кодера, не здесь).
"""

from __future__ import annotations

import pathlib

import pymupdf

from masker.ingest.pdf_ingest import ingest_pdf
from masker.mask.agent import PlanAgent
from masker.model import Document, Entity, EntityType, Source
from masker.render.pdf_render import render_pdf_redacted
from masker.validate.pdf_layout import layout_diff

_FONT = str(pathlib.Path(__file__).parent.parent.parent.parent / "src/masker/data/DejaVuSans.ttf")


def _make_source_two_lines(tmp_path: pathlib.Path) -> pathlib.Path:
    """Две строки, символьные боксы которых перекрываются по вертикали —
    та же геометрия, что воспроизводит Д10 (`tests/masker/render/test_pdf_render.py`)."""
    path = tmp_path / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "Verhnyaya stroka sekret", fontname="dvu", fontsize=13)
    page.insert_text((72, 112.7), "Nizhnyaya stroka tekst", fontname="dvu", fontsize=13)
    doc.save(str(path))
    doc.close()
    return path


def _entity_for(document: Document, containing: str, text: str) -> Entity:
    seg = next(s for s in document.segments if containing in s.text)
    start = seg.text.index(text)
    return Entity(
        type=EntityType.ORG_NAME,
        text=text,
        segment_order=seg.order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
        normalized=text,
    )


def _make_inflated_artifact(source_path: pathlib.Path, dest_path: pathlib.Path) -> None:
    """«Артефакт» с искусственно раздутым прямоугольником редакции — та же
    геометрия, что была у ``render_pdf_redacted`` до шага 3: прямоугольник
    залезает на соседнюю строку и стирает её текст по пересечению боксов.
    Построен напрямую через PyMuPDF, в обход ``render_pdf_redacted``,
    чтобы тест ловил регрессию самой метрики, а не совпадение с текущей
    реализацией рендера.
    """
    doc = pymupdf.open(str(source_path))
    page = doc[0]
    # Прямоугольник покрывает обе строки целиком — ровно раздутый случай.
    page.add_redact_annot(pymupdf.Rect(72, 85, 270, 116), fill=(0, 0, 0))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    doc.save(str(dest_path))
    doc.close()


def test_layout_diff_catches_collateral_removal(tmp_path: pathlib.Path) -> None:
    """Искусственно раздутый прямоугольник стирает соседнюю строку —
    ``removed`` обязан быть больше нуля, страница названа."""
    source = _make_source_two_lines(tmp_path)
    document = ingest_pdf(source)
    entity = _entity_for(document, "Verhnyaya", "sekret")
    plan = PlanAgent().plan(document, [entity])
    artifact = tmp_path / "broken.pdf"
    _make_inflated_artifact(source, artifact)

    diff = layout_diff(source, artifact, plan)

    assert diff.removed > 0, diff
    assert diff.pages == (0,), diff.pages
    assert "Nizhnyaya" in diff.first_diff or "tekst" in diff.first_diff, diff.first_diff


def test_layout_diff_is_zero_on_clean_render(tmp_path: pathlib.Path) -> None:
    """На нетронутом (обрезанном как положено) рендере расхождений нет —
    ``removed == 0``, список страниц пуст."""
    source = _make_source_two_lines(tmp_path)
    document = ingest_pdf(source)
    entity = _entity_for(document, "Verhnyaya", "sekret")
    plan = PlanAgent().plan(document, [entity])
    artifact = tmp_path / "clean.pdf"
    render_pdf_redacted(source, artifact, document, plan, style="blackbox")

    diff = layout_diff(source, artifact, plan)

    assert diff.removed == 0, diff
    assert diff.pages == ()


def test_layout_diff_ignores_inserted_markers(tmp_path: pathlib.Path) -> None:
    """Стиль ``marker`` вставляет текст маркера — без ``markers`` это лишний
    (``inserted``) символ, с ``markers`` он вычитается и расхождения нет."""
    source = _make_source_two_lines(tmp_path)
    document = ingest_pdf(source)
    entity = _entity_for(document, "Verhnyaya", "sekret")
    plan = PlanAgent().plan(document, [entity])
    artifact = tmp_path / "marker.pdf"
    render_pdf_redacted(source, artifact, document, plan, style="marker")

    without_markers = layout_diff(source, artifact, plan)
    assert without_markers.inserted > 0, without_markers

    markers = tuple(group.marker for group in plan.groups)
    with_markers = layout_diff(source, artifact, plan, markers=markers)
    assert with_markers.inserted == 0, with_markers
    assert with_markers.removed == 0, with_markers
