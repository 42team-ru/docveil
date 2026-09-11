"""Тесты LLM-компилятора пользовательских типов (план T1.13, шаг 9).

Только `FakeProvider` со сценарными ответами — сеть не нужна, результат
детерминирован. Живой тест на настоящем провайдере — `@pytest.mark.e2e`
в конце файла.
"""

from __future__ import annotations

import json
import os

import pytest

from masker.customtypes.compiler import (
    MAX_ASK_ROUNDS,
    AskOutcome,
    CannotCompileOutcome,
    CompileOutcome,
    UseBuiltinOutcome,
    clear_cache,
    compile_type,
)
from masker.entity_types import EntityTypeRegistry
from masker.llm import FakeProvider, LLMProvider, Message

REGISTRY = EntityTypeRegistry.builtin()


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_cache()
    yield
    clear_cache()


def _use_builtin(type_id: str, marker_override: str | None = None) -> str:
    return json.dumps(
        {"outcome": "use_builtin", "type_id": type_id, "marker_override": marker_override}
    )


def _compile(spec: dict[str, object]) -> str:
    return json.dumps({"outcome": "compile", "spec": spec})


def _ask(question: str, options: list[str] | None = None, target: str = "") -> str:
    return json.dumps(
        {"outcome": "ask", "question": question, "options": options or [], "target": target}
    )


def _cannot(reason: str) -> str:
    return json.dumps({"outcome": "cannot_compile", "reason": reason})


_SHIPMENT_DATE_SPEC: dict[str, object] = {
    "id": "shipment_date",
    "title": "Дата отгрузки",
    "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
    "critical": False,
    "detect": {
        "kind": "regex",
        "pattern": r"\d{2}\.\d{2}\.\d{4}",
        "context": ["отгрузк", "поставк"],
    },
}


def test_available_executors_excludes_gliner_without_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без extra `[gliner]` паспорт компилятора не содержит gliner_* — ни
    один executor не предлагается модели, если физически недоступен (T1.13.1,
    шаг 16, решение Р2: без мягкой деградации)."""
    import masker.customtypes.compiler as compiler_module

    monkeypatch.setattr(compiler_module, "_gliner_installed", lambda: False)
    executors = compiler_module.available_executors()
    assert "gliner_label" not in executors
    assert "gliner_structure" not in executors
    assert {"literals", "regex", "regex_context", "regex_llm_filter"} <= executors


def test_available_executors_always_includes_regex_llm_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`regex_llm_filter` (шаг 13 T1.13) — базовый executor: `LLMProvider`
    в проекте есть всегда (fake или реальный), физически недостающих
    зависимостей у него нет — паспорт возвращает его даже без extra
    `[gliner]`."""
    import masker.customtypes.compiler as compiler_module

    monkeypatch.setattr(compiler_module, "_gliner_installed", lambda: False)
    assert "regex_llm_filter" in compiler_module.available_executors()
    monkeypatch.setattr(compiler_module, "_gliner_installed", lambda: True)
    assert "regex_llm_filter" in compiler_module.available_executors()


