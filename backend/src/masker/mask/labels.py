"""Короткие русские метки типов сущностей для маркера обезличивания.

Отдельно от `policy/agent.py::_TYPE_TITLES`: те подписи сделаны для текста
вопроса человеку («Название организации», «Банковский счёт») и не влезают в
компактный маркер вида `[ПОСТАВЩИК-ИНН-2]`. Смешивать два словаря нельзя —
изменение формулировки вопроса не должно менять уже вставленные в документ
маркеры, и наоборот.
"""

from __future__ import annotations

from collections.abc import Iterable

from masker.entity_types import EntityTypeRegistry
from masker.model import EntityType, MaskGroup

#: Короткая метка типа для маркера. Обязана покрывать все члены `EntityType`
#: — иначе новый тип получит вместо метки KeyError при сборке плана, а не
#: тихую заглушку.
MARKER_TYPE_LABELS: dict[str, str] = {
    EntityType.ORG_NAME: "ОРГАНИЗАЦИЯ",
    EntityType.PERSON: "ФИО",
    EntityType.INN: "ИНН",
    EntityType.KPP: "КПП",
    EntityType.OGRN: "ОГРН",
    EntityType.SNILS: "СНИЛС",
    EntityType.BANK_ACCOUNT: "СЧЁТ",
    EntityType.BIK: "БИК",
    EntityType.BANK_NAME: "БАНК",
    EntityType.ADDRESS: "АДРЕС",
    EntityType.PHONE: "ТЕЛЕФОН",
    EntityType.EMAIL: "ПОЧТА",
    EntityType.PASSPORT: "ПАСПОРТ",
    EntityType.CONTRACT_NUMBER: "ДОГОВОР",
    EntityType.MONEY: "СУММА",
    EntityType.DATE: "ДАТА",
    EntityType.BIRTH_DATE: "РОЖДЕНИЕ",
    EntityType.SITE: "САЙТ",
    EntityType.FEDERAL_LAW: "ФЗ",
    EntityType.CONTRACT_AMOUNT: "СУММА-ДОГОВОРА",
    EntityType.DELIVERY_PERIOD: "СРОК-ПОСТАВКИ",
    EntityType.PAYMENT_TERMS: "УСЛОВИЯ-ОПЛАТЫ",
}


def type_marker_label(
    entity_type: str,
    registry: EntityTypeRegistry | None = None,
) -> str:
    """Вернуть короткую метку типа для маркера.

    Для встроенных типов — из MARKER_TYPE_LABELS. Для пользовательских —
    из registry.spec().marker_label. Падает KeyError, если тип неизвестен.
    """
    if entity_type in MARKER_TYPE_LABELS:
        return MARKER_TYPE_LABELS[entity_type]
    if registry is not None and entity_type in registry:
        return registry.spec(entity_type).marker_label
    raise KeyError(f"Unknown entity type: {entity_type!r}")


def compose_marker(role_label: str, type_label: str, number: int | None) -> str:
    """Собрать строку маркера из ролевой части, типовой метки и номера.

    Пустая `role_label` (сущность без профиля) не добавляет часть — маркер
    получается вида `[ИНН-2]` вместо выдуманного `[СТОРОНА-?-ИНН-2]`.
    Присутствие `number` в маркере решает вызывающий код (`PlanAgent`):
    здесь `None` всегда означает «без суффикса», а любое число — суффикс,
    даже единица. Асимметрия «первый без номера, второй с номером» внутри
    одной группы запрещена планом T1.6 и обеспечивается на стороне вызова.
    """
    parts = [part for part in (role_label, type_label) if part]
    if number is not None:
        parts.append(str(number))
    return "[" + "-".join(parts) + "]"


