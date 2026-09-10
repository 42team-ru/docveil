"""Тесты метаморфного корпуса (К1): `masker.evalgen` и его порог в `masker.eval`.

Смысл К1 — доказать, что `recall = 1.0` по критичным типам измерялось на
176 сущностях, записанных ровно так, как их записал человек, размечавший
корпус, а не на детекторе. Эти тесты проверяют сам генератор (детерминизм,
сохранность контрольных сумм, покрытие категорий) и то, что порог
`robust_recall` в `masker.eval` действительно встроен в ворота, а не просто
существует как неиспользуемая константа.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import masker.eval as eval_module
from masker import evalgen
from masker.detect.checksums import (
    is_valid_bik,
    is_valid_inn,
    is_valid_kpp,
    is_valid_ogrn,
    is_valid_snils,
)
from masker.model import (
    Anchor,
    Entity,
    EntityType,
    MaskPlan,
    Replacement,
    Source,
    ValidationReport,
)
from masker.pipeline import MaskResult

_VALIDATORS = {
    str(EntityType.INN): is_valid_inn,
    str(EntityType.KPP): is_valid_kpp,
    str(EntityType.OGRN): is_valid_ogrn,
    str(EntityType.SNILS): is_valid_snils,
    str(EntityType.BIK): is_valid_bik,
}


def test_generate_cases_is_deterministic() -> None:
    """Два прогона генератора дают побайтово одинаковый корпус — никакого
    `random` без сида, требование приёмки К1."""
    first = evalgen.generate_cases()
    second = evalgen.generate_cases()
    assert first == second
    assert len(first) > 0


def test_generate_cases_covers_all_eight_categories() -> None:
    """Все восемь категорий возмущений из плана К1 представлены хотя бы
    одним случаем — иначе часть плана осталась не реализована молча."""
    cases = evalgen.generate_cases()
    categories = {case.category for case in cases}
    expected = {
        "разрядка",
        "пробельные варианты",
        "перенос строки",
        "гомоглифы в метке",
        "слитно и в скобках",
        "альтернативные подписи",
        "формы ФИО и падежи",
        "опечатки в метке",
    }
    missing = expected - categories
    assert not missing, f"категории без единого случая: {missing}"


def test_numeric_perturbations_keep_checksum_valid() -> None:
    """Возмущение формы не имеет права испортить контрольную сумму —
    иначе тест мерил бы качество генератора, а не робастность детектора
    (явное требование К1: «контрольная сумма ИНН обязана сходиться»)."""
    checked = 0
    for case in evalgen.generate_cases():
        for entity_type, digits in case.expected:
            validator = _VALIDATORS.get(entity_type)
            if validator is None:
                continue
            assert validator(digits), (
                f"возмущённое значение не проходит контрольную сумму: "
                f"{entity_type}={digits!r} (случай {case.category}/{case.variant})"
            )
            checked += 1
    assert checked > 0


def test_bank_account_perturbation_matches_a_real_account_number() -> None:
    """Счёт не проверяется отдельной контрольной суммой (её нет) — значит
    сверяем иначе: цифры возмущённого значения обязаны совпасть с исходным
    значением из `fixtures/labeled/*.labels.json`, то есть генератор не
    портит цифры счёта при возмущении формы."""
    entities = evalgen._load_corpus_entities()
    real_accounts = {
        evalgen._digits_only(item["text"])
        for item in entities
        if item["type"] == str(EntityType.BANK_ACCOUNT)
    }
    checked = 0
    for case in evalgen.generate_cases():
        for entity_type, digits in case.expected:
            if entity_type != str(EntityType.BANK_ACCOUNT):
                continue
            assert digits in real_accounts
            checked += 1
    assert checked > 0


def test_genitive_matches_corpus_reality() -> None:
    """Эвристика родительного падежа (категория 7) — не общий морфологический
    решатель, а таблица под конкретные имена этого корпуса. Проверяем её на
    той части корпуса, где обе формы (именительный и родительный) уже
    присутствуют независимо друг от друга, — значит подобранная таблица
    действительно воспроизводит реальный русский язык, а не выдумку."""
    real_genitive_keys = {
        evalgen.normalize_value(EntityType.PERSON, "Иванова Ивана Ивановича"),
        evalgen.normalize_value(EntityType.PERSON, "Кузнецова Петра Алексеевича"),
        evalgen.normalize_value(EntityType.PERSON, "Сидоровой Анны Петровны"),
    }
    generated = [
        case
        for case in evalgen.generate_cases()
        if case.category == "формы ФИО и падежи" and case.variant == "родительный падеж"
    ]
    assert generated, "ни одного случая с родительным падежом не сгенерировано"
    matched = sum(1 for case in generated if case.expected[0][1] in real_genitive_keys)
    assert matched >= 3, (
        "эвристика склонения обязана воспроизводить реальные формы из корпуса "
        f"хотя бы для трёх известных имён, совпало {matched}"
    )


def test_evaluate_reports_recall_between_zero_and_one() -> None:
    """Санитарная проверка отчёта, не привязанная к конкретному числу —
    оно обязано меняться по мере правок Р1–Р3, тест не должен на него давить."""
    report = evalgen.evaluate()
    assert 0.0 <= report.recall <= 1.0
    assert report.total == len(evalgen.generate_cases())
    assert report.hit <= report.total
    assert sum(total for _hit, total in report.by_category.values()) == report.total


def test_min_robust_recall_threshold_exists_and_is_not_disabled() -> None:
    """Порог обязан существовать и быть содержательным (не 0.0, не 1.0
    «на глазок») — «Правило порогов» из TASKS.md."""
    assert 0.0 < eval_module.MIN_ROBUST_RECALL < 1.0


#: Нейтральные профиль/судья — тесты порога `robust_recall` не про них
#: (тот же приём, что и в `test_eval.py::_patch_common`).
_NEUTRAL_PROFILE_JUDGE_METRICS = {
    "cluster_purity": 1.0,
    "role_coverage": 1.0,
    "role_accuracy": 1.0,
    "critical_in_questions": 0.0,
    "questions_per_document": 0.0,
    "policy_questions_per_document": 0.0,
    "critical_unmasked": 0.0,
}


def _isolate_from_rest_of_the_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Сделать так, чтобы `run()` проходил все ПРОЧИЕ пороги гарантированно —
    единственная переменная в тесте порога `robust_recall` это он сам, а не
    состояние остального корпуса (который в рабочем дереве сейчас частично
    правят другие агенты параллельно, см. `detect/`, `render/`)."""
    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(b"")
    labels = {"entities": [{"type": "inn", "text": "1234567890"}]}
    # К2 добавил вызовы `load_corpus(FIXTURES_HOLDOUT)`/`load_corpus(FIXTURES_NEGATIVE)`
    # внутри `run()` — заглушка обязана принимать (и игнорировать) этот
    # аргумент, иначе второй вызов падает `TypeError`. Пустой список для
    # holdout/negative печатает «ПРОПУЩЕН» и не участвует в пороге robust_recall.
    monkeypatch.setattr(
        eval_module,
        "load_corpus",
        lambda fixtures=eval_module.FIXTURES: (
            [(docx_path, labels)] if fixtures == eval_module.FIXTURES else []
        ),
    )
    # feat-image-ingest: `run()` также зовёт `load_image_corpus`; тесту
    # robust_recall картиночный корпус не нужен — подменяем пустым.
    monkeypatch.setattr(eval_module, "load_image_corpus", list)
    monkeypatch.setattr(
        eval_module, "_profile_judge_metrics", lambda _corpus: dict(_NEUTRAL_PROFILE_JUDGE_METRICS)
    )
    entity = Entity(
        type=EntityType.INN, text="1234567890", segment_order=0, start=0, end=10, source=Source.RULE
    )
    replacement = Replacement(
        ref="R1",
        entity=entity,
        marker="[X]",
        group_id="G1",
        profile_id="",
        anchor=Anchor(fmt="docx", locator=("body", 0)),
    )
    result = MaskResult(
        plan=MaskPlan(replacements=(replacement,), groups=(), skipped=(), requested_types=()),
        validation=ValidationReport(
            leaked=(), residual=(), checked_artifacts=(), checked_parts=(), ok=True
        ),
        artifacts=(),
    )

    @contextmanager
    def fake(path: Path, *, types: Any, custom_types: Any = ()) -> Iterator[MaskResult]:
        yield result

    monkeypatch.setattr("masker.pipeline.mask_and_validate", fake)


