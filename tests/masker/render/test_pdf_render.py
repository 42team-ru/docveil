"""Тесты pdf_render: preview (highlight) и redacted (настоящее удаление) через `MaskPlan`."""

from __future__ import annotations

import pathlib
import stat

import pymupdf
import pytest

from masker.ingest.pdf_ingest import ingest_pdf, page_chars
from masker.mask.agent import PlanAgent
from masker.model import (
    Anchor,
    Document,
    Entity,
    EntityType,
    MaskPlan,
    Profile,
    ProfileMember,
    Replacement,
    Source,
)
from masker.refs import EntityIndex
from masker.render.pdf_render import (
    MarkerDegradation,
    MarkerDoesNotFitError,
    _entity_rects,
    _insert_marker_ladder,
    render_pdf_preview,
    render_pdf_redacted,
)

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


def test_pdf_marker_from_plan(tmp_path: pathlib.Path) -> None:
    """Ради этого шага всё затевалось: в PDF тоже маркер с ролью, а не
    латинский тип."""
    src = _make_pdf_with_inn(tmp_path)
    dest = tmp_path / "redacted.pdf"
    document = ingest_pdf(src)
    entity = _entity_for_doc(document, _INN, EntityType.INN)
    index = EntityIndex([entity])
    profile = _profile_for("ПОСТАВЩИК", [entity], index)
    render_pdf_redacted(src, dest, document, _plan(document, [entity], profiles=[profile]))
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert "[ПОСТАВЩИК-ИНН]" in text
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
    assert outcome.degradations == ()


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
    assert outcome.degradations == ()
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
    render_pdf_redacted(src, dest, document, _plan(document, [entity]))
    doc = pymupdf.open(str(dest))
    text = doc[0].get_text()
    doc.close()
    assert text.count("[ФИО]") == 1, text


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


# ── лестница отступления маркера (план T2.2.1, пачка 5, решение заказчика) ────


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
    try:
        with pytest.raises(MarkerDoesNotFitError):
            _insert_marker_ladder(page, font, degenerate, degenerate, _org_replacement())
    finally:
        doc.close()


def test_pdf_marker_degrades_to_type_label_when_full_marker_does_not_fit(
    tmp_path: pathlib.Path,
) -> None:
    """Не влез полный маркер, но влезла короткая метка типа — деградация,
    не падение; факт спуска возвращается для отчёта человеку."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    try:
        # 20pt: полный маркер (мин. ширина ~31pt на 2pt шрифте) не влезает
        # ни при одном размере, короткая метка «ОРГАНИЗАЦИЯ» (~15pt на 2pt) — влезает.
        narrow = pymupdf.Rect(72, 100, 92, 115)
        replacement = _org_replacement()
        degradation = _insert_marker_ladder(page, font, narrow, narrow, replacement)
    finally:
        doc.close()
    assert degradation == MarkerDegradation(
        page=0, entity_type="org_name", marker=replacement.marker, shown_as="type_label"
    )


def test_pdf_marker_degrades_to_blank_when_nothing_fits(tmp_path: pathlib.Path) -> None:
    """Не влезла даже короткая метка — пустой прямоугольник без текста,
    исходный текст всё равно удалён, падения по-прежнему нет."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    try:
        # 10pt: даже метка «ОРГАНИЗАЦИЯ» (мин. ширина ~15pt) не влезает.
        tiny = pymupdf.Rect(72, 100, 82, 115)
        replacement = _org_replacement()
        degradation = _insert_marker_ladder(page, font, tiny, tiny, replacement)
    finally:
        doc.close()
    assert degradation == MarkerDegradation(
        page=0, entity_type="org_name", marker=replacement.marker, shown_as="blank"
    )


def test_marker_style_ladder_unchanged(tmp_path: pathlib.Path) -> None:
    """Регрессия: откат `blackbox` (план T2.2.2, шаг 1) не задевает лестницу
    `marker` — полный маркер по-прежнему первая и лучшая ступень."""
    src = _make_pdf_with_inn(tmp_path)
    doc = pymupdf.open(str(src))
    page = doc[0]
    font = pymupdf.Font(fontfile=_FONT)
    try:
        wide = pymupdf.Rect(72, 100, 300, 115)  # полный маркер сюда помещается
        replacement = _org_replacement()
        degradation = _insert_marker_ladder(page, font, wide, wide, replacement)
    finally:
        doc.close()
    assert degradation is None


def test_render_pdf_redacted_returns_degradation_report(tmp_path: pathlib.Path) -> None:
    """`render_pdf_redacted` отдаёт список деградаций — план T2.2.1, пачка 5:
    «каждый спуск на ступень ниже фиксируется в отчёте»."""
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
    assert len(outcome.degradations) == 1, outcome.degradations
    assert outcome.degradations[0].shown_as in ("type_label", "blank")
    assert outcome.degradations[0].entity_type == "org_name"
    assert outcome.degradations[0].page == 0


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
