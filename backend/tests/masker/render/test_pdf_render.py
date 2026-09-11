"""Тесты pdf_render: preview (highlight) и redacted (настоящее удаление) через `MaskPlan`."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import stat

import pymupdf
import pytest

import masker.eval as eval_module
import masker.render.pdf_render as pdf_render_module
from masker.ingest.pdf_ingest import PageChars, ingest_pdf, page_chars
from masker.mask.agent import PlanAgent
from masker.model import (
    Anchor,
    Document,
    Entity,
    EntityType,
    MaskPlan,
    PdfRegion,
    Profile,
    ProfileMember,
    Replacement,
    Source,
)
from masker.refs import EntityIndex
from masker.render.pdf_render import (
    _LINE_BREAK_RECT,
    MarkerDoesNotFitError,
    _entity_rects,
    _label_box_candidates,
    _line_boxes,
    _quantize_erase_rect,
    _try_ladder,
    compute_erase_geometry,
    compute_label_geometry,
    count_highlight_overlaps,
    render_pdf_preview,
    render_pdf_redacted,
)
from masker.validate.agent import ValidateAgent
from masker.validate.pdf_layout import layout_diff

_INN = "3662103003"
_AUTHOR = "Тест Автор"
_FONT = str(pathlib.Path(__file__).parent.parent.parent.parent / "src/masker/data/DejaVuSans.ttf")


def _make_pdf_block(tmp_path: pathlib.Path, lines: list[str]) -> pathlib.Path:
    """Однострaничный PDF с одним текстовым блоком на несколько строк —
    тот же приём, что и в `tests/masker/ingest/test_pdf_ingest.py`:
    `insert_textbox` даёт общую раскладку абзаца, `insert_text` — нет."""
    path = tmp_path / "block.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    rect = pymupdf.Rect(72, 72, 500, 700)
    page.insert_textbox(rect, "\n".join(lines), fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _make_pdf_with_inn(tmp_path: pathlib.Path, pages: int = 1) -> pathlib.Path:
    path = tmp_path / "source.pdf"
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100 + i * 20), f"ИНН {_INN}", fontsize=12)
    doc.set_metadata({"author": _AUTHOR})
    doc.save(str(path))
    doc.close()
    return path


def _make_pdf_with_pii_widget(tmp_path: pathlib.Path) -> pathlib.Path:
    """PDF со сложной формой: текст PII живёт в appearance виджета.

    ``apply_redactions`` не редактирует appearance stream поля формы, хотя
    ``page.get_text`` и ``search_for`` этот текст видят. Такое же устройство
    у виджета электронной подписи в реальном договоре из М14.
    """
    path = tmp_path / "form-layout.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Contract details", fontsize=12)
    page.insert_text((72, 104), "Signer certificate:", fontsize=10)
    page.insert_text((72, 136), "Signature is in the form field at right", fontsize=10)
    widget = pymupdf.Widget()
    widget.field_name = "signer_certificate"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_value = "Ivanova  Tatyana  Petrovna; email=signer@example.test"
    widget.rect = pymupdf.Rect(280, 88, 550, 150)
    widget.text_font = "helv"
    widget.text_fontsize = 9
    page.add_widget(widget)
    doc.save(str(path))
    doc.close()
    return path


def _filled_rect_colors(path: pathlib.Path) -> list[tuple[float, float, float]]:
    """Цвета фактически нарисованных заполненных прямоугольников PDF."""
    doc = pymupdf.open(path)
    try:
        return [
            drawing["fill"]
            for drawing in doc[0].get_drawings()
            if drawing["fill"] is not None and any(item[0] == "re" for item in drawing["items"])
        ]
    finally:
        doc.close()


def _make_pdf_overlapping_lines(tmp_path: pathlib.Path) -> pathlib.Path:
    """Синтетический PDF из двух строк, чьи символьные боксы перекрываются
    по вертикали — воспроизводит Д10 плана T2.2.2: шаг строк 12.7pt при
    высоте бокса глифа ~15.2pt (числа из диагностики на реальном
    документе, `docs/plans/T2.2.2-render-and-recall.md`, раздел «Д10»).
    Каждая строка — отдельный вызов ``insert_text`` и отдельный текстовый
    блок PyMuPDF: `page_chars` при этом всё равно даёт двум строкам
    перекрывающиеся боксы и разные ``line_id``."""
    path = tmp_path / "overlap.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "Verhnyaya stroka sekret", fontname="dvu", fontsize=13)
    page.insert_text((72, 112.7), "Nizhnyaya stroka tekst", fontname="dvu", fontsize=13)
    doc.save(str(path))
    doc.close()
    return path


def _make_pdf_fully_overlapping_lines(tmp_path: pathlib.Path) -> pathlib.Path:
    """Синтетический PDF из двух строк, наложенных друг на друга почти
    целиком (наложенный текст, штамп) — план T2.2.2, шаг 3, п. 4: обрезка
    прямоугольника по соседней строке обязана отмениться, а не молча
    схлопнуть его в нулевую или отрицательную высоту."""
    path = tmp_path / "stamped.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "sekretnoe slovo tut", fontname="dvu", fontsize=10)
    page.insert_text((72, 108), "SHTAMP NALOZHEN SVERHU I SNIZU", fontname="dvu", fontsize=44)
    doc.save(str(path))
    doc.close()
    return path


def _entity_for_doc(document: Document, text: str, etype: EntityType) -> Entity:
    seg = next(s for s in document.segments if text in s.text)
    start = seg.text.index(text)
    return Entity(
        type=etype,
        text=text,
        segment_order=seg.order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
        normalized=text,
    )


def _plan(
    document: Document, entities: list[Entity], *, profiles: list[Profile] | None = None
) -> MaskPlan:
    return PlanAgent().plan(document, entities, profiles=profiles)


def _profile_for(marker_label: str, members: list[Entity], index: EntityIndex) -> Profile:
    from masker.model import Anchor

    return Profile(
        id="P1",
        members=[
            ProfileMember(
                entity=entity, anchor=Anchor(fmt="pdf", locator=()), ref=index.ref(entity)
            )
            for entity in members
        ],
        marker_label=marker_label,
    )


# ── preview ──────────────────────────────────────────────────────────────────


def test_preview_adds_highlight_annotation(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_preview(src, dest, document, [entity])
    doc = pymupdf.open(str(dest))
    annots = list(doc[0].annots())
    doc.close()
    assert len(annots) > 0


def test_preview_preserves_original_text(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_preview(src, dest, document, [entity])
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert _INN in text


def test_preview_permissions(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    render_pdf_preview(src, dest, document, [])
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_preview_entity_not_found_graceful(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "preview.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.INN,
        text="0000000000",  # нет в документе
        segment_order=seg.order,
        start=0,
        end=10,
        source=Source.RULE,
    )
    render_pdf_preview(src, dest, document, [entity])  # не должен бросать


# ── redacted ─────────────────────────────────────────────────────────────────


def test_redacted_text_absent_from_text_layer(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, _plan(document, [entity]))
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert _INN not in text


def test_redacted_text_absent_from_raw_bytes(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, _plan(document, [entity]))
    assert _INN.encode() not in dest.read_bytes()


def test_redacted_marker_appears_in_text(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, _plan(document, [entity]))
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "[ИНН]" in text


@pytest.mark.parametrize("style", ("marker", "blackbox"))
def test_redacted_form_widget_is_deleted_when_its_planned_text_overlaps(
    tmp_path: pathlib.Path, style: str
) -> None:
    """М14: каждая замена из виджета формы должна физически исчезнуть.

    До удаления виджета этот тест оставляет обе строки в text layer: PyMuPDF
    применяет прямоугольники к content stream страницы, но не к appearance
    stream виджета. Проверка через ValidateAgent доказывает не наличие
    заливки, а отсутствие каждого исходного значения в готовом артефакте.
    """
    src = _make_pdf_with_pii_widget(tmp_path)
    dest = tmp_path / f"redacted-{style}.pdf"
    document = ingest_pdf(src)
    person = "Ivanova  Tatyana  Petrovna"
    email = "signer@example.test"
    plan = _plan(
        document,
        [
            _entity_for_doc(document, person, EntityType.PERSON),
            _entity_for_doc(document, email, EntityType.EMAIL),
        ],
    )

    outcome = render_pdf_redacted(src, dest, document, plan, style=style)

    assert {replacement.ref for replacement in outcome.replacements} == {
        replacement.ref for replacement in plan.replacements
    }
    assert ValidateAgent().validate(plan, [dest], source=src).leaked == ()
    doc = pymupdf.open(dest)
    try:
        assert list(doc[0].widgets() or ()) == []
        text = doc[0].get_text()
    finally:
        doc.close()
    assert person not in text
    assert email not in text


def test_centered_marker_uses_vector_dots_without_polluting_text_layer(
    tmp_path: pathlib.Path,
) -> None:
    """Маркер стоит в центре своей области, а точки остаются только графикой.

    Возврат ``insert_textbox(... TEXT_ALIGN_LEFT)`` оставит заметно большой
    левый зазор и уронит это сравнение координат. Если заменить векторные
    точки строкой ``"..."``, упадёт проверка text layer.
    """
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]))

    replacement = outcome.replacements[0]
    region = replacement.label_region
    assert region is not None
    shown = outcome.markers[0].shown_label
    assert shown == "[ИНН]"

    result = pymupdf.open(str(dest))
    try:
        chars = page_chars(result[0])
        start = chars.text.index(shown)
        marker_boxes = chars.boxes[start : start + len(shown)]
        marker_box = pymupdf.Rect(marker_boxes[0])
        for char_box in marker_boxes[1:]:
            marker_box |= char_box
        assert marker_box.x0 > region.x0 + 5.0  # не возвращаться к левому краю
        assert abs(marker_box.x0 + marker_box.x1 - region.x0 - region.x1) < 0.2
        assert "." not in chars.text
        dot_drawings = [
            drawing
            for drawing in result[0].get_drawings()
            if drawing["type"] == "f"
            and drawing["items"]
            and all(item[0] == "c" for item in drawing["items"])
        ]
        assert any(drawing["rect"].x1 < marker_box.x0 for drawing in dot_drawings)
        assert any(drawing["rect"].x0 > marker_box.x1 for drawing in dot_drawings)
    finally:
        result.close()


def test_pdf_marker_from_plan(tmp_path: pathlib.Path) -> None:
    """Ради этого шага всё затевалось: в PDF тоже маркер с ролью, а не
    латинский тип — человекочитаемой формы (план М4), а не капсом с дефисами.

    Своя (не общая) фикстура — с запасом свободного места после ИНН,
    доказанно свободным для расширения подписи (план М1, правило 3):
    `_make_pdf_with_inn` рассчитана впритык под голый ``[ИНН]`` и с полом
    читаемости 8 pt (план М1, правило 1) не оставляет места для роли.
    """
    path = tmp_path / "source.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), f"ИНН {_INN}          ", fontsize=12)
    doc.save(str(path))
    doc.close()

    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(path)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    index = EntityIndex([entity])
    profile = _profile_for("ПОСТАВЩИК", [entity], index)
    render_pdf_redacted(path, dest, document, _plan(document, [entity], profiles=[profile]))
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "[Поставщик ИНН]" in text
    assert _INN not in text
    assert "[INN]" not in text


def test_redacted_metadata_cleared(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    render_pdf_redacted(src, dest, document, _plan(document, []))
    doc = pymupdf.open(str(dest))
    author = doc.metadata.get("author", "")
    doc.close()
    assert author == ""


def test_redacted_page_count_preserved(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path, pages=3)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entities = [_entity_for_doc(document, _INN, EntityType.INN)]
    render_pdf_redacted(src, dest, document, _plan(document, entities))
    src_doc = pymupdf.open(str(src))
    dst_doc = pymupdf.open(str(dest))
    assert len(dst_doc) == len(src_doc)
    src_doc.close()
    dst_doc.close()


def test_redacted_permissions(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    render_pdf_redacted(src, dest, document, _plan(document, []))
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_redacted_entity_not_found_graceful(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.INN,
        text="0000000000",
        segment_order=seg.order,
        start=0,
        end=10,
        source=Source.RULE,
    )
    render_pdf_redacted(src, dest, document, _plan(document, [entity]))  # не должен бросать


def test_blackbox_original_text_absent(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert _INN not in text


def test_blackbox_no_bracketed_marker_in_text(tmp_path: pathlib.Path) -> None:
    """`blackbox` не показывает полный маркер плана (план T2.2.2, шаг 1,
    отменяет решение пачки 5 плана T2.2.1) — на нём вообще нет текста."""
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "[ИНН]" not in text


def test_blackbox_inserts_no_text(tmp_path: pathlib.Path) -> None:
    """Решение заказчика (план T2.2.2, шаг 1): чёрный прямоугольник — просто
    чёрный, без короткой метки типа и вообще без вставленного текста, даже
    когда место физически позволило бы что-то вписать.

    Источник — голое значение без слова «ИНН» рядом (в отличие от
    `_make_pdf_with_inn`), чтобы при регрессии метка в результате была
    однозначно нашей вставкой, а не уцелевшим обрывком исходного текста.
    """
    src = _make_pdf_block(tmp_path, [_INN])
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "ИНН" not in text, text
    assert text.strip() == "", text
    assert outcome.markers == ()


def test_blackbox_reuses_marker_redaction_base_without_marker_text(tmp_path: pathlib.Path) -> None:
    """Второй стиль берёт общую очищенную основу, но остаётся немым.

    11.09.2026: это регрессия для оптимизации ``both`` — reuse разрешён
    только после настоящего ``apply_redactions()``, до вставки marker-текста.
    """
    src = _make_pdf_block(tmp_path, [_INN])
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    plan = _plan(document, [entity])
    render_pdf_redacted(src, tmp_path / "marker.pdf", document, plan, style="marker")
    outcome = render_pdf_redacted(src, tmp_path / "black.pdf", document, plan, style="blackbox")

    doc = pymupdf.open(str(tmp_path / "black.pdf"))
    text = doc[0].get_text()
    doc.close()
    assert _INN not in text
    assert text.strip() == "", text
    assert outcome.markers == ()


def test_blackbox_never_reports_degradation(tmp_path: pathlib.Path) -> None:
    """`blackbox` никогда не порождает `MarkerDegradation` — «без текста»
    для него замысел стиля, а не деградация (план T2.2.2, шаг 1). Тот же
    заведомо узкий сценарий, на котором стиль `marker` деградирует
    (`test_render_pdf_redacted_returns_degradation_report`)."""
    src = _make_pdf_block(tmp_path, ["ШБС"])
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.ORG_NAME,
        text=seg.text.strip(),
        segment_order=seg.order,
        start=0,
        end=len(seg.text.strip()),
        source=Source.RULE,
    )
    index = EntityIndex([entity])
    profile = _profile_for("ПОТРЕБИТЕЛЬ-ОРГАНИЗАЦИЯ-МАОУ-ГИМНАЗИЯ-1", [entity], index)
    plan = _plan(document, [entity], profiles=[profile])
    outcome = render_pdf_redacted(src, dest, document, plan, style="blackbox")
    assert outcome.markers == ()
    assert outcome.collisions == ()


def test_redacted_multipage_all_redacted(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path, pages=2)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    # Создаём по одной сущности для каждого сегмента, содержащего ИНН
    entities = [
        Entity(
            type=EntityType.INN,
            text=_INN,
            segment_order=seg.order,
            start=seg.text.index(_INN),
            end=seg.text.index(_INN) + len(_INN),
            source=Source.RULE,
            confidence=1.0,
            normalized=_INN,
        )
        for seg in document.segments
        if _INN in seg.text
    ]
    render_pdf_redacted(src, dest, document, _plan(document, entities))
    doc = pymupdf.open(str(dest))
    for page in doc:
        assert _INN not in page.get_text()
    doc.close()


# ── шаг 9: локализация по смещениям, а не поиском (Д1, Д2) ────────────────────


def test_pdf_entity_across_line_break_gets_rects_on_both_lines(tmp_path: pathlib.Path) -> None:
    """Сущность через перенос строки даёт по прямоугольнику на каждую строку,
    у прямоугольников разные ``line_id`` (план T2.2.2, шаг 2/3)."""
    path = _make_pdf_block(tmp_path, ["Иванов", "Иванович работает"])
    doc = pymupdf.open(str(path))
    chars = page_chars(doc[0])
    doc.close()
    start = chars.text.index("Иванов")
    end = chars.text.index("Иванович") + len("Иванович")
    assert chars.text[start:end] == "Иванов Иванович"

    rects = _entity_rects(chars, start, end)

    assert len(rects) == 2, rects
    (line_a, rect_a), (line_b, rect_b) = rects
    assert line_a != line_b
    # Разные строки — разная вертикаль базовой линии.
    assert rect_a.y0 != rect_b.y0


def test_pdf_marker_inserted_once_per_replacement(tmp_path: pathlib.Path) -> None:
    """Маркер вставлен один раз на `Replacement`, даже если сущность
    разбита переносом строки на несколько прямоугольников (Д1: раньше
    рендер искал строку заново и вставлял маркер в каждое найденное
    вхождение)."""
    src = _make_pdf_block(tmp_path, ["Иванов", "Иванович работает"])
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    start = seg.text.index("Иванов")
    end = seg.text.index("Иванович") + len("Иванович")
    entity = Entity(
        type=EntityType.PERSON,
        text=seg.text[start:end],
        segment_order=seg.order,
        start=start,
        end=end,
        source=Source.NER,
        confidence=0.9,
        normalized="иванов иванович",
    )
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]))
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert len(outcome.markers) == 1
    shown = outcome.markers[0].shown_label
    assert shown != "", outcome.markers
    assert text.count(shown) == 1, text


def test_group_gets_one_consistent_label_across_wide_and_narrow_occurrences(
    tmp_path: pathlib.Path,
) -> None:
    """План М4, пункт 3: одна и та же группа обязана печататься одной и той
    же строкой во всём документе, даже если её вхождения сидят в местах
    разной ширины.

    Раньше `_place_label` гонял лестницу отступления на каждом вхождении
    отдельно: в широком месте побеждала полная человеческая форма, в узком
    — сокращение, и одна и та же сущность получала два разных маркера в
    одном документе (диагностика на `contract_pdf_02_school.pdf`, план М4:
    5 групп из 68 получили по два маркера). Одна и та же фамилия здесь
    встречается дважды: один раз с большим запасом пробелов справа (влезла
    бы полная форма ``[Поставщик Представитель]``), второй раз — сразу
    перед непробельным соседом без места на расширение (влезает только
    компактный код). Обе строки обязаны показать одно и то же."""
    path = tmp_path / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    # Широкое вхождение — много свободных пробелов справа по той же строке.
    page.insert_text((72, 100), "Иванов" + " " * 60, fontname="dvu", fontsize=12)
    # Узкое — сразу после сущности непробельный сосед, расширение запрещено
    # (план М1, правило 3: расширение только в доказанно свободное место).
    page.insert_text((72, 300), "Иванов,подпись", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()

    document = ingest_pdf(path)
    entities = []
    for seg in document.segments:
        if "Иванов" in seg.text:
            start = seg.text.index("Иванов")
            entities.append(
                Entity(
                    type=EntityType.PERSON,
                    text="Иванов",
                    segment_order=seg.order,
                    start=start,
                    end=start + len("Иванов"),
                    source=Source.RULE,
                    confidence=1.0,
                    normalized="иванов",
                )
            )
    assert len(entities) == 2, "фикстура обязана дать два отдельных сегмента с «Иванов»"
    index = EntityIndex(entities)
    profile = _profile_for("ПОСТАВЩИК", entities, index)
    plan = _plan(document, entities, profiles=[profile])
    assert len(plan.groups) == 1, "обе сущности обязаны попасть в одну группу"

    dest = tmp_path / "redacted.pdf"
    outcome = render_pdf_redacted(path, dest, document, plan, style="marker")

    assert len(outcome.markers) == 2
    shown_labels = {marker.shown_label for marker in outcome.markers}
    assert len(shown_labels) == 1, (
        f"одна группа получила {len(shown_labels)} разных маркеров: {outcome.markers}"
    )
    # Осмысленный тест, а не тавтология: без общегруппового выбора широкое
    # вхождение показало бы канонический маркер, а не общее сокращение.
    (shown_label,) = shown_labels
    assert shown_label != plan.groups[0].canonical_label


def _org_replacement(marker: str = "[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]") -> Replacement:
    entity = Entity(
        type=EntityType.ORG_NAME,
        text="Вектор",
        segment_order=0,
        start=0,
        end=6,
        source=Source.RULE,
    )
    return Replacement(
        ref="R1",
        entity=entity,
        marker=marker,
        group_id="G1",
        profile_id="",
        anchor=Anchor(fmt="pdf", locator=("page", 0, 0, 6)),
    )


# ── лестница отступления маркера (план М1) ─────────────────────────────────


def test_pdf_insert_textbox_failure_is_loud_only_on_degenerate_rect(
    tmp_path: pathlib.Path,
) -> None:
    """Исключение осталось только на вырожденный (нулевой площади)
    прямоугольник — на любой настоящей ширине лестница отступления
    спускается до короткой метки или пустого прямоугольника, но не падает."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    degenerate = pymupdf.Rect(72, 100, 72, 100)  # нулевые ширина и высота
    ladder = [("[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]", ""), ("ОРГАНИЗАЦИЯ", "type_only")]
    try:
        with pytest.raises(MarkerDoesNotFitError):
            _try_ladder(page, font, degenerate, ladder)
    finally:
        doc.close()


