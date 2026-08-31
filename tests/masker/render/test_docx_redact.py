"""Тесты docx_redact: настоящее редактирование DOCX."""

from __future__ import annotations

import pathlib
import stat
import zipfile

import pytest
from docx import Document as open_docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from masker.ingest.docx_ingest import ingest_docx
from masker.model import Entity, EntityType, Source
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


def _entity_for(document, text: str, etype: EntityType) -> Entity:
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


# ── marker style ──────────────────────────────────────────────────────────────


def test_entity_text_removed_from_paragraph(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, [entity])
    doc = open_docx(str(dest))
    texts = [p.text for p in doc.paragraphs]
    assert all(_INN not in t for t in texts)


def test_marker_appears_in_marker_style(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, [entity], style="marker")
    doc = open_docx(str(dest))
    texts = " ".join(p.text for p in doc.paragraphs)
    assert "[INN]" in texts


def test_marker_style_shading_applied(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, [entity], style="marker")
    doc = open_docx(str(dest))
    for para in doc.paragraphs:
        for run in para.runs:
            if "[INN]" in run.text:
                shd = run._r.find(f".//{qn('w:rPr')}/{qn('w:shd')}")
                if shd is None:
                    shd = run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
                assert shd is not None
                assert shd.get(qn("w:fill")).upper() == "E8E8E8"
                return
    pytest.fail("маркер [INN] не найден среди runs")


# ── blackbox style ────────────────────────────────────────────────────────────


def test_blackbox_original_text_absent(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, [entity], style="blackbox")
    doc = open_docx(str(dest))
    assert all(_INN not in p.text for p in doc.paragraphs)


def test_blackbox_text_absent_from_xml(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, [entity], style="blackbox")
    with zipfile.ZipFile(dest) as z:
        xml = z.read("word/document.xml").decode()
    assert _INN not in xml


def test_blackbox_black_shading_applied(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    render_docx_redacted(src, dest, document, [entity], style="blackbox")
    doc = open_docx(str(dest))
    for para in doc.paragraphs:
        for run in para.runs:
            if "[INN]" in run.text:
                shd = run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
                assert shd is not None
                assert shd.get(qn("w:fill")).upper() == "000000"
                assert run.font.color.rgb == RGBColor(0, 0, 0)
                return
    pytest.fail("маркер [INN] не найден среди runs")


# ── метаданные и permissions ──────────────────────────────────────────────────


def test_metadata_cleared(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    render_docx_redacted(src, dest, document, [])
    doc = open_docx(str(dest))
    assert doc.core_properties.author == ""


def test_permissions(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    render_docx_redacted(src, dest, document, [])
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
    render_docx_redacted(src, dest, document, [entity])  # не должен бросать


def test_invalid_style_raises(tmp_path: pathlib.Path) -> None:
    src = _make_docx(tmp_path)
    dest = tmp_path / "redacted.docx"
    document = ingest_docx(src)
    with pytest.raises(ValueError):
        render_docx_redacted(src, dest, document, [], style="unknown")


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
    render_docx_redacted(src, dest, document, [entity])

    result = open_docx(str(dest))
    cell_text = result.tables[0].rows[0].cells[0].paragraphs[0].text
    assert _INN not in cell_text
    assert "[INN]" in cell_text


# ── несколько сущностей ───────────────────────────────────────────────────────


def test_multiple_entities_same_paragraph(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "multi.docx"
    doc = open_docx()
    doc.add_paragraph(f"ИНН {_INN} и ИНН {_INN2}")
    doc.save(str(src))

    document = ingest_docx(src)
    e1 = _entity_for(document, _INN, EntityType.INN)
    e2 = _entity_for(document, _INN2, EntityType.INN)
    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, [e1, e2])

    result = open_docx(str(dest))
    texts = " ".join(p.text for p in result.paragraphs)
    assert _INN not in texts
    assert _INN2 not in texts
    assert texts.count("[INN]") == 2


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
    render_docx_redacted(src, dest, document, [entity])

    result = open_docx(str(dest))
    texts = " ".join(p.text for p in result.paragraphs)
    assert _INN not in texts
    assert texts.count("[INN]") == 1
