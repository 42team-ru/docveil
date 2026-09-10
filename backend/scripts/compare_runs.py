"""Сравнение прогонов корпуса: что даёт конфигурация, а что теряет.

Прогоны складывает `run_corpus.py`; здесь они ставятся рядом. Главное, чего
не видно в одиночном прогоне, — **что именно** нашла одна конфигурация и не
нашла другая. Разница в третьем знаке после запятой не говорит ни о чём;
список конкретных сущностей говорит всё.

    python scripts/compare_runs.py out/runs/ner-none-* out/runs/gliner-none-*
    python scripts/compare_runs.py out/runs/*          # все прогоны разом
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


def load(run_dir: pathlib.Path) -> dict[str, Any]:
    summary = run_dir / "summary.json"
    if not summary.is_file():
        raise FileNotFoundError(f"нет summary.json в {run_dir}")
    return json.loads(summary.read_text(encoding="utf-8"))


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=pathlib.Path, help="каталоги прогонов")
    parser.add_argument(
        "--missed",
        action="store_true",
        help="показать, что нашёл первый прогон и не нашли остальные",
    )
    args = parser.parse_args(argv)

    runs: list[tuple[pathlib.Path, dict[str, Any]]] = []
    for path in args.runs:
        if not path.is_dir():
            continue
        try:
            runs.append((path, load(path)))
        except FileNotFoundError as error:
            print(f"пропущен: {error}", file=sys.stderr)
    if not runs:
        print("нечего сравнивать", file=sys.stderr)
        return 2

    print(f"{'конфигурация':28} {'critR':>7} {'recall':>7} {'утечки':>7} {'сек':>7}  документов")
    for _path, data in runs:
        config = data["configuration"]
        name = f"{config['layer']}+{config['llm_profile']}"
        print(
            f"{name:28} {_fmt(data['critical_recall']):>7} {_fmt(data['recall']):>7} "
            f"{data['leaked_total']:>7} {_fmt(data['seconds']):>7}  "
            f"{data['succeeded']}/{data['documents']}"
        )

    if len(runs) > 1:
        print("\nРАЗНИЦА ПО ДОКУМЕНТАМ (найдено замен):")
        _base_path, base = runs[0]
        base_docs = {r["document"]: r for r in base["per_document"]}
        for _path, data in runs[1:]:
            config = data["configuration"]
            print(f"\n  {config['layer']}+{config['llm_profile']} против базового:")
            shown = 0
            for record in data["per_document"]:
                other = base_docs.get(record["document"])
                if not other or record.get("status") != "ok" or other.get("status") != "ok":
                    continue
                delta = record.get("found", 0) - other.get("found", 0)
                if delta:
                    sign = "+" if delta > 0 else ""
                    print(f"    {record['document'][:44]:46} {sign}{delta}")
                    shown += 1
            if not shown:
                print("    различий нет")

    if args.missed:
        print("\nЧТО НЕ НАЙДЕНО (первые 20 по каждому прогону):")
        for _path, data in runs:
            config = data["configuration"]
            missed: list[str] = []
            for record in data["per_document"]:
                missed.extend(record.get("missed", []))
            print(f"\n  {config['layer']}+{config['llm_profile']}: всего {len(missed)}")
            for item in missed[:20]:
                print(f"    {item[:90]}")

    leaking = [(p, d) for p, d in runs if d["leaked_total"]]
    if leaking:
        print("\nУТЕЧКИ — разбирать в первую очередь:")
        for _path, data in leaking:
            config = data["configuration"]
            print(f"  {config['layer']}+{config['llm_profile']}: {data['leaked_total']}")
            for record in data["per_document"]:
                for leak in record.get("leaked_detail", [])[:3]:
                    print(
                        f"    {record['document'][:34]:36} {leak['type']:14} "
                        f"{leak['value'][:34]!r} → {leak['artifact']}"
                    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
