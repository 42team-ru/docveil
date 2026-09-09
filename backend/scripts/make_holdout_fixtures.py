"""Генератор отложенного (holdout) и негативного корпусов — задача К2.

Отличие от `scripts/make_fixtures.py`: те документы формируют обучающий
корпус, на котором настраиваются детекторы (`fixtures/labeled/`). Документы
отсюда никто не смотрит при отладке детекторов — только при замере К2.
Организации, ФИО и реквизиты здесь **не пересекаются** с `fixtures/labeled/`
и с `fixtures/gliner/`: иначе holdout измерял бы память о корпусе, а не
обобщение.

Реквизиты с контрольной суммой (ИНН, ОГРН/ОГРНИП, СНИЛС, счёт+БИК) сгенерированы
детерминированно через `masker.detect.checksums` — контрольная цифра вычислена
по тому же алгоритму, что её потом проверяет детектор, а не подобрана
случайно. Никакого `random`: весь текст — литералы.

Формат разметки идентичен `fixtures/labeled/*.labels.json` — его читает
`masker.eval.load_holdout` / `load_negative`.
"""

from __future__ import annotations

import json
import pathlib

from docx import Document as DocxDocument
from docx.shared import Pt

from masker.detect.checksums import (
    _weighted_mod11,  # noqa: PLC2701 — тот же приватный помощник, что тесты К1 используют напрямую
    is_valid_account,
    is_valid_bik,
    is_valid_inn,
    is_valid_kpp,
    is_valid_ogrn,
    is_valid_snils,
)
from masker.detect.checksums import _INN10, _INN11, _INN12  # noqa: PLC2701

OUT_HOLDOUT = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "holdout"
OUT_NEGATIVE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "negative"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def save_deterministic(doc: DocxDocument, path: pathlib.Path) -> None:
    """Сохранить DOCX с фиксированными ZIP-метаданными — как `make_fixtures.py`."""
    import zipfile

    source = path.with_suffix(".source.docx")
    target = path.with_suffix(".deterministic.docx")
    doc.save(source)
    with (
        zipfile.ZipFile(source) as archive,
        zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as output,
    ):
        for name in sorted(archive.namelist()):
            original = archive.getinfo(name)
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = original.external_attr
            info.create_system = original.create_system
            output.writestr(info, archive.read(name))
    source.unlink()
    target.replace(path)


def _make_inn10(base9: str) -> str:
    d = [int(c) for c in base9]
    check = _weighted_mod11(d, _INN10)
    value = base9 + str(check)
    assert is_valid_inn(value), value
    return value


def _make_inn12(base10: str) -> str:
    d = [int(c) for c in base10]
    c10 = _weighted_mod11(d, _INN11)
    c11 = _weighted_mod11([*d, c10], _INN12)
    value = base10 + str(c10) + str(c11)
    assert is_valid_inn(value), value
    return value


def _make_ogrn13(base12: str) -> str:
    body = int(base12)
    check = body % 11 % 10
    value = base12 + str(check)
    assert is_valid_ogrn(value), value
    return value


def _make_ogrnip15(base14: str) -> str:
    body = int(base14)
    check = body % 13 % 10
    value = base14 + str(check)
    assert is_valid_ogrn(value), value
    return value


def _make_snils(base9: str) -> str:
    digits = [int(c) for c in base9]
    total = sum(digit * (9 - i) for i, digit in enumerate(digits))
    if total < 100:
        control = total
    elif total in (100, 101):
        control = 0
    else:
        control = total % 101
        if control == 100:
            control = 0
    value = f"{base9[:3]}-{base9[3:6]}-{base9[6:9]} {control:02d}"
    assert is_valid_snils(value), value
    return value


def _make_account(bik: str, base19: str) -> str:
    for last in range(10):
        candidate = base19 + str(last)
        if is_valid_account(candidate, bik):
            return candidate
    raise ValueError(f"не нашлось контрольной цифры счёта для {base19!r} / БИК {bik!r}")


