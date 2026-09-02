"""Детерминированный запрос к LLM и строгий разбор его ответа."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from masker.llm import Message
from masker.model import Document, EntityType, Profile
from masker.profile.blocks import ContextBlock, block_text
from masker.refs import EntityIndex

LLM_BATCH_CHARS = 6000

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
- profiles — сущности, сгруппированные по субъектам; пустой role_title значит,
  что роль не удалось определить по структуре документа;
- blocks — фрагменты документа, где встречаются эти сущности; segments
  перечисляет номера сегментов блока.

Верни ровно один JSON-объект с полями profiles и candidates. Без пояснений,
без markdown, без текста вокруг.

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
  Профиль без поля confidence отбрасывается целиком. Роль применяется, только
  если твоя уверенность строго выше уже имеющейся, поэтому 0.0 означает
  «оставить как есть».

Поле candidates — персональные данные, которые видны в blocks, но отсутствуют
в entities. По одному объекту на находку:
- segment_order — номер сегмента, где встретился текст, из segments
  соответствующего блока;
- text — фрагмент этого сегмента, скопированный посимвольно; несовпадающий
  дословно кандидат отбрасывается;
- type — одно из значений: {types};
- confidence — число от 0 до 1.
Не предлагай текст, пересекающийся с уже найденными сущностями. Если находок
нет, верни пустой список.""".format(
    types=", ".join(entity_type.value for entity_type in EntityType)
)


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


def build_request(
    document: Document, profiles: list[Profile], blocks: list[ContextBlock], index: EntityIndex
) -> list[list[Message]]:
    """Собрать стабильные пачки запроса, разделяя только по объёму текста."""
    payload = {
        "entities": [
            {
                "ref": ref,
                "type": index.entity(ref).type.value,
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
    # Модели нечего решать по блокам без сущностей — отправка всего документа
    # стоит лишних денег и лишний раз выносит текст наружу.
    chunks = [(block, block_text(document.segments, block)) for block in blocks if block.entities]
    batches: list[list[dict[str, object]]] = [[]]
    length = 0
    for block, text in chunks:
        if batches[-1] and length + len(text) > LLM_BATCH_CHARS:
            batches.append([])
            length = 0
        batches[-1].append(
            {
                "id": block.id,
                "label": block.label,
                "heading": block.heading,
                # Без номеров сегментов кандидату не на что сослаться:
                # segment_order известен только по entities, а находка модели —
                # как раз то, чего в entities нет.
                "segments": [span.segment_order for span in block.spans],
                "text": text,
            }
        )
        length += len(text)
    messages: list[list[Message]] = []
    for batch in batches:
        request = {**payload, "blocks": batch}
        messages.append(
            [
                Message("system", SYSTEM_PROMPT),
                Message(
                    "user",
                    json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            ]
        )
    return messages


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
