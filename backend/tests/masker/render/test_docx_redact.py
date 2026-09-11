"""Тесты docx_redact: настоящее редактирование DOCX через `MaskPlan`."""

from __future__ import annotations

import pathlib
import re
import stat
import zipfile

import pytest
from docx import Document as open_docx
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from masker.ingest.docx_ingest import ingest_docx
from masker.mask.agent import PlanAgent
from masker.model import (
    Anchor,
    Document,
    Entity,
    EntityType,
    MaskPlan,
    Profile,
    ProfileMember,
    Source,
)
from masker.refs import EntityIndex
from masker.render.docx_redact import render_docx_redacted

_INN = "3662103003"
_AUTHOR = "Тест Автор"
_INN2 = "7707083893"


def _make_docx(tmp_path: pathlib.Path, text: str = f"ИНН {_INN}") -> pathlib.Path:
    path = tmp_path / "source.docx"
    doc = open_docx()
    doc.core_properties.author = _AUTHOR
    doc.add_paragraph(text)
    doc.save(str(path))
    return path


def _entity_for(document: Document, text: str, etype: EntityType) -> Entity:
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
    """План без фильтров и решений — то, что реально строит простой CLI без
    ``--profile``: единственный источник маркеров для рендера (T1.6)."""
    return PlanAgent().plan(document, entities, profiles=profiles)


def _profile_for(marker_label: str, members: list[Entity], index: EntityIndex) -> Profile:
    """Профиль для теста: `PlanAgent` смотрит только на `marker_label` и
    `ProfileMember.ref` — сам якорь профиля рендеру не нужен."""
    return Profile(
        id="P1",
        members=[
            ProfileMember(
                entity=entity, anchor=Anchor(fmt="docx", locator=()), ref=index.ref(entity)
            )
            for entity in members
        ],
        marker_label=marker_label,
    )


# ── marker style ──────────────────────────────────────────────────────────────


def test_entity_text_removed_from_paragraph(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, _plan(document, [entity]))
    doc = open_docx(str(dest))
    texts = [p.text for p in doc.paragraphs]
    assert all(_INN not in t for t in texts)


def test_marker_appears_in_marker_style(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, _plan(document, [entity]), style="marker")
    doc = open_docx(str(dest))
    texts = " ".join(p.text for p in doc.paragraphs)
    assert "[ИНН]" in texts


def test_marker_style_shading_applied(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, _plan(document, [entity]), style="marker")
    doc = open_docx(str(dest))
    for para in doc.paragraphs:
        for run in para.runs:
            if "[ИНН]" in run.text:
                shd = run._r.find(f".//{qn('w:rPr')}/{qn('w:shd')}")
                if shd is None:
                    shd = run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
                assert shd is not None
                assert shd.get(qn("w:fill")).upper() == "FFDE66"
                return
    pytest.fail("маркер [ИНН] не найден среди runs")


def test_marker_style_accepts_custom_background_and_none(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)

    colored = tmp_path / "colored.docx"
    render_docx_redacted(
        src, colored, document, _plan(document, [entity]), highlight_background="#12ab34"
    )
    colored_doc = open_docx(str(colored))
    colored_run = next(
        run for paragraph in colored_doc.paragraphs for run in paragraph.runs if "[ИНН]" in run.text
    )
    colored_shading = colored_run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
    assert colored_shading is not None
    assert colored_shading.get(qn("w:fill")) == "12AB34"

    without_background = tmp_path / "without-background.docx"
    render_docx_redacted(
        src, without_background, document, _plan(document, [entity]), highlight_background=None
    )
    plain_doc = open_docx(str(without_background))
    plain_run = next(
        run for paragraph in plain_doc.paragraphs for run in paragraph.runs if "[ИНН]" in run.text
    )
    assert plain_run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}") is None


# ── маркер плана с ролью (T1.6) ────────────────────────────────────────────────


def test_marker_from_plan_is_written_into_docx(tmp_path: pathlib.Path) -> None:
    """Ради этого шага всё затевалось: маркер с ролью, а не латинский тип."""
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    index = EntityIndex([entity])
    profile = _profile_for("ПОСТАВЩИК", [entity], index)
    render_docx_redacted(src, dest, document, _plan(document, [entity], profiles=[profile]))
    doc = open_docx(str(dest))
    texts = " ".join(p.text for p in doc.paragraphs)
    assert "[ПОСТАВЩИК-ИНН-1]" in texts
    assert "[INN]" not in texts
    assert _INN not in texts