def test_gate_fails_when_robust_recall_threshold_raised_above_actual(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ключевой тест приёмки К1: «тест, падающий при откате порога».

    Если порог случайно поднимут выше фактического значения — ворота обязаны
    провалиться. Если кто-то уберёт саму проверку `robust_recall` из
    `eval.run()` (откатит её из ворот), этот тест перестанет проходить даже
    с завышенным порогом — то есть ловит и откат порога, и выпадение проверки
    из ворот целиком.
    """
    _isolate_from_rest_of_the_gate(monkeypatch, tmp_path)
    fixed_report = evalgen.MetamorphicReport(total=10, hit=4, by_category={"разрядка": (4, 10)})
    monkeypatch.setattr(eval_module.evalgen, "evaluate", lambda: fixed_report)
    monkeypatch.setattr(eval_module, "MIN_ROBUST_RECALL", fixed_report.recall + 0.05)

    code = eval_module.run(gate=True)
    output = capsys.readouterr().out

    assert code == 1, "порог выше фактического robust_recall обязан провалить ворота"
    assert "robust_recall" in output


def test_gate_passes_when_robust_recall_threshold_below_actual(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Симметричный случай — заниженный порог не должен ложно ронять ворота
    из-за robust_recall (остальные метрики в этом тесте нейтрализованы)."""
    _isolate_from_rest_of_the_gate(monkeypatch, tmp_path)
    fixed_report = evalgen.MetamorphicReport(total=10, hit=4, by_category={"разрядка": (4, 10)})
    monkeypatch.setattr(eval_module.evalgen, "evaluate", lambda: fixed_report)
    monkeypatch.setattr(eval_module, "MIN_ROBUST_RECALL", fixed_report.recall - 0.05)

    code = eval_module.run(gate=True)
    assert code == 0
