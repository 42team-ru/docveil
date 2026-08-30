"""Ворота должны уметь не пройти: на каждый валидный реквизит есть битый."""

import pytest

from masker.detect.checksums import (
    is_valid_account,
    is_valid_bik,
    is_valid_inn,
    is_valid_kpp,
    is_valid_ogrn,
    is_valid_snils,
)


@pytest.mark.parametrize("inn", ["3662103003", "7707083893", "500100732259"])
def test_inn_valid(inn: str) -> None:
    assert is_valid_inn(inn)


@pytest.mark.parametrize(
    "inn", ["3662103004", "7707083892", "500100732258", "123456789", "abcdefghij", ""]
)
def test_inn_invalid(inn: str) -> None:
    assert not is_valid_inn(inn)


@pytest.mark.parametrize("ogrn", ["1023601546902", "1027700132195"])
def test_ogrn_valid(ogrn: str) -> None:
    assert is_valid_ogrn(ogrn)


def test_ogrn_invalid() -> None:
    assert not is_valid_ogrn("1023601546903")


def test_snils() -> None:
    assert is_valid_snils("112-233-445 95")
    assert not is_valid_snils("112-233-445 96")


def test_bik() -> None:
    assert is_valid_bik("042007681")
    assert not is_valid_bik("142007681")


def test_kpp() -> None:
    assert is_valid_kpp("366201001")
    assert not is_valid_kpp("36620100")


def test_account_requires_matching_bik() -> None:
    # Счёт валиден только в паре со «своим» БИК — на чужом контрольная сумма рвётся.
    assert not is_valid_account("40702810100000000002", "044525225")


def test_account_valid_with_correct_bik() -> None:
    """Проверка, что алгоритм работает на реальных данных (дефект 1)."""
    # Сбербанк корр. счёт (проверенные данные)
    assert is_valid_account("30101810400000000225", "044525225")

    # Фикстура contract_01 с валидным счётом
    assert is_valid_account("40702810100000000002", "042007681")

    # Старый синтетический счёт не должен проходить
    assert not is_valid_account("40702810100000000001", "042007681")
