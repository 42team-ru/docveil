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

from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.judge import JudgeAgent
from masker.model import CRITICAL_TYPES, EntityType, is_critical
from masker.profile import ProfileAgent

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "labeled"

#: Пороги ворот. Пропуск критичного реквизита — утечка, поэтому recall = 1.0.
MIN_RECALL_CRITICAL = 1.0
MIN_RECALL_OTHER = 0.85
MIN_PRECISION = 0.90
MIN_CLUSTER_PURITY = 1.0
# T3.2 поднимет минимальное покрытие ролями до 0.90 после расширения корпуса.
MIN_ROLE_COVERAGE = 0.70
MAX_QUESTIONS = 12


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


def _profile_judge_metrics(corpus: list[tuple[pathlib.Path, dict[str, Any]]]) -> dict[str, float]:
    """Посчитать профиль и судью напрямую, пока общий pipeline ещё не собран."""
    matched = 0
    party_matched = 0
    covered = 0
    pure = 0
    role_checked = 0
    role_correct = 0
    critical_questions = 0
    questions = 0
    synonyms_path = FIXTURES.parent / "role_synonyms.json"
    synonyms = (
        json.loads(synonyms_path.read_text(encoding="utf-8")) if synonyms_path.exists() else {}
    )
    for path, labels in corpus:
        if path.suffix != ".docx":
            continue
        document = ingest_docx(path)
        detection = DetectAgent().detect(document)
        profiles = ProfileAgent().profile(document, detection)
        judge = JudgeAgent().judge(detection, profiles)
        profile_by_value = {
            (member.entity.type.value, member.entity.text): profile
            for profile in profiles.profiles
            for member in profile.members
        }
        for item in labels["entities"]:
            profile = profile_by_value.get((item["type"], item["text"]))
            if profile is None:
                continue
            matched += 1
            if profile.role_title:
                covered += 1
            party = item.get("party")
            if party:
                party_matched += 1
                peers = [
                    member
                    for member in profile.members
                    if any(
                        candidate["type"] == member.entity.type.value
                        and candidate["text"] == member.entity.text
                        and candidate.get("party") == party
                        for candidate in labels["entities"]
                    )
                ]
                pure += int(bool(peers))
                expected_roles = {value.casefold() for value in synonyms.get(party, [])}
                if expected_roles:
                    role_checked += 1
                    role_correct += int(profile.role_title.casefold() in expected_roles)
        questions += len(judge.questions)
        refs_to_entities = {
            member.ref: member.entity for profile in profiles.profiles for member in profile.members
        }
        critical_questions += sum(
            1
            for question in judge.questions
            for ref in question.refs
            if ref in refs_to_entities and is_critical(refs_to_entities[ref].type)
        )
    return {
        "cluster_purity": pure / party_matched if party_matched else 1.0,
        "role_coverage": covered / matched if matched else 1.0,
        "role_accuracy": role_correct / role_checked if role_checked else 1.0,
        "critical_in_questions": float(critical_questions),
        "questions_per_document": questions / len(corpus) if corpus else 0.0,
    }


def _print_profile_judge(metrics: dict[str, float]) -> list[str]:
    print("\nПРОФИЛИ И СУДЬЯ")
    for name, value in metrics.items():
        print(f"{name:<24}{value:.3f}")
    failures: list[str] = []
    if metrics["cluster_purity"] < MIN_CLUSTER_PURITY:
        failures.append("cluster_purity ниже порога")
    if metrics["role_coverage"] < MIN_ROLE_COVERAGE:
        failures.append("role_coverage ниже порога")
    if metrics["questions_per_document"] > MAX_QUESTIONS:
        failures.append("слишком много вопросов")
    if metrics["critical_in_questions"] != 0:
        failures.append("критичные сущности попали в вопросы")
    return failures


def run(gate: bool) -> int:
    corpus = load_corpus()
    profile_failures = _print_profile_judge(_profile_judge_metrics(corpus)) if corpus else []
    try:
        from masker.pipeline import mask_document
    except ImportError:
        print("МЕТРИКИ ПРОПУЩЕНЫ: masker.pipeline ещё не реализован.")
        print("После T1.10 этот пропуск обязан исчезнуть — иначе ворота декоративны.")
        return 1 if gate and profile_failures else 0

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

    failures.extend(profile_failures)
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
