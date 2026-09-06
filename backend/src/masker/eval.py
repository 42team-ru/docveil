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
from masker.entity_types import EntityTypeRegistry
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.judge import JudgeAgent
from masker.model import Document, EntityType, MaskPlan, is_critical
from masker.policy.agent import PolicyAgent
from masker.profile import ProfileAgent
from masker.run import RunFailedError
from masker.typeconfig import load_type_config
from masker.validate.parts import docx_parts, pdf_parts

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "labeled"

#: Расширение файла → его ingest. Единственное место, которое решает, каким
#: парсером читать документ корпуса — раньше решение было спрятано в
#: `if path.suffix != ".docx": continue` (Д7 плана T2.2.1): PDF физически не
#: попадал в метрики, и идеальные цифры по DOCX маскировали провал по PDF.
_INGEST_BY_SUFFIX: dict[str, Any] = {".docx": ingest_docx, ".pdf": ingest_pdf}


def _ingest(path: pathlib.Path) -> Document:
    ingest = _INGEST_BY_SUFFIX.get(path.suffix.casefold())
    if ingest is None:
        raise ValueError(f"eval не умеет читать формат {path.suffix!r}: {path}")
    doc: Document = ingest(path)
    return doc


def _collapse(text: str) -> str:
    """Схлопнуть пробелы для сравнения — разметка не должна зависеть от
    того, режет ingest документ по строкам или по блокам (см. схему
    разметки PDF-корпуса, план T2.2.1, пункт 1)."""
    return " ".join(text.split())


def _artifact_text(path: pathlib.Path) -> str:
    """Видимый текст артефакта целиком — по всем частям контейнера.

    Та же независимая от production-детекции читалка, что использует
    ``ValidateAgent`` (``masker.validate.parts``): достаточно видимого
    текста, дублей маркера в бинарных частях (картинки) не бывает.
    """
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        return "\n".join(part.text for part in docx_parts(path))
    if suffix == ".pdf":
        return "\n".join(part.text for part in pdf_parts(path))
    raise ValueError(f"eval не умеет читать формат {path.suffix!r}: {path}")


def duplicate_marker_count(plan: MaskPlan, artifacts: tuple[pathlib.Path, ...]) -> int:
    """Сколько лишних вхождений маркера набралось по всем группам и артефактам.

    Для каждой группы плана маркер обязан встретиться в тексте артефакта
    ровно столько раз, сколько у неё ``Replacement`` (``len(group.refs)``).
    Разница больше нуля — дубль (Д1 плана T2.2.1: маркер вставлен не один
    раз на замену). Отрицательная разница — пропуск вставки, это ловит
    ``leaked_total``/recall, а не эта метрика, поэтому в сумму не идёт.
    """
    total = 0
    for artifact in artifacts:
        text = _artifact_text(artifact)
        for group in plan.groups:
            if not group.marker:
                continue
            diff = text.count(group.marker) - len(group.refs)
            if diff > 0:
                total += diff
    return total


