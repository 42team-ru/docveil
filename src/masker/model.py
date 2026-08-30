"""Контракты, общие для всех агентов.

Единственное место, где определены типы, пересекающие границы агентов.
Менять сигнатуры здесь — значит править всех потребителей.
"""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    """Типы данных, которые пользователь может попросить обезличить."""

    ORG_NAME = "org_name"
    PERSON = "person"
    INN = "inn"
    KPP = "kpp"
    OGRN = "ogrn"
    SNILS = "snils"
    BANK_ACCOUNT = "bank_account"
    BIK = "bik"
    BANK_NAME = "bank_name"
    ADDRESS = "address"
    PHONE = "phone"
    EMAIL = "email"
    PASSPORT = "passport"
    CONTRACT_NUMBER = "contract_number"
    MONEY = "money"
    DATE = "date"
    SITE = "site"


#: Типы, пропуск которых — утечка персональных/платёжных данных.
#: Для них порог recall в воротах равен 1.0.
CRITICAL_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.INN,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.BANK_ACCOUNT,
        EntityType.PASSPORT,
    }
)

