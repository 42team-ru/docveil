"""Детерминированный запрос к LLM и строгий разбор его ответа."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from masker.llm import Message
from masker.model import Document, EntityType, Profile
from masker.refs import EntityIndex

# Меньшее число означает, что модель честно не знает роль. Порог намеренно
# живёт рядом со схемой ответа, а не в eval: это правило применения роли в
# рабочем графе, не порог приёмочных метрик.
MIN_LLM_ROLE_CONFIDENCE = 0.8

# Прежняя инструкция состояла из одной строки «верни JSON с profiles и
# candidates». На реальном договоре модель вернула запрос дословно обратно:
# скопировала непустой role_title, оставила пустые пустыми и не прислала
# confidence вовсе. Формально ответ был корректен, пользы — ноль. Поэтому
# инструкция обязана называть задачу, описывать каждое поле и говорить, что
# происходит с ответом дальше.
SYSTEM_PROMPT = """Ты определяешь роли сторон в российском договоре, из которого
уже извлечены персональные данные.

На вход подаётся один JSON-объект:
- entities — найденные сущности; у каждой есть ref, type и дословный text;
- profiles — только субъекты, для которых эвристика не определила роль либо
  определила её неуверенно;
- segments — текст всего документа с номерами сегментов.

Верни ровно один JSON-объект с полем profiles. Без пояснений, без markdown,
без текста вокруг.

Поле profiles — по одному элементу на каждый входной профиль:
- id — идентификатор входного профиля без изменений;
- members — список ref этого профиля, скопированный без изменений; профиль
  с изменённым составом отклоняется целиком;
- role_title — как сторона названа в самом документе: «Продавец», «Покупатель»,
  «Заказчик», «Арендатор», «Исполнитель». Главная твоя работа — заполнить
  role_title там, где он пуст. Роль бери из текста, не выдумывай отсутствующую.
  Если субъект не является стороной договора (третье лицо, должник, чьё
  имущество продают, суд, орган власти), верни пустой role_title
  и confidence 0.0;
- confidence — обязательное число от 0 до 1: твоя уверенность в role_title.
  Профиль без поля confidence отбрасывается целиком. При confidence ниже 0.8
  роль не будет назначена, поэтому верни пустой role_title и 0.0, если
  документ не даёт уверенного основания.

Поле candidates необязательно: это персональные данные из segments, которых
нет в entities. Если находок нет, верни пустой список. У кандидата обязательны
segment_order, text, type и confidence; type — одно из: {types}.
Не предлагай текст, пересекающийся с уже найденными сущностями.
""".format(types=", ".join(entity_type.value for entity_type in EntityType))

ROLE_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "profiles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "members": {"type": "array", "items": {"type": "string"}},
                    "role_title": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["id", "members", "role_title", "confidence"],
                "additionalProperties": False,
            },
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_order": {"type": "integer", "minimum": 0},
                    "text": {"type": "string"},
                    "type": {"type": "string", "enum": [item.value for item in EntityType]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["segment_order", "text", "type", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["profiles"],
    "additionalProperties": False,
}


@dataclass(slots=True)
class DecisionProfile:
    id: str
    role_title: str
    confidence: float
    members: list[str]


@dataclass(slots=True)
class Decision:
    profiles: list[DecisionProfile] = field(default_factory=list)
    candidates: list[dict[str, object]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def build_request(document: Document, profiles: list[Profile], index: EntityIndex) -> list[Message]:
    """Собрать один стабильный запрос роли для всего документа."""
    payload = {
        "entities": [
            {
                "ref": ref,
                "type": index.entity(ref).type,
                "text": index.entity(ref).text,
                "segment_order": index.entity(ref).segment_order,
            }
            for ref in index.refs()
        ],
        "profiles": [
            {
                "id": profile.id,
                "role_title": profile.role_title,
                "members": [member.ref for member in profile.members],
            }
            for profile in profiles
        ],
    }
    request = {
        **payload,
        "segments": [
            {"order": segment.order, "text": segment.text} for segment in document.segments
        ],
    }
    return [
        Message("system", SYSTEM_PROMPT),
        Message(
            "user", json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ),
    ]


def parse_response(raw: str) -> Decision:
    """Безопасно разобрать ответ модели; испорченный ответ не прерывает обработку."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return Decision(diagnostics=["LLM вернула невалидный JSON"])
    if not isinstance(parsed, dict):
        return Decision(diagnostics=["LLM вернула JSON не-объект"])
    profiles: list[DecisionProfile] = []
    diagnostics: list[str] = []
    for item in parsed.get("profiles", []):
        if not isinstance(item, dict):
            diagnostics.append("некорректный профиль LLM")
            continue
        if "confidence" not in item:
            # Молчаливый ноль неотличим от честного «не уверен»: он гарантированно
            # проигрывает структурной роли, и предложение исчезает без следа.
            diagnostics.append(f"LLM не вернула confidence для {item.get('id', '?')}")
            continue
        try:
            profiles.append(
                DecisionProfile(
                    id=str(item["id"]),
                    role_title=str(item.get("role_title", "")),
                    confidence=max(0.0, min(1.0, float(item["confidence"]))),
                    members=[str(ref) for ref in item.get("members", [])],
                )
            )
        except (KeyError, TypeError, ValueError):
            diagnostics.append("некорректные поля профиля LLM")
    candidates = [item for item in parsed.get("candidates", []) if isinstance(item, dict)]
    return Decision(profiles=profiles, candidates=candidates, diagnostics=diagnostics)


def valid_decision(decision: Decision, profiles: list[Profile], index: EntityIndex) -> Decision:
    """Отклонить изменения состава профилей, неизвестные ссылки и опасные слияния."""
    existing = {profile.id: {member.ref for member in profile.members} for profile in profiles}
    valid: list[DecisionProfile] = []
    diagnostics = list(decision.diagnostics)
    for proposal in decision.profiles:
        if proposal.id not in existing:
            diagnostics.append(f"LLM указала неизвестный профиль {proposal.id}")
            continue
        proposed = set(proposal.members)
        if not proposed <= set(index.refs()):
            diagnostics.append(f"LLM указала неизвестную сущность в {proposal.id}")
            continue
        # На этой стадии все детектированные сущности уже структурно назначены.
        # Поэтому изменение состава является и потерей, и потенциальным опасным слиянием.
        if proposed != existing[proposal.id]:
            diagnostics.append(f"LLM попыталась изменить состав {proposal.id}")
            continue
        valid.append(proposal)
    return Decision(profiles=valid, candidates=decision.candidates, diagnostics=diagnostics)