#: Пороги ворот. Пропуск критичного реквизита — утечка, поэтому recall = 1.0.
MIN_RECALL_CRITICAL = 1.0
MIN_RECALL_OTHER = 0.85
MIN_PRECISION = 0.90
#: Исключения для типов, где NER (Natasha) даёт систематические FP на PDF —
#: поднять до глобального MIN_PRECISION/MIN_RECALL_OTHER после замены Natasha
#: на GLiNER2 (план T3.2, Фаза 0 п.6).
_MIN_PRECISION_OVERRIDE: dict[str, float] = {
    "org_name": 0.45,  # 21 FP Natasha на school.pdf: публ. органы, заголовки таблиц
    "address": 0.50,  # PDF span-boundary FP: слипание смежных адресов в одном сегменте
}
_MIN_RECALL_OVERRIDE: dict[str, float] = {
    "address": 0.80,  # 2 FN на school.pdf: граница span не совпадает с разметкой
}
MIN_CLUSTER_PURITY = 1.0
# T3.2 поднимет минимальное покрытие ролями до 0.90 после расширения корпуса.
MIN_ROLE_COVERAGE = 0.70
# T3.2: стартовый порог; поднять до 0.80 после улучшения промпта ProfileAgent.
MIN_ROLE_ACCURACY = 0.60
#: Вопросы судьи (Q*) — по одной конкретной сущности. Раздельно от вопросов
#: политики (раздел T1.5.1): природа разная, общий порог мерить бессмысленно.
MAX_QUESTIONS = 12
#: Вопросы политики (TYPE-*/PROFILE-*) — по одному на каждый найденный тип и
#: профиль, поэтому их всегда больше, чем вопросов судьи. Порог пересчитан
#: после добавления DateDetector (T1.15): среднее выросло до ≈11.8, берём
#: 13 с запасом на рост корпуса.
MAX_POLICY_QUESTIONS = 13
#: Критичный тип/профиль, снятый без двойного подтверждения, — утечка.
#: Порог жёсткий и не подлежит пересмотру без решения о варианте A (раздел 3).
MAX_CRITICAL_UNMASKED = 0
#: Утечка в редактирующем артефакте — провал прогона, порог нулевой
#: (T2.2.1, шаг 3): раньше эта цифра существовала внутри ``ValidateAgent``,
#: но ворота её не читали (Д7).
MAX_LEAKED_TOTAL = 0
#: Маркер должен встречаться в артефакте ровно по разу на ``Replacement``
#: своей группы — дубль (Д1) означает, что исходный текст под ним уже
#: удалён, а замена продублирована поверх пустого места.
MAX_DUPLICATE_MARKERS = 0
#: Прогон корпуса — измерительный инструмент: одна аномальная сущность на
#: одном документе (план T2.2.1, пачка 4) не имеет права ослепить ворота
#: целиком и скрыть leaked_total/duplicate_markers по остальным документам.
#: Порог всё равно нулевой — «не ослеплять» не значит «прощать»: любой
#: падший рендер обязан быть виден в отчёте с именем документа и маркером.
#: Прямой вызов рендера на одном документе (CLI) при этом продолжает падать
#: громко — здесь ловится только агрегирующий прогон по корпусу.
MAX_RENDER_FAILURES = 0
#: Текстовый слой PDF вне замен обязан остаться посимвольно на месте (Д10,
#: план T2.2.2, шаг 5): прямоугольник редакции не имеет права стереть текст
#: соседней строки. Порог нулевой — как и у leaked_total, «немного вёрстки
#: потеряно» не бывает мелочью.
MAX_LAYOUT_REMOVED_CHARS = 0


def corpus_registry(corpus: list[tuple[pathlib.Path, dict[str, Any]]]) -> EntityTypeRegistry:
    """Реестр встроенных типов, расширенный пользовательскими типами всего корпуса.

    Нужен только для того, чтобы порог recall по типу (шаг 6, design notes
    6.8) читался из реестра, а не из ``CRITICAL_TYPES`` — иначе пользовательский
    ``critical: true`` не проверялся бы по-настоящему. Корпус никогда не зовёт
    LLM-компилятор: ``custom_types`` в разметке — уже готовые спеки.
    """
    registry = EntityTypeRegistry.builtin()
    for _path, labels in corpus:
        raw = labels.get("custom_types", [])
        if not raw:
            continue
        specs = load_type_config({"version": 1, "types": raw})
        registry = registry.extend(spec.spec for spec in specs)
    return registry


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


