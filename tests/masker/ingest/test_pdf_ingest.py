"""Тесты pdf_ingest: разбор текстового слоя PDF в Document."""

from __future__ import annotations

import hashlib
import pathlib

import pymupdf

from masker.ingest.pdf_ingest import ingest_pdf, page_chars

_FONT = str(
    pathlib.Path(__file__).parent.parent.parent.parent
    / "src"
    / "masker"
    / "data"
    / "DejaVuSans.ttf"
)


def _make_pdf(tmp_path: pathlib.Path, pages: list[list[str]]) -> pathlib.Path:
    """Создать PDF с заданным текстом; pages[i] — список строк на странице i.

    Каждая строка — отдельный вызов ``insert_text`` и, эмпирически
    проверено, отдельный текстовый блок PyMuPDF (нет общей раскладки
    абзаца) — годится для тестов, которым нужен один блок = одна строка.
    """
    path = tmp_path / "test.pdf"
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        page.insert_font(fontname="dvu", fontfile=_FONT)
        y = 72.0
        for line in lines:
            page.insert_text((72, y), line, fontname="dvu", fontsize=12)
            y += 20
    doc.save(str(path))
    doc.close()
    return path


def _make_pdf_block(tmp_path: pathlib.Path, lines: list[str]) -> pathlib.Path:
    """Создать однострaничный PDF, где все строки лежат в ОДНОМ текстовом блоке.

    ``insert_textbox`` с ``\\n`` внутри строки — единственный надёжный
    способ получить многострочный блок PyMuPDF в тесте (план T2.2.1,
    шаг 8): реальные документы дают такие блоки после конвертации
    Word/LibreOffice → PDF, а низкоуровневый ``insert_text`` — нет.
    """
    path = tmp_path / "block.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=_FONT)
    rect = pymupdf.Rect(72, 72, 500, 700)
    page.insert_textbox(rect, "\n".join(lines), fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_segment_count_equals_nonempty_lines(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Строка 1", "", "Строка 2", "   ", "Строка 3"]])
    doc = ingest_pdf(path)
    assert len(doc.segments) == 3


def test_order_is_dense_from_zero(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А", "Б", "В"]])
    doc = ingest_pdf(path)
    assert [s.order for s in doc.segments] == list(range(len(doc.segments)))


def test_anchor_fmt_is_pdf(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Текст"]])
    doc = ingest_pdf(path)
    assert all(s.anchor.fmt == "pdf" for s in doc.segments)


def test_anchor_locator_structure(tmp_path: pathlib.Path) -> None:
    """Якорь PDF — символьный диапазон, не bbox (план T2.2.1, шаг 8)."""
    path = _make_pdf(tmp_path, [["Текст"]])
    doc = ingest_pdf(path)
    loc = doc.segments[0].anchor.locator
    assert loc[0] == "page"
    assert len(loc) == 4
    _, page_num, char_start, char_end = loc
    assert isinstance(page_num, int)
    assert isinstance(char_start, int)
    assert isinstance(char_end, int)
    assert char_start < char_end


def test_blank_lines_are_skipped(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["", "   ", "\t"]])
    doc = ingest_pdf(path)
    assert len(doc.segments) == 0


def test_image_blocks_are_skipped(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "img.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # Вставить прямоугольник — это vector drawing block, не text block (type!=0)
    page.draw_rect(pymupdf.Rect(10, 10, 100, 100), color=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    result = ingest_pdf(path)
    assert len(result.segments) == 0


def test_multipage_order(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А"], ["Б"], ["В"]])
    doc = ingest_pdf(path)
    texts = [s.text.strip() for s in sorted(doc.segments, key=lambda s: s.order)]
    assert texts == ["А", "Б", "В"]


def test_multipage_page_nums_in_locators(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А"], ["Б"]])
    doc = ingest_pdf(path)
    page_nums = [int(s.anchor.locator[1]) for s in doc.segments]
    assert page_nums == [0, 1]


def test_meta_extraction(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "meta.pdf"
    src = pymupdf.open()
    src.new_page()
    src.set_metadata({"author": "Иван Иванов", "title": "Тест"})
    src.save(str(path))
    src.close()
    doc = ingest_pdf(path)
    assert doc.meta.get("author") == "Иван Иванов"
    assert doc.meta.get("title") == "Тест"


def test_empty_meta_gives_empty_dict(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Текст"]])
    doc = ingest_pdf(path)
    assert doc.meta == {}


def test_pdf_ingest_is_deterministic(tmp_path: pathlib.Path) -> None:
    """Два прогона ingest дают одинаковый список ``(order, anchor, text)``."""
    path = _make_pdf(tmp_path, [["ИНН 3662103003", "Петров Иван"]])
    doc1 = ingest_pdf(path)
    doc2 = ingest_pdf(path)
    locs1 = [(s.order, s.anchor.locator, s.text) for s in doc1.segments]
    locs2 = [(s.order, s.anchor.locator, s.text) for s in doc2.segments]
    assert locs1 == locs2


def test_source_not_modified(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["Текст"]])
    before = _sha256(path)
    ingest_pdf(path)
    assert _sha256(path) == before


def test_label_contains_page_number(tmp_path: pathlib.Path) -> None:
    path = _make_pdf(tmp_path, [["А"], ["Б"]])
    doc = ingest_pdf(path)
    labels = [s.anchor.label for s in doc.segments]
    assert "стр. 1" in labels
    assert "стр. 2" in labels


# ---------------------------------------------------------------------------
# Сегмент = блок, якорь = символьный диапазон (план T2.2.1, шаг 8, Д3).
# ---------------------------------------------------------------------------


def test_page_chars_len_matches_text(tmp_path: pathlib.Path) -> None:
    """Число боксов равно длине текста — иначе срез якоря бьёт мимо."""
    path = _make_pdf_block(tmp_path, ["Первая строка", "Вторая строка подлиннее"])
    doc = pymupdf.open(str(path))
    chars = page_chars(doc[0])
    doc.close()
    assert len(chars.text) == len(chars.boxes)


def test_page_text_equals_concatenation_of_segments(tmp_path: pathlib.Path) -> None:
    """Текст страницы посимвольно совпадает с конкатенацией сегментов по
    срезам якорей — иначе рендер (шаг 9) считает смещение не в тот глиф."""
    path = _make_pdf_block(
        tmp_path, ["и Общество с", "Ограниченной Ответственностью «Вектор»", "в лице Иванова"]
    )
    result = ingest_pdf(path)
    doc = pymupdf.open(str(path))
    chars = page_chars(doc[0])
    doc.close()
    for segment in result.segments:
        _, _, char_start, char_end = segment.anchor.locator
        assert chars.text[char_start:char_end] == segment.text


# ---------------------------------------------------------------------------
# `page_chars` отдаёт номер строки каждому символу (план T2.2.2, шаг 2).
# ---------------------------------------------------------------------------


def test_page_chars_lengths_agree(tmp_path: pathlib.Path) -> None:
    """Инвариант ``PageChars``: длины ``text``, ``boxes`` и ``line_ids`` равны."""
    path = _make_pdf_block(tmp_path, ["Первая строка", "Вторая строка подлиннее"])
    doc = pymupdf.open(str(path))
    chars = page_chars(doc[0])
    doc.close()
    assert len(chars.text) == len(chars.boxes) == len(chars.line_ids)


def test_page_chars_line_id_changes_on_line_break(tmp_path: pathlib.Path) -> None:
    """Все символы `Мокиной Светланы Владимировны` — один и тот же
    ``line_id``, а первый символ `Ограниченной` следующей строки —
    ``line_id + 1`` (план T2.2.2, шаг 2, приёмка)."""
    path = _make_pdf_block(
        tmp_path,
        ["и Мокиной Светланы Владимировны, Общество с", "Ограниченной Ответственностью «Вектор»"],
    )
    doc = pymupdf.open(str(path))
    chars = page_chars(doc[0])
    doc.close()

    start = chars.text.index("Мокиной Светланы Владимировны")
    end = start + len("Мокиной Светланы Владимировны")
    line_ids_of_phrase = set(chars.line_ids[start:end])
    assert len(line_ids_of_phrase) == 1, line_ids_of_phrase
    phrase_line_id = next(iter(line_ids_of_phrase))

    next_line_start = chars.text.index("Ограниченной")
    assert chars.line_ids[next_line_start] == phrase_line_id + 1


def test_page_chars_line_ids_are_monotonic(tmp_path: pathlib.Path) -> None:
    """Номер строки не убывает по ходу текста и не сбрасывается на границе
    блока — счётчик сквозной по странице (план T2.2.2, шаг 2)."""
    path = _make_pdf_block(tmp_path, ["Первая строка", "Вторая строка", "Третья строка"])
    doc = pymupdf.open(str(path))
    chars = page_chars(doc[0])
    doc.close()
    assert list(chars.line_ids) == sorted(chars.line_ids)


def test_page_chars_is_deterministic(tmp_path: pathlib.Path) -> None:
    """Два вызова подряд дают идентичный результат (план T2.2.2, шаг 2, приёмка)."""
    path = _make_pdf_block(tmp_path, ["и Общество с", "Ограниченной Ответственностью «Вектор»"])
    doc = pymupdf.open(str(path))
    first = page_chars(doc[0])
    second = page_chars(doc[0])
    doc.close()
    assert first == second


def test_pdf_segment_covers_line_break_inside_org_name(tmp_path: pathlib.Path) -> None:
    """Оргформа, разорванная переносом строки, попадает в один сегмент (Д3):
    сегодня ``Entity`` не может пересечь границу сегмента, значит без этого
    шага «Общество с» и «Ограниченной Ответственностью «...»» остаются
    двумя разными сегментами навсегда."""
    path = _make_pdf_block(
        tmp_path, ["и Общество с", "Ограниченной Ответственностью «Вектор»", "в лице Иванова"]
    )
    doc = ingest_pdf(path)
    assert any(
        "Общество с Ограниченной Ответственностью «Вектор»" in " ".join(s.text.split())
        for s in doc.segments
    )


def test_pdf_segment_covers_line_break_inside_person(tmp_path: pathlib.Path) -> None:
    """Тот же перенос, но внутри ФИО (реальный обрыв на странице 1
    `contract_pdf_02_school.pdf`: «Зубрицкой Татьяны» / «Ивановны»)."""
    path = _make_pdf_block(
        tmp_path, ["в лице Директора Зубрицкой Татьяны", "Ивановны, действующего на основании"]
    )
    doc = ingest_pdf(path)
    assert any("Зубрицкой Татьяны Ивановны" in " ".join(s.text.split()) for s in doc.segments)


def test_block_is_split_before_contract_clause_number(tmp_path: pathlib.Path) -> None:
    """Риск Р3: блок реквизитов на десятки строк не должен склеивать обе
    стороны договора в один сегмент/профиль — режем перед номером пункта
    (``1.``, ``2.3.``), а не по подобранной длине."""
    path = _make_pdf_block(
        tmp_path,
        [
            "Реквизиты Заказчика: ИНН 6663057404",
            "2. Реквизиты Исполнителя: ИНН 6686164522",
        ],
    )
    doc = ingest_pdf(path)
    assert len(doc.segments) == 2
    assert doc.segments[0].text.strip().startswith("Реквизиты Заказчика")
    assert doc.segments[1].text.strip().startswith("2. Реквизиты Исполнителя")


def test_block_is_not_split_on_bare_number_mid_line(tmp_path: pathlib.Path) -> None:
    """Номер посреди строки (не начало пункта) блок не режет."""
    path = _make_pdf_block(tmp_path, ["Дом 12 по улице Ленина", "далее по тексту"])
    doc = ingest_pdf(path)
    assert len(doc.segments) == 1