def test_ladder_falls_back_to_shorter_rung_when_full_marker_does_not_fit(
    tmp_path: pathlib.Path,
) -> None:
    """Не влез полный маркер, но влезла короткая метка типа — деградация,
    не падение; факт спуска возвращается вызывающему для отчёта."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    ladder = [("[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]", ""), ("ОРГАНИЗАЦИЯ", "type_only")]
    try:
        # 90pt: полный маркер (мин. ширина ~125pt на 8pt, пол читаемости)
        # не влезает ни при одном разрешённом размере, «ОРГАНИЗАЦИЯ»
        # (мин. ширина ~62pt на 8pt) — влезает.
        narrow = pymupdf.Rect(72, 100, 162, 115)
        outcome = _try_ladder(page, font, narrow, ladder)
    finally:
        doc.close()
    assert outcome is not None
    text, fallback_reason, size = outcome
    assert text == "ОРГАНИЗАЦИЯ"
    assert fallback_reason == "type_only"
    assert size >= 8.0


def test_ladder_returns_none_when_nothing_fits(tmp_path: pathlib.Path) -> None:
    """Не влезла даже короткая метка — сигнал вызывающему оставить
    подсветку без текста, падения по-прежнему нет."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    ladder = [("[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]", ""), ("ОРГАНИЗАЦИЯ", "type_only")]
    try:
        tiny = pymupdf.Rect(72, 100, 82, 115)  # 10pt — даже «ОРГАНИЗАЦИЯ» не влезает
        outcome = _try_ladder(page, font, tiny, ladder)
    finally:
        doc.close()
    assert outcome is None