def test_marker_longer_than_source_does_not_pad(tmp_path: pathlib.Path) -> None:
    """ИНН — 10 знаков, маркер с ролью — длиннее исходного значения:
    паддинг не должен уйти в минус, а текст маркера не должен обрезаться."""
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    assert len(_INN) == 10
    index = EntityIndex([entity])
    profile = _profile_for("ПОСТАВЩИК", [entity], index)
    plan = _plan(document, [entity], profiles=[profile])
    marker = plan.replacements[0].marker
    assert marker == "[ПОСТАВЩИК-ИНН-1]"
    assert len(marker) > len(_INN)
    render_docx_redacted(src, dest, document, plan)
    doc = open_docx(str(dest))
    texts = " ".join(p.text for p in doc.paragraphs)
    assert "[ПОСТАВЩИК-ИНН-1]" in texts
    # маркер не обрезан padding'ом с отрицательной длиной
    assert texts.count("[ПОСТАВЩИК-ИНН-1]") == 1


def test_blackbox_style_with_role_marker_removes_original_text(tmp_path: pathlib.Path) -> None:
    """Комбинация, которую специально стоит проверить: маркер с ролью
    длиннее исходного значения (паддинг не добавляется) в blackbox-стиле —
    заливка не должна разъехаться, а исходный текст обязан пропасть из XML
    целиком, а не только визуально."""
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    index = EntityIndex([entity])
    profile = _profile_for("ПОСТАВЩИК", [entity], index)
    plan = _plan(document, [entity], profiles=[profile])
    render_docx_redacted(src, dest, document, plan, style="blackbox")
    with zipfile.ZipFile(dest) as z:
        xml = z.read("word/document.xml").decode()
    assert _INN not in xml
    doc = open_docx(str(dest))
    for para in doc.paragraphs:
        for run in para.runs:
            if "[ПОСТАВЩИК-ИНН-1]" in run.text:
                shd = run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
                assert shd is not None
                assert shd.get(qn("w:fill")).upper() == "000000"
                return
    pytest.fail("маркер [ПОСТАВЩИК-ИНН-1] не найден среди runs")


def test_blackbox_marker_has_no_dot_padding(tmp_path: pathlib.Path) -> None:
    """М2: паддинг символами убран как способ сохранения ширины — маркер
    короче исходного значения не должен обрастать точками ни в каком стиле.
    Раньше здесь стоял ``test_blackbox_marker_padding_uses_dots``, проверявший
    ровно обратное: то, что паддинг точками есть. Переписан, потому что
    продуктовое решение М2 явно отказывается от символьного паддинга как
    способа сохранения ширины (пиксельное совпадение вёрстки не обещается,
    для точной геометрии — PDF)."""
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = _plan(document, [entity])
    assert len(plan.replacements[0].marker) < len(_INN)
    render_docx_redacted(src, dest, document, plan, style="blackbox")
    doc = open_docx(str(dest))
    for para in doc.paragraphs:
        for run in para.runs:
            if "[ИНН]" in run.text:
                assert run.text == "[ИНН]"
                assert "." not in run.text
                return
    pytest.fail("маркер [ИНН] не найден среди runs")


def test_marker_style_no_padding_tail(tmp_path: pathlib.Path) -> None:
    """М2: маркер короче исходного значения не должен получать хвост из
    NBSP/пробелов — раньше `_NBSP` на деле был обычным U+0020, который Word
    схлопывает, а сам паддинг всё равно не давал совпадения ширины."""
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = _plan(document, [entity])
    marker = plan.replacements[0].marker
    assert len(marker) < len(_INN)
    render_docx_redacted(src, dest, document, plan, style="marker")
    doc = open_docx(str(dest))
    for para in doc.paragraphs:
        for run in para.runs:
            if marker in run.text:
                assert run.text == marker
                return
    pytest.fail(f"маркер {marker!r} не найден среди runs")


def test_marker_run_text_has_no_padding_in_xml(tmp_path: pathlib.Path) -> None:
    """Приёмка М2: искусственных хвостов из пробелов/точек в выходном XML
    нет — проверяется распаковкой docx, а не только объектной моделью."""
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = _plan(document, [entity])
    marker = plan.replacements[0].marker
    render_docx_redacted(src, dest, document, plan, style="marker")
    with zipfile.ZipFile(dest) as z:
        xml = z.read("word/document.xml").decode()
    assert re.search(rf"<w:t[^>]*>{re.escape(marker)}</w:t>", xml) is not None
    assert "....." not in xml


# ── blackbox style ────────────────────────────────────────────────────────────


