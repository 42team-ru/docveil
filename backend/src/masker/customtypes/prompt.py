"""Промпт LLM-компилятора пользовательских типов.

Никакого разбора ответа здесь нет (это `compiler.py`) — только сборка
запроса. Разделение то же, что у `masker.profile.prompt`: одно место строит
детерминированный запрос, другое — строго разбирает ответ.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from masker.llm import Message

#: Версия промпта — часть ключа кэша (`compiler.py`): правка текста промпта
#: сама инвалидирует кэш, без ручной чистки.
PROMPT_VERSION = "1"

#: Описание каждого executor'а для промпта — форма JSON, которую он ожидает
#: в `detect`, и когда его выбирать (design notes T1.13, раздел 2.4).
#: `gliner_label`/`gliner_structure` сюда не входят никогда в этом модуле:
#: паспорт передаётся из `compiler.available_executors()`, а GLiNER не
#: физически доступен компилятору, пока не подключён T1.13.1 (решение Р2
#: плана T1.13 — без мягкой деградации).
_EXECUTOR_DESCRIPTIONS: dict[str, str] = {
    "literals": (
        'literals — точный список значений. detect: {"kind": "literals", '
        '"values": ["...", "..."], "match": "whole_word"|"substring", "ignorecase": bool}. '
        "Выбирай, когда пользователь перечисляет конкретные строки (коды, названия из списка)."
    ),
    "regex": (
        'regex — регулярное выражение без якорных слов. detect: {"kind": "regex", '
        '"pattern": "...", "ignorecase": bool}. Выбирай для чёткого синтаксического шаблона '
        "(номер, код, дата в известном формате), который не нужно отличать по контексту."
    ),
    "regex_context": (
        "regex_context — то же регулярное выражение плюс якорные слова рядом со значением. "
        'detect: {"kind": "regex", "pattern": "...", "context": ["слово1", "слово2"], '
        '"ignorecase": bool}. Выбирай, когда сам формат значения неоднозначен без контекста '
        "(например, дата бывает и датой отгрузки, и датой подписания — context их различает)."
    ),
    "regex_llm_filter": (
        "regex_llm_filter — регулярное выражение находит кандидатов, а решение по каждому "
        'принимает модель по контексту вокруг совпадения. detect: {"kind": "regex_llm_filter", '
        '"pattern": "...", "ignorecase": bool}. Дорогой executor (вызов модели на каждого '
        "кандидата в документе) — выбирай, только если ни regex, ни regex_context не отличают "
        "нужные значения от похожих, но ненужных."
    ),
}

#: Не `str.format` — тело содержит буквальные JSON-примеры с фигурными
#: скобками (`{n}`, `{role}`, `{...}`), экранировать их удвоением менее
#: надёжно, чем просто склеить статичные части строкой.
_SYSTEM_PROMPT_HEADER = """Ты компилируешь пользовательское описание типа персональных \
данных в исполнимую спецификацию для системы обезличивания тендерных документов.

Доступные способы поиска (executor'ы) — используй только их, ничего другого не существует:
"""

_SYSTEM_PROMPT_BUILTIN_HEADER = """
Уже встроенные типы (не предлагай их заново своей спекой — верни use_builtin):
"""

_SYSTEM_PROMPT_FOOTER = """
Если запрос описывает что-то принципиально не сводимое ни к одному executor'у выше \
(открытый смысловой поиск без чёткого якоря или шаблона) — верни cannot_compile, \
не пытайся выдумать regex «на глаз», который совпадёт со случайным текстом.

Верни ровно один JSON-объект без пояснений, без markdown, без текста вокруг. Значение \
поля "outcome" — один из четырёх видов, форма строго такая:

1) {"outcome": "use_builtin", "type_id": "<id встроенного типа из списка выше>", \
"marker_override": "[МЕТКА-{n}]" | null}
2) {"outcome": "compile", "spec": {"id": "<строчными латиницей, ^[a-z][a-z0-9_]{2,31}$>", \
"title": "<русское название>", "marker": "[МЕТКА-{n}]", "critical": true|false, \
"detect": {...}}}
3) {"outcome": "ask", "question": "<уточняющий вопрос по-русски>", \
"options": ["вариант1", "вариант2"], "target": "<к какому описанию относится вопрос>"}
4) {"outcome": "cannot_compile", "reason": "<почему не получилось, по-русски>"}

Правила:
- id новой спеки не должен совпадать со встроенным типом и обязан быть на латинице.
- "marker" обязан содержать плейсхолдер {n} или {role} буквально в строке.
- critical: true ставь только если пропуск значения — прямая утечка (аналог ИНН/счёта),
  а не эстетика.
- Не пиши регулярку с вложенным квантификатором или альтернацией внутри повторения —
  она будет отклонена валидатором как риск катастрофического бэктрекинга.
- Если запрос уже покрыт встроенным типом (ФИО, ИНН, организация, адрес, телефон, email,
  паспорт, СНИЛС, ОГРН, КПП, БИК, банк, счёт, номер договора, сумма, дата, сайт) — верни
  use_builtin, а не свою спеку поверх него."""


def build_messages(
    description: str,
    *,
    executors: Iterable[str],
    builtin_types: Sequence[tuple[str, str]],
    feedback: str = "",
) -> list[Message]:
    """Собрать запрос на одно пользовательское описание.

    `feedback` — текст предыдущего раунда: либо ответ пользователя на
    `ask`, либо текст ошибки валидатора (единственный ретрай, `compiler.py`).
    Пустая строка — первый, «чистый» вызов.
    """
    executor_lines = "\n".join(
        f"- {name}: {_EXECUTOR_DESCRIPTIONS[name]}"
        for name in sorted(executors)
        if name in _EXECUTOR_DESCRIPTIONS
    )
    builtin_lines = (
        "\n".join(f"- {type_id}: {title}" for type_id, title in sorted(builtin_types)) or "(нет)"
    )
    system = (
        _SYSTEM_PROMPT_HEADER
        + executor_lines
        + _SYSTEM_PROMPT_BUILTIN_HEADER
        + builtin_lines
        + _SYSTEM_PROMPT_FOOTER
    )
    payload: dict[str, str] = {"description": description}
    if feedback:
        payload["feedback"] = feedback
    return [
        Message("system", system),
        Message(
            "user", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ),
    ]