assert is_valid_kpp("165801001")
assert is_valid_kpp("770101001")
assert is_valid_kpp("631201001")
assert is_valid_kpp("781201001")
assert is_valid_bik("049205603")
assert is_valid_bik("044525225")
assert is_valid_bik("043601607")


def _set_cell_paragraphs(cell, lines: list[str]) -> None:
    cell.paragraphs[0].text = lines[0]
    for line in lines[1:]:
        cell.add_paragraph(line)


def holdout_01_supply() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Договор поставки медицинского оборудования: коммерческая организация
    против бюджетного учреждения здравоохранения, тендерный контекст 44-ФЗ.

    Проверяет: контрактные суммы/сроки/оплату (Фаза 1–2) на незнакомых
    формулировках, и — отдельно интересный случай — публичное учреждение
    как сторона (детектор `org_name` может отфильтровать его как публичный
    орган, это тоже честный результат замера, а не повод переписывать текст).
    """
    inn_supplier = _make_inn10("165812340")
    ogrn_supplier = _make_ogrn13("102160234501")
    inn_buyer = _make_inn10("770123456")
    ogrn_buyer = _make_ogrn13("103770012340")
    snils_director = _make_snils("223344556")
    acc_supplier = _make_account("049205603", "4070281080000000000")
    acc_buyer = _make_account("044525225", "4070281010000000000")

    doc = DocxDocument()
    doc.core_properties.author = "Holdout-корпус К2"
    doc.core_properties.title = "Договор поставки медицинского оборудования 87/2026"

    doc.add_heading("ДОГОВОР ПОСТАВКИ МЕДИЦИНСКОГО ОБОРУДОВАНИЯ № 87/2026", level=1)
    doc.add_paragraph("г. Казань, 12 февраля 2026 г.")
    doc.add_paragraph(
        f"Общество с ограниченной ответственностью «Волга-Техномаш», "
        f"ИНН {inn_supplier}, КПП 165801001, ОГРН {ogrn_supplier}, именуемое "
        f"в дальнейшем «Поставщик», в лице генерального директора Морозова "
        f"Артёма Викторовича, действующего на основании Устава, с одной стороны, и"
    )
    doc.add_paragraph(
        f"Государственное бюджетное учреждение здравоохранения «Городская "
        f"клиническая больница № 15», ИНН {inn_buyer}, КПП 770101001, "
        f"ОГРН {ogrn_buyer}, именуемое в дальнейшем «Заказчик», в лице "
        f"главного врача Беляевой Дарьи Игоревны, действующей на основании "
        f"лицензии, с другой стороны, совместно именуемые «Стороны», "
        f"заключили настоящий договор о нижеследующем."
    )
    doc.add_paragraph(
        "Договор заключён в соответствии с Федеральным законом № 44-ФЗ «О "
        "контрактной системе в сфере закупок товаров, работ, услуг для "
        "обеспечения государственных и муниципальных нужд»."
    )

    doc.add_heading("1. Реквизиты Поставщика", level=2)
    doc.add_paragraph(
        "Юридический адрес: 420111, Респ. Татарстан, г. Казань, ул. Профсоюзная, д. 15, оф. 302"
    )
    doc.add_paragraph(f"Расчётный счёт № {acc_supplier}, БИК 049205603")
    doc.add_paragraph("Тел.: +7-917-123-45-67, эл. почта: sales@volga-technomash.example")
    doc.add_paragraph("СНИЛС генерального директора: " + snils_director)

    doc.add_heading("2. Реквизиты Заказчика", level=2)
    doc.add_paragraph("Юридический адрес: 115280, г. Москва, ул. Ленинская Слобода, д. 26")
    doc.add_paragraph(f"Расчётный счёт № {acc_buyer}, БИК 044525225")
    doc.add_paragraph("Телефон: 8 (495) 987-65-43, e-mail: info@gkb15.example")

    doc.add_heading("3. Цена договора и порядок расчётов", level=2)
    doc.add_paragraph(
        "Общая цена договора составляет 2 480 000 рублей 00 копеек, НДС не облагается."
    )
    doc.add_paragraph(
        "Оплата производится в течение 15 банковских дней с момента "
        "подписания акта приёма-передачи оборудования. Аванс — 30% от цены "
        "договора перечисляется в течение 10 рабочих дней после подписания "
        "договора."
    )

    doc.add_heading("4. Срок поставки", level=2)
    doc.add_paragraph(
        "Срок поставки — 45 рабочих дней с момента поступления аванса на счёт Поставщика."
    )

    doc.add_heading("5. Реквизиты сторон (сводная таблица)", level=2)
    table = doc.add_table(rows=4, cols=3)
    table.style = "Table Grid"
    rows = [
        ("Реквизит", "Поставщик", "Заказчик"),
        ("ИНН", inn_supplier, inn_buyer),
        ("Телефон", "+7-917-123-45-67", "8 (495) 987-65-43"),
        ("Расчётный счёт", acc_supplier, acc_buyer),
    ]
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            table.rows[i].cells[j].text = val

    doc.add_heading("6. Подписи", level=2)
    doc.add_paragraph("Поставщик: ______________ А.В. Морозов")
    doc.add_paragraph("Заказчик: ______________ Д.И. Беляева")

    labels = [
        {
            "type": "org_name",
            "text": "Общество с ограниченной ответственностью «Волга-Техномаш»",
            "party": "supplier",
        },
        {"type": "inn", "text": inn_supplier, "party": "supplier"},
        {"type": "kpp", "text": "165801001", "party": "supplier"},
        {"type": "ogrn", "text": ogrn_supplier, "party": "supplier"},
        {"type": "person", "text": "Морозова Артёма Викторовича", "party": "supplier"},
        {
            "type": "org_name",
            "text": "Государственное бюджетное учреждение здравоохранения «Городская клиническая больница № 15»",
            "party": "customer",
        },
        {"type": "inn", "text": inn_buyer, "party": "customer"},
        {"type": "kpp", "text": "770101001", "party": "customer"},
        {"type": "ogrn", "text": ogrn_buyer, "party": "customer"},
        {"type": "person", "text": "Беляевой Дарьи Игоревны", "party": "customer"},
        {"type": "federal_law", "text": "44-ФЗ"},
        {
            "type": "address",
            "text": "420111, Респ. Татарстан, г. Казань, ул. Профсоюзная, д. 15, оф. 302",
        },
        {"type": "bank_account", "text": acc_supplier, "party": "supplier"},
        {"type": "bik", "text": "049205603", "party": "supplier"},
        {"type": "phone", "text": "+7-917-123-45-67", "party": "supplier"},
        {"type": "email", "text": "sales@volga-technomash.example", "party": "supplier"},
        {"type": "snils", "text": snils_director, "party": "supplier"},
        {"type": "address", "text": "115280, г. Москва, ул. Ленинская Слобода, д. 26"},
        {"type": "bank_account", "text": acc_buyer, "party": "customer"},
        {"type": "bik", "text": "044525225", "party": "customer"},
        {"type": "phone", "text": "8 (495) 987-65-43", "party": "customer"},
        {"type": "email", "text": "info@gkb15.example", "party": "customer"},
        {"type": "contract_amount", "text": "2 480 000 рублей"},
        # Значение сущности — весь захват регулярки вместе со словом-триггером
        # («срок поставки»/«в течение»), а не только число: так его и
        # находит ContractAmountDetector/DeliveryPeriodDetector/
        # PaymentTermsDetector по конструкции (см. их тесты в
        # tests/masker/detect/test_contract_params.py). Замер 2026-09-08:
        # три следующих ниже случая payment_terms находятся полностью.
        {"type": "delivery_period", "text": "Срок поставки — 45 рабочих дней"},
        {"type": "payment_terms", "text": "в течение 15 банковских дней с момента подписания"},
        {"type": "payment_terms", "text": "Аванс — 30%"},
        {"type": "payment_terms", "text": "в течение 10 рабочих дней после подписания"},
        {"type": "person", "text": "А.В. Морозов", "party": "supplier"},
        {"type": "person", "text": "Д.И. Беляева", "party": "customer"},
        {"type": "date", "text": "12 февраля 2026"},
        {"type": "contract_number", "text": "87/2026"},
    ]
    return doc, labels


def holdout_02_lease() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Договор аренды нежилого помещения: физлицо-арендодатель против ООО.

    Проверяет: паспорт/СНИЛС/дату рождения физлица-стороны (не директора),
    четыре разных адреса в одном документе (регистрация арендодателя,
    объект аренды, юр. адрес арендатора), роли «арендодатель»/«арендатор»
    (их нет в `fixtures/role_synonyms.json` — как и «заказчик»/«исполнитель»
    в contract_08, только с другими словами).
    """
    inn_tenant = _make_inn10("631234567")
    ogrn_tenant = _make_ogrn13("103631000123")
    snils_landlord = _make_snils("667788990")
    acc_tenant = _make_account("043601607", "4070281070000000000")

    doc = DocxDocument()
    doc.core_properties.author = "Holdout-корпус К2"
    doc.core_properties.title = "Договор аренды нежилого помещения 5/2026"

    doc.add_heading("ДОГОВОР АРЕНДЫ НЕЖИЛОГО ПОМЕЩЕНИЯ № 5/2026", level=1)
    doc.add_paragraph("г. Самара, «01» марта 2026 года")
    doc.add_paragraph(
        "Гражданин Российской Федерации Соловьёв Николай Петрович, 3 "
        "сентября 1975 года рождения, паспорт 45 12 № 778899, выдан "
        "14.03.2019 отделом УФМС России по Самарской области, СНИЛС "
        f"{snils_landlord}, зарегистрированный по адресу: 443010, г. Самара, "
        "ул. Ленинградская, д. 5, кв. 42, именуемый в дальнейшем "
        "«Арендодатель», с одной стороны, и"
    )
    doc.add_paragraph(
        f"Общество с ограниченной ответственностью «Стройсервис Плюс», "
        f"ИНН {inn_tenant}, КПП 631201001, ОГРН {ogrn_tenant}, в лице "
        f"директора Кравцовой Олеси Игоревны, именуемое в дальнейшем "
        f"«Арендатор», с другой стороны, заключили настоящий договор о "
        f"нижеследующем."
    )

    doc.add_heading("1. Предмет договора", level=2)
    doc.add_paragraph(
        "Арендодатель передаёт, а Арендатор принимает во временное "
        "пользование нежилое помещение по адресу: г. Самара, ул. Мичурина, "
        "д. 15, пом. 3, общей площадью 64,2 кв. м."
    )

    doc.add_heading("2. Реквизиты Арендатора", level=2)
    doc.add_paragraph("Юридический адрес: 443080, г. Самара, ул. Революционная, д. 70, оф. 11")
    doc.add_paragraph(f"Расчётный счёт № {acc_tenant}, БИК 043601607")
    doc.add_paragraph("Телефон: 8-846-270-11-22, e-mail: office@stroyservice-plus.example")

    doc.add_heading("3. Порядок оплаты", level=2)
    doc.add_paragraph(
        "Арендная плата вносится ежемесячно не позднее 5 числа текущего "
        "месяца путём перечисления на расчётный счёт Арендодателя."
    )

    doc.add_heading("4. Подписи", level=2)
    doc.add_paragraph("Арендодатель: ______________ Н.П. Соловьёв")
    doc.add_paragraph("Арендатор: ______________ О.И. Кравцова")

    labels = [
        {"type": "person", "text": "Соловьёв Николай Петрович", "party": "landlord"},
        {"type": "birth_date", "text": "3 сентября 1975", "party": "landlord"},
        {"type": "passport", "text": "45 12 № 778899", "party": "landlord"},
        {"type": "date", "text": "14.03.2019"},
        {"type": "snils", "text": snils_landlord, "party": "landlord"},
        {"type": "address", "text": "443010, г. Самара, ул. Ленинградская, д. 5, кв. 42"},
        {
            "type": "org_name",
            "text": "Общество с ограниченной ответственностью «Стройсервис Плюс»",
            "party": "tenant",
        },
        {"type": "inn", "text": inn_tenant, "party": "tenant"},
        {"type": "kpp", "text": "631201001", "party": "tenant"},
        {"type": "ogrn", "text": ogrn_tenant, "party": "tenant"},
        {"type": "person", "text": "Кравцовой Олеси Игоревны", "party": "tenant"},
        {"type": "address", "text": "г. Самара, ул. Мичурина, д. 15, пом. 3"},
        {"type": "address", "text": "443080, г. Самара, ул. Революционная, д. 70, оф. 11"},
        {"type": "bank_account", "text": acc_tenant, "party": "tenant"},
        {"type": "bik", "text": "043601607", "party": "tenant"},
        {"type": "phone", "text": "8-846-270-11-22", "party": "tenant"},
        {"type": "email", "text": "office@stroyservice-plus.example", "party": "tenant"},
        {"type": "person", "text": "Н.П. Соловьёв", "party": "landlord"},
        {"type": "person", "text": "О.И. Кравцова", "party": "tenant"},
        {"type": "date", "text": "«01» марта 2026"},
        {"type": "contract_number", "text": "5/2026"},
    ]
    return doc, labels


