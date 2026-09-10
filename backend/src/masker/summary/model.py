"""Модель карточки договора и её безопасного экспорта."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

FactStatus = Literal["found", "ambiguous", "not_found", "confirmed"]


class FactAnchor(BaseModel):
    """Ссылка на точный диапазон в оригинале, пригодная для UI и JSON."""

    fmt: str
    locator: list[str | int | float]
    label: str = ""
    segment_order: int
    start: int
    end: int


class FactAlternative(BaseModel):
    """Не выбранный кандидат правила с его происхождением."""

    value: str
    purpose: str | None = None
    source: str
    anchors: list[FactAnchor]


class ContractFact(BaseModel):
    """Один факт карточки.

    ``not_found`` означает только «не обнаружено»: это не вывод об отсутствии
    условия в договоре. Заполненный факт всегда имеет хотя бы один якорь.
    """

    value: str | None = None
    source_quote: str | None = None
    anchors: list[FactAnchor] = []
    source: str | None = None
    status: FactStatus = "not_found"
    alternatives: list[FactAlternative] = []

    @model_validator(mode="after")
    def _filled_fact_has_anchor(self) -> ContractFact:
        if self.status in {"found", "confirmed"} and not self.anchors:
            raise ValueError("заполненный факт должен содержать якорь оригинала")
        return self


class MoneyFact(ContractFact):
    """Выбранная цена договора и кандидаты, похожие на НДС/аванс/штраф."""

    currency: str | None = None
    vat: str | None = None
    purpose: str | None = None


class PaymentStage(BaseModel):
    """Один этап расчётов; пустые поля означают «не удалось выделить»."""

    percentage: str | None = None
    amount: str | None = None
    onset_event: str | None = None
    days: int | None = None
    day_kind: str | None = None


class PaymentFact(ContractFact):
    """Условия оплаты без склеивания несвязанных фраз через точку с запятой."""

    stages: list[PaymentStage] = []


class DeliveryFact(ContractFact):
    """Срок поставки с объектом/партией, событием отсчёта и видом дней."""

    object_or_batch: str | None = None
    onset_event: str | None = None
    days: int | None = None
    day_kind: str | None = None


class ContractParty(BaseModel):
    """Совместимое представление стороны для существующего HTML-отчёта."""

    name: str | None = None
    role_title: str | None = None
    inn: str | None = None
    ogrn: str | None = None


class ContractSummary(BaseModel):
    """Карточка договора.

    Старые плоские поля остаются временно для совместимости отчёта. Новые
    ``*_fact`` поля — контракт карточки: они содержат статус, цитату и якорь.
    """

    customer: ContractParty | None = None
    supplier: ContractParty | None = None
    federal_law: list[str] = []
    contract_amount: str | None = None
    delivery_periods: list[str] = []
    payment_terms: str | None = None
    contract_number: str | None = None

    customer_fact: ContractFact = ContractFact()
    supplier_fact: ContractFact = ContractFact()
    federal_law_facts: list[ContractFact] = []
    #: Не заполняется лишь от упоминания ФЗ: это отдельный, более сильный факт.
    procurement_regime: ContractFact = ContractFact()
    contract_amount_fact: MoneyFact = MoneyFact()
    payment_facts: list[PaymentFact] = []
    delivery_facts: list[DeliveryFact] = []
    contract_number_fact: ContractFact = ContractFact()

    generated_at: str = ""
    llm_calls: int = 0
