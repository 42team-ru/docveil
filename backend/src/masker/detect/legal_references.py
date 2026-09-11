"""Признаки ссылок на нормативные акты, не являющихся персональными данными."""

from __future__ import annotations

import re

#: Склонённые формы «федеральный закон». Это именно вид нормативного акта,
#: а не название стороны договора. Слово «от» после него связывает дату с
#: принятием закона, а не с событием конкретного договора.
_FEDERAL_LAW_RE = re.compile(
    r"\bфедеральн(?:ый|ого|ому|ым|ом|ые|ых|ыми)\s+"
    r"закон(?:а|у|ом|ы|ов|ами|ах|е)?\b",
    flags=re.IGNORECASE,
)
_ADOPTION_PREFIX_RE = re.compile(
    rf"{_FEDERAL_LAW_RE.pattern}\s+от\s*$",
    flags=re.IGNORECASE,
)


def is_federal_law_reference(text: str) -> bool:
    """Есть ли в тексте обозначение федерального закона в любой падежной форме."""
    return _FEDERAL_LAW_RE.search(text) is not None


def is_federal_law_adoption_date(text: str, date_start: int) -> bool:
    """Связана ли дата непосредственно с предшествующей ссылкой на закон.

    Проверяем только конструкцию «Федеральным законом от <дата>»: так дата
    поставки или подписания, встретившаяся позднее в том же сегменте, не
    получит иммунитет только из-за упомянутого раньше закона.
    """
    return _ADOPTION_PREFIX_RE.search(text[:date_start]) is not None
