"""Метрики по размеченному корпусу. Шаг ворот «метрики».

Принимать работу надо по цифрам, а не по рассказу агента. Здесь эти цифры
и считаются: precision / recall / F1 по каждому типу сущности.

Пока пайплайн не собран, шаг громко сообщает, что пропущен. Оставленный
пропуск после того, как пайплайн заработал, — дефект, а не мелочь.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

from masker.model import CRITICAL_TYPES, EntityType

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "labeled"

#: Пороги ворот. Пропуск критичного реквизита — утечка, поэтому recall = 1.0.
MIN_RECALL_CRITICAL = 1.0
MIN_RECALL_OTHER = 0.85
MIN_PRECISION = 0.90


def load_corpus() -> list[tuple[pathlib.Path, dict[str, Any]]]:
    """Документ плюс его ручная разметка."""
    corpus: list[tuple[pathlib.Path, dict[str, Any]]] = []
    for labels in sorted(FIXTURES.glob("*.labels.json")):
        doc = next(
            (
                p
                for p in FIXTURES.glob(labels.name.replace(".labels.json", ".*"))
                if not p.name.endswith(".labels.json")
            ),
            None,
        )
        if doc is not None:
            corpus.append((doc, json.loads(labels.read_text(encoding="utf-8"))))
    return corpus


def score(expected: set[tuple[str, str]], found: set[tuple[str, str]]) -> dict[str, float]:
    tp = len(expected & found)
    fp = len(found - expected)
    fn = len(expected - found)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def run(gate: bool) -> int:
    try:
        from masker.pipeline import mask_document
    except ImportError:
        print("МЕТРИКИ ПРОПУЩЕНЫ: masker.pipeline ещё не реализован.")
        print("После T1.10 этот пропуск обязан исчезнуть — иначе ворота декоративны.")
        return 0

    corpus = load_corpus()
    if not corpus:
        print("МЕТРИКИ ПРОПУЩЕНЫ: в fixtures/labeled нет размеченных документов.")
        return 1

    by_type: dict[str, dict[str, set[tuple[str, str]]]] = defaultdict(
        lambda: {"expected": set(), "found": set()}
    )
    for path, labels in corpus:
        result = mask_document(path, types=list(EntityType))
        for item in labels["entities"]:
            by_type[item["type"]]["expected"].add((path.name, item["text"]))
        for repl in result.replacements:
            by_type[repl.entity.type.value]["found"].add((path.name, repl.entity.text))

    print(f"{'тип':<18}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    failures: list[str] = []
    for name in sorted(by_type):
        m = score(by_type[name]["expected"], by_type[name]["found"])
        print(
            f"{name:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}"
            f"{m['f1']:>7.3f}{m['fn']:>5}{m['fp']:>5}"
        )
        critical = name in {t.value for t in CRITICAL_TYPES}
        min_recall = MIN_RECALL_CRITICAL if critical else MIN_RECALL_OTHER
        if m["recall"] < min_recall:
            failures.append(f"{name}: recall {m['recall']:.3f} < {min_recall}")
        if m["precision"] < MIN_PRECISION:
            failures.append(f"{name}: precision {m['precision']:.3f} < {MIN_PRECISION}")

    if failures and gate:
        print("\nПОРОГИ НЕ ВЗЯТЫ:")
        for f in failures:
            print(f"  {f}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Метрики обезличивания по корпусу")
    parser.add_argument("--gate", action="store_true", help="ненулевой код при провале порогов")
    args = parser.parse_args()
    return run(gate=args.gate)


if __name__ == "__main__":
    sys.exit(main())
