"""Загрузка и валидация пользовательской конфигурации типов сущностей.

Формат — `docs/plans/T1.13-entity-type-registry.md`, раздел «Пользовательская
конфигурация». Три источника опасности пользовательской регулярки — ReDoS,
переопределение встроенного типа и молчаливое совпадение с пустой строкой —
проверяются здесь же, до того как паттерн попадёт в `ConfigDetector`.

Валидатор регулярок разбирает паттерн через `re._parser.parse` (приватный, но
стабильный модуль стандартной библиотеки) и отклоняет конструкции, ведущие к
катастрофическому бэктрекингу: вложенный квантификатор (`(a+)+`) и
альтернация внутри повторения (`(a|a)*`) дают одну и ту же комбинаторную
неоднозначность движка `re`, поэтому проверяются одним правилом обхода.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from re import _constants, _parser  # type: ignore[attr-defined]
from typing import Any

import yaml

from masker.entity_types import EntityTypeSpec
from masker.model import EntityType

#: Пользовательская регулярка длиннее этого — уже не «номер договора»,
#: а конструкция, которую невозможно проверить глазами при код-ревью.
MAX_PATTERN_LEN = 200

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
_BUILTIN_IDS = frozenset(t.value for t in EntityType)
_ALLOWED_FLAG_MASK = re.IGNORECASE | re.UNICODE
_DETECT_KINDS = frozenset({"literals", "regex"})
_MATCH_MODES = frozenset({"whole_word", "substring"})


class CustomTypeError(Exception):
    """Ошибка в пользовательской конфигурации типов — файл не загружается целиком."""


@dataclass(frozen=True, slots=True)
class CustomTypeSpec:
    """`EntityTypeSpec` пользовательского типа плюс скомпилированный матчер.

    `kind` определяет, какие поля матчера заполнены содержательно: для
    `"literals"` — только `pattern` (одна альтернация экранированных
    значений с приоритетом длинного совпадения), для `"regex"` — `pattern`
    и, если задан, `context` — обязательные слова в окне ±80 символов
    вокруг совпадения (проверяется в `ConfigDetector`, не здесь).
    """

    spec: EntityTypeSpec
    kind: str  # "literals" | "regex"
    pattern: re.Pattern[str]
    context: tuple[str, ...] = ()


def load_type_config(source: Path | dict[str, Any]) -> list[CustomTypeSpec]:
    """Загрузить и провалидировать пользовательскую конфигурацию типов.

    `source` — путь к YAML-файлу (`masker.types.yaml`) либо уже разобранный
    словарь того же формата (используется в тестах и будет использован API,
    план T1.13, раздел «Где лежит»). Любое нарушение схемы или небезопасная
    регулярка останавливают загрузку целиком: `CustomTypeError` с id
    проблемного типа в тексте сообщения.
    """
    raw = _load_raw(source)
    _validate_top_level(raw)

    specs: list[CustomTypeSpec] = []
    seen_at: dict[str, int] = {}
    for index, item in enumerate(raw["types"], start=1):
        custom = _build_type(item, index)
        type_id = custom.spec.id
        if type_id in seen_at:
            raise CustomTypeError(
                f"Тип {type_id!r} объявлен дважды: запись #{seen_at[type_id]} и запись #{index}"
            )
        seen_at[type_id] = index
        specs.append(custom)
    return specs


def _load_raw(source: Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    text = source.read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise CustomTypeError(f"Конфигурация типов {source}: верхний уровень должен быть словарём")
    return loaded


def _validate_top_level(raw: dict[str, Any]) -> None:
    if raw.get("version") != 1:
        raise CustomTypeError("Конфигурация типов: поддерживается только 'version: 1'")
    types = raw.get("types")
    if not isinstance(types, list) or not types:
        raise CustomTypeError("Конфигурация типов: поле 'types' должно быть непустым списком")


def _build_type(item: Any, index: int) -> CustomTypeSpec:
    if not isinstance(item, dict):
        raise CustomTypeError(f"Запись #{index} в 'types' должна быть словарём")

    type_id = item.get("id")
    if not isinstance(type_id, str) or not _ID_RE.match(type_id):
        raise CustomTypeError(
            f"Запись #{index}: id {type_id!r} не соответствует формату "
            r"^[a-z][a-z0-9_]{2,31}$"
        )
    if type_id in _BUILTIN_IDS:
        raise CustomTypeError(
            f"Тип {type_id!r}: совпадает со встроенным типом EntityType, "
            f"переопределение встроенных типов запрещено"
        )

    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CustomTypeError(f"Тип {type_id!r}: поле 'title' должно быть непустой строкой")

    marker = item.get("marker")
    if not isinstance(marker, str) or ("{n}" not in marker and "{role}" not in marker):
        raise CustomTypeError(
            f"Тип {type_id!r}: поле 'marker' должно содержать плейсхолдер {{n}} или {{role}}"
        )

    critical = bool(item.get("critical", False))
    if critical:
        warnings.warn(
            f"Тип {type_id!r} объявлен критичным (critical: true): порог recall в "
            f"воротах поднимается до 1.0, пользовательская регулярка обязана его "
            f"держать",
            stacklevel=2,
        )

    detect = item.get("detect")
    if not isinstance(detect, dict):
        raise CustomTypeError(f"Тип {type_id!r}: поле 'detect' должно быть словарём")

    kind = detect.get("kind")
    if kind not in _DETECT_KINDS:
        raise CustomTypeError(
            f"Тип {type_id!r}: 'detect.kind' должен быть 'literals' или 'regex', получено {kind!r}"
        )

    spec = EntityTypeSpec(
        id=type_id,
        title=title,
        marker_label=_marker_label_from_template(marker),
        critical=critical,
        builtin=False,
    )

    if kind == "literals":
        pattern = _build_literal_pattern(detect, type_id)
        return CustomTypeSpec(spec=spec, kind="literals", pattern=pattern)
    return _build_regex_type(spec, detect, type_id)


def _marker_label_from_template(marker: str) -> str:
    """Извлечь короткую метку типа из шаблона маркера конфигурации.

    Итоговый маркер собирает `compose_marker` (`mask/labels.py`) из ролевой
    части и номера — этот код заполняет только `EntityTypeSpec.marker_label`,
    текстовую часть без квадратных скобок и плейсхолдеров `{role}`/`{n}`.
    """
    inner = marker.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    for placeholder in ("{role}", "{n}"):
        inner = inner.replace(placeholder, "")
    inner = re.sub(r"-{2,}", "-", inner)
    return inner.strip("-")


def _build_literal_pattern(detect: dict[str, Any], type_id: str) -> re.Pattern[str]:
    values = detect.get("values")
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(v, str) and v for v in values)
    ):
        raise CustomTypeError(
            f"Тип {type_id!r}: 'detect.values' должен быть непустым списком строк"
        )

    match_mode = detect.get("match", "whole_word")
    if match_mode not in _MATCH_MODES:
        raise CustomTypeError(
            f"Тип {type_id!r}: 'detect.match' должен быть 'whole_word' или 'substring'"
        )
    ignorecase = bool(detect.get("ignorecase", False))

    # Дедуп с сохранением порядка первого вхождения — set() тут запрещён:
    # порядок итерации str-множества не детерминирован между процессами
    # (рандомизация хэша), а сортировка ниже стабильна только при
    # детерминированном входе.
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    ordered = sorted(unique, key=len, reverse=True)

    alternation = "|".join(re.escape(v) for v in ordered)
    if match_mode == "whole_word":
        body = f"(?<![\\w])(?:{alternation})(?![\\w])"
    else:
        body = f"(?:{alternation})"
    flags = re.IGNORECASE if ignorecase else 0
    return re.compile(body, flags)


def _build_regex_type(spec: EntityTypeSpec, detect: dict[str, Any], type_id: str) -> CustomTypeSpec:
    pattern_str = detect.get("pattern")
    if not isinstance(pattern_str, str) or not pattern_str:
        raise CustomTypeError(f"Тип {type_id!r}: 'detect.pattern' должен быть непустой строкой")
    ignorecase = bool(detect.get("ignorecase", False))

    context_raw = detect.get("context", [])
    if not isinstance(context_raw, list) or not all(isinstance(c, str) and c for c in context_raw):
        raise CustomTypeError(
            f"Тип {type_id!r}: 'detect.context' должен быть списком непустых строк"
        )
    context = tuple(context_raw)

    compiled = _compile_safe_regex(pattern_str, ignorecase, type_id)
    return CustomTypeSpec(spec=spec, kind="regex", pattern=compiled, context=context)


def _compile_safe_regex(pattern_str: str, ignorecase: bool, type_id: str) -> re.Pattern[str]:
    if len(pattern_str) > MAX_PATTERN_LEN:
        raise CustomTypeError(
            f"Тип {type_id!r}: регулярное выражение длиннее {MAX_PATTERN_LEN} символов"
        )
    try:
        parsed = _parser.parse(pattern_str)
    except re.error as exc:
        raise CustomTypeError(
            f"Тип {type_id!r}: не удалось разобрать регулярное выражение: {exc}"
        ) from exc

    if parsed.state.flags & ~_ALLOWED_FLAG_MASK:
        raise CustomTypeError(
            f"Тип {type_id!r}: во встроенных флагах регулярного выражения разрешён "
            f"только IGNORECASE"
        )
    _check_pattern_safety(parsed, type_id, pattern_str, inside_repeat=False)

    flags = re.IGNORECASE if ignorecase else 0
    compiled = re.compile(pattern_str, flags)
    if compiled.fullmatch("") is not None:
        raise CustomTypeError(f"Тип {type_id!r}: регулярное выражение сопоставимо с пустой строкой")
    return compiled


def _check_pattern_safety(sub: Any, type_id: str, pattern_str: str, *, inside_repeat: bool) -> None:
    """Обойти AST паттерна и отклонить конструкции, опасные для `re`.

    Отклоняются: обратные ссылки (`GROUPREF`/`GROUPREF_EXISTS`, механизм не
    прогонит их через быстрый DFA), вложенный квантификатор и альтернация
    внутри повторения — обе дают одну и ту же комбинаторную неоднозначность
    (`(a+)+$` и `(a|a)*b` — оба взрывные, хотя только в первом есть буквально
    два вложенных `MAX_REPEAT`).
    """
    for op, av in sub:
        if op in (_constants.GROUPREF, _constants.GROUPREF_EXISTS):
            raise CustomTypeError(
                f"Тип {type_id!r}: обратные ссылки в регулярном выражении запрещены "
                f"(риск катастрофического бэктрекинга): {pattern_str!r}"
            )
        if op in (_constants.MAX_REPEAT, _constants.MIN_REPEAT):
            if inside_repeat:
                raise CustomTypeError(
                    f"Тип {type_id!r}: вложенный квантификатор в регулярном "
                    f"выражении запрещён (риск катастрофического бэктрекинга): "
                    f"{pattern_str!r}"
                )
            _min_count, _max_count, body = av
            _check_pattern_safety(body, type_id, pattern_str, inside_repeat=True)
            continue
        if op == _constants.BRANCH:
            if inside_repeat:
                raise CustomTypeError(
                    f"Тип {type_id!r}: альтернация внутри повторения запрещена "
                    f"(даёт ту же неоднозначность бэктрекинга, что и вложенный "
                    f"квантификатор): {pattern_str!r}"
                )
            _dummy, branches = av
            for branch in branches:
                _check_pattern_safety(branch, type_id, pattern_str, inside_repeat=inside_repeat)
            continue
        if op == _constants.SUBPATTERN:
            _group, add_flags, del_flags, body = av
            if (add_flags | del_flags) & ~re.IGNORECASE:
                raise CustomTypeError(
                    f"Тип {type_id!r}: во встроенных флагах регулярного выражения "
                    f"разрешён только IGNORECASE"
                )
            _check_pattern_safety(body, type_id, pattern_str, inside_repeat=inside_repeat)
            continue
        if op in (_constants.ASSERT, _constants.ASSERT_NOT):
            _direction, body = av
            _check_pattern_safety(body, type_id, pattern_str, inside_repeat=inside_repeat)
            continue
        # LITERAL, NOT_LITERAL, IN, AT, ANY и подобные — терминальные узлы,
        # вложенных квантификаторов или альтернации содержать не могут.
