"""LLM-компилятор пользовательских типов: слова → один из четырёх исходов.

Вызов модели идёт только через `masker.llm.LLMProvider` (требование
заказчика №6, `AGENTS.md`) — никакого прямого клиента. AST-валидатор
регулярок (`masker.typeconfig.load_type_config`) — единственная граница
безопасности; здесь он не дублируется, только вызывается на исходе
`compile`.

`gliner_label`/`gliner_structure` в `available_executors()` не попадают
никогда в этой версии модуля: GLiNER физически не подключён (T1.13.1,
решение Р2 плана T1.13 — «без мягкой деградации», паспорт строится из
фактически доступного). `regex_llm_filter` появится здесь шагом 13, когда
executor будет физически реализован.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from masker.customtypes.prompt import PROMPT_VERSION, build_messages
from masker.entity_types import EntityTypeRegistry
from masker.llm import LLMError, LLMProvider
from masker.typeconfig import CustomTypeError, load_type_config

#: После третьего раунда уточнения — cannot_compile, а не четвёртый вопрос
#: (design notes T1.13, вопрос 4: «отдать последнее лучшее» отвергнуто).
MAX_ASK_ROUNDS = 3

#: Executor'ы, которые компилятор физически может использовать сегодня.
#: Пополняется по мере подключения детекторов (шаг 13 добавит
#: `regex_llm_filter`); `gliner_label`/`gliner_structure` — задача T1.13.1,
#: шаг 16, здесь их нет намеренно.
_AVAILABLE_EXECUTORS: frozenset[str] = frozenset({"literals", "regex", "regex_context"})


def available_executors() -> frozenset[str]:
    """Паспорт executor'ов, физически доступных компилятору прямо сейчас."""
    return _AVAILABLE_EXECUTORS


class CompilerParseError(Exception):
    """Ответ модели не удалось разобрать в один из четырёх исходов."""


@dataclass(frozen=True, slots=True)
class UseBuiltinOutcome:
    """Запрос уже покрыт встроенным типом — ничего компилировать не надо."""

    type_id: str
    marker_override: str | None = None
    kind: Literal["use_builtin"] = "use_builtin"


@dataclass(frozen=True, slots=True)
class CompileOutcome:
    """Готовая спека — элемент `types` для `load_type_config`, уже провалидирован."""

    spec: dict[str, object]
    kind: Literal["compile"] = "compile"


@dataclass(frozen=True, slots=True)
class AskOutcome:
    """Неоднозначность: нужен один уточняющий вопрос пользователю."""

    question: str
    options: list[str]
    target: str
    kind: Literal["ask"] = "ask"


@dataclass(frozen=True, slots=True)
class CannotCompileOutcome:
    """Компилятор не может свести запрос ни к одному executor'у."""

    reason: str
    kind: Literal["cannot_compile"] = "cannot_compile"


CompilerOutcome = UseBuiltinOutcome | CompileOutcome | AskOutcome | CannotCompileOutcome

#: Кэш готовых спеков в процессе — design notes T1.13, вопрос 5. Ключ несёт
#: версию промпта, поэтому правка промпта сама инвалидирует кэш.
_CACHE: OrderedDict[str, CompilerOutcome] = OrderedDict()
_CACHE_MAXSIZE = 128


def clear_cache() -> None:
    """Очистить кэш скомпилированных спеков. Только для тестов между сценариями."""
    _CACHE.clear()


def _cache_key(description: str, model_id: str, executors: frozenset[str]) -> str:
    normalized = " ".join(description.strip().casefold().split())
    passport = "|".join(sorted(executors))
    raw = f"{PROMPT_VERSION}|{model_id}|{normalized}|{passport}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _builtin_passport(registry: EntityTypeRegistry) -> tuple[tuple[str, str], ...]:
    """Только настоящие встроенные типы — `use_builtin` не должен ссылаться
    на уже скомпилированный в этой же сессии пользовательский тип."""
    return tuple(
        sorted(
            (type_id, registry.spec(type_id).title)
            for type_id in registry.ids()
            if registry.spec(type_id).builtin
        )
    )