def test_ladder_prefers_full_marker_when_it_fits(tmp_path: pathlib.Path) -> None:
    """Регрессия: полный (канонический) маркер по-прежнему первая и лучшая
    ступень лестницы, когда места достаточно."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    ladder = [("[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]", ""), ("ОРГАНИЗАЦИЯ", "type_only")]
    try:
        wide = pymupdf.Rect(72, 100, 300, 115)  # полный маркер сюда помещается
        outcome = _try_ladder(page, font, wide, ladder)
    finally:
        doc.close()
    assert outcome is not None
    text, fallback_reason, _size = outcome
    assert text == "[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]"
    assert fallback_reason == ""


@pytest.mark.parametrize("width", [5.0, 12.0, 18.0, 25.0, 40.0, 90.0, 160.0, 400.0])
def test_ladder_never_uses_a_font_below_the_readability_floor(
    tmp_path: pathlib.Path, width: float
) -> None:
    """План М1, критерий приёмки: ни на одном прогоне маркер не отрендерен
    шрифтом меньше 8 pt — свойство проверяется на диапазоне ширин поля, а
    не на одном удачном примере."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    ladder = [
        ("[ПОСТАВЩИК-ФИО-1]", ""),
        ("[ПОСТ-ФИО-1]", "role_short"),
        ("[П-ФИО-1]", "role_initial"),
        ("[Ф1]", "compact"),
        ("ФИО", "type_only"),
    ]
    try:
        box = pymupdf.Rect(72, 100, 72 + width, 115)
        outcome = _try_ladder(page, font, box, ladder)
    finally:
        doc.close()
    if outcome is not None:
        _text, _reason, size = outcome
        assert size >= 8.0


def test_render_pdf_redacted_returns_degradation_report(tmp_path: pathlib.Path) -> None:
    """`render_pdf_redacted` отдаёт факт деградации в `RenderOutcome.markers`
    — «каждый спуск на ступень ниже фиксируется для отчёта»."""
    # Короткое исходное значение — узкий прямоугольник; длинная составная
    # роль профиля — маркер шире, чем это узкое поле, независимо от шрифта.
    src = _make_pdf_block(tmp_path, ["ШБС"])
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.ORG_NAME,
        text=seg.text.strip(),
        segment_order=seg.order,
        start=0,
        end=len(seg.text.strip()),
        source=Source.RULE,
    )
    index = EntityIndex([entity])
    profile = _profile_for("ПОТРЕБИТЕЛЬ-ОРГАНИЗАЦИЯ-МАОУ-ГИМНАЗИЯ-1", [entity], index)
    plan = _plan(document, [entity], profiles=[profile])
    outcome = render_pdf_redacted(src, dest, document, plan, style="marker")
    assert len(outcome.markers) == 1, outcome.markers
    assert outcome.markers[0].fallback_reason != ""
    assert outcome.markers[0].font_size == 0.0 or outcome.markers[0].font_size >= 8.0
    assert outcome.markers[0].page == 0


# ── контракт читаемой маски: erase/paint/label раздельны (план М1) ────────────


def test_multiline_entity_picks_widest_line_for_label_not_first(tmp_path: pathlib.Path) -> None:
    """План М1, правило 2: подпись ставится в пригодный прямоугольник, а
    не в первый — первая строка многострочного ФИО тут состоит из одного
    инициала и физически не может вместить даже сокращённую метку, а
    вторая строка (полное продолжение) — может."""
    src = _make_pdf_block(tmp_path, ["И", "Морозова Инга Петровна далее по тексту"])
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.PERSON,
        text=seg.text.strip(),
        segment_order=seg.order,
        start=0,
        end=len(seg.text.strip()),
        source=Source.NER,
        confidence=0.9,
        normalized=seg.text.strip().lower(),
    )
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]))
    assert len(outcome.markers) == 1
    # Первая строка («И» в одиночестве) не могла вместить ни одной
    # непустой ступени лестницы — если бы рендер настаивал на первой
    # строке, результат был бы `fallback_reason="blank"`.
    assert outcome.markers[0].shown_label != ""
    assert outcome.markers[0].fallback_reason == ""