def test_blackbox_original_text_absent(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    doc = open_docx(str(dest))
    assert all(_INN not in p.text for p in doc.paragraphs)


def test_blackbox_text_absent_from_xml(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    with zipfile.ZipFile(dest) as z:
        xml = z.read("word/document.xml").decode()
    assert _INN not in xml


def test_blackbox_black_shading_applied(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, _plan(document, [entity]), style="blackbox")
    doc = open_docx(str(dest))
    for para in doc.paragraphs:
        for run in para.runs:
            if "[ИНН]" in run.text:
                shd = run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
                assert shd is not None
                assert shd.get(qn("w:fill")).upper() == "000000"
                assert run.font.color.rgb == RGBColor(0, 0, 0)
                return
    pytest.fail("маркер [ИНН] не найден среди runs")


# ── метаданные и permissions ──────────────────────────────────────────────────


def test_metadata_cleared(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    render_docx_redacted(src, dest, document, _plan(document, []))
    doc = open_docx(str(dest))
    assert doc.core_properties.author == ""


def test_permissions(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    render_docx_redacted(src, dest, document, _plan(document, []))
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


# ── устойчивость ──────────────────────────────────────────────────────────────


def test_entity_not_found_graceful(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    seg = document.segments[0]
    entity = Entity(
        type=EntityType.INN,
        text="0000000000",
        segment_order=seg.order,
        start=0,
        end=10,
        source=Source.RULE,
    )
    render_docx_redacted(src, dest, document, _plan(document, [entity]))  # не должен бросать


def test_invalid_style_raises(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    with pytest.raises(ValueError):
        render_docx_redacted(src, dest, document, _plan(document, []), style="unknown")


# ── таблицы ──────────────────────────────────────────────────────────────────


def test_table_cell_entity_redacted(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "table.docx"
    doc = open_docx()
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].paragraphs[0].add_run(_INN)
    table.rows[0].cells[1].paragraphs[0].add_run("другой текст")
    doc.save(str(src))

    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, _plan(document, [entity]))

    result = open_docx(str(dest))
    cell_text = result.tables[0].rows[0].cells[0].paragraphs[0].text
    assert _INN not in cell_text
    assert "[ИНН]" in cell_text


# ── несколько сущностей ───────────────────────────────────────────────────────


def test_multiple_entities_same_paragraph(tmp_path: pathlib.Path) -> None:
    """Два разных ИНН в одном абзаце дают два разных пронумерованных
    маркера: одинаковый текст `[INN]` для разных значений (как было до
    T1.6) — это как раз тот дефект согласованности, который план чинит."""
    src = tmp_path / "multi.docx"
    doc = open_docx()
    doc.add_paragraph(f"ИНН {_INN} и ИНН {_INN2}")
    doc.save(str(src))

    document = ingest_docx(src)
    e1 = _entity_for(document, _INN, EntityType.INN)
    e2 = _entity_for(document, _INN2, EntityType.INN)
    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, _plan(document, [e1, e2]))

    result = open_docx(str(dest))
    texts = " ".join(p.text for p in result.paragraphs)
    assert _INN not in texts
    assert _INN2 not in texts
    assert "[ИНН-1]" in texts
    assert "[ИНН-2]" in texts
    assert texts.count("[ИНН-1]") == 1
    assert texts.count("[ИНН-2]") == 1


# ── сущность пересекает граница run'ов ───────────────────────────────────────


def test_multirun_entity_single_marker(tmp_path: pathlib.Path) -> None:
    """Сущность, разбитая на два run'а, получает ровно один маркер."""
    src = tmp_path / "multirun.docx"
    doc = open_docx()
    para = doc.add_paragraph()
    # Разбить ИНН на два run'а: "366210" + "3003"
    half = len(_INN) // 2
    para.add_run(f"ИНН {_INN[:half]}")
    para.add_run(_INN[half:])
    doc.save(str(src))

    document = ingest_docx(src)
    # Сущность охватывает оба run'а
    seg = document.segments[0]
    start = seg.text.index(_INN)
    entity = Entity(
        type=EntityType.INN,
        text=_INN,
        segment_order=seg.order,
        start=start,
        end=start + len(_INN),
        source=Source.RULE,
        confidence=1.0,
        normalized=_INN,
    )
    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, _plan(document, [entity]))

    result = open_docx(str(dest))
    texts = " ".join(p.text for p in result.paragraphs)
    assert _INN not in texts
    assert texts.count("[ИНН]") == 1


def test_multirun_entity_marker_inherits_dominant_run_style(tmp_path: pathlib.Path) -> None:
    """М2: клонировать стиль надо у run'а с наибольшим перекрытием сущности,
    а не у того, что физически идёт первым. Если бы маркер наследовал
    оформление первого run'а (одна цифра, кегль 6pt), кегль маркера был бы
    6pt — реальный размер большей части ИНН (14pt) был бы потерян."""
    src = tmp_path / "multirun_dominant.docx"
    doc = open_docx()
    para = doc.add_paragraph()
    para.add_run("ИНН ")
    tiny = para.add_run(_INN[0])
    tiny.font.size = Pt(6)
    dominant = para.add_run(_INN[1:])
    dominant.font.size = Pt(14)
    doc.save(str(src))

    document = ingest_docx(src)
    seg = document.segments[0]
    start = seg.text.index(_INN)
    entity = Entity(
        type=EntityType.INN,
        text=_INN,
        segment_order=seg.order,
        start=start,
        end=start + len(_INN),
        source=Source.RULE,
        confidence=1.0,
        normalized=_INN,
    )
    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, _plan(document, [entity]))

    result = open_docx(str(dest))
    for para in result.paragraphs:
        for run in para.runs:
            if "[ИНН]" in run.text:
                assert run.font.size == Pt(14)
                return
    pytest.fail("маркер [ИНН] не найден среди runs")
