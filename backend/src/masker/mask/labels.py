"""Русские метки типов сущностей для маркера обезличивания — машинные и человеческие.

Отдельно от `policy/agent.py::_TYPE_TITLES`: те подписи сделаны для текста
вопроса человеку («Название организации», «Банковский счёт») и не влезают в
компактный маркер вида `[ПОСТАВЩИК-ИНН-2]`. Смешивать два словаря нельзя —
изменение формулировки вопроса не должно менять уже вставленные в документ
маркеры, и наоборот.

Два параллельных словаря типов, по той же причине раздельные: `MARKER_TYPE_LABELS`
(капс, дефисы) — машинный формат `MaskGroup.marker`, контракт `eval.py`/`report`/
`validate`, трогать нельзя; `HUMAN_TYPE_LABELS` (план М4) — обычный регистр,
для `MaskGroup.canonical_label`, который печатается в PDF (`render/pdf_render.py`,
лестница отступления). DOCX по-прежнему вставляет `MaskGroup.marker` как есть.
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
    EntityType.REGISTRY_KEY: "РЕЕСТРОВЫЙ-КЛЮЧ",
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


#: Человеческая (не аббревиатурная) метка типа для читаемого маркера (план
#: М4). Отдельно и от `MARKER_TYPE_LABELS` (капс — машинный `MaskGroup.marker`,
#: контракт eval.py/report/validate, трогать который нельзя), и от
#: `entity_types.py::EntityTypeSpec.title` (формулировка для отчёта/UI) — три
#: словаря меняются по трём разным причинам, смешивать нельзя (см. докстринг
#: модуля). Настоящие аббревиатуры (ИНН, КПП, ОГРН, СНИЛС, БИК, ФЗ) остаются
#: капсом — это не «крик», а нормальное написание реквизита.
HUMAN_TYPE_LABELS: dict[str, str] = {
    EntityType.ORG_NAME: "Организация",
    EntityType.PERSON: "Представитель",
    EntityType.INN: "ИНН",
    EntityType.KPP: "КПП",
    EntityType.OGRN: "ОГРН",
    EntityType.SNILS: "СНИЛС",
    EntityType.BANK_ACCOUNT: "Расчётный счёт",
    EntityType.BIK: "БИК",
    EntityType.BANK_NAME: "Банк",
    EntityType.ADDRESS: "Адрес",
    EntityType.PHONE: "Телефон",
    EntityType.EMAIL: "Почта",
    EntityType.PASSPORT: "Паспорт",
    EntityType.CONTRACT_NUMBER: "Номер договора",
    EntityType.MONEY: "Сумма",
    EntityType.DATE: "Дата договора",
    EntityType.BIRTH_DATE: "Дата рождения",
    EntityType.SITE: "Сайт",
    EntityType.FEDERAL_LAW: "Федеральный закон",
    EntityType.REGISTRY_KEY: "Реестровый ключ",
    EntityType.CONTRACT_AMOUNT: "Сумма договора",
    EntityType.DELIVERY_PERIOD: "Срок поставки",
    EntityType.PAYMENT_TERMS: "Условия оплаты",
}


def human_type_label(
    entity_type: str,
    registry: EntityTypeRegistry | None = None,
) -> str:
    """Вернуть человеческую метку типа для читаемого маркера (план М4).

    Для встроенных типов — из ``HUMAN_TYPE_LABELS``. Для пользовательских —
    ``registry.spec().title`` (та же формулировка, что заказчик типа указал
    в конфигурации, а не выведенная из ``marker_label``). Падает ``KeyError``,
    если тип неизвестен — молчаливая заглушка спрятала бы новый тип без
    метки, а не подсказала бы, где её завести.
    """
    if entity_type in HUMAN_TYPE_LABELS:
        return HUMAN_TYPE_LABELS[entity_type]
    if registry is not None and entity_type in registry:
        return registry.spec(entity_type).title
    raise KeyError(f"Unknown entity type: {entity_type!r}")


def humanize_role(role_label: str) -> str:
    """Человеческая форма ролевой метки: обычный регистр, пробел вместо дефиса.

    ``role_label`` приходит из ``Profile.marker_label`` в машинном формате —
    капс, слова через дефис (``ЗАКАЗЧИК``, ``ФИНАНСОВОГО-УПРАВЛЯЮЩЕГО``,
    ``СТОРОНА-2`` — числовой фолбэк, когда роль не найдена в тексте
    документа). Строится он в ``profile/labels.py`` как
    ``role_title(label).upper().replace(" ", "-")``, где
    ``role_title = normalize_label(label).capitalize()`` — здесь та же
    операция в обратную сторону: нижний регистр, пробелы, заглавная только
    первая буква всей строки (``"Финансового управляющего"``, не
    ``"Финансового Управляющего"``). Пустая строка (сущность без профиля)
    возвращается как есть — добавлять роль там нечего.
    """
    if not role_label:
        return ""
    return role_label.replace("-", " ").lower().capitalize()


def compose_canonical_label(
    role_label: str,
    entity_type: str,
    number: int | None,
    registry: EntityTypeRegistry | None = None,
) -> str:
    """Собрать человекочитаемую каноническую метку группы (план М4, пункт 1).

    В отличие от ``compose_marker`` (капс, дефисы — машинный контракт
    ``MaskGroup.marker``, менять который нельзя, см. его докстринг), роль
    здесь выводится вперёд обычным регистром, слова разделены пробелом:
    ``ЗАКАЗЧИК`` + ``ФИО`` → ``"Заказчик Представитель"``, а не
    ``"ЗАКАЗЧИК-ФИО"``.

    Для ``org_name`` с известной ролью тип не добавляется вовсе: группа и
    есть эта сторона договора («Заказчик», а не «Заказчик Организация» —
    второе слово не несёт смысла, раз роль уже называет организацию). Во
    всех остальных случаях с известной ролью метка — ``"<Роль> <Тип>"``; без
    роли — просто тип (``"Номер договора"``, ``"Дата договора"``). ``number``
    добавляется только тогда, когда вызывающий код (``PlanAgent``) решил, что
    сущностей такого рода больше одной — та же асимметрия «без номера у
    единственной/с номером у нескольких», что и в ``compose_marker``.
    """
    role = humanize_role(role_label)
    type_label = human_type_label(entity_type, registry)
    if role and entity_type == EntityType.ORG_NAME:
        text = role
    elif role:
        text = f"{role} {type_label}"
    else:
        text = type_label
    if number is not None:
        text = f"{text} {number}"
    return f"[{text}]"


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


def _role_only_label(role_label: str, number: int | None) -> str:
    """Метка «только роль», без типа: ``[Заказчик]``/``[Заказчик 2]``."""
    role = humanize_role(role_label)
    text = f"{role} {number}" if number is not None else role
    return f"[{text}]"


def marker_ladder(
    group: MaskGroup,
    registry: EntityTypeRegistry | None = None,
) -> list[tuple[str, str]]:
    """Лестница отступления маркера группы (план М1 правило 4, план М4 пункт 2):

    ``[Заказчик Представитель]`` → ``[Заказчик]`` → ``[Ф1]`` → ``[Представитель]`` → ``""``.

    Пробуем от самой полной человеческой формы (``group.canonical_label``,
    план М4) к самой короткой — первая, что поместится, побеждает
    (``render/pdf_render.py``). Возвращает список ``(текст, fallback_reason)``
    от лучшего к худшему. Пустой ``fallback_reason`` у первого элемента —
    показан канонический маркер без сокращений. Рунги, совпадающие текстом с
    предыдущим (например, у сущности без роли рунг «только роль» не
    строится вовсе), пропускаются — пробовать их отдельно бессмысленно.
    """
    type_label = human_type_label(group.type, registry)
    show_number = group.marker.endswith(f"-{group.number}]")
    suffix = group.number if show_number else None

    steps: list[tuple[str, str]] = [(group.canonical_label, "")]
    if group.role_label:
        role_only = _role_only_label(group.role_label, suffix)
        if role_only != steps[-1][0]:
            steps.append((role_only, "role_only"))
    if group.compact_label and group.compact_label != steps[-1][0]:
        steps.append((group.compact_label, "compact"))
    type_only = f"[{type_label}]"
    if type_only != steps[-1][0]:
        steps.append((type_only, "type_only"))
    steps.append(("", "blank"))
    return steps
