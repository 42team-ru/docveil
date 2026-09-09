"""Части контейнера (docx/pdf/xlsx) для поиска утечек Validate (T1.8, шаг 8).

Побайтового поиска по частям контейнера недостаточно самого по себе: Word
режет значение сущности по run'ам (`ИНН 36` + `62103003`, см.
`ingest/docx_ingest.py`), и в `word/document.xml` исходная строка целиком
может не встретиться ни разу, хотя человек, открывший файл, прочитает её
как одну строку. Поэтому у каждой части, где это применимо, есть не только
`raw` (для побайтового поиска), но и `text` — извлечённый видимый текст,
который run'ы уже склеивает.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import pymupdf

from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.xlsx_ingest import ingest_xlsx
from masker.model import Document

#: Единственная часть docx, для которой видимый текст берём через полный
#: разбор `ingest_docx` (склеенные run'ы), а не через наивную конкатенацию
#: текстовых узлов XML — см. докстринг модуля.
_DOCUMENT_XML = "word/document.xml"
_XML_NAME_SUFFIXES = (".xml", ".rels")


@dataclass(frozen=True, slots=True)
class DocPart:
    """Одна часть контейнера: имя, сырые байты, извлечённый видимый текст.

    ``text`` — пустая строка для частей, где извлекать нечего (бинарные
    данные вроде картинок) или не для чего (текст не заявлен применимым).
    """

    name: str
    raw: bytes
    text: str


def docx_parts(path: Path) -> list[DocPart]:
    """Вернуть все элементы zip-архива docx, имена отсортированы.

    Сортировка — не косметика, а детерминизм: `zipfile.namelist()` отдаёт
    архивный порядок записи, который не гарантирован между перезаписями
    одного и того же логического содержимого (см. раздел «Детерминизм»
    плана T1.6/T1.8).
    """
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
        raw_by_name = {name: archive.read(name) for name in names}

    document_text = _document_xml_text(path)

    parts: list[DocPart] = []
    for name in names:
        raw = raw_by_name[name]
        if name == _DOCUMENT_XML:
            text = document_text
        elif name.endswith(_XML_NAME_SUFFIXES):
            text = _xml_text_nodes(raw)
        else:
            text = ""
        parts.append(DocPart(name=name, raw=raw, text=text))
    return parts


def _document_xml_text(path: Path) -> str:
    """Видимый текст `word/document.xml` — через `ingest_docx`.

    `ingest_docx` намеренно не заходит во вложенные таблицы, колонтитулы и
    сноски (см. его докстринг) — это ровно то же содержимое, что физически
    лежит в `word/document.xml`, а не во всём контейнере: остальные части
    (`word/header*.xml`, `word/footnotes.xml`, ...) получают текст отдельно,
    наивной конкатенацией текстовых узлов, ниже.
    """
    document = ingest_docx(path)
    return "\n".join(segment.text for segment in document.segments)


def _xml_text_nodes(raw: bytes) -> str:
    """Конкатенация текстовых узлов произвольного XML-фрагмента docx.

    Годится для `docProps/*`, `word/header*.xml`, `word/footnotes.xml` и
    так далее — везде, где не нужна склейка по run'ам, а нужен весь видимый
    текст части. Часть, которая не парсится как XML (не должно случаться
    для файлов с суффиксом `.xml`/`.rels`, но защищаемся от повреждённого
    архива), даёт пустой текст, а не падение.
    """
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return ""
    return "".join(node.text for node in root.iter() if node.text)


def pdf_parts(path: Path) -> list[DocPart]:
    """Вернуть текстовый слой PDF постранично плюс часть ``metadata``.

    Части страниц называются ``"page N"`` (нумерация с 1 — так же, как
    ``Anchor.label`` для абзацев докса, "человеческая", не индекс массива).
    Часть ``metadata`` объединяет словарь ``doc.metadata`` (autor, title,
    ...) и XMP-метаданные (``doc.get_xml_metadata()`` — то же содержимое,
    на которое указывает ``doc.xref_xml_metadata()``, но без ручного
    разбора xref-потока).
    """
    doc = pymupdf.open(str(path))
    parts: list[DocPart] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        text = page.get_text()
        parts.append(DocPart(name=f"page {page_index + 1}", raw=text.encode("utf-8"), text=text))

    metadata_text = "\n".join(
        f"{key}: {value}" for key, value in sorted(doc.metadata.items()) if value
    )
    xmp_text = doc.get_xml_metadata()
    combined_text = "\n".join(part for part in (metadata_text, xmp_text) if part)
    parts.append(DocPart(name="metadata", raw=combined_text.encode("utf-8"), text=combined_text))
    doc.close()
    return parts


def xlsx_parts(path: Path) -> list[DocPart]:
    """Вернуть все XML-части XLSX, где могут остаться данные пользователя.

    Проверяются не только листы и ``sharedStrings.xml``, но весь XML
    контейнера: кэш формулы хранится в ``xl/worksheets/*.xml``, а значения
    могут оказаться также в ``calcChain.xml``, связях и пользовательских
    свойствах. Бинарные части (картинки, шрифты) текста не содержат и не
    участвуют в поиске.
    """
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(_XML_NAME_SUFFIXES))
        raw_by_name = {name: archive.read(name) for name in names}

    worksheet_text = _xlsx_worksheet_text(raw_by_name, ingest_xlsx(path))
    parts: list[DocPart] = []
    for name in names:
        raw = raw_by_name[name]
        # Ячейки читаются тем же ingest, что и основным графом: это находит
        # отображаемое значение, даже если XML разрезал его на несколько узлов.
        text = worksheet_text.get(name, _xml_text_nodes(raw))
        parts.append(DocPart(name=name, raw=raw, text=text))
    return parts


def _xlsx_worksheet_text(raw_by_name: dict[str, bytes], document: Document) -> dict[str, str]:
    """Сопоставить XML листа с текстом его сегментов.

    Нельзя подставлять весь ``Document`` для каждого ``sheet*.xml``: это
    удваивает видимые маркеры в многостраничной книге и искажает метрику
    ``duplicate_markers``. Связь ``sheet name → XML part`` читаем из
    ``workbook.xml`` и его relationships, а не предполагаем ``sheet1.xml``:
    Excel вправе назначить файлу листа другое имя.
    """
    workbook_xml = raw_by_name.get("xl/workbook.xml")
    relationships_xml = raw_by_name.get("xl/_rels/workbook.xml.rels")
    if workbook_xml is None or relationships_xml is None:
        return {}
    try:
        workbook = ElementTree.fromstring(workbook_xml)
        relationships = ElementTree.fromstring(relationships_xml)
    except ElementTree.ParseError:
        return {}

    relationship_targets: dict[str, str] = {}
    for relationship in relationships:
        target = relationship.attrib.get("Target")
        identifier = relationship.attrib.get("Id")
        if not target or not identifier:
            continue
        relationship_targets[identifier] = (
            target.lstrip("/") if target.startswith("/") else "xl/" + target
        )
    worksheet_by_name: dict[str, str] = {}
    relationship_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in workbook.iter():
        if not sheet.tag.endswith("}sheet"):
            continue
        sheet_name = sheet.attrib.get("name")
        target = relationship_targets.get(sheet.attrib.get(relationship_id, ""))
        if sheet_name and target:
            worksheet_by_name[sheet_name] = target

    text_by_part: dict[str, list[str]] = {}
    for segment in document.segments:
        locator = segment.anchor.locator
        if len(locator) != 4 or locator[0] != "cell" or not isinstance(locator[1], str):
            continue
        target = worksheet_by_name.get(locator[1])
        if target:
            text_by_part.setdefault(target, []).append(segment.text)
    return {name: "\n".join(text) for name, text in text_by_part.items()}
