"""Разбор и валидация календарных дат (план T1.15, шаг 1).

Отдельный модуль без зависимостей на другой код `detect/`: `normalize.py`
импортирует его для ISO-ключа согласованности (`14.10.1986` == `14 октября
1986`), `dates.py` — для детекции. Прямые импорты `normalize ↔ dates`
создали бы цикл, поэтому разбор живёт отдельно.

Никаких `datetime.date.today()`: диапазон валидных лет — константа, иначе
результат разбора зависел бы от дня прогона (детерминизм, `AGENTS.md`).
"""

from __future__ import annotations

from datetime import date

MIN_YEAR = 1900
MAX_YEAR = 2100

#: Родительный падеж — форма, в которой месяц стоит в дате «10 января 2025».
#: Именительный — на случай текстов, где дата записана как «Январь 2025»
#: (сейчас такие не ловим, но нормализация от них не должна падать).
#: Ключ — форма в тексте (после `casefold` и замены «ё»→«е»), значение —
#: номер месяца. Замену «ё» делаем здесь, чтобы вызывающий не думал о ней.
_MONTHS: dict[str, int] = {
    # январь
    "января": 1,
    "январь": 1,
    # февраль
    "февраля": 2,
    "февраль": 2,
    # март
    "марта": 3,
    "март": 3,
    # апрель
    "апреля": 4,
    "апрель": 4,
    # май
    "мая": 5,
    "май": 5,
    # июнь
    "июня": 6,
    "июнь": 6,
    # июль
    "июля": 7,
    "июль": 7,
    # август
    "августа": 8,
    "август": 8,
    # сентябрь
    "сентября": 9,
    "сентябрь": 9,
    # октябрь
    "октября": 10,
    "октябрь": 10,
    # ноябрь
    "ноября": 11,
    "ноябрь": 11,
    # декабрь
    "декабря": 12,
    "декабрь": 12,
}


def month_number(word: str) -> int | None:
    """Номер месяца по слову любой поддерживаемой падежной формы или ``None``."""
    return _MONTHS.get(word.casefold().replace("ё", "е"))


def parse_date(day: int, month: int, year: int) -> date | None:
    """Собрать дату из трёх целых или вернуть ``None`` при невозможной комбинации.

    Проверка через `datetime.date`, а не самописная арифметика:
    31 февраля и 29 февраля не-високосного года отбрасываются сразу,
    без списков дней по месяцам.
    """
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_literal(text: str) -> date | None:
    """Разобрать одну строку в дату; ``None``, если формат не подходит.

    Поддерживаются формы:

    * ``dd.mm.yyyy`` — `14.10.1986`
    * ``dd/mm/yyyy`` — `12/02/2025`
    * ``yyyy-mm-dd`` — `2025-02-12`
    * день + месяц словом + год — `10 марта 2025`
    * день в кавычках — `«12» февраля 2025` (кавычки уже сняты вызывающим)

    Двузначные годы и «в марте 2025» не поддерживаются осознанно (план
    T1.15, раздел «Форматы»).
    """
    stripped = text.strip().strip("«»\"'“”„")
    if not stripped:
        return None

    #: Числовые формы — фиксированный порядок разбора, чтобы `12.02.2025`
    #: и `2025-02-12` не спорили друг с другом (детерминизм).
    if "." in stripped:
        parts = stripped.split(".")
        if len(parts) == 3:
            return _parse_ints(parts, day_idx=0, month_idx=1, year_idx=2)
    if "/" in stripped:
        parts = stripped.split("/")
        if len(parts) == 3:
            return _parse_ints(parts, day_idx=0, month_idx=1, year_idx=2)
    if "-" in stripped:
        parts = stripped.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return _parse_ints(parts, day_idx=2, month_idx=1, year_idx=0)

    #: Текстовая форма: день + слово-месяц + год. Разделители внутри —
    #: пробелы; лишние пробелы игнорируем.
    tokens = stripped.split()
    if len(tokens) == 3:
        month = month_number(tokens[1])
        if month is None:
            return None
        try:
            day = int(tokens[0].strip("«»\"'“”„"))
            year = int(tokens[2])
        except ValueError:
            return None
        return parse_date(day, month, year)

    return None


def _parse_ints(parts: list[str], *, day_idx: int, month_idx: int, year_idx: int) -> date | None:
    """Собрать дату из трёх строковых компонент по указанным индексам."""
    try:
        day = int(parts[day_idx])
        month = int(parts[month_idx])
        year = int(parts[year_idx])
    except ValueError:
        return None
    return parse_date(day, month, year)