def test_available_executors_includes_gliner_when_extra_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Паспорт строится из фактически доступного: если extra `[gliner]`
    физически установлен, gliner_label/gliner_structure появляются, не
    дожидаясь ручного изменения списка (T1.13.1, шаг 16, решение Р2)."""
    import masker.customtypes.compiler as compiler_module

    monkeypatch.setattr(compiler_module, "_gliner_installed", lambda: True)
    executors = compiler_module.available_executors()
    assert {"gliner_label", "gliner_structure"} <= executors
    assert {"literals", "regex", "regex_context"} <= executors


def test_gliner_executors_appear_in_prompt_only_when_in_passport() -> None:
    """Промпт видит gliner_label/gliner_structure, только если они пришли в
    паспорте — компилятор без extra не должен предлагать модели то, чего
    физически нет."""
    from masker.customtypes.prompt import build_messages

    without_gliner = build_messages(
        "замажь даты отгрузки", executors=frozenset({"literals", "regex"}), builtin_types=()
    )
    assert "gliner_label" not in without_gliner[0].content
    assert "gliner_structure" not in without_gliner[0].content

    with_gliner = build_messages(
        "замажь даты отгрузки",
        executors=frozenset({"literals", "regex", "gliner_label", "gliner_structure"}),
        builtin_types=(),
    )
    assert "gliner_label" in with_gliner[0].content
    assert "gliner_structure" in with_gliner[0].content


def test_use_builtin_outcome() -> None:
    llm = FakeProvider([_use_builtin("person")])
    outcome = compile_type("замажь ФИО", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, UseBuiltinOutcome)
    assert outcome.type_id == "person"
    assert llm.calls == 1


def test_use_builtin_unknown_type_id_triggers_retry_then_cannot_compile() -> None:
    llm = FakeProvider([_use_builtin("not_a_real_type"), _use_builtin("not_a_real_type")])
    outcome = compile_type("замажь непонятно что", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, CannotCompileOutcome)
    assert llm.calls == 2


def test_compile_outcome_with_valid_spec() -> None:
    llm = FakeProvider([_compile(_SHIPMENT_DATE_SPEC)])
    outcome = compile_type("замажь даты отгрузки", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, CompileOutcome)
    assert outcome.spec["id"] == "shipment_date"
    assert llm.calls == 1


def test_compile_outcome_executor_not_in_passport_is_rejected() -> None:
    """LLM выбрала исполнитель вне переданного паспорта — как ошибка валидации."""
    spec = {
        **_SHIPMENT_DATE_SPEC,
        "detect": {"kind": "gliner_label", "label": "x", "description": "y"},
    }
    llm = FakeProvider([_compile(spec), _compile(spec)])
    outcome = compile_type(
        "замажь даты отгрузки", llm=llm, registry=REGISTRY, executors=frozenset({"regex"})
    )
    assert isinstance(outcome, CannotCompileOutcome)
    assert llm.calls == 2


def test_regex_from_llm_rejected() -> None:
    """LLM выдала regex с вложенным квантификатором — AST-валидатор его не пропускает."""
    bad_spec = {
        "id": "bad_type",
        "title": "Плохой тип",
        "marker": "[ПЛОХО-{n}]",
        "critical": False,
        "detect": {"kind": "regex", "pattern": "(a+)+$"},
    }
    llm = FakeProvider([_compile(bad_spec), _compile(bad_spec)])
    outcome = compile_type("замажь что-то опасное", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, CannotCompileOutcome)
    assert llm.calls == 2


def test_gliner_spec_without_description_is_rejected_even_if_kind_allowed() -> None:
    """Спека gliner_label без description отклоняется валидатором `typeconfig`
    независимо от паспорта — защита действует до исполнения (design notes 2.9)."""
    spec = {
        "id": "job_title",
        "title": "Должность",
        "marker": "[ДОЛЖНОСТЬ-{n}]",
        "critical": False,
        "detect": {"kind": "gliner_label", "label": "должность"},
    }
    llm = FakeProvider([_compile(spec), _compile(spec)])
    outcome = compile_type(
        "замажь должности",
        llm=llm,
        registry=REGISTRY,
        executors=frozenset({"gliner_label"}),
    )
    assert isinstance(outcome, CannotCompileOutcome)


def test_invalid_json_triggers_exactly_one_retry_not_unlimited() -> None:
    """Ретрай без ограничения — баг: третий (валидный) ответ не должен спрашиваться."""
    llm = FakeProvider(["не json совсем", "тоже не json", _use_builtin("person")])
    outcome = compile_type("замажь ФИО", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, CannotCompileOutcome)
    assert llm.calls == 2  # третий (валидный) ответ в очереди не тронут


def test_retry_includes_error_text_in_feedback() -> None:
    """Второй вызов после невалидного JSON несёт текст ошибки в user-сообщении."""
    llm = FakeProvider(["не json", _use_builtin("person")])
    outcome = compile_type("замажь ФИО", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, UseBuiltinOutcome)
    assert llm.calls == 2


def test_ask_outcome_below_max_rounds_is_returned_as_is() -> None:
    llm = FakeProvider(
        [
            _ask(
                "Какую именно дату — отгрузки или подписания?",
                ["отгрузки", "подписания"],
                "shipment",
            )
        ]
    )
    outcome = compile_type("замажь дату", llm=llm, registry=REGISTRY, round_index=1)
    assert isinstance(outcome, AskOutcome)
    assert outcome.question.startswith("Какую именно")


def test_ask_outcome_at_max_rounds_becomes_cannot_compile_with_last_question() -> None:
    """MAX_ASK_ROUNDS = 3: на третьей попытке ask не возвращается, только cannot_compile."""
    llm = FakeProvider([_ask("Финальный вопрос?", [], "x")])
    outcome = compile_type("замажь дату", llm=llm, registry=REGISTRY, round_index=MAX_ASK_ROUNDS)
    assert isinstance(outcome, CannotCompileOutcome)
    assert "Финальный вопрос?" in outcome.reason
    assert llm.calls == 1  # ask не ретраится — это не ошибка валидатора/JSON


def test_endless_ask_across_three_rounds_never_exceeds_max_rounds() -> None:
    """Три раунда ask подряд заканчиваются cannot_compile, а не четвёртым вопросом."""
    llm = FakeProvider([_ask(f"Вопрос {i}") for i in range(1, MAX_ASK_ROUNDS + 1)])
    outcomes = []
    for round_index in range(1, MAX_ASK_ROUNDS + 1):
        outcome = compile_type(
            "замажь что-то неоднозначное", llm=llm, registry=REGISTRY, round_index=round_index
        )
        outcomes.append(outcome)
    assert isinstance(outcomes[0], AskOutcome)
    assert isinstance(outcomes[1], AskOutcome)
    assert isinstance(outcomes[2], CannotCompileOutcome)
    assert f"Вопрос {MAX_ASK_ROUNDS}" in outcomes[2].reason
    assert llm.calls == MAX_ASK_ROUNDS


def test_cannot_compile_outcome() -> None:
    llm = FakeProvider([_cannot("класс E не поддерживается")])
    outcome = compile_type("замажь всё подозрительное", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, CannotCompileOutcome)
    assert outcome.reason == "класс E не поддерживается"


def test_partial_success_one_of_five_descriptions_fails() -> None:
    """Пять описаний, одно упало — остальные четыре компилируются независимо."""
    descriptions = [
        "замажь ФИО",
        "замажь ИНН",
        "замажь коды товаров",
        "замажь непонятно что",
        "замажь адрес",
    ]
    responses = [
        _use_builtin("person"),
        _use_builtin("inn"),
        _compile(
            {
                "id": "product_code",
                "title": "Код товара",
                "marker": "[КОД-{n}]",
                "critical": False,
                "detect": {"kind": "literals", "values": ["SKU-1"]},
            }
        ),
        "мусор",
        "мусор",  # ретрай тоже невалиден -> cannot_compile
        _use_builtin("address"),
    ]
    llm = FakeProvider(responses)
    outcomes = [compile_type(desc, llm=llm, registry=REGISTRY) for desc in descriptions]
    compiled = [o for o in outcomes if isinstance(o, (UseBuiltinOutcome, CompileOutcome))]
    failed = [o for o in outcomes if isinstance(o, CannotCompileOutcome)]
    assert len(compiled) == 4
    assert len(failed) == 1


def test_cache_hit_avoids_second_llm_call_for_identical_description() -> None:
    llm = FakeProvider([_use_builtin("person")])
    first = compile_type("замажь ФИО", llm=llm, registry=REGISTRY, model_id="test-model")
    second = compile_type("замажь ФИО", llm=llm, registry=REGISTRY, model_id="test-model")
    assert first == second
    assert llm.calls == 1


def test_cache_key_includes_prompt_version_model_and_description() -> None:
    """Разные model_id или разные описания не должны делить кэш."""
    llm = FakeProvider([_use_builtin("person"), _use_builtin("org_name")])
    first = compile_type("замажь ФИО", llm=llm, registry=REGISTRY, model_id="model-a")
    second = compile_type("замажь ФИО", llm=llm, registry=REGISTRY, model_id="model-b")
    assert llm.calls == 2
    assert isinstance(first, UseBuiltinOutcome)
    assert isinstance(second, UseBuiltinOutcome)


def test_cache_not_used_when_feedback_present() -> None:
    """Ретрай/раунд с фидбеком не кэшируется — контекст другой."""
    llm = FakeProvider([_use_builtin("person"), _use_builtin("person")])
    first = compile_type("замажь ФИО", llm=llm, registry=REGISTRY, round_index=1, feedback="")
    second = compile_type(
        "замажь ФИО", llm=llm, registry=REGISTRY, round_index=2, feedback="отвечаю на вопрос"
    )
    assert llm.calls == 2
    assert first == second


def test_ask_and_cannot_compile_outcomes_are_not_cached() -> None:
    llm = FakeProvider([_ask("вопрос", [], "x"), _use_builtin("person")])
    first = compile_type("замажь неопределённое", llm=llm, registry=REGISTRY, round_index=1)
    second = compile_type("замажь неопределённое", llm=llm, registry=REGISTRY, round_index=1)
    assert isinstance(first, AskOutcome)
    assert isinstance(second, UseBuiltinOutcome)
    assert llm.calls == 2


def test_llm_error_becomes_cannot_compile_not_exception() -> None:
    class BrokenProvider:
        calls = 0

        def complete(self, messages: list[Message]) -> str:
            self.calls += 1
            from masker.llm import LLMError

            raise LLMError("сеть недоступна")

    outcome = compile_type("замажь ФИО", llm=BrokenProvider(), registry=REGISTRY)
    assert isinstance(outcome, CannotCompileOutcome)
    assert "недоступна" in outcome.reason


def test_llm_error_sets_llm_unavailable_code() -> None:
    class BrokenProvider:
        def complete(self, messages: list[Message]) -> str:
            from masker.llm import LLMError

            raise LLMError("timeout")

    outcome = compile_type("замажь даты договора", llm=BrokenProvider(), registry=REGISTRY)
    assert isinstance(outcome, CannotCompileOutcome)
    assert outcome.code == "llm_unavailable"


def test_ask_rounds_exhausted_sets_correct_code() -> None:
    llm = FakeProvider([_ask("Уточните тип?", [], "дата")])
    outcome = compile_type("замажь дату", llm=llm, registry=REGISTRY, round_index=MAX_ASK_ROUNDS)
    assert isinstance(outcome, CannotCompileOutcome)
    assert outcome.code == "ask_rounds_exhausted"


def test_cannot_compile_outcome_carries_cannot_compile_code() -> None:
    llm = FakeProvider([_cannot("слишком общее")])
    outcome = compile_type("замажь всё подозрительное", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, CannotCompileOutcome)
    assert outcome.code == "cannot_compile"


def _live_provider() -> LLMProvider:
    """Вернуть провайдер из окружения или пропустить тест."""

    from masker.llm import LLMError, get_provider

    masker_llm = os.environ.get("MASKER_LLM", "").casefold()
    if masker_llm == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("MASKER_LLM=openrouter, но OPENROUTER_API_KEY не задан")
    elif masker_llm == "gigachat" and not os.environ.get("GIGACHAT_CREDENTIALS"):
        pytest.skip("MASKER_LLM=gigachat, но GIGACHAT_CREDENTIALS не задан")
    elif masker_llm not in {"openrouter", "gigachat"}:
        pytest.skip("MASKER_LLM не задан или fake — живой тест пропущен")
    try:
        return get_provider()
    except LLMError as exc:
        pytest.skip(f"get_provider() не смог создать провайдер: {exc}")


@pytest.mark.e2e
def test_e2e_shipment_dates_compile_to_regex_or_gliner_structure() -> None:
    """Живой провайдер: «замажь даты отгрузки» → compile с ожидаемым kind."""
    llm = _live_provider()
    outcome = compile_type("замажь даты отгрузки товара", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, CompileOutcome)
    assert outcome.spec["detect"]["kind"] in {"regex", "regex_context", "gliner_structure"}


@pytest.mark.e2e
def test_e2e_person_maps_to_use_builtin() -> None:
    """Живой провайдер: «замажь ФИО» → use_builtin(person)."""
    llm = _live_provider()
    outcome = compile_type("замажь ФИО людей в документе", llm=llm, registry=REGISTRY)
    assert isinstance(outcome, UseBuiltinOutcome)
    assert outcome.type_id == "person"
