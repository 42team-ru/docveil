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

import re
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
    EntityType.POWER_OF_ATTORNEY_NUMBER: "НОМЕР-ДОВЕРЕННОСТИ",
    EntityType.IP_ADDRESS: "IP-АДРЕС",
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
    EntityType.DATE: "Дата",
    EntityType.BIRTH_DATE: "Дата рождения",
    EntityType.SITE: "Сайт",
    EntityType.FEDERAL_LAW: "Федеральный закон",
    EntityType.REGISTRY_KEY: "Реестровый ключ",
    EntityType.POWER_OF_ATTORNEY_NUMBER: "Номер доверенности",
    EntityType.IP_ADDRESS: "IP-адрес",
    EntityType.CONTRACT_AMOUNT: "Сумма договора",
    EntityType.DELIVERY_PERIOD: "Срок поставки",
    EntityType.PAYMENT_TERMS: "Условия оплаты",
}

#: Типы условий описывают сам договор, а не одну из его сторон. 11.09.2026:
#: явная классификация не даёт контекстному профилю приклеить «Сторона N» к
#: сроку, цене или номеру сделки и делает правило проверяемым в одном месте.
DOCUMENT_OWNED_TYPES: frozenset[str] = frozenset(
    {
        EntityType.CONTRACT_NUMBER,
        EntityType.CONTRACT_AMOUNT,
        EntityType.DELIVERY_PERIOD,
        EntityType.PAYMENT_TERMS,
        EntityType.DATE,
    }
)


def belongs_to_subject(entity_type: str) -> bool:
    """Принадлежит ли тип стороне, а не документу как сделке."""
    return entity_type not in DOCUMENT_OWNED_TYPES


def is_anonymous_role(role_label: str) -> bool:
    """Распознать технический фолбэк профиля, который нельзя печатать человеку."""
    return role_label.startswith("СТОРОНА-")


def contextual_type_label(entity_type: str, text: str, start: int, end: int) -> str:
    """Вернуть смысловую подпись реквизита по ближайшему контексту.

    Тип ``date`` намеренно остаётся общим контрактом детектора: один и тот
    же формат даты встречается у договора, доверенности и лицензии. Здесь,
    на границе с читаемой маской, контекст превращается в подпись, не меняя
    тип, правила поиска или политику.
    """
    # 11.09.2026: подпись должна объяснять значение, а не выдавать каждую
    # дату за дату договора — это устраняет ложную семантику в PDF и легенде.
    before = text[max(0, start - 100) : start].casefold()
    after = text[end : min(len(text), end + 100)].casefold()
    nearby = before + " " + after
    if entity_type == EntityType.DATE:
        if re.search(r"срок\s+лицензи|лицензи\w*\s*[—-]?\s*до\s*$", before):
            return "Срок действия лицензии"
        if "доверенност" in before:
            return "Дата доверенности"
        if "переоформлен" in before:
            return "Дата переоформления лицензии"
        if "регистрационн" in before:
            return "Дата регистрации лицензии"
        # 11.09.2026: строка лицензии начинается с номера «Л…», а слово
        # «лицензия» часто находится только в предыдущем абзаце преамбулы.
        # Формат номера уже проверен детектором, поэтому это надёжный признак
        # даты выдачи, а не угадывание по произвольной букве «Л».
        if re.search(r"Л\d{3}-\d{5}-\d{2}/\d{8}", before, re.I):
            return "Дата выдачи лицензии"
        if "постановк" in nearby and "уч[её]т" in nearby:
            return "Дата постановки на учёт"
        if "лицензи" in nearby:
            return "Дата выдачи лицензии"
        if "договор" in nearby or "контракт" in nearby:
            return "Дата договора"
        return "Дата"
    if entity_type == EntityType.REGISTRY_KEY:
        # 12.09.2026: в строке реквизитов часто рядом стоят ОКТМО, ОКАТО и
        # ОКПО. Выбирать первый встретившийся в окне нельзя: ОКАТО тогда
        # получал подпись ОКПО. Ближайшая метка слева однозначно задаёт код.
        code_labels = (
            ("икз", "Идентификационный код закупки"),
            ("кбк", "КБК"),
            ("окпо", "ОКПО"),
            ("октмо", "ОКТМО"),
            ("окато", "ОКАТО"),
        )
        _position, label = max(
            ((before.rfind(token), title) for token, title in code_labels),
            default=(-1, ""),
        )
        if _position >= 0:
            return label
        if "икз" in before or ("идентификационн" in before and "закупк" in before):
            return "Идентификационный код закупки"
        if "кбк" in before:
            return "КБК"
        if "окпо" in before:
            return "ОКПО"
        if "октмо" in before:
            return "ОКТМО"
        if "окато" in before:
            return "ОКАТО"
        if (
            "лицензи" in nearby
            or re.fullmatch(r"Л\d{3}-\d{5}-\d{2}/\d{8}", text[start:end], re.I)
            or re.search(r"Л\d{3}-\d{5}-\d{2}/\d{8}", before, re.I)
        ):
            return "Номер лицензии"
    return human_type_label(entity_type)


