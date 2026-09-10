"""Р9: границы NER-спанов не приклеивают соседнее слово и не обрезают
собственную форму сущности из чужого спана.

Р9-1 (PERSON): регрессия на `holdout_02_lease.docx`: Natasha отдаёт верный
`PER(31,56)='Соловьёв Николай Петрович'`, но `expand_person_left` до
правки тянул влево «Федерации» из соседнего `LOC('Российской Федерации')`
— «Федерации» заглавное кириллическое слово, не ролевое/оргформа/улица, и
единственным заслоном остаётся морфология (`has_name_grammeme`, план Р9-1,
`docs/plans/tasks-krmi-2026-09-09.md`, §0.2).

Р9-2 (ORG): регрессия на `holdout_01_supply.docx`: Natasha отдаёт только
название в кавычках («Городская клиническая больница № 15»), полная форма
бюджетного учреждения слева обрезана, потому что её не было в словаре
`org_forms.yaml` (план Р9-2, там же)."""

from __future__ import annotations

from pathlib import Path

from masker.detect import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.model import EntityType

_HOLDOUT_01 = (
    Path(__file__).resolve().parents[3] / "fixtures" / "holdout" / "holdout_01_supply.docx"
)
_HOLDOUT_02 = Path(__file__).resolve().parents[3] / "fixtures" / "holdout" / "holdout_02_lease.docx"


def test_holdout_02_lease_person_span_is_not_glued_to_federation() -> None:
    """Прогон настоящего `DetectAgent` на реальном документе, не строковая
    фикстура: спан `person` в сегменте 2 равен ровно `'Соловьёв Николай
    Петрович'`, без приклеенного слева «Федерации»."""
    document = ingest_docx(_HOLDOUT_02)
    persons = [
        entity
        for entity in DetectAgent().detect(document).entities
        if entity.type is EntityType.PERSON and entity.segment_order == 2
    ]
    assert len(persons) == 1, persons
    entity = persons[0]
    assert entity.text == "Соловьёв Николай Петрович"
    assert entity.start == 31
    assert entity.end == 56


def test_holdout_01_supply_org_span_includes_full_institution_form() -> None:
    """Прогон настоящего `DetectAgent` на реальном документе: спан
    `org_name` заказчика равен gold-строке из
    `holdout_01_supply.labels.json` побайтово — с полной формой
    бюджетного учреждения слева, а не только названием в кавычках."""
    document = ingest_docx(_HOLDOUT_01)
    orgs = [
        entity
        for entity in DetectAgent().detect(document).entities
        if entity.type is EntityType.ORG_NAME and entity.segment_order == 3
    ]
    assert len(orgs) == 1, orgs
    entity = orgs[0]
    assert entity.text == (
        "Государственное бюджетное учреждение здравоохранения «Городская клиническая больница № 15»"
    )
    assert entity.start == 0
    assert entity.end == 90
