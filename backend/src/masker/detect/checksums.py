"""Контрольные суммы российских реквизитов.

Смысл модуля: превратить «похоже на ИНН» в «это ИНН» без модели и без сети.
Регулярка на 10 цифр даёт ложные срабатывания на любом номере накладной;
регулярка плюс контрольная цифра — практически не даёт.
"""

from __future__ import annotations

_INN10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _digits(value: str) -> list[int] | None:
    stripped = value.replace(" ", "").replace("-", "")
    if not stripped.isdigit():
        return None
    return [int(c) for c in stripped]


def _weighted_mod11(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=True)) % 11 % 10


def is_valid_inn(value: str) -> bool:
    """ИНН юрлица (10 цифр) или физлица/ИП (12 цифр)."""
    d = _digits(value)
    if d is None:
        return False
    if len(d) == 10:
        return _weighted_mod11(d[:9], _INN10) == d[9]
    if len(d) == 12:
        return _weighted_mod11(d[:10], _INN11) == d[10] and _weighted_mod11(d[:11], _INN12) == d[11]
    return False


def is_valid_ogrn(value: str) -> bool:
    """ОГРН (13 цифр) или ОГРНИП (15 цифр)."""
    d = _digits(value)
    if d is None:
        return False
    if len(d) == 13:
        body = int("".join(map(str, d[:12])))
        return body % 11 % 10 == d[12]
    if len(d) == 15:
        body = int("".join(map(str, d[:14])))
        return body % 13 % 10 == d[14]
    return False


def is_valid_snils(value: str) -> bool:
    """СНИЛС: 11 цифр, последние две — контрольные."""
    d = _digits(value)
    if d is None or len(d) != 11:
        return False
    total = sum(digit * (9 - i) for i, digit in enumerate(d[:9]))
    if total < 100:
        control = total
    elif total in (100, 101):
        control = 0
    else:
        control = total % 101
        if control == 100:
            control = 0
    return control == d[9] * 10 + d[10]


def is_valid_bik(value: str) -> bool:
    """БИК: 9 цифр, форматная проверка — контрольной суммы у БИК нет и не было.

    Первые два разряда — признак учреждения Банка России (Положение ЦБ РФ
    №579-П). В обороте встречаются три: `04` — учреждения ЦБ РФ, `01` —
    с 2022 года подразделения Федерального казначейства, обслуживающие
    бюджетные счета, и `02` — операционные подразделения ЦБ, через которые
    идут счета ТОФК. Последний отсутствовал в правиле, и БИК `024501901`
    (Операционный департамент Банка России // Межрегиональное операционное
    УФК, г. Москва) оставался открытым в выходных файлах — замерено
    11.09.2026 на `arkhschool-68-183.pdf`, Р22.

    Принимать любые девять цифр нельзя: столько же разрядов у КПП, и
    правило начало бы разбирать соседний реквизит как БИК.
    """
    d = _digits(value)
    return d is not None and len(d) == 9 and d[0] == 0 and d[1] in (1, 2, 4)


def is_valid_account(account: str, bik: str) -> bool:
    """Банковский счёт (20 цифр) — проверяется только в паре с БИК.

    Ключ проверки — три цифры перед контрольной суммой: либо последние три
    цифры БИК (обычный расчётный/лицевой счёт), либо «0» + разряды 5-6 БИК
    (счёт учреждения в подразделении Банка России). Второй ключ раньше
    применялся только к счетам на `301...` (корсчета банков), но через то
    же подразделение ЦБ проходят единый казначейский счёт (`40102...`) и
    казначейские счета (`0321.../0323...`) — с тем же самым вторым ключом.
    Перечислять в коде все балансовые счета, которым нужен второй ключ, —
    значит ловить тот же дефект на следующей реформе плана счетов, поэтому
    счёт принимается, если сошёлся **хотя бы один** из двух ключей. Цена
    размена: вероятность ложного принятия у случайного 20-значного числа
    растёт примерно с 1/10 до 2/10 — для критичного типа с обязательным
    recall=1.0 это правильная сторона размена (см. план T2.2.1, Д8).
    Алгоритм контрольной суммы: Положение ЦБ РФ №579-П.
    """
    acc = _digits(account)
    b = _digits(bik)
    if acc is None or b is None or len(acc) != 20 or len(b) != 9:
        return False
    bik_s = "".join(map(str, b))
    acc_s = "".join(map(str, acc))
    weights = (7, 1, 3)

    def _checksum_ok(prefix: str) -> bool:
        control = prefix + acc_s
        total = sum(int(d) * weights[i % 3] for i, d in enumerate(control))
        return total % 10 == 0

    return _checksum_ok(bik_s[6:9]) or _checksum_ok("0" + bik_s[4:6])


def is_valid_kpp(value: str) -> bool:
    """КПП: 9 знаков, контрольной суммы нет — только формат."""
    s = value.replace(" ", "")
    if len(s) != 9 or not s[:4].isdigit() or not s[6:].isdigit():
        return False
    return all(c.isdigit() or c in "ABCEHKMNOPTX" for c in s[4:6])
