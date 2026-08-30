"""Статический HTML-отчёт для визуальной проверки чанков и PII."""

from __future__ import annotations

from html import escape
from itertools import pairwise
from pathlib import Path
from typing import Any

from docx import Document as open_docx
from docx.table import Table
from docx.text.paragraph import Paragraph

_STYLE = """
:root { color-scheme: light; font-family: Inter, Arial, sans-serif; color: #202124; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f7f9; }
header { background: #fff; border-bottom: 1px solid #dfe1e5; padding: 24px 32px; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 32px 48px; }
h1 { margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }
h2 { margin: 28px 0 12px; font-size: 18px; letter-spacing: 0; }
h3 { margin: 0; font-size: 15px; letter-spacing: 0; }
p { margin: 0; }
.muted { color: #5f6368; font-size: 13px; }
.danger { margin-top: 16px; padding: 12px 14px; color: #8a1c1c; background: #fde8e7;
  border-left: 4px solid #c62828; font-weight: 700; }
.summary { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.badge { display: inline-flex; align-items: center; gap: 6px; border: 1px solid #c9cdd2;
  background: #fff; padding: 5px 8px; border-radius: 6px; font-size: 12px; }
.badge strong { font-size: 14px; }
.warning { padding: 10px 12px; background: #fff3cd; border-left: 4px solid #b7791f;
  margin: 8px 0; }
table { width: 100%; border-collapse: collapse; background: #fff; }
th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid #e3e5e8;
  vertical-align: top; font-size: 13px; }
th { color: #4b5056; background: #f0f2f4; font-weight: 700; }
.chunk { margin: 0 0 14px; background: #fff; border: 1px solid #dfe1e5; border-radius: 6px;
  overflow: hidden; }
.chunk-head { display: flex; justify-content: space-between; gap: 12px; padding: 11px 14px;
  background: #f0f2f4; border-bottom: 1px solid #dfe1e5; }
.chunk-text { padding: 16px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere;
  font-family: Georgia, "Times New Roman", serif; font-size: 16px; }
.pii { position: relative; display: inline; padding: 2px 3px; border-radius: 3px;
  border-bottom: 2px solid; }
.pii-label { font-family: Inter, Arial, sans-serif; font-size: 9px; font-weight: 800;
  margin-left: 4px; vertical-align: super; }
.pii-person { background: #ffe1e6; border-color: #c62828; }
.pii-org_name { background: #dceeff; border-color: #1565c0; }
.pii-inn, .pii-kpp, .pii-ogrn { background: #fff0c2; border-color: #a66300; }
.pii-snils, .pii-passport { background: #f3dcff; border-color: #7b1fa2; }
.pii-bank_account, .pii-bik, .pii-bank_name { background: #dcf5e7; border-color: #237a49; }
.pii-email, .pii-phone, .pii-site { background: #d9f3f5; border-color: #087f8c; }
.pii-address, .pii-date { background: #e7e2ff; border-color: #5145a6; }
.pii-contract_number, .pii-money { background: #eceff1; border-color: #546e7a; }
.chunk table { border-top: 1px solid #e3e5e8; }
.type { font-weight: 800; font-size: 11px; text-transform: uppercase; }
.empty { padding: 20px; background: #fff; border: 1px solid #dfe1e5; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 0 0 10px; font-size: 12px; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; }
.legend-swatch { width: 22px; height: 14px; border: 1px solid #d0aa35; background: #fff7cf; }
.document-view { background: #fff; border: 1px solid #dfe1e5; }
.document-line { display: grid; grid-template-columns: 46px minmax(0, 1fr); min-height: 34px;
  border-bottom: 1px solid #eef0f2; }
.line-number { padding: 8px 7px; color: #73777c; background: #f4f5f6; text-align: right;
  font: 11px/1.5 monospace; user-select: none; }
.line-text { padding: 8px 12px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere;
  font-family: Georgia, "Times New Roman", serif; }
.document-heading .line-text { font-weight: 700; }
.chunk-range { background: #fff7cf; box-shadow: inset 0 -2px #d0aa35; }
.document-table { border-top: 3px solid #c62828; border-bottom: 1px solid #dfe1e5;
  padding: 10px 12px 14px; background: #fffafa; }
.document-table-head { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 8px;
  color: #8a1c1c; font-size: 12px; font-weight: 800; }
.table-scroll { overflow-x: auto; }
.document-table table { min-width: 620px; border: 1px solid #e2caca; }
.document-table td { white-space: pre-wrap; font-family: Georgia, "Times New Roman", serif; }
.supplement { margin-top: 12px; padding: 12px; border-left: 4px solid #c62828;
  background: #fff; }
.supplement dt { margin-top: 8px; font-weight: 700; }
.supplement dd { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 700px) {
  header, main { padding-left: 16px; padding-right: 16px; }
  .chunk-head { display: block; }
  .chunk-head .muted { margin-top: 4px; }
  th:nth-child(3), td:nth-child(3) { display: none; }
  .document-line { grid-template-columns: 34px minmax(0, 1fr); }
  .line-text { padding-left: 9px; padding-right: 9px; }
}
"""


