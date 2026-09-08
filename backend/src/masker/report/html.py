"""Статический HTML-отчёт для визуальной проверки чанков и PII."""

from __future__ import annotations

from html import escape
from itertools import pairwise
from pathlib import Path
from typing import Any

from docx import Document as open_docx
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from masker.ingest.docx_ingest import DocxLocator

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
.critical-banner { margin-top: 12px; padding: 12px 14px; color: #fff; background: #c62828;
  border-left: 4px solid #8a1c1c; font-weight: 700; }
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
.document-table { border-top: 3px solid #2f6f4e; border-bottom: 1px solid #dfe1e5;
  padding: 10px 12px 14px; background: #fbfffd; }
.document-table-head { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 8px;
  color: #24543c; font-size: 12px; font-weight: 800; }
.table-scroll { overflow-x: auto; }
.document-table table { min-width: 620px; border: 1px solid #c9ddd0; }
.document-table td { white-space: pre-wrap; font-family: Georgia, "Times New Roman", serif; }
.supplement { margin-top: 12px; padding: 12px; border-left: 4px solid #c62828;
  background: #fff; }
.supplement dt { margin-top: 8px; font-weight: 700; }
.supplement dd { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.contract-card { background: #fff; border: 1px solid #dfe1e5; border-radius: 6px;
  overflow: hidden; margin-top: 4px; }
.contract-card table { width: 100%; }
.contract-card td:first-child { width: 200px; color: #4b5056; font-weight: 700; }
.contract-party { display: flex; flex-direction: column; gap: 2px; }
.contract-party .party-name { font-weight: 700; }
.contract-party .party-meta { font-size: 12px; color: #5f6368; }
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
        marker = str(item.get("marker") or "")
        rows.append(
            "<tr>"
            f'<td><span class="type">{escape(str(item["type"]))}</span></td>'
            f"<td>{escape(str(item['text']))}</td>"
            f"<td>{escape(marker)}</td>"
            f"<td>{escape(str(item['source']))}</td>"
            f"<td>{float(item['confidence']):.2f}</td>"
            f"<td>{int(item['start'])}:{int(item['end'])}</td>"
            "</tr>"
        )
    return "".join(rows)


def _groups(report: dict[str, Any]) -> str:
    """Блок «Группы согласованности»: один маркер — одна строка.

    Показывает то, ради чего T1.6 существует: сколько раз встретилось
    значение и каким единым маркером оно везде заменено. ``plan`` в отчёте
    может отсутствовать (старый report.json, report_version < 4) —
    в этом случае блок пуст, а не падает.
    """
    plan = report.get("plan")
    groups = plan.get("groups", []) if isinstance(plan, dict) else []
    if not groups:
        return '<p class="empty">Групп согласованности нет.</p>'
    rows: list[str] = []
    for group in groups:
        rows.append(
            "<tr>"
            f'<td><span class="type">{escape(str(group["marker"]))}</span></td>'
            f"<td>{escape(str(group.get('type_title', group['type'])))}</td>"
            f"<td>{escape(str(group['profile_id']))}</td>"
            f"<td>{int(group['ref_count'])}</td>"
            f"<td>{escape(str(group['sample']))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Маркер</th><th>Тип</th><th>Профиль</th>"
        "<th>Встречается</th><th>Образец</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _marker_legend(report: dict[str, Any]) -> str:
    """Блок «Легенда сокращений маркера» (план М1, правило 6).

    Заказчик видит в документе короткую форму (``[Ф1]``), когда полный
    маркер (``[ПОСТАВЩИК-ФИО-1]``) не влез в поле — эта таблица расшифровывает
    каждое такое сокращение и перечисляет страницы, где оно встречается.
    ``report["marker_legend"]`` может отсутствовать в старом report.json —
    в этом случае блок пуст, а не падает (тот же приём, что и в ``_groups``).
    """
    legend = report.get("marker_legend") or []
    if not legend:
        return '<p class="empty">Сокращений маркера нет — везде показан полный маркер.</p>'
    rows: list[str] = []
    for item in legend:
        pages = ", ".join(str(int(page)) for page in item.get("pages", []))
        rows.append(
            "<tr>"
            f'<td><span class="type">{escape(str(item["shown_label"]))}</span></td>'
            f"<td>{escape(str(item['canonical_label']))}</td>"
            f"<td>{escape(pages)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Показано</th><th>Означает</th>"
        f"<th>Страницы</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _review_possible(report: dict[str, Any]) -> str:
    """Блок «Снять одним кликом» (Р8): группы уровня ``possible`` отдельным
    списком, как просил заказчик, — не искать их по всему отчёту.

    ``report["review_possible"]`` может отсутствовать в старом report.json
    — блок пуст, а не падает (тот же приём, что и в ``_groups``).
    """
    groups = report.get("review_possible") or []
    if not groups:
        return '<p class="empty">Групп уровня possible нет — снимать маску вручную не с чего.</p>'
    rows: list[str] = []
    for group in groups:
        rows.append(
            "<tr>"
            f'<td><span class="type">{escape(str(group["marker"]))}</span></td>'
            f"<td>{escape(str(group.get('type_title', group['type'])))}</td>"
            f"<td>{int(group['ref_count'])}</td>"
            f"<td>{escape(str(group['sample']))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Маркер</th><th>Тип</th><th>Встречается</th>"
        f"<th>Образец</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


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
            "<table><thead><tr><th>Тип</th><th>Текст</th><th>Маркер</th><th>Источник</th>"
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
    body_details = f"{document['body']['nonempty_paragraphs']} абзацев"
    if int(document["body"].get("skipped_blocks", 0)):
        body_details += f", пропущено блоков: {document['body']['skipped_blocks']}"
    table_details = (
        f"{document['tables']['count']} таблиц, {document['tables']['nonempty_paragraphs']} абзацев"
    )
    if int(document["tables"].get("nested_count", 0)):
        table_details += f", вложенных таблиц: {document['tables']['nested_count']}"
    rows = [
        ("Основной текст", _processed_label(document["body"]["processed"]), body_details),
        ("Таблицы", _processed_label(document["tables"]["processed"]), table_details),
        (
            "Колонтитулы",
            _processed_label(document["headers"]["processed"]),
            f"{document['headers']['parts_with_text']} header, "
            f"{document['footers']['parts_with_text']} footer с текстом",
        ),
        (
            "Сноски",
            _processed_label(document["footnotes"]["processed"]),
            "есть текст" if document["footnotes"]["has_text"] else "нет текста",
        ),
        (
            "Метаданные",
            _processed_label(document["metadata"]["processed"]),
            ", ".join(document["metadata"]["present_fields"]) or "пусто",
        ),
    ]
    return "".join(
        f"<tr><td>{escape(name)}</td><td>{processed}</td><td>{escape(details)}</td></tr>"
        for name, processed, details in rows
    )


def _processed_label(value: object) -> str:
    return "да" if value else "нет"


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


def _report_locator(raw: object) -> DocxLocator | None:
    if not isinstance(raw, list):
        return None
    locator: list[str | int] = []
    for item in raw:
        if not isinstance(item, str | int):
            return None
        locator.append(item)
    return tuple(locator)


def _table_markup(
    table: Table,
    table_index: int,
    chunks_by_locator: dict[DocxLocator, list[dict[str, Any]]],
    *,
    processed: bool,
) -> str:
    rows: list[str] = []
    locator_table_index = table_index - 1
    for row_idx, tr in enumerate(table._tbl.tr_lst):
        cell_markup: list[str] = []
        for cell_idx, tc in enumerate(tr.tc_lst):
            cell = _Cell(tc, table)
            paragraphs: list[str] = []
            for para_idx, paragraph_xml in enumerate(tc.p_lst):
                paragraph = Paragraph(paragraph_xml, cell)
                locator = ("table", locator_table_index, row_idx, cell_idx, para_idx)
                chunks = chunks_by_locator.get(locator, [])
                paragraphs.append(_document_paragraph_markup(paragraph.text, chunks))
            cell_markup.append(f"<td>{'<br>'.join(paragraphs) or '&nbsp;'}</td>")
        cells = "".join(cell_markup)
        rows.append(f"<tr>{cells}</tr>")
    status = "обработана" if processed else "не обработана"
    return (
        '<div class="document-table">'
        '<div class="document-table-head">'
        f"<span>Таблица {table_index}</span><span>{status}</span>"
        "</div>"
        f'<div class="table-scroll"><table><tbody>{"".join(rows)}</tbody></table></div>'
        "</div>"
    )


def _full_document(report: dict[str, Any], source: Path) -> str:
    source_docx = open_docx(str(source))
    chunks_by_locator: dict[DocxLocator, list[dict[str, Any]]] = {}
    for chunk in report["chunks"]:
        locator = _report_locator(chunk["anchor"]["locator"])
        if locator is not None:
            chunks_by_locator.setdefault(locator, []).append(chunk)

    blocks: list[str] = []
    paragraph_index = 0
    table_index = 0
    tables_processed = bool(report["document_coverage"]["tables"]["processed"])
    for block in source_docx.iter_inner_content():
        if isinstance(block, Paragraph):
            chunks = chunks_by_locator.get(("body", paragraph_index), [])
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
            blocks.append(
                _table_markup(
                    block,
                    table_index,
                    chunks_by_locator,
                    processed=tables_processed,
                )
            )
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


def _contract_party_cell(party: dict[str, Any] | None) -> str:
    if not party:
        return "—"
    parts: list[str] = []
    name = str(party.get("name") or "")
    role = str(party.get("role_title") or "")
    inn = str(party.get("inn") or "")
    ogrn = str(party.get("ogrn") or "")
    if name:
        parts.append(f'<span class="party-name">{escape(name)}</span>')
    meta: list[str] = []
    if role:
        meta.append(escape(role))
    if inn:
        meta.append(f"ИНН {escape(inn)}")
    if ogrn:
        meta.append(f"ОГРН {escape(ogrn)}")
    if meta:
        parts.append(f'<span class="party-meta">{" · ".join(meta)}</span>')
    return f'<div class="contract-party">{"".join(parts)}</div>' if parts else "—"


def _contract_summary_card(report: dict[str, Any]) -> str:
    cs = report.get("contract_summary")
    if not cs or not isinstance(cs, dict):
        return ""
    rows: list[str] = []

    def row(label: str, value: str) -> str:
        return f"<tr><td>{escape(label)}</td><td>{value}</td></tr>"

    rows.append(row("Заказчик", _contract_party_cell(cs.get("customer"))))
    rows.append(row("Поставщик", _contract_party_cell(cs.get("supplier"))))

    laws = cs.get("federal_law") or []
    rows.append(row("Федеральный закон", escape(", ".join(laws)) if laws else "—"))

    amount = str(cs.get("contract_amount") or "") or "—"
    rows.append(row("Сумма договора", escape(amount)))

    periods = cs.get("delivery_periods") or []
    rows.append(row("Сроки поставки", escape("; ".join(periods)) if periods else "—"))

    number = str(cs.get("contract_number") or "") or "—"
    rows.append(row("Номер договора", escape(number)))

    return f'<div class="contract-card"><table><tbody>{"".join(rows)}</tbody></table></div>'


def _critical_unmasked_banner(report: dict[str, Any]) -> str:
    """Красный баннер, если человек осознанно снял маску с критичного типа.

    Раздел 3 плана T1.5.1: снятие маски с ``CRITICAL_TYPES`` — громкое
    событие, а не тихая настройка.
    """
    items = report.get("decisions", {}).get("critical_unmasked") or []
    if not items:
        return ""
    targets = ", ".join(sorted({str(item["target"]) for item in items}))
    return (
        '<p class="critical-banner">ВНИМАНИЕ: маска снята с критичного типа '
        f"({escape(targets)}) — осознанное решение человека, --unmask-critical.</p>"
    )


def render_html_report(report: dict[str, Any], source: Path, destination: Path) -> None:
    """Записать локальный HTML с цветной разметкой PII внутри чанков."""
    missing = report["detection_coverage"]["requested_without_detector"]
    missing_warning = ""
    if missing:
        missing_warning = (
            '<p class="warning"><strong>Нет активного детектора:</strong> '
            f"{escape(', '.join(missing))}</p>"
        )
    critical_banner = _critical_unmasked_banner(report)
    contract_card = _contract_summary_card(report)
    contract_section = f"<h2>Карточка договора</h2>{contract_card}" if contract_card else ""
    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>PII report · {escape(str(report["input"]))}</title><style>{_STYLE}</style></head>
<body><header><h1>{escape(str(report["input"]))}</h1>
<p class="muted">PII {int(report["entity_count"])} · чанков {int(report["chunk_count"])}</p>
<div class="summary">{_summary(report)}</div>
<p class="danger">НЕ БЕЗОПАСЕН ДЛЯ ЭКСПОРТА: это диагностический отчёт с исходными PII.</p>
{critical_banner}
</header><main>{missing_warning}
{contract_section}
<h2>Покрытие документа</h2><table><thead><tr><th>Область</th><th>Обработана</th>
<th>Фактическое содержимое</th></tr></thead><tbody>{_coverage(report)}</tbody></table>
<h2>Группы согласованности</h2>{_groups(report)}
<h2>Легенда сокращений маркера</h2>{_marker_legend(report)}
<h2>Снять одним кликом (уровень possible)</h2>{_review_possible(report)}
<h2 id="full-document">Полный документ</h2>
<div class="legend"><span class="legend-item"><span class="legend-swatch"></span>
Контекст chunk</span>
<span class="legend-item"><mark class="pii pii-person">PII</mark>Найденная сущность</span></div>
<section class="document-view">{_full_document(report, source)}</section>{_metadata(report, source)}
<h2>Контекстные чанки</h2>{_chunks(report)}
</main></body></html>"""
    destination.write_text(html, encoding="utf-8")
    destination.chmod(0o600)
