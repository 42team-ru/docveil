"""Быстрая проверка одного документа: что детекторы нашли и что упустили.

Зачем отдельно от `run_corpus.py`. Тот прогоняет весь корпус через полный
конвейер с рендером обоих артефактов и побайтовой проверкой — это минуты
и заметная нагрузка на машину. Во время правки детектора нужен другой
цикл: поменял правило, за пару секунд увидел, что изменилось на одном
документе.

Здесь работает только детекция. Ни рендера, ни маскирования, ни
валидации — значит и памяти нужно в разы меньше, и параллельные агенты
не мешают друг другу.

    python scripts/check_doc.py fixtures/real-contracts/open-contracts/brsc-contract.pdf
    python scripts/check_doc.py <файл> --type money      # только один тип
    python scripts/check_doc.py <файл> --json out.json   # машиночитаемо

Что показывает:

- **найдено** — что вернули детекторы, по типам;
- **упущено** — что есть в разметке, но детекторы не нашли (нужен файл
  `<имя>.labels.json` рядом);
- **лишнее** — что нашли, но в разметке этого нет. Осторожно: разметка
  корпуса неполна, поэтому «лишнее» не равно «ошибка» — это кандидаты на
  проверку глазами, а не приговор.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import warnings
from collections import defaultdict
from typing import Any

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _labels_path(document: pathlib.Path) -> pathlib.Path | None:
    for candidate in (
        document.with_name(document.name + ".labels.json"),
        document.with_suffix(".labels.json"),
    ):
        if candidate.is_file():
            return candidate
    return None


def check(document: pathlib.Path, only_type: str | None = None) -> dict[str, Any]:
    """Прогнать детекцию и сверить с разметкой, если она рядом."""
    from masker.detect import default_detectors
    from masker.detect.agent import DetectAgent
    from masker.eval import _ingest
    from masker.model import CRITICAL_TYPES
    from masker.typeconfig import load_type_config

    labels_file = _labels_path(document)
    payload = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file is not None else {}
    gold = payload.get("entities", [])
    raw_custom = payload.get("custom_types", [])
    specs = load_type_config({"version": 1, "types": raw_custom}) if raw_custom else []

    started = time.perf_counter()
    doc = _ingest(document)
    entities = DetectAgent(default_detectors(specs)).detect(doc).entities
    elapsed = time.perf_counter() - started

    found = {(str(e.type), _collapse(e.text)) for e in entities}
    expected = {(g["type"], _collapse(g["text"])) for g in gold}
    if only_type:
        found = {k for k in found if k[0] == only_type}
        expected = {k for k in expected if k[0] == only_type}

    by_type: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"found": [], "missed": [], "extra": []}
    )
    for etype, text in sorted(found & expected):
        by_type[etype]["found"].append(text)
    for etype, text in sorted(expected - found):
        by_type[etype]["missed"].append(text)
    for etype, text in sorted(found - expected):
        by_type[etype]["extra"].append(text)

    critical = {c.value for c in CRITICAL_TYPES}
    crit_expected = {k for k in expected if k[0] in critical}
    crit_found = crit_expected & found
    return {
        "document": document.name,
        "has_labels": labels_file is not None,
        "entities_found": len(found),
        "gold_entities": len(expected),
        "critical_recall": (len(crit_found) / len(crit_expected) if crit_expected else None),
        "seconds": round(elapsed, 2),
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
    }


def _print(result: dict[str, Any], limit: int) -> None:
    print(f"{result['document']}  —  {result['seconds']} с")
    if not result["has_labels"]:
        print("разметки рядом нет: показано только найденное, сверить не с чем\n")
    print(f"найдено сущностей: {result['entities_found']}", end="")
    if result["has_labels"]:
        print(f", в разметке: {result['gold_entities']}", end="")
        if result["critical_recall"] is not None:
            print(f", recall критичных: {result['critical_recall']:.3f}", end="")
    print("\n")

    print(f"{'тип':18} {'совпало':>8} {'упущено':>8} {'лишнее':>8}")
    for etype, groups in result["by_type"].items():
        print(
            f"{etype:18} {len(groups['found']):>8} "
            f"{len(groups['missed']):>8} {len(groups['extra']):>8}"
        )

    missed_any = any(g["missed"] for g in result["by_type"].values())
    if missed_any:
        print("\nУПУЩЕНО (есть в разметке, детектор не нашёл):")
        for etype, groups in result["by_type"].items():
            for text in groups["missed"][:limit]:
                print(f"  {etype:16} {text[:78]!r}")
            if len(groups["missed"]) > limit:
                print(f"  {etype:16} … ещё {len(groups['missed']) - limit}")

    extra_any = any(g["extra"] for g in result["by_type"].values())
    if extra_any:
        print("\nЛИШНЕЕ (нашли, в разметке нет — разметка неполна, смотреть глазами):")
        for etype, groups in result["by_type"].items():
            for text in groups["extra"][:limit]:
                print(f"  {etype:16} {text[:78]!r}")
            if len(groups["extra"]) > limit:
                print(f"  {etype:16} … ещё {len(groups['extra']) - limit}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=pathlib.Path, help="один документ (.pdf/.docx/.xlsx)")
    parser.add_argument("--type", dest="only_type", help="показать только этот тип сущности")
    parser.add_argument("--json", type=pathlib.Path, help="записать результат в JSON")
    parser.add_argument("--limit", type=int, default=12, help="сколько примеров печатать")
    args = parser.parse_args(argv)

    if not args.document.is_file():
        print(f"нет файла {args.document}", file=sys.stderr)
        return 2
    result = check(args.document, args.only_type)
    if args.json:
        args.json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"записано: {args.json}")
    _print(result, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