def score(expected: set[tuple[str, ...]], found: set[tuple[str, ...]]) -> dict[str, float]:
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
    policy_questions = 0
    critical_unmasked = 0
    synonyms_path = FIXTURES.parent / "role_synonyms.json"
    synonyms = (
        json.loads(synonyms_path.read_text(encoding="utf-8")) if synonyms_path.exists() else {}
    )
    for path, labels in corpus:
        document = _ingest(path)
        detection = DetectAgent().detect(document)
        profiles = ProfileAgent().profile(document, detection)
        judge = JudgeAgent().judge(detection, profiles)
        profile_by_value = {
            (member.entity.type, _collapse(member.entity.text)): profile
            for profile in profiles.profiles
            for member in profile.members
        }
        for item in labels["entities"]:
            profile = profile_by_value.get((item["type"], _collapse(item["text"])))
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
                        candidate["type"] == member.entity.type
                        and _collapse(candidate["text"]) == _collapse(member.entity.text)
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
        policy_questions += len(PolicyAgent().questions(detection, profiles))
        # Неинтерактивный прогон: никто не спрашивал — только уверенность
        # судьи и защита критичных типов могут повлиять на решение (раздел 6
        # плана T1.5.1, needs_human/finalize_node). Порог critical_unmasked
        # == 0 держит инвариант «двойное подтверждение обязательно».
        policy_result = PolicyAgent().apply(
            detection,
            profiles,
            judge.verdicts,
            [],
            [],
            {},
            allow_unmask_critical=False,
        )
        critical_unmasked += len(policy_result.critical_unmasked)
    return {
        "cluster_purity": pure / party_matched if party_matched else 1.0,
        "role_coverage": covered / matched if matched else 1.0,
        "role_accuracy": role_correct / role_checked if role_checked else 1.0,
        "critical_in_questions": float(critical_questions),
        "questions_per_document": questions / len(corpus) if corpus else 0.0,
        "policy_questions_per_document": policy_questions / len(corpus) if corpus else 0.0,
        "critical_unmasked": float(critical_unmasked),
    }


def _print_profile_judge(metrics: dict[str, float]) -> list[str]:
    print("\nПРОФИЛИ И СУДЬЯ")
    for name, value in metrics.items():
        print(f"{name:<30}{value:.3f}")
    failures: list[str] = []
    if metrics["cluster_purity"] < MIN_CLUSTER_PURITY:
        failures.append("cluster_purity ниже порога")
    if metrics["role_coverage"] < MIN_ROLE_COVERAGE:
        failures.append("role_coverage ниже порога")
    if metrics["role_accuracy"] < MIN_ROLE_ACCURACY:
        failures.append(f"role_accuracy {metrics['role_accuracy']:.3f} < {MIN_ROLE_ACCURACY}")
    if metrics["questions_per_document"] > MAX_QUESTIONS:
        failures.append("слишком много вопросов судьи")
    if metrics["critical_in_questions"] != 0:
        failures.append("критичные сущности попали в вопросы")
    if metrics["policy_questions_per_document"] > MAX_POLICY_QUESTIONS:
        failures.append("слишком много вопросов политики (типы/профили)")
    if metrics["critical_unmasked"] > MAX_CRITICAL_UNMASKED:
        failures.append("критичный тип снят без двойного подтверждения (critical_unmasked)")
    return failures