def test_style_marker_fills_erase_paint_and_label_regions(tmp_path: pathlib.Path) -> None:
    """Контракт М1: `erase_regions`/`paint_regions`/`label_region`
    заполнены после рендера стиля `marker`, а не пусты, как в исходном
    плане (до заполнения рендером)."""
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="marker")
    assert len(outcome.replacements) == 1
    replacement = outcome.replacements[0]
    assert replacement.erase_regions
    assert replacement.paint_regions
    assert replacement.label_region is not None


def test_style_blackbox_fills_erase_and_paint_but_not_label(tmp_path: pathlib.Path) -> None:
    """`blackbox` считает геометрию удаления, но никогда не строит подпись
    — `label_region` остаётся `None` (план М1)."""
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    replacement = outcome.replacements[0]
    assert replacement.erase_regions
    assert replacement.paint_regions
    assert replacement.label_region is None


def test_marker_uses_requested_pdf_background_color(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)

    render_pdf_redacted(
        src,
        dest,
        document,
        _plan(document, [entity]),
        style="marker",
        highlight_background="#0080FF",
    )

    assert any(color == pytest.approx((0.0, 128 / 255, 1.0)) for color in _filled_rect_colors(dest))


def test_marker_without_background_keeps_marker_but_draws_no_rectangle(
    tmp_path: pathlib.Path,
) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    white = tmp_path / "white.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    plan = _plan(document, [entity])

    render_pdf_redacted(src, white, document, plan, style="marker", highlight_background="#FFFFFF")
    assert _filled_rect_colors(white) == [(1.0, 1.0, 1.0)]

    outcome = render_pdf_redacted(
        src, dest, document, plan, style="marker", highlight_background="none"
    )

    assert _filled_rect_colors(dest) == []
    rendered = pymupdf.open(dest)
    try:
        assert "[ИНН]" in rendered[0].get_text()
    finally:
        rendered.close()
    assert _INN.encode() not in dest.read_bytes()
    assert outcome.replacements[0].paint_regions == ()
    assert ValidateAgent().validate(plan, [dest]).leaked == ()
    assert count_highlight_overlaps(plan, src, dest, highlight_background=None) == 0


def test_blackbox_ignores_requested_highlight_background(tmp_path: pathlib.Path) -> None:
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)

    render_pdf_redacted(
        src,
        dest,
        document,
        _plan(document, [entity]),
        style="blackbox",
        highlight_background="#00FF00",
    )

    assert _filled_rect_colors(dest) == [(0.0, 0.0, 0.0)]


def test_pdf_background_color_changes_artifact_but_remains_deterministic(
    tmp_path: pathlib.Path,
) -> None:
    src = _make_pdf_with_inn(tmp_path)
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    plan = _plan(document, [entity])
    first = tmp_path / "first.pdf"
    same = tmp_path / "same.pdf"
    other = tmp_path / "other.pdf"

    render_pdf_redacted(src, first, document, plan, highlight_background="#0080FF")
    render_pdf_redacted(src, same, document, plan, highlight_background="0080ff")
    render_pdf_redacted(src, other, document, plan, highlight_background="#00FF00")

    assert first.read_bytes() == same.read_bytes()
    assert first.read_bytes() != other.read_bytes()


def test_label_extension_does_not_erase_neighbouring_kept_word(tmp_path: pathlib.Path) -> None:
    """План М1, правило 3: расширение поля подписи — только в доказанно
    свободное место своей строки, `erase_regions` не трогается никогда.

    Без разделения регионов (одна и та же геометрия и для удаления, и для
    подписи) этот тест падает: чтобы вписать канонический маркер, старый
    код раздвигал сам прямоугольник **удаления**, и `apply_redactions`
    стирал бы часть соседнего слова, которое в план не входит."""
    path = tmp_path / "neighbour.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    # Один инициал — сущность, за которой (через несколько пробелов —
    # доказанно свободное место) следует НЕ входящее в план слово.
    page.insert_text((72, 100), "И        Незыблемовна", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()

    document = ingest_pdf(path)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.PERSON,
        text="И",
        segment_order=seg.order,
        start=0,
        end=1,
        source=Source.RULE,
        confidence=1.0,
        normalized="и",
    )
    dest = tmp_path / "redacted.pdf"
    outcome = render_pdf_redacted(path, dest, document, _plan(document, [entity]))

    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "Незыблемовна" in text, text

    replacement = outcome.replacements[0]
    erase_region = replacement.erase_regions[0]
    label_region = replacement.label_region
    assert label_region is not None
    # Область удаления одного инициала («И») квантуется вверх ровно до
    # одного кванта сетки 12 pt (план М1, правило 5) — не дальше, хотя
    # свободное место после неё тянется до самого «Незыблемовна». Подпись
    # же имела право расшириться в это свободное место значительно шире —
    # сама область удаления от этого расширения не растёт ни на пункт.
    assert erase_region.x1 - erase_region.x0 == pytest.approx(12.0)
    assert label_region.x1 >= erase_region.x1
    assert label_region.x1 - label_region.x0 > 12.0


# ── обрезка прямоугольника по соседней строке (Д10, план T2.2.2, шаг 3) ───────


def _entity_for_bare_text(document: Document, containing: str, text: str) -> Entity:
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


