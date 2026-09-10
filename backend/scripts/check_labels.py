"""Проверка разметки корпуса: каждая размеченная строка обязана быть в документе.

Зачем это отдельный инструмент. Разметку для корпуса настоящих договоров
делают агенты, и 11.09.2026 выяснилось, что агент способен записать
сущность, которой в документе нет вовсе: в `dagestanschool-kais-808.pdf`
оказались два выдуманных банковских счёта, а всего по корпусу — 36
выдуманных записей из 1849. Разметка, содержащая то, чего в документе нет,
портит метрику молча: детектор «не находит» несуществующее и выглядит хуже,
чем он есть.

Проверяется ровно одно, зато машинно: **строка из разметки буквально
встречается в тексте документа**. Пробелы схлопываются перед сравнением —
переносы строк в PDF ставятся где попало и к смыслу отношения не имеют.

Чего инструмент НЕ проверяет и проверить не может: полноту разметки. Если
сущность есть в документе, но не размечена, здесь это не видно — для
полноты нужен человек либо второй независимый проход.

    python scripts/check_labels.py fixtures/real/open-contracts
    python scripts/check_labels.py fixtures/real/open-contracts --fix
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import warnings
from typing import Any

warnings.filterwarnings("ignore")

#: Расширения, для которых умеем достать текст.
_READABLE = {".pdf", ".docx", ".xlsx"}


def document_text(path: pathlib.Path) -> str:
    """Весь текст документа одной строкой, включая распознанные картинки.

    Для PDF берётся именно сырой текстовый слой, а не наш ingest: проверка
    разметки не должна зависеть от того, как устроен разбор в движке.
    Иначе изменение ingest молча меняло бы вердикт по чужой разметке.
    """
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        import pymupdf

        return "\n".join(page.get_text() for page in pymupdf.open(path))
    if suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            parts.extend(cell.text for row in table.rows for cell in row.cells)
        return "\n".join(parts)
    if suffix == ".xlsx":
        import openpyxl

        book = openpyxl.load_workbook(path, data_only=False)
        return "\n".join(
            str(cell.value)
            for sheet in book.worksheets
            for row in sheet.iter_rows()
            for cell in row
            if cell.value is not None
        )
    raise ValueError(f"не умею читать {path.suffix!r}")


def collapse(value: str) -> str:
    """Схлопнуть пробелы: переносы в PDF ставятся произвольно."""
    return re.sub(r"\s+", " ", value).strip()


def find_document(labels_path: pathlib.Path) -> pathlib.Path | None:
    stem = labels_path.name.removesuffix(".labels.json")
    for suffix in _READABLE:
        candidate = labels_path.with_name(stem + suffix)
        if candidate.is_file():
            return candidate
    # Имя вида `contract.pdf.labels.json` — расширение уже в основе.
    candidate = labels_path.with_name(stem)
    return candidate if candidate.is_file() else None


def check_one(labels_path: pathlib.Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Вернуть (подтверждённые, выдуманные) записи разметки."""
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    entities = payload.get("entities", [])
    document = find_document(labels_path)
    if document is None:
        raise FileNotFoundError(f"нет документа рядом с {labels_path.name}")
    haystack = collapse(document_text(document))
    confirmed: list[dict[str, Any]] = []
    invented: list[dict[str, Any]] = []
    for item in entities:
        (confirmed if collapse(item.get("text", "")) in haystack else invented).append(item)
    return confirmed, invented


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=pathlib.Path, help="каталог с *.labels.json")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="удалить выдуманные записи из файлов разметки (правит файлы!)",
    )
    args = parser.parse_args(argv)

    files = sorted(args.directory.glob("*.labels.json"))
    if not files:
        print(f"в {args.directory} нет файлов *.labels.json", file=sys.stderr)
        return 2

    total = invented_total = 0
    by_type: dict[str, int] = {}
    for labels_path in files:
        try:
            confirmed, invented = check_one(labels_path)
        except (FileNotFoundError, ValueError) as error:
            print(f"  {labels_path.name}: ПРОПУЩЕН — {error}")
            continue
        total += len(confirmed) + len(invented)
        invented_total += len(invented)
        if not invented:
            continue
        total_here = len(confirmed) + len(invented)
        print(f"  {labels_path.name[:46]:48} выдумано {len(invented):3} из {total_here}")
        for item in invented[:5]:
            by_type[item.get("type", "?")] = by_type.get(item.get("type", "?"), 0) + 1
            print(f"      {item.get('type', '?'):16} {item.get('text', '')[:64]!r}")
        if len(invented) > 5:
            print(f"      … ещё {len(invented) - 5}")
        if args.fix:
            payload = json.loads(labels_path.read_text(encoding="utf-8"))
            payload["entities"] = confirmed
            labels_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    if not total:
        print("нечего проверять")
        return 1
    share = invented_total / total
    print(f"\nВСЕГО: {invented_total} из {total} записей не найдены в документах ({share:.1%})")
    if args.fix and invented_total:
        print("Выдуманные записи удалены. Полнота разметки при этом НЕ проверена.")
    return 1 if invented_total and not args.fix else 0


if __name__ == "__main__":
    sys.exit(main())
