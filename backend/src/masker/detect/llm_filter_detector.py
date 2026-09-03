"""Executor `regex_llm_filter`: регулярка ищет кандидатов, LLM решает по контексту.

Единственный детектор проекта, который зовёт `LLMProvider` (`masker.llm`) на
каждый *уникальный* кандидат, а не на весь сегмент/документ — годится только
для пользовательских типов, где синтаксис стабилен (значит регулярка
надёжно находит кандидатов), а решает семантика (design notes T1.13,
таблица 2.4). Бюджет вызовов и дедупликация — обязательные ограничители,
без них цена прогона документа не предсказуема.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from masker.detect.normalize import normalize_value
from masker.llm import LLMError, LLMProvider, Message
from masker.model import Document, Entity, Source
from masker.typeconfig import CustomTypeError, CustomTypeSpec

#: Бюджет обращений к LLM на документ (design notes T1.13, раздел 2.7).
#: Считается по числу *уникальных* пар (тип, нормализованное значение), не
#: по числу вхождений — иначе один и тот же номер, повторённый в футере на
#: каждой странице, исчерпывал бы бюджет сам по себе.
MAX_LLM_FILTER_CALLS_PER_DOCUMENT = 500

#: Окно контекста вокруг кандидата, в символах в каждую сторону — тот же
#: формат, что у якорных слов `regex_context` в `detect/config_detector.py`,
#: но здесь окно строится автоматически, не из слов пользователя.
CONTEXT_WINDOW_CHARS = 80

#: confidence решения модели — ниже правил и провалидированной регулярки без
#: фильтра (`ConfigDetector.REGEX_CONFIDENCE`): итоговое решение зависит не
#: только от синтаксиса, но и от интерпретации LLM.
LLM_FILTER_CONFIDENCE = 0.7

_SYSTEM_PROMPT = (
    "Тебе показан кандидат на персональные/платёжные данные, найденный регулярным "
    "выражением, и окно текста документа вокруг него. Верни ровно один JSON-объект "
    'без пояснений: {"mask": true} — если это настоящее значение искомого типа и его '
    'нужно замаскировать, {"mask": false} — если это похожий, но нерелевантный текст '
    "(ложное совпадение регулярки, например номер из другого контекста)."
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    spec: CustomTypeSpec
    segment_order: int
    start: int
    end: int
    text: str
    context: str


class LlmFilterDetector:
    """Провалидированная регулярка находит кандидатов, `LLMProvider` — решает.

    Приоритет — как у `ConfigDetector` (95): регулярка пользователя уже
    прошла AST-валидатор, разница только в том, кто разрешает неоднозначность
    внутри найденного синтаксиса.
    """

    name = "llm_filter"
    source = Source.LLM
    priority = 95

    def __init__(self, specs: Sequence[CustomTypeSpec], llm: LLMProvider) -> None:
        self._specs = [item for item in specs if item.kind == "regex_llm_filter"]
        self._llm = llm
        self.types: frozenset[str] = frozenset(item.spec.id for item in self._specs)

    def detect(self, document: Document) -> list[Entity]:
        candidates = self._collect_candidates(document)
        grouped = _group_by_key(candidates)

        if len(grouped) > MAX_LLM_FILTER_CALLS_PER_DOCUMENT:
            raise CustomTypeError(
                f"regex_llm_filter: {len(grouped)} уникальных кандидатов превышают "
                f"бюджет {MAX_LLM_FILTER_CALLS_PER_DOCUMENT} обращений к LLM на документ"
            )

        entities: list[Entity] = []
        for occurrences in grouped.values():
            if not self._decide(occurrences[0]):
                continue
            entities.extend(_to_entity(item) for item in occurrences)
        return sorted(
            entities, key=lambda item: (item.segment_order, item.start, item.end, item.type)
        )

    def _collect_candidates(self, document: Document) -> list[_Candidate]:
        found: list[_Candidate] = []
        for spec in self._specs:
            assert spec.pattern is not None
            for segment in document.segments:
                for match in spec.pattern.finditer(segment.text):
                    window_start = max(0, match.start() - CONTEXT_WINDOW_CHARS)
                    window_end = min(len(segment.text), match.end() + CONTEXT_WINDOW_CHARS)
                    found.append(
                        _Candidate(
                            spec=spec,
                            segment_order=segment.order,
                            start=match.start(),
                            end=match.end(),
                            text=match.group(),
                            context=segment.text[window_start:window_end],
                        )
                    )
        return found

    def _decide(self, candidate: _Candidate) -> bool:
        messages = _build_messages(candidate)
        try:
            raw = self._llm.complete(messages)
        except LLMError:
            # Сеть недоступна — тихая утечка дороже лишней маски: решаем "да".
            return True
        return _parse_decision(raw)


def _key(candidate: _Candidate) -> tuple[str, str]:
    return candidate.spec.spec.id, normalize_value(candidate.spec.spec.id, candidate.text)


def _group_by_key(candidates: Sequence[_Candidate]) -> dict[tuple[str, str], list[_Candidate]]:
    grouped: dict[tuple[str, str], list[_Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(_key(candidate), []).append(candidate)
    return grouped


def _build_messages(candidate: _Candidate) -> list[Message]:
    payload = {
        "type": candidate.spec.spec.id,
        "candidate": candidate.text,
        "context": candidate.context,
    }
    return [
        Message("system", _SYSTEM_PROMPT),
        Message(
            "user", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ),
    ]


def _parse_decision(raw: str) -> bool:
    """Неразборчивый ответ — решение "да": ложный негатив здесь равен утечке."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return True
    if not isinstance(parsed, dict):
        return True
    value = parsed.get("mask")
    if not isinstance(value, bool):
        return True
    return value


def _to_entity(candidate: _Candidate) -> Entity:
    return Entity(
        type=candidate.spec.spec.id,
        text=candidate.text,
        segment_order=candidate.segment_order,
        start=candidate.start,
        end=candidate.end,
        source=Source.LLM,
        confidence=LLM_FILTER_CONFIDENCE,
        normalized=normalize_value(candidate.spec.spec.id, candidate.text),
    )