def _pii_markup(item: dict[str, Any], text: str) -> str:
    entity_type = str(item["type"])
    title = escape(
        f"{entity_type} · {item['source']} · confidence {float(item['confidence']):.2f}",
        quote=True,
    )
    return (
        f'<mark class="pii pii-{escape(entity_type, quote=True)}" title="{title}">'
        f"{escape(text)}"
        f'<span class="pii-label">{escape(entity_type.upper())}</span></mark>'
    )


def _chunk_markup(chunk: dict[str, Any]) -> str:
    text = str(chunk["text"])
    pieces: list[str] = []
    cursor = 0
    pii_items = sorted(chunk["pii"], key=lambda item: int(item["chunk_start"]))
    for item in pii_items:
        start = int(item["chunk_start"])
        end = int(item["chunk_end"])
        pieces.append(escape(text[cursor:start]))
        pieces.append(_pii_markup(item, text[start:end]))
        cursor = end
    pieces.append(escape(text[cursor:]))
    return "".join(pieces)


def _pii_rows(chunk: dict[str, Any]) -> str:
    rows: list[str] = []
    for item in chunk["pii"]:
        rows.append(
            "<tr>"
            f'<td><span class="type">{escape(str(item["type"]))}</span></td>'
            f"<td>{escape(str(item['text']))}</td>"
            f"<td>{escape(str(item['source']))}</td>"
            f"<td>{float(item['confidence']):.2f}</td>"
            f"<td>{int(item['start'])}:{int(item['end'])}</td>"
            "</tr>"
        )
    return "".join(rows)


def _chunks(report: dict[str, Any]) -> str:
    chunks = report["chunks"]
    if not chunks:
        return '<p class="empty">В обработанной части документа PII не найдены.</p>'
    articles: list[str] = []
    for chunk in chunks:
        anchor = chunk["anchor"]
        articles.append(
            '<article class="chunk">'
            '<div class="chunk-head">'
            f"<h3>{escape(str(chunk['id']))} · {escape(str(anchor['label']))}</h3>"
            f'<p class="muted">segment {int(chunk["segment_order"])} · '
            f"{int(chunk['start'])}:{int(chunk['end'])} · PII {int(chunk['pii_count'])}</p>"
            "</div>"
            f'<div class="chunk-text">{_chunk_markup(chunk)}</div>'
            "<table><thead><tr><th>Тип</th><th>Текст</th><th>Источник</th>"
            f"<th>Confidence</th><th>Спан</th></tr></thead><tbody>{_pii_rows(chunk)}</tbody></table>"
            "</article>"
        )
    return "".join(articles)


def _summary(report: dict[str, Any]) -> str:
    by_type = report["summary"]["by_type"]
    badges = [
        f'<span class="badge"><span>{escape(str(name))}</span><strong>{int(count)}</strong></span>'
        for name, count in by_type.items()
    ]
    return "".join(badges)


def _coverage(report: dict[str, Any]) -> str:
    document = report["document_coverage"]
    rows = [
        ("Основной текст", "да", f"{document['body']['nonempty_paragraphs']} абзацев"),
        (
            "Таблицы",
            "нет",
            f"{document['tables']['count']} таблиц, "
            f"{document['tables']['nonempty_paragraphs']} абзацев",
        ),
        (
            "Колонтитулы",
            "нет",
            f"{document['headers']['parts_with_text']} header, "
            f"{document['footers']['parts_with_text']} footer с текстом",
        ),
        ("Сноски", "нет", "есть текст" if document["footnotes"]["has_text"] else "нет текста"),
        (
            "Метаданные",
            "нет",
            ", ".join(document["metadata"]["present_fields"]) or "пусто",
        ),
    ]
    return "".join(
        f"<tr><td>{escape(name)}</td><td>{processed}</td><td>{escape(details)}</td></tr>"
        for name, processed, details in rows
    )