def _parse_llm_response(raw: str) -> CompilerOutcome:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CompilerParseError(f"LLM вернула невалидный JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CompilerParseError("LLM вернула JSON, не являющийся объектом")

    outcome = parsed.get("outcome")
    if outcome == "use_builtin":
        type_id = parsed.get("type_id")
        if not isinstance(type_id, str) or not type_id:
            raise CompilerParseError("use_builtin без непустого 'type_id'")
        marker_override = parsed.get("marker_override")
        if marker_override is not None and not isinstance(marker_override, str):
            raise CompilerParseError("'marker_override' должен быть строкой или null")
        return UseBuiltinOutcome(type_id=type_id, marker_override=marker_override or None)

    if outcome == "compile":
        spec = parsed.get("spec")
        if not isinstance(spec, dict):
            raise CompilerParseError("compile без объекта 'spec'")
        return CompileOutcome(spec=spec)

    if outcome == "ask":
        question = parsed.get("question")
        if not isinstance(question, str) or not question.strip():
            raise CompilerParseError("ask без непустого 'question'")
        options = parsed.get("options", [])
        if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
            raise CompilerParseError("'options' должен быть списком строк")
        target = parsed.get("target", "")
        if not isinstance(target, str):
            raise CompilerParseError("'target' должен быть строкой")
        return AskOutcome(question=question, options=[str(item) for item in options], target=target)

    if outcome == "cannot_compile":
        reason = parsed.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise CompilerParseError("cannot_compile без непустого 'reason'")
        return CannotCompileOutcome(reason=reason)

    raise CompilerParseError(f"неизвестное значение 'outcome': {outcome!r}")


def _attempt(
    llm: LLMProvider,
    description: str,
    executors: frozenset[str],
    builtin_types: tuple[tuple[str, str], ...],
    feedback: str,
) -> tuple[CompilerOutcome | None, str]:
    """Один вызов модели. `(outcome, "")` при успехе, `(None, текст_ошибки)` иначе."""
    messages = build_messages(
        description, executors=executors, builtin_types=builtin_types, feedback=feedback
    )
    raw = llm.complete(messages)
    try:
        outcome = _parse_llm_response(raw)
    except CompilerParseError as exc:
        return None, str(exc)

    if isinstance(outcome, CompileOutcome):
        try:
            load_type_config({"version": 1, "types": [outcome.spec]})
        except CustomTypeError as exc:
            return None, str(exc)
        detect = outcome.spec.get("detect")
        kind = detect.get("kind") if isinstance(detect, dict) else None
        if kind not in executors:
            return None, f"компилятор выбрал недоступный executor {kind!r}"
    elif isinstance(outcome, UseBuiltinOutcome):
        known_ids = {type_id for type_id, _title in builtin_types}
        if outcome.type_id not in known_ids:
            return None, f"use_builtin ссылается на неизвестный встроенный тип {outcome.type_id!r}"

    return outcome, ""


def _call_llm_once(
    llm: LLMProvider,
    description: str,
    executors: frozenset[str],
    builtin_types: tuple[tuple[str, str], ...],
    feedback: str,
) -> CompilerOutcome:
    """Основной вызов плюс ровно один ретрай на невалидный ответ (design notes, риски)."""
    outcome, error = _attempt(llm, description, executors, builtin_types, feedback)
    if outcome is not None:
        return outcome

    retry_feedback = (
        f"{feedback}\n\nОшибка предыдущего ответа: {error}"
        if feedback
        else f"Ошибка предыдущего ответа: {error}"
    )
    outcome, error = _attempt(llm, description, executors, builtin_types, retry_feedback)
    if outcome is not None:
        return outcome

    return CannotCompileOutcome(
        reason=f"не удалось получить корректный ответ модели после одного ретрая: {error}"
    )


def compile_type(
    description: str,
    *,
    llm: LLMProvider,
    registry: EntityTypeRegistry,
    executors: frozenset[str] | None = None,
    feedback: str = "",
    round_index: int = 1,
    model_id: str = "",
) -> CompilerOutcome:
    """Скомпилировать одно пользовательское описание в один из четырёх исходов.

    `round_index` считает вызывающий (граф компиляции, шаг 11) — номер
    текущей попытки, начиная с 1. При исходе `ask` на `round_index >=
    MAX_ASK_ROUNDS` компилятор сам возвращает `cannot_compile` с текстом
    последнего вопроса в `reason`: четвёртого вопроса не будет.

    Кэшируется (design notes, вопрос 5) только «чистый» первый вызов
    (`round_index == 1` и без `feedback`) и только положительный исход
    (`use_builtin`/`compile`) — промежуточные `ask`/`cannot_compile` не
    «готовая спека», кэшировать их нечего.
    """
    active_executors = executors if executors is not None else available_executors()
    builtin_types = _builtin_passport(registry)
    use_cache = round_index == 1 and not feedback
    cache_key = _cache_key(description, model_id, active_executors) if use_cache else ""
    if use_cache and cache_key in _CACHE:
        _CACHE.move_to_end(cache_key)
        return _CACHE[cache_key]

    try:
        outcome = _call_llm_once(llm, description, active_executors, builtin_types, feedback)
    except LLMError as error:
        return CannotCompileOutcome(reason=f"LLM недоступна: {error}")

    if isinstance(outcome, AskOutcome) and round_index >= MAX_ASK_ROUNDS:
        outcome = CannotCompileOutcome(
            reason=(
                f"не удалось уточнить тип за {MAX_ASK_ROUNDS} раунда(ов), "
                f"последний вопрос: {outcome.question}"
            )
        )

    if use_cache and isinstance(outcome, (UseBuiltinOutcome, CompileOutcome)):
        _CACHE[cache_key] = outcome
        _CACHE.move_to_end(cache_key)
        if len(_CACHE) > _CACHE_MAXSIZE:
            _CACHE.popitem(last=False)

    return outcome