def holdout_03_transport() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Договор перевозки грузов: ИП-перевозчик против ООО-заказчика.

    Проверяет: ИНН/ОГРНИП физлица-предпринимателя (12/15 цифр — не 10/13,
    как у остальных фикстур), телефон формата 8-800, e-mail в верхнем
    регистре, номер договора с буквенным префиксом, второй федеральный
    закон (223-ФЗ, не 44-ФЗ, как в holdout_01).
    """
    inn_carrier = _make_inn12("7801234567")
    ogrnip_carrier = _make_ogrnip15("31278400012340")
    inn_customer = _make_inn10("781234561")
    ogrn_customer = _make_ogrn13("102780012349")
    snils_carrier = _make_snils("445566778")

    doc = DocxDocument()
    doc.core_properties.author = "Holdout-корпус К2"
    doc.core_properties.title = "Договор перевозки грузов У-12/2026"

    doc.add_heading("ДОГОВОР ПЕРЕВОЗКИ ГРУЗОВ № У-12/2026", level=1)
    doc.add_paragraph("г. Санкт-Петербург, 20 апреля 2026 года.")
    doc.add_paragraph(
        f"Индивидуальный предприниматель Дегтярёв Роман Олегович, ИНН "
        f"{inn_carrier}, ОГРНИП {ogrnip_carrier}, именуемый в дальнейшем "
        f"«Перевозчик», с одной стороны, и"
    )
    doc.add_paragraph(
        f"Общество с ограниченной ответственностью «Северная логистика», "
        f"ИНН {inn_customer}, КПП 781201001, ОГРН {ogrn_customer}, "
        f"именуемое в дальнейшем «Заказчик», в лице представителя по "
        f"доверенности Никоновой Елены Станиславовны, с другой стороны, "
        f"заключили договор о нижеследующем."
    )

    doc.add_heading("1. Реквизиты Перевозчика", level=2)
    doc.add_paragraph(
        "Адрес регистрации: 196006, г. Санкт-Петербург, Московский пр., д. 143, лит. А"
    )
    doc.add_paragraph("Телефон: 8-800-555-01-23")
    doc.add_paragraph("СНИЛС: " + snils_carrier)

    doc.add_heading("2. Реквизиты Заказчика", level=2)
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    _set_cell_paragraphs(
        table.cell(0, 0),
        [
            "Адрес: 191025, г. Санкт-Петербург, Невский пр., д. 90/92",
            "E-mail: INFO@SEVLOGISTIKA.EXAMPLE",
        ],
    )

    doc.add_heading("3. Особые условия", level=2)
    doc.add_paragraph(
        "Договор заключён в соответствии с Федеральным законом № 223-ФЗ "
        "«О закупках товаров, работ, услуг отдельными видами юридических лиц»."
    )

    doc.add_heading("4. Подписи", level=2)
    doc.add_paragraph("Перевозчик: ______________ Р.О. Дегтярёв")
    doc.add_paragraph("Заказчик: ______________ Е.С. Никонова")

    labels = [
        {"type": "person", "text": "Дегтярёв Роман Олегович", "party": "carrier"},
        {"type": "inn", "text": inn_carrier, "party": "carrier"},
        {"type": "ogrn", "text": ogrnip_carrier, "party": "carrier"},
        {
            "type": "org_name",
            "text": "Общество с ограниченной ответственностью «Северная логистика»",
            "party": "customer",
        },
        {"type": "inn", "text": inn_customer, "party": "customer"},
        {"type": "kpp", "text": "781201001", "party": "customer"},
        {"type": "ogrn", "text": ogrn_customer, "party": "customer"},
        {"type": "person", "text": "Никоновой Елены Станиславовны", "party": "customer"},
        {"type": "address", "text": "196006, г. Санкт-Петербург, Московский пр., д. 143, лит. А"},
        {"type": "phone", "text": "8-800-555-01-23", "party": "carrier"},
        {"type": "snils", "text": snils_carrier, "party": "carrier"},
        {"type": "address", "text": "191025, г. Санкт-Петербург, Невский пр., д. 90/92"},
        {"type": "email", "text": "INFO@SEVLOGISTIKA.EXAMPLE", "party": "customer"},
        {"type": "federal_law", "text": "223-ФЗ"},
        {"type": "date", "text": "20 апреля 2026"},
        {"type": "contract_number", "text": "У-12/2026"},
        {"type": "person", "text": "Р.О. Дегтярёв", "party": "carrier"},
        {"type": "person", "text": "Е.С. Никонова", "party": "customer"},
    ]
    return doc, labels


def negative_01_gost() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Технические условия на резисторы — ноль сущностей PII по построению.

    Ни одной организации-стороны, ни одного человека, ни одного платёжного
    реквизита. Числа, даты и коды здесь — техническая номенклатура (ГОСТ/ТУ,
    номер партии, допуски, температурный диапазон), которая по форме похожа
    на реквизиты, но не является персональными или платёжными данными.
    Любая сущность, найденная в этом документе, — ложное срабатывание по
    определению (см. `masker.eval._print_negative`).
    """
    doc = DocxDocument()
    doc.core_properties.author = "Негативный корпус К2"
    doc.core_properties.title = "Технические условия ТУ 3450-014-07622645-2020"

    doc.add_heading(
        "ТЕХНИЧЕСКИЕ УСЛОВИЯ НА РЕЗИСТОРЫ ПОСТОЯННЫЕ НЕПРОВОЛОЧНЫЕ ТУ 3450-014-07622645-2020",
        level=1,
    )

    doc.add_heading("1. Область применения", level=2)
    doc.add_paragraph("Дата введения — 01.07.2020.")
    doc.add_paragraph(
        "Настоящие технические условия распространяются на резисторы "
        "постоянные непроволочные типа С2-33Н и устанавливают технические "
        "требования, правила приёмки, методы контроля, маркировку, "
        "упаковку, транспортирование и хранение."
    )
    doc.add_paragraph(
        "Изделия соответствуют требованиям ГОСТ Р 52931-2008, ГОСТ "
        "2.601-2013 и ГОСТ 15150-69 в части климатического исполнения."
    )

    doc.add_heading("2. Технические требования", level=2)
    table = doc.add_table(rows=8, cols=2)
    table.style = "Table Grid"
    rows = [
        ("Параметр", "Значение"),
        ("Номинальная мощность рассеяния", "0,25 Вт"),
        ("Номинальное сопротивление", "от 1 Ом до 1 МОм"),
        ("Предельное отклонение сопротивления", "±5 %"),
        ("Температурный коэффициент сопротивления", "±200×10⁻⁶ 1/°C"),
        ("Диапазон рабочих температур", "от минус 60 °C до плюс 155 °C"),
        ("Относительная влажность воздуха при 25 °C", "до 98 %"),
        ("Наработка до отказа", "не менее 25 000 ч"),
    ]
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            table.rows[i].cells[j].text = val

    doc.add_heading("3. Маркировка", level=2)
    doc.add_paragraph(
        "На корпусе резистора наносится условное обозначение по схеме: "
        "С2-33Н-0,25-100 кОм±5 %-В, где «В» — группа климатического "
        "исполнения по ГОСТ 15150-69."
    )
    doc.add_paragraph(
        "Каждая партия сопровождается маркировкой номера партии по схеме "
        "ГГ-ММ-НННН, например 24-11-0347, и датой изготовления в формате "
        "квартал/год, например II кв. 2025 г."
    )

    doc.add_heading("4. Упаковка, транспортирование и хранение", level=2)
    doc.add_paragraph(
        "Резисторы упаковывают в тару по ГОСТ 23088-80, по 500 штук в "
        "потребительскую упаковку и не более 10 000 штук в транспортную тару."
    )
    doc.add_paragraph(
        "Транспортирование допускается всеми видами транспорта в крытых "
        "транспортных средствах в соответствии с правилами перевозок "
        "грузов, действующими на конкретном виде транспорта."
    )
    doc.add_paragraph(
        "Гарантийный срок хранения — 25 лет со дня изготовления при "
        "соблюдении условий хранения по группе 3 ГОСТ 15150-69."
    )

    doc.add_heading("5. Указания по эксплуатации", level=2)
    doc.add_paragraph(
        "Изготовитель гарантирует соответствие резисторов требованиям "
        "настоящих технических условий при соблюдении потребителем условий "
        "транспортирования, хранения и эксплуатации, установленных "
        "настоящими техническими условиями и ГОСТ Р 52931-2008."
    )
    doc.add_paragraph(
        "Настоящие технические условия введены в действие взамен ТУ "
        "3450-009-07622645-2015 и подлежат пересмотру не реже одного раза "
        "в 5 лет."
    )

    labels: list[dict[str, str]] = []
    return doc, labels


def main() -> int:
    OUT_HOLDOUT.mkdir(parents=True, exist_ok=True)
    OUT_NEGATIVE.mkdir(parents=True, exist_ok=True)
    for name, builder, out_dir in (
        ("holdout_01_supply", holdout_01_supply, OUT_HOLDOUT),
        ("holdout_02_lease", holdout_02_lease, OUT_HOLDOUT),
        ("holdout_03_transport", holdout_03_transport, OUT_HOLDOUT),
        ("negative_01_gost", negative_01_gost, OUT_NEGATIVE),
    ):
        doc, labels = builder()
        for p in doc.paragraphs:
            for run in p.runs:
                run.font.size = run.font.size or Pt(11)
        save_deterministic(doc, out_dir / f"{name}.docx")
        payload = {"entities": labels}
        (out_dir / f"{name}.labels.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{name}.docx — сущностей в разметке: {len(labels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