def test_redaction_does_not_erase_neighbour_line(tmp_path: pathlib.Path) -> None:
    """Д10: прямоугольник редакции первой строки не должен стирать текст
    соседней строки, даже если их символьные боксы по вертикали
    перекрываются — реальный дефект: строка «в лице Директора» стирала
    хвост соседней строки на всю свою ширину."""
    src = _make_pdf_overlapping_lines(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_bare_text(document, "Verhnyaya", "sekret")
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "Nizhnyaya stroka tekst" in text, text
    assert outcome.collisions == ()


def test_redaction_still_removes_own_line(tmp_path: pathlib.Path) -> None:
    """Защита от переобрезки (риск Р1 плана T2.2.2): своя строка обязана
    быть удалена — ровно так упал прототип на `Ивановны`, когда «своя»
    строка была вычислена неверно и прямоугольник схлопнулся в высоту 0."""
    src = _make_pdf_overlapping_lines(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_bare_text(document, "Verhnyaya", "sekret")
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "sekret" not in text, text
    assert outcome.collisions == ()


def test_overlapping_lines_fall_back_and_report_collision(tmp_path: pathlib.Path) -> None:
    """Строки наложены друг на друга целиком (штамп) — обрезка отменяется,
    текст всё равно удалён исходным прямоугольником, коллизия попала в
    возвращаемое значение (план T2.2.2, шаг 3, п. 4)."""
    src = _make_pdf_fully_overlapping_lines(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_bare_text(document, "sekretnoe", "sekretnoe")
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    assert len(outcome.collisions) == 1, outcome.collisions
    collision = outcome.collisions[0]
    assert collision.page == 0
    assert collision.entity_type == "org_name"
    assert isinstance(collision.line_id, int)
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "sekretnoe" not in text, text


# ── квантование ширины erase_regions по сетке 12 pt (план М1, правило 5) ──────


def _fake_line_chars(
    word_width: float, gap: float, blocker_width: float | None
) -> tuple[PageChars, pymupdf.Rect]:
    """Синтетическая строка без реального PDF/шрифта: слово шириной
    ``word_width`` от x=0, затем пробел шириной ``gap`` (доказанно свободное
    место), затем — опционально — непробельный символ шириной
    ``blocker_width`` сразу за пробелом (сосед, которого нельзя задевать)."""
    text = "W "
    boxes = [
        pymupdf.Rect(0.0, 0.0, word_width, 10.0),
        pymupdf.Rect(word_width, 0.0, word_width + gap, 10.0),
    ]
    line_ids = [0, 0]
    cursor = word_width + gap
    if blocker_width is not None:
        text += "X"
        boxes.append(pymupdf.Rect(cursor, 0.0, cursor + blocker_width, 10.0))
        line_ids.append(0)
        cursor += blocker_width
    chars = PageChars(text=text, boxes=tuple(boxes), line_ids=tuple(line_ids))
    line_box = pymupdf.Rect(0.0, 0.0, cursor, 10.0)
    return chars, line_box


def test_quantize_erase_rect_rounds_up_with_free_space() -> None:
    """Ширина 5pt при свободном месте справа — округляется вверх до первого
    кратного 12 (план М1, правило 5), не оставляя её нетронутой."""
    chars, line_box = _fake_line_chars(word_width=5.0, gap=1000.0, blocker_width=None)
    rect = pymupdf.Rect(0.0, 0.0, 5.0, 10.0)
    quantized = _quantize_erase_rect(chars, 0, rect, 0, 1, line_box)
    assert quantized.x0 == 0.0
    assert quantized.x1 == 12.0


def test_quantize_erase_rect_two_widths_in_same_quantum_are_byte_identical() -> None:
    """Главный критерий приёмки плана М1: две разные исходные ширины,
    попадающие в один квант (5pt и 10pt — обе < 12), дают побайтово
    одинаковый прямоугольник после квантования."""
    chars_a, line_box_a = _fake_line_chars(word_width=5.0, gap=1000.0, blocker_width=None)
    chars_b, line_box_b = _fake_line_chars(word_width=10.0, gap=1000.0, blocker_width=None)
    quantized_a = _quantize_erase_rect(
        chars_a, 0, pymupdf.Rect(0.0, 0.0, 5.0, 10.0), 0, 1, line_box_a
    )
    quantized_b = _quantize_erase_rect(
        chars_b, 0, pymupdf.Rect(0.0, 0.0, 10.0, 10.0), 0, 1, line_box_b
    )
    assert (quantized_a.x0, quantized_a.x1) == (quantized_b.x0, quantized_b.x1)
    assert quantized_a.x1 == 12.0


def test_quantize_erase_rect_does_not_shrink_rect_already_on_grid() -> None:
    """Ширина, уже кратная 12pt, не растёт (и тем более не сжимается) —
    иначе округление вверх было бы систематической утечкой в другую
    сторону: лишний квант там, где он не нужен."""
    chars, line_box = _fake_line_chars(word_width=24.0, gap=1000.0, blocker_width=None)
    rect = pymupdf.Rect(0.0, 0.0, 24.0, 10.0)
    quantized = _quantize_erase_rect(chars, 0, rect, 0, 1, line_box)
    assert quantized.x1 == 24.0


def test_quantize_erase_rect_stops_before_neighbouring_char() -> None:
    """Ловушка задания: полный квант потребовал бы залезть на соседний
    непробельный символ — расширение обязано остановиться на его границе, а
    не дотянуть до кратного 12, иначе ``apply_redactions`` стёр бы соседа."""
    chars, line_box = _fake_line_chars(word_width=5.0, gap=3.0, blocker_width=6.0)
    rect = pymupdf.Rect(0.0, 0.0, 5.0, 10.0)
    quantized = _quantize_erase_rect(chars, 0, rect, 0, 1, line_box)
    # Полный квант дал бы x1=12.0, но сосед начинается в x=8.0.
    assert quantized.x1 == 8.0
    assert quantized.x1 >= rect.x1  # никогда не становится уже оригинала


def _person_entity(document: Document, seg_text_contains: str, name: str) -> Entity:
    seg = next(s for s in document.segments if seg_text_contains in s.text)
    start = seg.text.index(name)
    return Entity(
        type=EntityType.PERSON,
        text=name,
        segment_order=seg.order,
        start=start,
        end=start + len(name),
        source=Source.RULE,
        confidence=1.0,
        normalized=name.lower(),
    )


def test_two_different_surnames_in_same_width_quantum_get_identical_geometry(
    tmp_path: pathlib.Path,
) -> None:
    """Приёмка плана М1: «Попов» (38.58pt) и «Иванов» (45.62pt) — разной
    исходной ширины, но оба округляются вверх до одного и того же кванта
    (48pt) при достаточном свободном месте справа. Оба слова начинаются в
    одном и том же x0 на своей строке — итоговая геометрия по горизонтали
    (x0, x1) обязана совпасть побайтово, не «примерно»."""
    path = tmp_path / "surnames.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "Попов        далее", fontname="dvu", fontsize=12)
    page.insert_text((72, 130), "Иванов        далее", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()

    document = ingest_pdf(path)
    entities = [
        _person_entity(document, "Попов", "Попов"),
        _person_entity(document, "Иванов", "Иванов"),
    ]
    dest = tmp_path / "redacted.pdf"
    outcome = render_pdf_redacted(path, dest, document, _plan(document, entities), style="blackbox")

    by_text = {r.entity.text: r for r in outcome.replacements}
    popov_region = by_text["Попов"].erase_regions[0]
    ivanov_region = by_text["Иванов"].erase_regions[0]
    assert popov_region.x1 - popov_region.x0 != pytest.approx(38.58, abs=0.5)  # квант сработал
    assert (popov_region.x0, popov_region.x1) == (ivanov_region.x0, ivanov_region.x1)
    assert popov_region.x1 - popov_region.x0 == pytest.approx(48.0)


def test_quantized_erase_region_never_erases_neighbouring_word(tmp_path: pathlib.Path) -> None:
    """Расширение до полного кванта (24pt для «Ли», 16.8pt исходной ширины)
    упёрлось бы в «Смирнова» через один узкий пробел — итоговая область
    обязана остановиться раньше и не стереть ни одного символа соседа."""
    path = tmp_path / "neighbour_word.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "Ли Смирнова", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()

    document = ingest_pdf(path)
    entity = _person_entity(document, "Смирнова", "Ли")
    dest = tmp_path / "redacted.pdf"
    plan = _plan(document, [entity])
    outcome = render_pdf_redacted(path, dest, document, plan, style="blackbox")

    doc2 = pymupdf.open(str(dest))
    text = doc2[0].get_text()
    doc2.close()
    assert "Смирнова" in text, text

    region = outcome.replacements[0].erase_regions[0]
    assert region.x1 - region.x0 < 24.0  # квант не дотянут — сосед рядом
    assert region.x1 - region.x0 > 16.8 - 0.5  # но шире исходного «Ли»

    diff = layout_diff(path, dest, plan)
    assert diff.removed == 0, diff.first_diff


# ── compute_erase_geometry: пересчёт геометрии без открытия артефакта (план М3) ───


def test_compute_erase_geometry_matches_render_pdf_redacted(tmp_path: pathlib.Path) -> None:
    """``compute_erase_geometry`` обязана дать побайтово ту же геометрию
    ``erase_regions``, что и настоящий ``render_pdf_redacted`` — план М3
    (сертификат обезличивания) пересчитывает ширину эрейз-региона заново по
    исходнику и плану, не открывая уже сохранённый артефакт (аннотация
    редакции необратимо потребляется ``apply_redactions``, восстановить её
    из готового файла нельзя)."""
    path = tmp_path / "surnames.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "Попов        далее", fontname="dvu", fontsize=12)
    page.insert_text((72, 130), "Иванов        далее", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()

    document = ingest_pdf(path)
    entities = [
        _person_entity(document, "Попов", "Попов"),
        _person_entity(document, "Иванов", "Иванов"),
    ]
    plan = _plan(document, entities)
    dest = tmp_path / "redacted.pdf"
    outcome = render_pdf_redacted(path, dest, document, plan, style="blackbox")

    geometry = compute_erase_geometry(path, plan)

    by_ref = {repl.ref: repl for repl in outcome.replacements}
    assert set(geometry) == set(by_ref)
    for ref, regions in geometry.items():
        assert regions == by_ref[ref].erase_regions


def test_compute_erase_geometry_ignores_docx_replacements(tmp_path: pathlib.Path) -> None:
    """Замены с ``anchor.fmt != "pdf"`` не участвуют — у них нет координатной
    геометрии, которую можно пересчитать по странице."""
    path = tmp_path / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "Иванов", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()

    document = ingest_pdf(path)
    entity = _person_entity(document, "Иванов", "Иванов")
    plan = _plan(document, [entity])
    docx_only_plan = MaskPlan(
        replacements=tuple(
            Replacement(
                ref=repl.ref,
                entity=repl.entity,
                marker=repl.marker,
                group_id=repl.group_id,
                profile_id=repl.profile_id,
                anchor=Anchor(fmt="docx", locator=("body", 0)),
            )
            for repl in plan.replacements
        ),
        groups=plan.groups,
        skipped=plan.skipped,
        requested_types=plan.requested_types,
    )

    assert compute_erase_geometry(path, docx_only_plan) == {}


# ── М6-1: erase_regions не имеют права измениться ни на pt ────────────────────
#
# label_region (подпись) план М6-1 обязан считать по **уже отредактированной**
# странице, а erase_regions (что реально стирается ``apply_redactions``) —
# нет: они остаются на до-редакционной геометрии, как и раньше, иначе
# `add_redact_annot` мог бы стереть больше, чем безопасно доказано
# (`_free_extension_right` строится по ещё не тронутым боксам соседей). Этот
# файл — эталон, сгенерированный ДО правки М6-1 (тем же кодом
# `compute_erase_geometry`, который правка не касается: `_trim_to_own_line`,
# `_quantize_erase_rect`, `_entity_rects` в диффе М6-1 не менялись ни строкой)
# — побайтовое совпадение здесь и есть страховка от утечки при обрезке
# `label_box` (план, риск «М6-2 схлопывает прямоугольник и сущность утекает»).
_ERASE_GEOMETRY_GOLDEN = pathlib.Path(__file__).parent / "erase_geometry_golden.json"


def _make_pdf_erase_geometry_scenarios(tmp_path: pathlib.Path) -> pathlib.Path:
    """Четыре страницы, каждая — отдельная ветка ``_trim_to_own_line``/
    ``_quantize_erase_rect``, уже покрытая другими тестами этого файла по
    отдельности: квантование до полного 12pt-шага (план М1, правило 5),
    квантование, остановленное соседом без единого pt зазора (план М5),
    обрезка серединой полосы перекрытия строк (Д10), отменённая обрезка при
    полном перекрытии строк — коллизия (план T2.2.2, шаг 3, п. 4)."""
    path = tmp_path / "erase_geometry_scenarios.pdf"
    doc = pymupdf.open()

    page0 = doc.new_page()
    page0.insert_font(fontname="dvu", fontfile=_FONT)
    page0.insert_text((72, 100), "Попов        далее", fontname="dvu", fontsize=12)

    page1 = doc.new_page()
    page1.insert_font(fontname="dvu", fontfile=_FONT)
    page1.insert_text((72, 100), "от 08.09.2026№158-ПК", fontname="dvu", fontsize=12)

    page2 = doc.new_page()
    page2.insert_font(fontname="dvu", fontfile=_FONT)
    page2.insert_text((72, 100), "Verhnyaya stroka sekret", fontname="dvu", fontsize=13)
    page2.insert_text((72, 112.7), "Nizhnyaya stroka tekst", fontname="dvu", fontsize=13)

    page3 = doc.new_page()
    page3.insert_font(fontname="dvu", fontfile=_FONT)
    page3.insert_text((72, 100), "sekretnoe slovo tut", fontname="dvu", fontsize=10)
    page3.insert_text((72, 108), "SHTAMP NALOZHEN SVERHU I SNIZU", fontname="dvu", fontsize=44)

    doc.save(str(path))
    doc.close()
    return path


def _erase_geometry_scenario_plan(path: pathlib.Path) -> MaskPlan:
    document = ingest_pdf(path)
    entities = [
        _person_entity(document, "Попов", "Попов"),
        _entity_for_bare_text_m5(document, "08.09.2026№158-ПК", "08.09.2026"),
        _entity_for_bare_text(document, "Verhnyaya", "sekret"),
        _entity_for_bare_text(document, "sekretnoe", "sekretnoe"),
    ]
    return _plan(document, entities)


def _dump_erase_geometry(
    geometry: dict[str, tuple[PdfRegion, ...]],
) -> dict[str, list[dict[str, float | int]]]:
    """Сериализация, устойчивая к порядку обхода словаря (план, риск
    «недетерминизм от порядка обхода») — ключи отсортированы явно, а не
    оставлены в порядке вставки ``dict``."""
    return {
        ref: [dataclasses.asdict(region) for region in regions]
        for ref, regions in sorted(geometry.items())
    }


def test_compute_erase_geometry_golden_dump_unchanged_by_m6_1(tmp_path: pathlib.Path) -> None:
    """Приёмка М6-1, п. 2: ``compute_erase_geometry`` даёт побайтово тот же
    JSON-дамп, что и до правки — обрезке в М6-1 подлежит только
    ``label_box`` (подпись), эрейз-геометрия остаётся до-редакционной."""
    path = _make_pdf_erase_geometry_scenarios(tmp_path)
    plan = _erase_geometry_scenario_plan(path)

    geometry = compute_erase_geometry(path, plan)
    dump = _dump_erase_geometry(geometry)

    golden = json.loads(_ERASE_GEOMETRY_GOLDEN.read_text(encoding="utf-8"))
    assert dump == golden


def test_highlight_style_paints_visible_background_not_white(tmp_path: pathlib.Path) -> None:
    """Файл называется `masked_highlight`, и постановка требует, чтобы
    найденное было **подсвечено**. Белая заливка на белой странице не
    подсвечивает ничего: область удаления неотличима от пустого места, и
    человек не видит, что здесь вообще что-то было. Тест падает, если
    заливка стиля `marker` вернётся к белому.
    """
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="marker")

    region = outcome.replacements[0].erase_regions[0]
    doc = pymupdf.open(dest)
    page = doc[region.page]
    # Точка внутри области удаления, заведомо не задетая глифом маркера:
    # правый край полосы, по вертикали — середина.
    pix = page.get_pixmap(clip=pymupdf.Rect(region.x1 - 2, region.y0 + 1, region.x1, region.y1 - 1))
    samples = {pix.pixel(x, y) for x in range(pix.width) for y in range(pix.height)}
    doc.close()

    assert samples, "область удаления пуста — нечего проверять"
    assert samples != {(255, 255, 255)}, (
        f"подсвеченный вариант закрашен белым: подсветки нет, выборка пикселей {samples}"
    )


def test_label_stays_on_the_line_where_entity_started(tmp_path: pathlib.Path) -> None:
    """Маркер обязан стоять там, где стоял оригинал.

    Регресс с реального документа: у сущности, разорванной переносом,
    хвост на следующей строке шире головы. Пока рендер выбирал кандидата
    «по наибольшей ширине», полный маркер не влезал в узкую первую строку,
    зато влезал во вторую — и уезжал на 455 pt влево и на строку вниз.
    Читатель искал сторону договора там, где она написана, и находил
    пустоту. Сокращение на месте лучше переезда: расшифровка стоит одной
    строки легенды.
    """
    org = "Общество с Ограниченной Ответственностью Ромашка"
    src = _make_pdf_block(
        tmp_path,
        [
            "Заказчик просит Общество с",
            "Ограниченной Ответственностью Ромашка оплатить счёт.",
        ],
    )
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, org, EntityType.ORG_NAME)
    outcome = render_pdf_redacted(src, dest, document, _plan(document, [entity]), style="marker")

    replacement = outcome.replacements[0]
    label = replacement.label_region
    assert label is not None
    first_erase = min(replacement.erase_regions, key=lambda r: (r.y0, r.x0))
    assert abs(label.y0 - first_erase.y0) < 3.0, (
        "подпись уехала на другую строку: "
        f"label.y0={label.y0:.1f}, первая область удаления y0={first_erase.y0:.1f}"
    )


# ── М5: подсветка не смеет накрывать чужой символ ─────────────────────────────


def test_label_box_candidates_stops_exactly_at_free_extension_boundary() -> None:
    """Прямое воспроизведение дефекта плана М5: сосед («№») начинается
    ровно на границе доказанно свободного расширения вправо
    (``_free_extension_right``) — свободного места вообще нет. Старый код
    добавлял к этой границе безусловные ``+2pt`` — ровно те пункты, что
    заезжали на живой символ на реальном документе (заказчик нашёл это
    глазами 08.09.2026). Новый код обязан остановиться ровно на границе.

    ``post_chars`` здесь совпадает с тем, что было бы «до» редактирования —
    в этих тестах нет своего прохода ``apply_redactions``, а проверяется
    сама формула границы (план М6-1 меняет только **источник** боксов, не
    саму формулу «до первого чужого непробельного символа»)."""
    text = "W№"
    boxes = (pymupdf.Rect(0.0, 0.0, 10.0, 10.0), pymupdf.Rect(10.0, 0.0, 16.0, 10.0))
    chars = PageChars(text=text, boxes=boxes, line_ids=(0, 0))
    line_boxes = _line_boxes(chars)

    trimmed_rects = [(0, pymupdf.Rect(0.0, 0.0, 10.0, 10.0))]
    candidates = _label_box_candidates(chars, line_boxes, line_boxes, trimmed_rects)

    assert len(candidates) == 1
    _erase_rect, label_box = candidates[0]
    assert label_box.x1 == pytest.approx(10.0), (
        f"подсветка залезла на соседа: label.x1={label_box.x1:.2f}, "
        "граница доказанно свободного расширения — 10.0"
    )


def test_label_box_candidates_vertical_padding_does_not_cross_into_line_below() -> None:
    """План М5, вертикальная ось: символ соседней строки оказался всего в
    0.5pt ниже своей строки (реальный шаг строки может быть меньше высоты
    бокса глифа, та же причина, что у Д10) — безусловный ``+2`` по нижнему
    краю поля подписи заехал бы прямо на него. ``_free_extension_vertical``
    обязана зажать отступ доказанно свободной границей, а не добавлять его
    поверх неё."""
    text = "W X"
    boxes = (
        pymupdf.Rect(0.0, 0.0, 10.0, 10.0),
        _LINE_BREAK_RECT,
        pymupdf.Rect(0.0, 10.5, 10.0, 20.5),
    )
    chars = PageChars(text=text, boxes=boxes, line_ids=(0, 0, 1))
    line_boxes = _line_boxes(chars)

    trimmed_rects = [(0, pymupdf.Rect(0.0, 0.0, 10.0, 10.0))]
    candidates = _label_box_candidates(chars, line_boxes, line_boxes, trimmed_rects)

    assert len(candidates) == 1
    _erase_rect, label_box = candidates[0]
    assert label_box.y1 <= 10.5 + 0.01, (
        f"подпись залезла на строку ниже: label.y1={label_box.y1:.2f}, сосед начинается на y=10.5"
    )


def test_label_box_candidates_vertical_padding_does_not_cross_into_line_above() -> None:
    """Симметрия предыдущего теста — преграда сверху, а не снизу."""
    text = "X W"
    boxes = (
        pymupdf.Rect(0.0, -10.5, 10.0, -0.5),
        _LINE_BREAK_RECT,
        pymupdf.Rect(0.0, 0.0, 10.0, 10.0),
    )
    chars = PageChars(text=text, boxes=boxes, line_ids=(0, 0, 1))
    line_boxes = _line_boxes(chars)

    trimmed_rects = [(1, pymupdf.Rect(0.0, 0.0, 10.0, 10.0))]
    candidates = _label_box_candidates(chars, line_boxes, line_boxes, trimmed_rects)

    assert len(candidates) == 1
    _erase_rect, label_box = candidates[0]
    assert label_box.y0 >= -0.5 - 0.01, (
        f"подпись залезла на строку выше: label.y0={label_box.y0:.2f}, сосед кончается на y=-0.5"
    )


def test_label_box_candidates_keep_default_margin_without_neighbours() -> None:
    """Без соседа рядом отступ на воздух под глифы остаётся тем же, что и
    раньше (``-1`` сверху, ``+2`` снизу) — план М5 не имеет права снять
    читаемость там, где расширяться было безопасно."""
    text = "W"
    chars = PageChars(text=text, boxes=(pymupdf.Rect(0.0, 0.0, 10.0, 10.0),), line_ids=(0,))
    line_boxes = _line_boxes(chars)

    trimmed_rects = [(0, pymupdf.Rect(0.0, 0.0, 10.0, 10.0))]
    candidates = _label_box_candidates(chars, line_boxes, line_boxes, trimmed_rects)

    assert len(candidates) == 1
    _erase_rect, label_box = candidates[0]
    assert label_box.y0 == pytest.approx(-1.0)
    assert label_box.y1 == pytest.approx(12.0)


def test_line_boxes_skip_space_drops_lines_made_only_of_space() -> None:
    """План М6-1: строка, целиком состоящая из пробелов (искусственный
    «хвост» после ``apply_redactions``), не должна попасть в результат
    вовсе — иначе она давала бы вертикальный центр, совпадающий с центром
    собственной строки, и обрезала бы отступ пополам без единого
    настоящего соседа рядом."""
    text = "   "
    boxes = (
        pymupdf.Rect(0.0, 0.0, 5.0, 10.0),
        pymupdf.Rect(5.0, 0.0, 10.0, 10.0),
        pymupdf.Rect(10.0, 0.0, 15.0, 10.0),
    )
    chars = PageChars(text=text, boxes=boxes, line_ids=(3, 3, 3))
    result = _line_boxes(chars, skip_space=True)
    assert 3 not in result, "строка целиком из пробелов не должна считаться преградой вовсе"


def test_label_box_candidates_keeps_protective_margin_when_neighbour_line_has_real_text() -> None:
    """Регресс, найденный при разборе ``fix/r9-span-boundaries``
    (``highlight_overlaps`` 315 → 1090 после М6-1,
    ``contract_pdf_02_school.pdf``, стр. 42, группа «МАОУ гимназия №144»):
    у соседней строки сверху хвостовой пробел стоит ниже последней
    настоящей буквы (частый артефакт метрик шрифта PyMuPDF — бокс пробела
    не совпадает по высоте с боксами букв). Прежний ``skip_space=True``
    вырезал пробел из объединения **любой** строки, а не только строки,
    целиком состоящей из пробелов, — из-за этого полоса соседней строки с
    реальным текстом становилась короче своего настоящего видимого текста,
    середина полосы перекрытия сдвигалась ближе к собственной строке, чем
    позволяет настоящая буква соседа, и подпись заезжала на неё."""
    text = "X W"
    boxes = (
        pymupdf.Rect(0.0, -10.0, 10.0, 0.3),  # 'X' — настоящая буква соседней строки
        pymupdf.Rect(10.0, -10.5, 15.0, 1.5),  # ' ' — хвостовой пробел, ниже буквы
        pymupdf.Rect(0.0, 0.0, 10.0, 20.0),  # 'W' — собственная строка
    )
    chars = PageChars(text=text, boxes=boxes, line_ids=(0, 0, 1))
    pre_line_boxes = _line_boxes(chars)  # источник own_line, как «до» редактирования
    post_line_boxes = _line_boxes(chars, skip_space=True)  # план М6-1

    trimmed_rects = [(1, pymupdf.Rect(0.0, 0.9, 10.0, 20.0))]
    candidates = _label_box_candidates(chars, pre_line_boxes, post_line_boxes, trimmed_rects)

    assert len(candidates) == 1
    _erase_rect, label_box = candidates[0]
    assert label_box.y0 >= 0.3 - 0.01, (
        "подпись залезла на настоящую букву соседней строки сверху "
        f"(её низ y=0.3): label.y0={label_box.y0:.2f}"
    )


def test_label_box_candidates_own_line_remainder_after_redaction_is_not_a_neighbour() -> None:
    """Второй регресс, вскрытый при том же разборе (``highlight_overlaps``
    315 → 1090): исправление предыдущего теста включает пробелы обратно в
    объединение остатка собственной строки, и тогда этот остаток перестаёт
    быть равен ``pre_line_boxes[line_id]`` (тот включает ещё и саму
    стёртую сущность) — сравнение ``other == own_line`` в
    ``_free_extension_vertical`` никогда не срабатывает на настоящей
    редакции, только в синтетических тестах, где «до» и «после» совпадают
    буквально. Без более общего критерия остаток собственной строки
    (реальный текст **после** сущности на той же строке) ложно считается
    отдельной строкой снизу и обрезает вертикальный отступ до долей пункта,
    хотя настоящего соседа на другой физической строке нет вовсе."""
    text_pre = "WXY"
    pre_boxes = (
        pymupdf.Rect(0.0, 0.0, 10.0, 10.0),  # 'W' — сущность
        pymupdf.Rect(10.0, 0.0, 20.0, 10.0),  # 'X' — станет пробелом после apply_redactions
        pymupdf.Rect(20.0, 0.0, 30.0, 10.0),  # 'Y' — реальный текст той же строки после сущности
    )
    pre_chars = PageChars(text=text_pre, boxes=pre_boxes, line_ids=(0, 0, 0))
    pre_line_boxes = _line_boxes(pre_chars)

    # После apply_redactions символа сущности в page_chars уже нет вовсе,
    # остаток строки — пробел на месте «X» (тот же приём, что и в тесте
    # плана М6-1 выше) и настоящий «Y» после него.
    text_post = " Y"
    post_boxes = (
        pymupdf.Rect(10.0, 0.0, 20.0, 10.0),
        pymupdf.Rect(20.0, 0.0, 30.0, 10.0),
    )
    post_chars = PageChars(text=text_post, boxes=post_boxes, line_ids=(0, 0))
    post_line_boxes = _line_boxes(post_chars, skip_space=True)

    trimmed_rects = [(0, pymupdf.Rect(0.0, 0.0, 10.0, 10.0))]
    candidates = _label_box_candidates(post_chars, pre_line_boxes, post_line_boxes, trimmed_rects)

    assert len(candidates) == 1
    _erase_rect, label_box = candidates[0]
    assert label_box.y1 == pytest.approx(12.0), (
        "остаток собственной строки после редакции ложно принят за чужую "
        f"строку снизу: label.y1={label_box.y1:.2f}, ожидалось 12.0 "
        "(без постороннего соседа отступ снизу — стандартный +2)"
    )


def test_label_box_candidates_never_extends_into_another_replacements_erase_rect() -> None:
    """Третий регресс того же разбора (``highlight_overlaps`` 1090 → 813
    после первых двух фиксов, ``contract_pdf_02_school.pdf``, стр. 26,
    группа «Муниципальное автономное...», сосед — уже вставленный маркер
    «[Заказчик 2]» другой замены той же страницы). ``compute_label_geometry``
    считает геометрию всех замен страницы ДО того, как в какую-либо из них
    вписан текст маркера: эрейз-регион чужой замены к этому моменту уже
    пуст в ``post_chars`` (``apply_redactions`` стёр его исходный текст),
    но не свободен — туда скоро впишется чужой маркер. Расширение обязано
    остановиться на границе чужого эрейз-региона, даже если в
    ``post_chars`` там сейчас буквально пусто."""
    text = "W "
    chars = PageChars(
        text=text,
        boxes=(
            pymupdf.Rect(0.0, 0.0, 10.0, 13.0),  # 'W' — сущность
            pymupdf.Rect(10.0, 0.0, 200.0, 13.0),  # хвост строки — доказанно свободное место
        ),
        line_ids=(0, 0),
    )
    pre_line_boxes = _line_boxes(chars)
    post_line_boxes = _line_boxes(chars, skip_space=True)

    trimmed_rects = [(0, pymupdf.Rect(0.0, 0.0, 10.0, 13.0))]
    # Чужая замена того же прогона: её эрейз-регион уже пуст (её символы
    # стёрты), но скоро туда впишется её собственный маркер.
    other_erase_rects = [pymupdf.Rect(50.0, -2.0, 90.0, 9.0)]

    candidates = _label_box_candidates(
        chars, pre_line_boxes, post_line_boxes, trimmed_rects, other_erase_rects
    )

    assert len(candidates) == 1
    _erase_rect, label_box = candidates[0]
    assert label_box.x1 <= 50.0 + 0.01, (
        f"подпись залезла в эрейз-регион другой замены: label.x1={label_box.x1:.2f}"
    )


def test_label_box_candidates_do_not_share_vertical_margin_with_another_mask() -> None:
    """11.09.2026: две соседние маски не могут накрывать маркеры друг друга.

    Середина полосы пересечения строк достаточна для redaction, но оставляет
    часть erase-региона соседа доступной для подписи. Здесь верхняя граница
    своей строки пересекается с нижней границей уже удалённого поля: подпись
    обязана начаться не раньше конца соседней маски.
    """
    text = "XW"
    chars = PageChars(
        text=text,
        boxes=(
            pymupdf.Rect(0.0, 0.0, 10.0, 10.0),
            pymupdf.Rect(0.0, 9.0, 10.0, 21.0),
        ),
        line_ids=(0, 1),
    )
    pre_line_boxes = _line_boxes(chars)
    post_line_boxes = _line_boxes(chars, skip_space=True)
    own = pymupdf.Rect(0.0, 10.0, 10.0, 20.0)
    other = pymupdf.Rect(0.0, 0.0, 10.0, 10.0)

    candidates = _label_box_candidates(chars, pre_line_boxes, post_line_boxes, [(1, own)], [other])

    assert candidates[0][1].y0 >= other.y1 - 0.01


def test_label_box_candidates_uses_post_redaction_chars_not_pre() -> None:
    """Сердце плана М6-1: свободная граница ищется по ``post_chars``
    (аргумент функции), а ``pre_line_boxes`` не подмешивает в поиск соседей
    ничего, кроме собственной строки. Здесь сосед, реально стоявший на
    границе в ``pre_line_boxes``/до печати, в ``post_chars`` уже стёрт
    (апостериорная страница) — граница обязана уйти дальше, а не
    остановиться там, где сосед стоял до редактирования. Старый код (проход
    один раз, до ``apply_redactions``) в точности этот сосед и видел бы —
    прямое воспроизведение регресса, который чинит М6-1 (сдвиг хвоста
    кернингового рана после ``apply_redactions``, план TASKS.md М6)."""
    # До редактирования: "W" (сущность) следом "X" (сосед, который на
    # настоящей странице к моменту вставки подписи уже будет стёрт другой
    # заменой того же прогона) следом "Y" (настоящий, непустой сосед).
    text = "WXY"
    pre_boxes = (
        pymupdf.Rect(0.0, 0.0, 10.0, 10.0),
        pymupdf.Rect(10.0, 0.0, 20.0, 10.0),
        pymupdf.Rect(20.0, 0.0, 30.0, 10.0),
    )
    pre_chars = PageChars(text=text, boxes=pre_boxes, line_ids=(0, 0, 0))
    pre_line_boxes = _line_boxes(pre_chars)

    # После редактирования "X" стёрт (apply_redactions вычистил его —
    # символа для него в page_chars больше нет вовсе), "Y" остался на месте.
    post_text = "W Y"
    post_boxes = (
        pymupdf.Rect(0.0, 0.0, 10.0, 10.0),
        pymupdf.Rect(10.0, 0.0, 20.0, 10.0),  # пробел там, где было "X"
        pymupdf.Rect(20.0, 0.0, 30.0, 10.0),
    )
    post_chars = PageChars(text=post_text, boxes=post_boxes, line_ids=(0, 0, 0))
    post_line_boxes = _line_boxes(post_chars)

    trimmed_rects = [(0, pymupdf.Rect(0.0, 0.0, 10.0, 10.0))]

    old_style_candidates = _label_box_candidates(
        pre_chars, pre_line_boxes, pre_line_boxes, trimmed_rects
    )
    new_style_candidates = _label_box_candidates(
        post_chars, pre_line_boxes, post_line_boxes, trimmed_rects
    )

    _erase_rect, old_label_box = old_style_candidates[0]
    _erase_rect, new_label_box = new_style_candidates[0]
    assert old_label_box.x1 == pytest.approx(10.0), (
        "контроль: поиск по до-редакционным боксам обязан остановиться "
        f"на «X» (x=10.0), получено {old_label_box.x1:.2f}"
    )
    assert new_label_box.x1 == pytest.approx(20.0), (
        "план М6-1: поиск по пост-редакционным боксам обязан пройти сквозь "
        f"уже стёртое место «X» до настоящего соседа «Y» (x=20.0), "
        f"получено {new_label_box.x1:.2f}"
    )


def _entity_for_bare_text_m5(document: Document, containing: str, text: str) -> Entity:
    seg = next(s for s in document.segments if containing in s.text)
    start = seg.text.index(text)
    return Entity(
        type=EntityType.DATE,
        text=text,
        segment_order=seg.order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
        normalized=text,
    )


def _make_pdf_date_with_zero_gap_neighbour(tmp_path: pathlib.Path) -> pathlib.Path:
    """Воспроизводит дефект, найденный заказчиком глазами 08.09.2026: дата,
    сразу за которой (без единого пункта зазора) стоит ``№`` — реальный
    текст школьного договора «...от 08.09.2026№158-ПК»."""
    path = tmp_path / "date_no_gap.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    page.insert_text((72, 100), "от 08.09.2026№158-ПК", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def test_label_extension_never_crosses_a_zero_gap_neighbour(tmp_path: pathlib.Path) -> None:
    """Полный рендер того самого дефекта (план М5): маркер даты не имеет
    права зайти на «№», стоящий сразу за ней без единого пункта зазора."""
    path = _make_pdf_date_with_zero_gap_neighbour(tmp_path)
    document = ingest_pdf(path)
    entity = _entity_for_bare_text_m5(document, "08.09.2026№158-ПК", "08.09.2026")
    dest = tmp_path / "redacted.pdf"
    outcome = render_pdf_redacted(path, dest, document, _plan(document, [entity]))

    result_doc = pymupdf.open(str(dest))
    result_text = result_doc[0].get_text()
    result_doc.close()
    assert "№158-ПК" in result_text, result_text  # сосед пережил рендер целиком

    replacement = outcome.replacements[0]
    label_region = replacement.label_region
    assert label_region is not None

    source_doc = pymupdf.open(str(path))
    source_chars = page_chars(source_doc[0])
    source_doc.close()
    neighbour_x0 = source_chars.boxes[source_chars.text.index("№")].x0

    assert label_region.x1 <= neighbour_x0 + 0.02, (
        f"подсветка залезла на «№»: label.x1={label_region.x1:.2f}, №.x0={neighbour_x0:.2f}"
    )


def test_highlight_overlap_count_is_zero_on_fixed_render(tmp_path: pathlib.Path) -> None:
    """Метрика ворот (``masker.eval.highlight_overlap_count``, план М5) на
    том же дефекте, но измеренная по-настоящему — рендером в файл
    ``masked_highlight.pdf`` и независимым пересчётом геометрии подсветки
    (``compute_label_geometry``), как и требует задание («мерить по
    выходному файлу»)."""
    path = _make_pdf_date_with_zero_gap_neighbour(tmp_path)
    document = ingest_pdf(path)
    entity = _entity_for_bare_text_m5(document, "08.09.2026№158-ПК", "08.09.2026")
    plan = _plan(document, [entity])
    artifact = tmp_path / "masked_highlight.pdf"
    render_pdf_redacted(path, artifact, document, plan, style="marker")

    assert eval_module.highlight_overlap_count(plan, path, (artifact,)) == 0


def test_highlight_overlap_count_detects_a_widened_region_over_a_neighbour(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ловит саму метрику, а не только геометрию: если пересчитанный
    ``label_region`` (пусть даже намеренно испорченный — воспроизводит
    старый безусловный ``+2pt``) пересекает живой символ выходного файла,
    ``highlight_overlap_count`` обязана увидеть это, а не промолчать."""
    path = _make_pdf_date_with_zero_gap_neighbour(tmp_path)
    document = ingest_pdf(path)
    entity = _entity_for_bare_text_m5(document, "08.09.2026№158-ПК", "08.09.2026")
    plan = _plan(document, [entity])
    artifact = tmp_path / "masked_highlight.pdf"
    render_pdf_redacted(path, artifact, document, plan, style="marker")

    ref = plan.replacements[0].ref
    real_geometry = compute_label_geometry(path, plan)
    region, text, size = real_geometry[ref]
    # Центрированный маркер при расширении только справа сдвинулся бы в
    # черновой реконструкции на 1pt и мог бы ложно «съесть» символ соседа.
    # Расширяем поле симметрично: это по-прежнему намеренно испорченная
    # подсветка над «№», но позиция настоящего маркера остаётся той же.
    widened_region = PdfRegion(
        page=region.page, x0=region.x0 - 2.0, y0=region.y0, x1=region.x1 + 2.0, y1=region.y1
    )
    monkeypatch.setattr(
        pdf_render_module,
        "compute_label_geometry",
        lambda *_a, **_k: {ref: (widened_region, text, size)},
    )

    assert eval_module.highlight_overlap_count(plan, path, (artifact,)) > 0
