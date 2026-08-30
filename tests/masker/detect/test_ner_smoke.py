from pathlib import Path

import pytest

from masker.detect import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.model import EntityType

pytestmark = pytest.mark.models


def test_tasks_acceptance_line() -> None:
    text = 'ООО "Ромашка" (ИНН 3662103003), в лице Генерального директора Петровой Марии Сергеевны'
    from masker.model import Anchor, Document, Segment

    document = Document("test.docx", "docx", [Segment(text, Anchor("docx", ("body", 0)), 0)])

    entities = DetectAgent().detect(document).entities

    assert (EntityType.INN, "3662103003") in {(item.type, item.text) for item in entities}
    assert (EntityType.ORG_NAME, 'ООО "Ромашка"') in {(item.type, item.text) for item in entities}


def test_two_runs_are_identical() -> None:
    path = Path(__file__).resolve().parents[3] / "fixtures/labeled/contract_03_ner.docx"
    document = ingest_docx(path)

    first = DetectAgent().detect(document).entities
    second = DetectAgent().detect(document).entities

    assert first == second


def test_contract_01_expected_model_output() -> None:
    path = Path(__file__).resolve().parents[3] / "fixtures/labeled/contract_01.docx"
    actual = [(item.type, item.text) for item in DetectAgent().detect(ingest_docx(path)).entities]

    assert actual == [
        (EntityType.ORG_NAME, "Акционерное общество «Триема»"),
        (EntityType.INN, "3662103003"),
        (EntityType.KPP, "366201001"),
        (EntityType.OGRN, "1023601546902"),
        (EntityType.PERSON, "Иванова Ивана Ивановича"),
        (EntityType.ORG_NAME, "Общество с ограниченной ответственностью «Вектор»"),
        (EntityType.INN, "7707083893"),
        (EntityType.KPP, "770701001"),
        (EntityType.PERSON, "Сидоровой Анны Петровны"),
        (EntityType.ADDRESS, "394018, г. Воронеж, ул. Кирова, д. 4, оф. 12"),
        (EntityType.BANK_ACCOUNT, "40702810100000000002"),
        (EntityType.BIK, "042007681"),
        (EntityType.PHONE, "+7 (473) 250-10-10"),
        (EntityType.EMAIL, "info@triema.example"),
        (EntityType.ADDRESS, "101000, г. Москва, ул. Мясницкая, д. 26"),
        (EntityType.PHONE, "8-910-347-51-07"),
        (EntityType.EMAIL, "zakupki@vektor.example"),
        (EntityType.PERSON, "И.И. Иванов"),
        (EntityType.PERSON, "А.П. Сидорова"),
    ]
