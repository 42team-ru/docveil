"""Модель карточки договора (Фаза 3 плана).

Саммари и маскирование независимы: одна и та же детекция кормит две ветки —
(а) MaskPlan (опционально, по политике) и (б) ContractSummary в отчёте (всегда).
"""

from __future__ import annotations

from pydantic import BaseModel


class ContractParty(BaseModel):
    """Сторона договора: имя, роль и ключевые реквизиты."""

    name: str | None = None
    role_title: str | None = None
    inn: str | None = None
    ogrn: str | None = None


class ContractSummary(BaseModel):
    """Карточка договора — ключевые параметры, извлечённые детекторами.

    Все поля опциональны: отсутствие значения означает, что детекторы не
    нашли данный параметр в документе, а не что он там отсутствует.
    """

    customer: ContractParty | None = None
    supplier: ContractParty | None = None
    #: Уникальные ссылки на федеральные законы о закупках («44-ФЗ», «223-ФЗ» ...).
    federal_law: list[str] = []
    #: Текст сущности contract_amount — первое найденное значение.
    contract_amount: str | None = None
    #: Уникальные тексты сущностей delivery_period — все найденные в документе.
    delivery_periods: list[str] = []
    #: Условия оплаты (Фаза 2 — regex_llm_filter); пока не реализовано.
    payment_terms: str | None = None
    #: Номер договора — первая сущность типа contract_number.
    contract_number: str | None = None
    #: ISO-8601 метка времени сборки карточки.
    generated_at: str = ""
    #: Число обращений к LLM за сессию (аудит стоимости).
    llm_calls: int = 0