def assign_type_codes(
    types: Iterable[str],
    registry: EntityTypeRegistry | None = None,
) -> dict[str, str]:
    """Дать каждому типу из ``types`` короткий буквенный код, уникальный
    среди всех типов сразу (план М1, критерий 2: сокращённые маркеры двух
    разных сущностей никогда не совпадают).

    Начинаем с одной буквы метки типа (``ФИО`` → ``Ф``) и, если код уже
    занят другим типом (``ОРГАНИЗАЦИЯ`` и ``ОГРН`` оба начинаются на «О»),
    берём на букву больше (``ОГ`` против ``ОР``), пока код не станет
    свободен. Порядок обхода — по отсортированному id типа, а не по порядку
    первого появления в документе: код не должен зависеть от того, какая
    сущность встретилась раньше, иначе один и тот же документ, обработанный
    дважды, но с сущностями в разном порядке подачи детектору, получил бы
    разные коды (риск нарушить детерминизм отчёта).
    """
    used: set[str] = set()
    codes: dict[str, str] = {}
    for entity_type in sorted(set(types)):
        base = type_marker_label(entity_type, registry)
        letters = [ch for ch in base if ch.isalpha()]
        code = ""
        for length in range(1, len(letters) + 1):
            candidate = "".join(letters[:length])
            if candidate not in used:
                code = candidate
                break
        if not code:
            # Не должно происходить у нормальных меток (буквы совпадающих
            # типов не могут полностью совпасть, если сами метки различны),
            # но не молчим, а гарантируем уникальность числовым хвостом.
            suffix = 1
            candidate = f"{base}{suffix}"
            while candidate in used:
                suffix += 1
                candidate = f"{base}{suffix}"
            code = candidate
        used.add(code)
        codes[entity_type] = code
    return codes


def assign_compact_labels(
    ordered_types: list[tuple[object, str]],
    registry: EntityTypeRegistry | None = None,
) -> dict[object, str]:
    """Построить `compact_label` для каждой группы — вида `[Ф1]`, `[Ф2]`, `[О1]`.

    ``ordered_types`` — пары (ключ группы, тип сущности) в порядке первого
    появления группы в документе. Номер внутри кода — сквозной по всему
    документу для данного типа, **не** по паре (роль, тип): именно поэтому
    `[ПОСТАВЩИК-ФИО-1]` и `[ПОКУПАТЕЛЬ-ФИО-1]` (одинаковый номер внутри
    своей пары) получают разные компактные метки `[Ф1]`/`[Ф2]` — два
    профиля с разными ролями никогда не схлопываются в одну короткую метку
    (план М1, критерий приёмки).
    """
    distinct_types = {entity_type for _key, entity_type in ordered_types}
    codes = assign_type_codes(distinct_types, registry)
    seq_by_type: dict[str, int] = {}
    result: dict[object, str] = {}
    for key, entity_type in ordered_types:
        seq_by_type[entity_type] = seq_by_type.get(entity_type, 0) + 1
        result[key] = f"[{codes[entity_type]}{seq_by_type[entity_type]}]"
    return result


def _abbreviate_role(role_label: str, length: int) -> str:
    """Первые ``length`` букв роли, без цифр и дефисов-разделителей."""
    letters = [ch for ch in role_label if ch.isalpha()]
    return "".join(letters[:length]) or role_label[:length]


def marker_ladder(
    group: MaskGroup,
    registry: EntityTypeRegistry | None = None,
) -> list[tuple[str, str]]:
    """Лестница отступления маркера группы (план М1, правило 4):

    `[ПОСТАВЩИК-ФИО-1]` → `[ПОСТ-ФИО-1]` → `[П-ФИО-1]` → `[Ф1]` → `ФИО` → ``""``.

    Возвращает список ``(текст, fallback_reason)`` от лучшего к худшему.
    Пустой ``fallback_reason`` у первого элемента — показан канонический
    маркер без сокращений. Рунги, совпадающие текстом с предыдущим
    (например, у сущности без роли рунги 2/3 равны канонической метке),
    пропускаются — пробовать их отдельно бессмысленно.
    """
    type_label = type_marker_label(group.type, registry)
    show_number = group.marker.endswith(f"-{group.number}]")
    suffix = group.number if show_number else None

    steps: list[tuple[str, str]] = [(group.canonical_label, "")]
    if group.role_label:
        for role_variant, reason in (
            (_abbreviate_role(group.role_label, 4), "role_short"),
            (_abbreviate_role(group.role_label, 1), "role_initial"),
        ):
            candidate = compose_marker(role_variant, type_label, suffix)
            if candidate != steps[-1][0]:
                steps.append((candidate, reason))
    if group.compact_label and group.compact_label != steps[-1][0]:
        steps.append((group.compact_label, "compact"))
    if type_label != steps[-1][0]:
        steps.append((type_label, "type_only"))
    steps.append(("", "blank"))
    return steps
