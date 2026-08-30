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
    """БИК: 9 цифр, первые две — код страны 04."""
    d = _digits(value)
    return d is not None and len(d) == 9 and d[0] == 0 and d[1] == 4


def is_valid_account(account: str, bik: str) -> bool:
    """Банковский счёт (20 цифр) — проверяется только в паре с БИК.

    Расчётный счёт приписывается к последним трём цифрам БИК,
    корреспондентский — к «0» плюс код региона из БИК.
    Алгоритм: Положение ЦБ РФ №579-П.
    """
    acc = _digits(account)
    b = _digits(bik)
    if acc is None or b is None or len(acc) != 20 or len(b) != 9:
        return False
    bik_s = "".join(map(str, b))
    acc_s = "".join(map(str, acc))

    # Определяем ключ: для корр. счёта (301...) используем "0" + региональный код БИК
    prefix = "0" + bik_s[4:6] if acc_s.startswith("301") else bik_s[6:9]

    control = prefix + acc_s
    weights = (7, 1, 3)
    total = sum(int(d) * weights[i % 3] for i, d in enumerate(control))
    return total % 10 == 0


def is_valid_kpp(value: str) -> bool:
    """КПП: 9 знаков, контрольной суммы нет — только формат."""
    s = value.replace(" ", "")
    if len(s) != 9 or not s[:4].isdigit() or not s[6:].isdigit():
        return False
    return all(c.isdigit() or c in "ABCEHKMNOPTX" for c in s[4:6])