def _document_paragraph_markup(text: str, chunks: list[dict[str, Any]]) -> str:
    boundaries = {0, len(text)}
    pii_items: list[dict[str, Any]] = []
    for chunk in chunks:
        boundaries.update((int(chunk["start"]), int(chunk["end"])))
        pii_items.extend(chunk["pii"])
        for item in chunk["pii"]:
            boundaries.update((int(item["start"]), int(item["end"])))

    pieces: list[str] = []
    positions = sorted(position for position in boundaries if 0 <= position <= len(text))
    for start, end in pairwise(positions):
        value = text[start:end]
        entity = next(
            (item for item in pii_items if int(item["start"]) <= start and end <= int(item["end"])),
            None,
        )
        if entity is not None:
            pieces.append(_pii_markup(entity, value))
            continue
        inside_chunk = any(
            int(chunk["start"]) <= start and end <= int(chunk["end"]) for chunk in chunks
        )
        css_class = ' class="chunk-range"' if inside_chunk else ""
        pieces.append(f"<span{css_class}>{escape(value)}</span>")
    return "".join(pieces) or "&nbsp;"


def _table_markup(table: Table, table_index: int) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells = "".join(
            f"<td>{escape(cell.text).replace(chr(10), '<br>')}</td>" for cell in row.cells
        )
        rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="document-table">'
        '<div class="document-table-head">'
        f"<span>Таблица {table_index}</span><span>НЕ ОБРАБОТАНА ДЕТЕКТОРОМ</span>"
        "</div>"
        f'<div class="table-scroll"><table><tbody>{"".join(rows)}</tbody></table></div>'
        "</div>"
    )


def _full_document(report: dict[str, Any], source: Path) -> str:
    source_docx = open_docx(str(source))
    chunks_by_paragraph: dict[int, list[dict[str, Any]]] = {}
    for chunk in report["chunks"]:
        locator = chunk["anchor"]["locator"]
        if len(locator) == 2 and locator[0] == "body" and isinstance(locator[1], int):
            chunks_by_paragraph.setdefault(locator[1], []).append(chunk)

    blocks: list[str] = []
    paragraph_index = 0
    table_index = 0
    for block in source_docx.iter_inner_content():
        if isinstance(block, Paragraph):
            chunks = chunks_by_paragraph.get(paragraph_index, [])
            style_name = block.style.name if block.style is not None else ""
            heading = " document-heading" if style_name.startswith("Heading") else ""
            blocks.append(
                f'<div class="document-line{heading}">'
                f'<span class="line-number">P{paragraph_index + 1}</span>'
                f'<div class="line-text">{_document_paragraph_markup(block.text, chunks)}</div>'
                "</div>"
            )
            paragraph_index += 1
        elif isinstance(block, Table):
            table_index += 1
            blocks.append(_table_markup(block, table_index))
    return "".join(blocks)


def _metadata(report: dict[str, Any], source: Path) -> str:
    source_docx = open_docx(str(source))
    properties = source_docx.core_properties
    rows: list[str] = []
    for name in report["document_coverage"]["metadata"]["present_fields"]:
        value = getattr(properties, name, "")
        rows.append(f"<dt>{escape(str(name))}</dt><dd>{escape(str(value))}</dd>")
    if not rows:
        return ""
    return f'<dl class="supplement"><strong>Метаданные · НЕ ОБРАБОТАНЫ</strong>{"".join(rows)}</dl>'


def render_html_report(report: dict[str, Any], source: Path, destination: Path) -> None:
    """Записать локальный HTML с цветной разметкой PII внутри чанков."""
    missing = report["detection_coverage"]["requested_without_detector"]
    missing_warning = ""
    if missing:
        missing_warning = (
            '<p class="warning"><strong>Нет активного детектора:</strong> '
            f"{escape(', '.join(missing))}</p>"
        )
    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>PII report · {escape(str(report["input"]))}</title><style>{_STYLE}</style></head>
<body><header><h1>{escape(str(report["input"]))}</h1>
<p class="muted">PII {int(report["entity_count"])} · чанков {int(report["chunk_count"])}</p>
<div class="summary">{_summary(report)}</div>
<p class="danger">НЕ БЕЗОПАСЕН ДЛЯ ЭКСПОРТА: это диагностический отчёт с исходными PII.</p>
</header><main>{missing_warning}
<h2>Покрытие документа</h2><table><thead><tr><th>Область</th><th>Обработана</th>
<th>Фактическое содержимое</th></tr></thead><tbody>{_coverage(report)}</tbody></table>
<h2 id="full-document">Полный документ</h2>
<div class="legend"><span class="legend-item"><span class="legend-swatch"></span>
Контекст chunk</span>
<span class="legend-item"><mark class="pii pii-person">PII</mark>Найденная сущность</span></div>
<section class="document-view">{_full_document(report, source)}</section>{_metadata(report, source)}
<h2>Контекстные чанки</h2>{_chunks(report)}
</main></body></html>"""
    destination.write_text(html, encoding="utf-8")
    destination.chmod(0o600)
