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


@pytest.mark.parametrize("bik", ["016577551", "046577904"])
def test_treasury_bik_is_valid(bik: str) -> None:
    """Д8, план T2.2.1: с 2022 года казначейские БИК выдаются с префиксом
    01 — `016577551` не должен отбрасываться как «неправильный БИК», у
    него просто раньше не было принятого префикса в коде."""
    assert is_valid_bik(bik)


def test_bik_rejects_unknown_prefix() -> None:
    # Заведомо битый вариант — префикс не 01 и не 04.
    assert not is_valid_bik("996577551")


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


def test_treasury_account_key_uses_cbr_prefix() -> None:
    """Д8, план T2.2.1: и единый казначейский счёт (40102...), и
    казначейский счёт (0323...) проверяются вторым ключом («0» + разряды
    5-6 БИК) — раньше этот ключ применялся только к счетам на 301..."""
    treasury_bik = "016577551"
    assert is_valid_account("03234643657010006200", treasury_bik)
    assert is_valid_account("40102810645370000054", treasury_bik)


def test_account_still_rejects_mismatched_treasury_bik() -> None:
    # Заведомо битый вариант: тот же счёт, но БИК от другого учреждения.
    assert not is_valid_account("03234643657010006200", "049205603")
