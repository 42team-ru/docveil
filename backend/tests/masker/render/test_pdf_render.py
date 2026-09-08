"""Тесты pdf_render: preview (highlight) и redacted (настоящее удаление) через `MaskPlan`."""

from __future__ import annotations

import pathlib
import stat

import pymupdf
import pytest

from masker.ingest.pdf_ingest import PageChars, ingest_pdf, page_chars
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
    MarkerDoesNotFitError,
    _entity_rects,
    _quantize_erase_rect,
    _try_ladder,
    compute_erase_geometry,
    render_pdf_preview,
    render_pdf_redacted,
)
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
    латинский тип.

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