_SHORT_TYPE_LABELS: dict[str, str] = {
    "Дата доверенности": "Довер.",
    "Дата выдачи лицензии": "Выд. лиц.",
    "Дата переоформления лицензии": "Переоф. лиц.",
    "Дата регистрации лицензии": "Рег. лиц.",
    "Срок действия лицензии": "Срок лиц.",
    "Дата постановки на учёт": "Учёт",
    "Дата договора": "Дата дог.",
    "Дата": "Дата",
    "Идентификационный код закупки": "ИКЗ",
    "Номер лицензии": "Лицензия",
    "Номер доверенности": "Ном. дов.",
    "Представитель": "Предст.",
    "Организация": "Орг.",
    "Реестровый ключ": "Ключ",
}


def short_type_label(label: str) -> str:
    """Сократить смысловую подпись без буквенно-цифрового шифра."""
    # 11.09.2026: `[Довер. 2]` читается без легенды, в отличие от `[ДА2]`.
    return _SHORT_TYPE_LABELS.get(label, label)


def short_role_label(role_label: str) -> str:
    """Дать роли короткую, но различимую форму для узкой PDF-метки."""
    # 11.09.2026: роль различает стороны сильнее типа; удалять её нельзя.
    role = humanize_role(role_label)
    if role == "Заказчик":
        return "Зак."
    if role == "Исполнитель":
        return "Исп."
    return role[:4] + "." if len(role) > 4 else role


def label_number(label: str) -> int | None:
    """Вернуть напечатанный в метке завершающий номер, если он есть."""
    match = re.search(r"(\d+)(?:\])?$", label)
    return int(match.group(1)) if match else None


def align_compact_label_number(compact_label: str, canonical_label: str) -> str:
    """Привести номер короткой метки к номеру канонической формы.

    Номер — часть идентичности группы, а не расходный счётчик ступени
    отступления. Сокращать можно тип или роль, но не переназывать группу.
    """
    compact_stem = re.sub(r"\d+\]$", "]", compact_label)
    number = label_number(canonical_label)
    if number is None:
        return compact_stem
    return f"{compact_stem[:-1]}{number}]"


def compact_type_code(entity_type: str, registry: EntityTypeRegistry | None = None) -> str:
    """Вернуть короткий различитель типа для метки с уже названной ролью."""
    # 11.09.2026: роль занимает главное место; один-два символа типа сохраняют
    # различие реквизитов и влезают туда, где полное «Расчётный счёт» не влезает.
    # Ключ — строка, а не `EntityType`: сюда приходят и пользовательские типы,
    # которых в перечислении нет. Без явной аннотации mypy выводит тип ключа
    # по литералам перечисления и ругается на `get(entity_type, ...)`.
    labels: dict[str, str] = {
        EntityType.INN: "И",
        EntityType.KPP: "К",
        EntityType.OGRN: "ОГ",
        EntityType.PERSON: "П",
        EntityType.ORG_NAME: "ОР",
        EntityType.BANK_ACCOUNT: "С",
        EntityType.BIK: "Б",
        EntityType.ADDRESS: "А",
        EntityType.EMAIL: "Э",
        EntityType.PASSPORT: "ПС",
        EntityType.PHONE: "Т",
        EntityType.CONTRACT_NUMBER: "Д",
        EntityType.POWER_OF_ATTORNEY_NUMBER: "В",
        EntityType.MONEY: "С",
        EntityType.DATE: "ДТ",
    }
    return labels.get(entity_type, short_type_label(human_type_label(entity_type, registry))[:2])


