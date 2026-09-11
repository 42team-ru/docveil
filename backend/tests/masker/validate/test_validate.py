"""Тесты ValidateAgent: независимая проверка обезличенных артефактов (T1.8, шаг 9)."""

from __future__ import annotations

import pathlib
import shutil
import zipfile

import pymupdf
import pytest
from docx import Document as open_docx

import masker.render.docx_redact as docx_redact_module
from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.ingest.xlsx_ingest import ingest_xlsx
from masker.mask.agent import PlanAgent
from masker.model import Action, Document, Entity, EntityType, Source
from masker.refs import EntityIndex
from masker.render.docx_redact import render_docx_redacted
from masker.render.pdf_render import render_pdf_redacted
from masker.render.xlsx_redact import render_xlsx_redacted
from masker.validate.agent import ValidateAgent, _ValueMatcher
from masker.validate.parts import xlsx_parts

ROOT = next(
    parent
    for parent in pathlib.Path(__file__).resolve().parents
    if (parent / "pyproject.toml").is_file()
)
FIXTURES = ROOT / "fixtures" / "labeled"

_INN = "3662103003"
_AUTHOR = "Тест Автор"


def _entity_for(document: Document, text: str, etype: EntityType) -> Entity:
    seg = next(s for s in document.segments if text in s.text)
    start = seg.text.index(text)
    return Entity(
        type=etype,
        text=text,
        segment_order=seg.order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
        normalized=text,
    )