def run(gate: bool) -> int:
    corpus = load_corpus()
    profile_failures = _print_profile_judge(_profile_judge_metrics(corpus)) if corpus else []
    try:
        from masker.pipeline import mask_and_validate
    except ImportError:
        print("МЕТРИКИ ПРОПУЩЕНЫ: masker.pipeline ещё не реализован.")
        print("После T1.10 этот пропуск обязан исчезнуть — иначе ворота декоративны.")
        return 1 if gate and profile_failures else 0

    if not corpus:
        print("МЕТРИКИ ПРОПУЩЕНЫ: в fixtures/labeled нет размеченных документов.")
        return 1

    registry = corpus_registry(corpus)
    by_type: dict[str, dict[str, set[tuple[str, ...]]]] = defaultdict(
        lambda: {"expected": set(), "found": set()}
    )
    # Разрез по форматам (шаг 2 плана T2.2.1): без него идеальные цифры по
    # DOCX маскируют провал по PDF — ровно то, что случилось в Д7.
    by_format: dict[str, dict[str, set[tuple[str, ...]]]] = defaultdict(
        lambda: {"expected": set(), "found": set()}
    )
    # Гейт на утечки и дубли маркеров по всему корпусу (шаг 3 плана T2.2.1):
    # оба редактирующих артефакта строятся и проверяются ``ValidateAgent``
    # здесь же, одним прогоном с планом — не отдельным вторым вызовом графа.
    leaked_total = 0
    duplicate_markers = 0
    # Сохранность вёрстки PDF вне замен (Д10, план T2.2.2, шаг 5) — сумма
    # ``removed_chars`` по всем PDF-артефактам корпуса; для DOCX-документов
    # ``result.validation.layout`` пуст (`ValidateAgent` считает layout
    # только для PDF), поэтому сумма не искажается посторонним форматом.
    layout_removed_chars = 0
    layout_failures: list[str] = []
    render_failures: list[str] = []
    for path, labels in corpus:
        fmt = path.suffix.casefold().lstrip(".")
        custom_types = labels.get("custom_types", [])
        try:
            with mask_and_validate(
                path, types=list(EntityType), custom_types=custom_types
            ) as result:
                for item in labels["entities"]:
                    key = (path.name, item["type"], _collapse(item["text"]))
                    by_type[item["type"]]["expected"].add(key)
                    by_format[fmt]["expected"].add(key)
                for repl in result.plan.replacements:
                    key = (path.name, repl.entity.type, _collapse(repl.entity.text))
                    by_type[repl.entity.type]["found"].add(key)
                    by_format[fmt]["found"].add(key)
                leaked_total += len(result.validation.leaked)
                duplicate_markers += duplicate_marker_count(result.plan, result.artifacts)
                for layout in result.validation.layout:
                    layout_removed_chars += layout.removed_chars
                    if layout.removed_chars:
                        layout_failures.append(
                            f"{path.name}/{layout.artifact}: removed={layout.removed_chars} "
                            f"pages={list(layout.pages)} {layout.first_diff}"
                        )
        except RunFailedError as error:
            # Не глотать тихо: документ выпадает из P/R/F1 (план на него не
            # посчитан), но факт и место падения обязаны остаться видимыми —
            # иначе один аномальный документ маскировал бы метрики по всем
            # остальным, ровно то, чего требовалось избежать (Д7 наоборот).
            render_failures.append(f"{path.name}: {error}")

    print(f"{'тип':<18}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    failures: list[str] = []
    for name in sorted(by_type):
        m = score(by_type[name]["expected"], by_type[name]["found"])
        print(
            f"{name:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}"
            f"{m['f1']:>7.3f}{m['fn']:>5}{m['fp']:>5}"
        )
        critical = registry.is_critical(name)
        min_recall = (
            MIN_RECALL_CRITICAL if critical else _MIN_RECALL_OVERRIDE.get(name, MIN_RECALL_OTHER)
        )
        min_prec = _MIN_PRECISION_OVERRIDE.get(name, MIN_PRECISION)
        if m["recall"] < min_recall:
            failures.append(f"{name}: recall {m['recall']:.3f} < {min_recall}")
        if m["precision"] < min_prec:
            failures.append(f"{name}: precision {m['precision']:.3f} < {min_prec}")

    print(f"\nФОРМАТЫ\n{'формат':<18}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    for fmt in sorted(by_format):
        m = score(by_format[fmt]["expected"], by_format[fmt]["found"])
        print(
            f"{fmt:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}"
            f"{m['f1']:>7.3f}{m['fn']:>5}{m['fp']:>5}"
        )

    print(f"\nleaked_total{leaked_total:>22}")
    print(f"duplicate_markers{duplicate_markers:>17}")
    print(f"layout_removed_chars{layout_removed_chars:>14}")
    for failure in layout_failures:
        print(f"  {failure}")
    print(f"render_failures{len(render_failures):>19}")
    for failure in render_failures:
        print(f"  {failure}")
    if leaked_total > MAX_LEAKED_TOTAL:
        failures.append(f"leaked_total {leaked_total} > {MAX_LEAKED_TOTAL} — утечка в артефактах")
    if duplicate_markers > MAX_DUPLICATE_MARKERS:
        failures.append(
            f"duplicate_markers {duplicate_markers} > {MAX_DUPLICATE_MARKERS} — "
            "маркер вставлен не один раз на Replacement"
        )
    if layout_removed_chars > MAX_LAYOUT_REMOVED_CHARS:
        failures.append(
            f"layout_removed_chars {layout_removed_chars} > {MAX_LAYOUT_REMOVED_CHARS} — "
            "прямоугольник редакции стёр текст вне своих замен (Д10): " + "; ".join(layout_failures)
        )
    if len(render_failures) > MAX_RENDER_FAILURES:
        failures.append(
            f"render_failures {len(render_failures)} > {MAX_RENDER_FAILURES} — "
            "рендер упал на документе(ах) корпуса: " + "; ".join(render_failures)
        )

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