def minimum_marker_label(
    group: MaskGroup,
    registry: EntityTypeRegistry | None = None,
) -> str:
    """Вернуть последнюю текстовую ступень, сохраняющую сторону и вид значения.

    12.09.2026: узкие ячейки реального PDF (вплоть до 16.6 pt) не вмещают
    даже ``[№ дов. 1]``. Пустая жёлтая область не объясняет читателю ничего,
    поэтому перед ``blank`` остаётся короткая, но различимая подпись:
    ``[ИП1]`` — исполнитель-представитель №1, ``[В1]`` — доверенность №1.
    """
    role = ""
    if group.role_label and not is_anonymous_role(group.role_label):
        role = short_role_label(group.role_label)[:1]
    # Номер печатается только если он есть и в канонической форме: у
    # единственного номера договора ``[Д]`` не должен притворяться
    # «договором №1» и ломать связь подписи с легендой.
    number = label_number(group.canonical_label)
    suffix = str(number) if number is not None else ""
    return f"[{role}{compact_type_code(group.type, registry)}{suffix}]"


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
    display_type_label: str | None = None,
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
    # 11.09.2026: техническая «СТОРОНА-N» не объясняет читателю ничего;
    # оставляем нейтральную метку типа с устойчивым номером профиля.
    role = (
        ""
        if is_anonymous_role(role_label) or not belongs_to_subject(entity_type)
        else humanize_role(role_label)
    )
    type_label = display_type_label or human_type_label(entity_type, registry)
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
    ordered_types: list[tuple[object, str] | tuple[object, str, str | None]],
    registry: EntityTypeRegistry | None = None,
) -> dict[object, str]:
    """Построить короткие, но читаемые метки групп.

    ``ordered_types`` — пары (ключ группы, тип сущности) в порядке первого
    появления группы в документе. Номер внутри кода — сквозной по всему
    документу для данного типа, **не** по паре (роль, тип): именно поэтому
    `[ПОСТАВЩИК-ФИО-1]` и `[ПОКУПАТЕЛЬ-ФИО-1]` (одинаковый номер внутри
    своей пары) получают разные компактные метки `[Ф1]`/`[Ф2]` — два
    профиля с разными ролями никогда не схлопываются в одну короткую метку
    (план М1, критерий приёмки).
    """
    normalized = [(item[0], item[1], item[2] if len(item) == 3 else None) for item in ordered_types]
    labels = [
        label or human_type_label(entity_type, registry) for _key, entity_type, label in normalized
    ]
    total_by_label = {label: labels.count(label) for label in labels}
    seq_by_label: dict[str, int] = {}
    result: dict[object, str] = {}
    for key, entity_type, label in normalized:
        display = label or human_type_label(entity_type, registry)
        seq_by_label[display] = seq_by_label.get(display, 0) + 1
        suffix = f" {seq_by_label[display]}" if total_by_label[display] > 1 else ""
        # 11.09.2026: номер нужен только при нескольких одноимённых значениях;
        # иначе он удлиняет подпись, не добавляя читателю различающей информации.
        result[key] = f"[{short_type_label(display)}{suffix}]"
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
    steps: list[tuple[str, str]] = [(group.canonical_label, "")]
    # 11.09.2026: ступень «только роль» скрывала, кто именно является
    # представителем/реквизитом; короткая смысловая метка ниже сохраняет роль
    # значения и потому безопаснее для читаемости договора.
    if group.compact_label and group.compact_label != steps[-1][0]:
        steps.append((group.compact_label, "compact"))
    minimum = minimum_marker_label(group, registry)
    if minimum and minimum != steps[-1][0]:
        steps.append((minimum, "minimal"))
    steps.append(("", "blank"))
    return steps
