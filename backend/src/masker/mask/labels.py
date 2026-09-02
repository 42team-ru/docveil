"""Короткие русские метки типов сущностей для маркера обезличивания.

Отдельно от `policy/agent.py::_TYPE_TITLES`: те подписи сделаны для текста
вопроса человеку («Название организации», «Банковский счёт») и не влезают в
компактный маркер вида `[ПОСТАВЩИК-ИНН-2]`. Смешивать два словаря нельзя —
изменение формулировки вопроса не должно менять уже вставленные в документ
маркеры, и наоборот.
"""

from __future__ import annotations

from masker.model import EntityType

#: Короткая метка типа для маркера. Обязана покрывать все члены `EntityType`
#: — иначе новый тип получит вместо метки KeyError при сборке плана, а не
#: тихую заглушку.
MARKER_TYPE_LABELS: dict[EntityType, str] = {
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
    EntityType.SITE: "САЙТ",
}


def type_marker_label(entity_type: EntityType) -> str:
    """Вернуть короткую метку типа для маркера.

    Падает `KeyError`, если тип не заведён в `MARKER_TYPE_LABELS` — тихая
    заглушка здесь хуже падения, см. докстринг словаря.
    """
    return MARKER_TYPE_LABELS[entity_type]


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