def _make_docx(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    path = tmp_path / "source.docx"
    doc = open_docx()
    doc.add_paragraph(text)
    doc.save(str(path))
    return path


class _MarkerAsOrgDetector:
    """Детектор-заглушка: находит вставленный маркер и упрямо считает его
    названием организации — имитация ложного срабатывания Natasha на
    `[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]` (см. риск в плане T1.6/T1.8)."""

    name = "fake-marker-as-org"
    source = Source.NER
    priority = 0
    types = frozenset({EntityType.ORG_NAME})

    def __init__(self, marker: str) -> None:
        self._marker = marker

    def detect(self, document: Document) -> list[Entity]:
        found: list[Entity] = []
        for segment in document.segments:
            start = segment.text.find(self._marker)
            if start >= 0:
                found.append(
                    Entity(
                        type=EntityType.ORG_NAME,
                        text=self._marker,
                        segment_order=segment.order,
                        start=start,
                        end=start + len(self._marker),
                        source=Source.NER,
                        confidence=0.6,
                    )
                )
        return found


def test_broken_render_is_caught(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Рендер намеренно пропускает единственную замену (`monkeypatch` на
    `_redact_paragraph`, отбрасывающий последнюю сущность): `leaked`
    непуст, среди утечек есть и `kind="raw"`, и `kind="detector"` —
    независимые механизмы должны сработать оба."""
    src = _make_docx(tmp_path, f"ИНН {_INN}")
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = PlanAgent().plan(document, [entity])

    original_redact_paragraph = docx_redact_module._redact_paragraph

    def broken(
        paragraph: object,
        replacements: list[object],
        style: str,
        highlight_background: str | None,
    ) -> None:
        original_redact_paragraph(  # type: ignore[arg-type]
            paragraph, replacements[:-1], style, highlight_background
        )

    monkeypatch.setattr(docx_redact_module, "_redact_paragraph", broken)

    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, plan, style="marker")

    report = ValidateAgent().validate(plan, [dest])

    assert report.ok is False
    assert report.leaked
    assert any(leak.kind == "raw" for leak in report.leaked)
    assert any(leak.kind == "detector" for leak in report.leaked)


def test_pdf_validation_distinguishes_planned_occurrence_from_public_same_date(
    tmp_path: pathlib.Path,
) -> None:
    """11.09.2026: Р26-исключение не является утечкой одноимённой даты."""
    source = tmp_path / "same-date.pdf"
    doc = pymupdf.open()
    for text in ("Federal law from 06.04.2011 No. 63", "Contract from 06.04.2011"):
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(source)
    doc.close()

    document = ingest_pdf(source)
    segment = next(segment for segment in document.segments if "Contract" in segment.text)
    value = "06.04.2011"
    entity = Entity(
        type=EntityType.DATE,
        text=value,
        segment_order=segment.order,
        start=segment.text.index(value),
        end=segment.text.index(value) + len(value),
        source=Source.RULE,
        confidence=1.0,
        normalized=value,
    )
    plan = PlanAgent().plan(document, [entity])
    artifact = tmp_path / "masked.pdf"
    render_pdf_redacted(source, artifact, document, plan, style="marker")

    clean = ValidateAgent().validate(plan, [artifact], source=source)
    broken = ValidateAgent().validate(plan, [source], source=source)

    assert clean.leaked == ()
    assert broken.leaked and broken.leaked[0].value == value


def test_xlsx_render_is_checked_for_leaks_and_gets_certificate(tmp_path: pathlib.Path) -> None:
    """XLSX проходит те же validate/certificate-ворота, что DOCX и PDF."""
    source = FIXTURES / "order_01.xlsx"
    document = ingest_xlsx(source)
    entities = DetectAgent().detect(document).entities
    plan = PlanAgent().plan(document, entities)
    destination = tmp_path / "masked.xlsx"

    render_xlsx_redacted(source, destination, document, plan, style="marker")
    report = ValidateAgent().validate(plan, [destination], source=source)

    assert report.ok is True
    assert report.leaked == ()
    assert any(part.endswith("xl/worksheets/sheet1.xml") for part in report.checked_parts)
    assert report.certificate is not None
    assert report.certificate.ok is True
    source_worksheet_text = {part.name: part.text for part in xlsx_parts(source)}
    assert "3662103003" in source_worksheet_text["xl/worksheets/sheet1.xml"]
    # Текст первого листа не подставляется в каждый XML лист: иначе eval
    # посчитает маркер повторно и получит ложный duplicate_markers.
    assert "3662103003" not in source_worksheet_text["xl/worksheets/sheet2.xml"]


def test_xlsx_validate_scans_worksheets_shared_strings_and_calc_chain(
    tmp_path: pathlib.Path,
) -> None:
    """Скан контейнера не ограничен видимыми ячейками.

    В ``calcChain.xml`` обычно нет значения, но он всё равно должен быть
    частью побайтового прохода: Excel-файлы от внешних систем не обязаны
    соблюдать это ожидание. В листе хранится и обычное значение, и кэш
    формулы, поэтому проверка листа покрывает оба носителя.
    """
    source = FIXTURES / "order_01.xlsx"
    document = ingest_xlsx(source)
    entities = DetectAgent().detect(document).entities
    plan = PlanAgent().plan(document, entities)
    value = next(replacement.entity.text for replacement in plan.replacements)
    artifact = tmp_path / "leaking.xlsx"
    shutil.copy2(source, artifact)
    with zipfile.ZipFile(artifact, "a") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            (
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<si><t>{value}</t></si></sst>"
            ),
        )
        archive.writestr(
            "xl/calcChain.xml",
            (
                '<calcChain xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<c r="A1" i="{value}"/>'
                "</calcChain>"
            ),
        )

    report = ValidateAgent().validate(plan, [artifact], source=source)

    assert report.ok is False
    raw_parts = {leak.part for leak in report.leaked if leak.kind == "raw"}
    assert any(name.startswith("xl/worksheets/") for name in raw_parts)
    assert "xl/sharedStrings.xml" in raw_parts
    assert "xl/calcChain.xml" in raw_parts


def test_clean_render_has_no_leaks(tmp_path: pathlib.Path) -> None:
    """Честный прогон по всем фикстурам `fixtures/labeled/*.docx` с
    `--types all`: `leaked == ()`.

    После добавления `_propagate_to_occurrences` в `AddressDetector` утечка
    «г. Воронеж» в датостроке (`contract_06_address.docx`) устранена —
    пропагация покрывает все вхождения уже найденного адреса.
    Тест возвращён к инварианту «ноль утечек», без именованных исключений.
    """
    detector = DetectAgent()
    plan_agent = PlanAgent()
    validator = ValidateAgent()
    all_leaks: list[tuple[str, str, str, str]] = []

    fixtures = sorted(FIXTURES.glob("*.docx"))
    assert fixtures, "фикстуры fixtures/labeled/*.docx не найдены"

    for source in fixtures:
        document = ingest_docx(source)
        entities = detector.detect(document).entities
        plan = plan_agent.plan(document, entities, requested_types=frozenset(EntityType))
        dest = tmp_path / f"{source.stem}.redacted.docx"
        render_docx_redacted(source, dest, document, plan, style="marker")
        report = validator.validate(plan, [dest])
        for leak in report.leaked:
            all_leaks.append((source.name, leak.kind, leak.entity_type, leak.value))

    assert all_leaks == [], f"Появилась утечка — актуальный список: {all_leaks}"


def test_author_left_in_core_xml_is_a_leak(tmp_path: pathlib.Path) -> None:
    """docx, где `core.xml` содержит ФИО из плана: одна утечка
    `kind="metadata"`, `part == "docProps/core.xml"`."""
    person = "Иванов Иван Иванович"
    src = _make_docx(tmp_path, person)
    document = ingest_docx(src)
    entity = _entity_for(document, person, EntityType.PERSON)
    plan = PlanAgent().plan(document, [entity])

    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, plan, style="marker")
    # render_docx_redacted уже чистит author — намеренно возвращаем его
    # назад, чтобы проверить именно Validate, а не то, что Render и так
    # делает правильно (это отдельные тесты в tests/masker/render/).
    leaking_doc = open_docx(str(dest))
    leaking_doc.core_properties.author = person
    leaking_doc.save(str(dest))

    report = ValidateAgent().validate(plan, [dest])

    assert report.ok is False
    metadata_leaks = [leak for leak in report.leaked if leak.kind == "metadata"]
    assert len(metadata_leaks) == 1
    assert metadata_leaks[0].part == "docProps/core.xml"
    assert metadata_leaks[0].value == person


def test_value_split_across_runs_is_caught(tmp_path: pathlib.Path) -> None:
    """Значение разрезано по run'ам и не заменено: побайтовый поиск его не
    видит, текстовый — видит, `leaked` непуст."""
    src = tmp_path / "multirun.docx"
    doc = open_docx()
    para = doc.add_paragraph()
    half = len(_INN) // 2
    para.add_run(f"ИНН {_INN[:half]}")
    para.add_run(_INN[half:])
    doc.save(str(src))

    document = ingest_docx(src)
    seg = document.segments[0]
    start = seg.text.index(_INN)
    entity = Entity(
        type=EntityType.INN,
        text=_INN,
        segment_order=seg.order,
        start=start,
        end=start + len(_INN),
        source=Source.RULE,
        confidence=1.0,
        normalized=_INN,
    )
    plan = PlanAgent().plan(document, [entity])

    # "Сломанный" рендер: копия исходника без какой-либо правки — значение
    # осталось на месте, разрезанное по run'ам, как и было в исходнике.
    dest = tmp_path / "redacted.docx"
    shutil.copy2(src, dest)

    report = ValidateAgent().validate(plan, [dest])

    assert report.ok is False
    document_leaks = [leak for leak in report.leaked if leak.part == "word/document.xml"]
    assert document_leaks
    # Побайтовый поиск не видит разрезанное значение — утечка находится
    # только через текст, склеенный `ingest_docx`.
    assert all("побайтово" not in leak.detail for leak in document_leaks)
    assert any("разрезано" in leak.detail for leak in document_leaks)


def test_kept_entity_is_residual_not_leak(tmp_path: pathlib.Path) -> None:
    """Сущность с решением `keep` осталась в документе: попадает в
    `residual`, `ok is True`."""
    src = _make_docx(tmp_path, f"ИНН {_INN}")
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    ref = EntityIndex([entity]).ref(entity)

    plan = PlanAgent().plan(document, [entity], actions={ref: Action.KEEP})
    assert plan.replacements == ()

    # Маскировать нечего — рендер тут просто копия исходника.
    dest = tmp_path / "redacted.docx"
    shutil.copy2(src, dest)

    report = ValidateAgent().validate(plan, [dest])

    assert report.ok is True
    assert report.leaked == ()
    assert any(
        leak.kind == "detector" and leak.entity_type == "inn" and leak.value == _INN
        for leak in report.residual
    )


def test_marker_recognised_as_org_is_ignored(tmp_path: pathlib.Path) -> None:
    """Искусственная находка внутри вставленного маркера отбрасывается
    целиком — не в `leaked`, не в `residual`."""
    org_name = 'ООО "Ромашка"'
    src = _make_docx(tmp_path, org_name)
    document = ingest_docx(src)
    entity = _entity_for(document, org_name, EntityType.ORG_NAME)
    plan = PlanAgent().plan(document, [entity])
    marker = plan.replacements[0].marker

    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, plan, style="marker")

    fake_detector = DetectAgent([_MarkerAsOrgDetector(marker)])
    report = ValidateAgent(detector=fake_detector).validate(plan, [dest])

    assert report.leaked == ()
    assert report.residual == ()


def test_leaked_order_is_stable(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Два вызова дают одинаковый кортеж — раздел «Детерминизм» плана."""
    src = _make_docx(tmp_path, f"ИНН {_INN}, СНИЛС 112-233-445 95")
    document = ingest_docx(src)
    inn_entity = _entity_for(document, _INN, EntityType.INN)
    snils_entity = _entity_for(document, "112-233-445 95", EntityType.SNILS)
    plan = PlanAgent().plan(document, [inn_entity, snils_entity])

    original_redact_paragraph = docx_redact_module._redact_paragraph

    def broken(
        paragraph: object,
        replacements: list[object],
        style: str,
        highlight_background: str | None,
    ) -> None:
        original_redact_paragraph(paragraph, [], style, highlight_background)  # type: ignore[arg-type]

    monkeypatch.setattr(docx_redact_module, "_redact_paragraph", broken)

    dest = tmp_path / "redacted.docx"
    render_docx_redacted(src, dest, document, plan, style="marker")

    validator = ValidateAgent()
    first = validator.validate(plan, [dest])
    second = validator.validate(plan, [dest])

    assert first.leaked == second.leaked
    assert first.residual == second.residual
    assert len(first.leaked) >= 2  # обе сущности реально утекли


def test_value_matcher_finds_overlapping_values_in_one_pass() -> None:
    """Короткое значение не теряется, когда оно — префикс длинного."""
    matcher = _ValueMatcher(frozenset({"123", "1234", "234"}))
    assert matcher.find("x1234y") == {"123", "1234", "234"}


def test_pdf_text_layer_leak_is_caught(tmp_path: pathlib.Path) -> None:
    """`pymupdf` находит исходную строку в тексте страницы после
    «сломанного» редактирования PDF."""
    src = tmp_path / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"ИНН {_INN}", fontsize=12)
    doc.save(str(src))
    doc.close()

    document = ingest_pdf(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = PlanAgent().plan(document, [entity])

    # "Сломанный" рендер PDF: копия исходника, замену никто не применил.
    dest = tmp_path / "redacted.pdf"
    shutil.copy2(src, dest)

    report = ValidateAgent().validate(plan, [dest])

    assert report.ok is False
    assert any(
        leak.part == "page 1" and leak.entity_type == "inn" and leak.value == _INN
        for leak in report.leaked
    )


def test_render_pdf_redacted_is_actually_clean(tmp_path: pathlib.Path) -> None:
    """Контрольный положительный случай для PDF: честный `render_pdf_redacted`
    не оставляет утечек (в отличие от «сломанного» варианта выше)."""
    src = tmp_path / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"ИНН {_INN}", fontsize=12)
    doc.save(str(src))
    doc.close()

    document = ingest_pdf(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = PlanAgent().plan(document, [entity])

    dest = tmp_path / "redacted.pdf"
    render_pdf_redacted(src, dest, document, plan, style="marker")

    report = ValidateAgent().validate(plan, [dest])

    assert report.ok is True
    assert report.leaked == ()


def test_validate_attaches_certificate_for_pdf_with_source(tmp_path: pathlib.Path) -> None:
    """План М3: ``ValidateAgent.validate`` обязан вернуть заполненный
    ``ValidationReport.certificate`` (не ``None``) с тремя проверенными
    пунктами, когда передан ``source`` PDF-документа — иначе сертификат
    просто не появляется ни в ``report.json``, ни в отчёте человеку."""
    src = tmp_path / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"ИНН {_INN}", fontsize=12)
    doc.save(str(src))
    doc.close()

    document = ingest_pdf(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = PlanAgent().plan(document, [entity])

    dest = tmp_path / "redacted.pdf"
    render_pdf_redacted(src, dest, document, plan, style="marker")

    report = ValidateAgent().validate(plan, [dest], source=src)

    assert report.certificate is not None
    assert report.certificate.ok is True
    assert {check.name for check in report.certificate.checks} == {
        "leak_scan",
        "metadata_cleared",
        "width_quantization",
        "image_metadata_stripped",
    }


def test_validate_certificate_leak_scan_fails_when_render_is_broken(
    tmp_path: pathlib.Path,
) -> None:
    """Симметрия с ``test_broken_render_is_caught``: утечка не только
    попадает в ``report.leaked``, но и роняет пункт ``leak_scan`` сертификата
    — иначе сертификат мог бы «пройти», пока настоящий отчёт кричит об
    утечке."""
    src = _make_docx(tmp_path, f"ИНН {_INN}")
    document = ingest_docx(src)
    entity = _entity_for(document, _INN, EntityType.INN)
    plan = PlanAgent().plan(document, [entity])

    # "Сломанный" рендер: копия исходника без какой-либо правки.
    dest = tmp_path / "redacted.docx"
    shutil.copy2(src, dest)

    report = ValidateAgent().validate(plan, [dest])

    assert report.certificate is not None
    assert report.certificate.ok is False
    leak_check = next(check for check in report.certificate.checks if check.name == "leak_scan")
    assert leak_check.ok is False
