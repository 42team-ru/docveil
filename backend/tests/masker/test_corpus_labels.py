"""Аудит-тест полноты уже сделанной разметки PDF-корпуса (T2.2.1, шаг 1).

Разметка (`fixtures/labeled/contract_pdf_01.labels.json`,
`fixtures/labeled/contract_pdf_02_school.labels.json`) сделана и выверена
человеком — этот файл не про то, чтобы её создать, а про то, чтобы доказать
её полноту независимой проверкой. «Независимая» означает: свой обход текста
и свой regex, а не `detect/rules.py::PATTERNS` — иначе аудит и детектор
делили бы один и тот же слепой участок, и полнота разметки маскировала бы
именно тот дефект, который эта задача (T2.2.1) должна вскрыть в `make eval`.

Проверки:

1. Каждое число с валидной контрольной суммой (ИНН/ОГРН/СНИЛС/банковский
   счёт в паре хоть с каким-то 9-значным числом рядом в тексте) обязано
   быть в разметке — раздел «Схема разметки», пункт 4.
2. `text` не содержит двух пробелов подряд — пункт 1.
3. `type` — известный `EntityType` — пункт схемы «отдельная проверка».
4. `text` типа `person` не начинается с должности — пункт 6.
5. `contract_pdf_02_school.labels.json` содержит все четыре реквизита Д8
   (БИК/КПП/два казначейских счёта) с верным типом — пункт 9.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from masker.detect.checksums import is_valid_account, is_valid_inn, is_valid_ogrn, is_valid_snils
from masker.model import EntityType

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "labeled"

#: Своя регулярка — умышленно не `detect/rules.py::PATTERNS` (см. докстринг
#: модуля). Разделитель между цифрами — ровно пробел или дефис, **не**
#: `\s` целиком: текст здесь — весь текст страницы со переносами строк
#: (`_pdf_text`), а не production-сегмент из одной строки, и `\s` слил бы
#: два разных числа из соседних ячеек таблицы через перенос строки в одно
#: число — граница ровно та же (`(?<![\d\w])...(?![\d\w])`), что в
#: production, но применённая к другому по природе тексту.
_DIGIT_RUN = re.compile(r"(?<![\d\w])\d[\d \-]{7,30}\d(?![\d\w])")

#: Список должностей для аудита ФИО — не production-словарь
#: `detect/data/org_forms.yaml::role_stems` (тот про роли *сторон договора*:
#: поставщик/заказчик/исполнитель, а не про должности конкретных людей).
#: Минимален специально: ловит класс дефекта Д4 («Директора Зубрицкой»
#: осталось в тексте предполагаемого ФИО), не подменяет NER.
_JOB_TITLE_PREFIXES = (
    "генеральный директор",
    "директор",
    "заведующ",
    "представител",
    "начальник",
    "президент",
    "заместител",
    "управляющ",
)


def _pdf_text(path: Path) -> str:
    """Текст всех страниц PDF, независимо от `masker.ingest.pdf_ingest`."""
    document = pymupdf.open(str(path))
    try:
        return "\n".join(page.get_text("text") for page in document)
    finally:
        document.close()


def _digit_runs(text: str) -> set[str]:
    return {re.sub(r"[ \-]", "", match.group()) for match in _DIGIT_RUN.finditer(text)}


def checksum_valid_values(text: str) -> dict[str, set[str]]:
    """Все числа текста, чья контрольная сумма сходится, по типу реквизита.

    Банковский счёт (у него нет собственной контрольной суммы) принимается,
    если в тексте есть хоть одно 9-значное число, с которым пара проходит
    `is_valid_account` — тот же принцип, что и в `detect/rules.py::_accept`,
    но применённый ко всему тексту документа, а не к соседним сегментам.
    """
    runs = _digit_runs(text)
    nine_digit = [value for value in runs if len(value) == 9]
    found: dict[str, set[str]] = {
        "inn": set(),
        "ogrn": set(),
        "snils": set(),
        "bank_account": set(),
    }
    for value in runs:
        if len(value) in (10, 12) and is_valid_inn(value):
            found["inn"].add(value)
        if len(value) in (13, 15) and is_valid_ogrn(value):
            found["ogrn"].add(value)
        if len(value) == 11 and is_valid_snils(value):
            found["snils"].add(value)
        if len(value) == 20 and any(is_valid_account(value, bik) for bik in nine_digit):
            found["bank_account"].add(value)
    return found


def _label_digit_values(entities: list[dict[str, Any]]) -> set[str]:
    return {re.sub(r"[\s\-]", "", str(item["text"])) for item in entities}


def find_missing_checksum_labels(text: str, entities: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """`(тип, значение)` реквизитов с валидной контрольной суммой без разметки."""
    label_values = _label_digit_values(entities)
    found = checksum_valid_values(text)
    return {
        (kind, value)
        for kind, values in found.items()
        for value in values
        if value not in label_values
    }


def find_double_space_labels(entities: list[dict[str, Any]]) -> list[str]:
    return [str(item["text"]) for item in entities if "  " in str(item["text"])]


def find_unknown_type_labels(entities: list[dict[str, Any]]) -> list[str]:
    known = {member.value for member in EntityType}
    return [str(item["type"]) for item in entities if str(item["type"]) not in known]


def find_job_title_prefixed_persons(entities: list[dict[str, Any]]) -> list[str]:
    return [
        str(item["text"])
        for item in entities
        if str(item["type"]) == EntityType.PERSON.value
        and str(item["text"]).casefold().startswith(_JOB_TITLE_PREFIXES)
    ]


def _pdf_corpus() -> list[Path]:
    corpus = sorted(FIXTURES.glob("*.pdf"))
    assert corpus, "в fixtures/labeled нет ни одного PDF — аудит не над чем гонять"
    return corpus


def _labels_for(pdf_path: Path) -> dict[str, Any]:
    labels_path = pdf_path.parent / f"{pdf_path.stem}.labels.json"
    assert labels_path.exists(), f"нет разметки для {pdf_path.name}: {labels_path}"
    data: dict[str, Any] = json.loads(labels_path.read_text(encoding="utf-8"))
    return data


# ---------------------------------------------------------------------------
# Проверки реального корпуса — вот они и есть аудит, ради которого файл существует.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pdf_path", _pdf_corpus(), ids=lambda p: p.name)
def test_checksum_valid_requisites_are_all_labeled(pdf_path: Path) -> None:
    labels = _labels_for(pdf_path)
    missing = find_missing_checksum_labels(_pdf_text(pdf_path), labels["entities"])
    assert not missing, (
        f"{pdf_path.name}: в тексте есть реквизиты с валидной контрольной "
        f"суммой, которых нет в разметке: {sorted(missing)}"
    )


@pytest.mark.parametrize("pdf_path", _pdf_corpus(), ids=lambda p: p.name)
def test_label_text_has_no_double_spaces(pdf_path: Path) -> None:
    labels = _labels_for(pdf_path)
    offenders = find_double_space_labels(labels["entities"])
    assert not offenders, f"{pdf_path.name}: text с двумя пробелами подряд: {offenders}"


@pytest.mark.parametrize("pdf_path", _pdf_corpus(), ids=lambda p: p.name)
def test_label_type_is_known_entity_type(pdf_path: Path) -> None:
    labels = _labels_for(pdf_path)
    offenders = find_unknown_type_labels(labels["entities"])
    assert not offenders, f"{pdf_path.name}: неизвестный EntityType в разметке: {offenders}"


@pytest.mark.parametrize("pdf_path", _pdf_corpus(), ids=lambda p: p.name)
def test_person_label_does_not_start_with_job_title(pdf_path: Path) -> None:
    labels = _labels_for(pdf_path)
    offenders = find_job_title_prefixed_persons(labels["entities"])
    assert not offenders, f"{pdf_path.name}: в text попала должность вместо ФИО: {offenders}"


def test_school_contract_has_treasury_requisites_from_defect_8() -> None:
    """Д8/Р14: казначейские реквизиты размечены явно и с верным типом.

    Инвариант зафиксирован тестом, чтобы приёмку шага 4 (Д8) нельзя было
    незаметно обнулить правкой разметки — план T2.2.1, шаг 1.
    """
    labels = _labels_for(FIXTURES / "contract_pdf_02_school.pdf")
    by_text = {str(item["text"]): str(item["type"]) for item in labels["entities"]}
    expected = {
        "016577551": EntityType.BIK.value,
        "668601001": EntityType.KPP.value,
        "03234643657010006200": EntityType.BANK_ACCOUNT.value,
        "40102810645370000054": EntityType.BANK_ACCOUNT.value,
        "39062000144": EntityType.BANK_ACCOUNT.value,
    }
    for text, expected_type in expected.items():
        assert by_text.get(text) == expected_type, (
            f"реквизит {text!r} обязан быть размечен как {expected_type!r}, "
            f"сейчас: {by_text.get(text)!r}"
        )


# ---------------------------------------------------------------------------
# Юнит-тесты самих проверок: каждая ветка аудита обязана и ловить нарушение,
# и не срабатывать на корректных данных — иначе проверка декоративна.
# ---------------------------------------------------------------------------


def test_find_missing_checksum_labels_catches_unlabeled_inn() -> None:
    text = "В тексте затесался ИНН 7707083893 без всякой разметки рядом."
    missing = find_missing_checksum_labels(text, entities=[])
    assert ("inn", "7707083893") in missing


def test_find_missing_checksum_labels_passes_when_labeled() -> None:
    text = "ИНН 7707083893 указан и размечен."
    entities = [{"type": "inn", "text": "7707083893"}]
    assert find_missing_checksum_labels(text, entities) == set()


def test_find_missing_checksum_labels_ignores_invalid_checksum() -> None:
    # Битая последняя цифра настоящего ИНН — контрольная сумма не сходится,
    # значит это не реквизит, а произвольное десятизначное число.
    text = "Номер накладной 7707083890 контрольную сумму ИНН не проходит."
    missing = find_missing_checksum_labels(text, entities=[])
    assert missing == set()


def test_find_missing_checksum_labels_requires_nearby_bik_for_account() -> None:
    account = "40702810100000000002"
    bik = "770701001"
    # Без 9-значного числа рядом счёт проверить нечем — аудит не требует его.
    assert find_missing_checksum_labels(account, entities=[]) == set()
    # С валидной парой (счёт, БИК) в тексте — обязателен в разметке.
    text_with_bik = f"р/с {account} БИК {bik}"
    missing = find_missing_checksum_labels(text_with_bik, entities=[])
    assert ("bank_account", account) in missing


def test_find_double_space_labels_catches_double_space() -> None:
    assert find_double_space_labels([{"type": "org_name", "text": "ООО  «X»"}]) == ["ООО  «X»"]


def test_find_double_space_labels_passes_single_space() -> None:
    assert find_double_space_labels([{"type": "org_name", "text": "ООО «X»"}]) == []


def test_find_unknown_type_labels_catches_unknown_type() -> None:
    assert find_unknown_type_labels([{"type": "not_a_real_type", "text": "x"}]) == [
        "not_a_real_type"
    ]


def test_find_unknown_type_labels_passes_known_type() -> None:
    assert find_unknown_type_labels([{"type": "org_name", "text": "x"}]) == []


def test_find_job_title_prefixed_persons_catches_role_prefix() -> None:
    entities = [{"type": "person", "text": "Директора Зубрицкой"}]
    assert find_job_title_prefixed_persons(entities) == ["Директора Зубрицкой"]


def test_find_job_title_prefixed_persons_passes_surname_only() -> None:
    entities = [{"type": "person", "text": "Зубрицкой"}]
    assert find_job_title_prefixed_persons(entities) == []


def test_find_job_title_prefixed_persons_ignores_non_person_type() -> None:
    # Оргформа тоже может формально начинаться с похожего слова —
    # проверка обязана применяться только к type == "person".
    entities = [{"type": "org_name", "text": "Президент-Отель"}]
    assert find_job_title_prefixed_persons(entities) == []
