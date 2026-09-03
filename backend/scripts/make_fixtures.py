"""Генератор синтетического размеченного корпуса.

Реальные документы от заказчика придут позже и лягут в `fixtures/real/`
(он в .gitignore). До тех пор метрики считаются на синтетике, которая
намеренно содержит трудные случаи, а не только удобные.

Разметка пишется рядом в `<имя>.labels.json` — её формат читает `masker.eval`.
"""

from __future__ import annotations

import json
import pathlib
import zipfile

from docx import Document as DocxDocument
from docx.shared import Pt

OUT = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "labeled"
#: Фикстуры, детекция которых требует опционального extra `[gliner]`.
#: В общий корпус они попасть не могут: `make gate` обязан проходить на
#: машине без torch и без 1.1 ГБ весов, а `default_detectors` на спеке с
#: `kind="gliner_*"` там падает `RuntimeError`. Замер по ним делает
#: отдельный тест с маркером `gliner`.
OUT_GLINER = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "gliner"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def save_deterministic(doc: DocxDocument, path: pathlib.Path) -> None:
    """Сохранить DOCX с фиксированными ZIP-метаданными и порядком записей."""
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


def contract_01() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Обычный договор поставки: две стороны, блоки реквизитов, таблица."""
    doc = DocxDocument()
    doc.core_properties.author = "Петрова Мария Сергеевна"
    doc.core_properties.title = "Договор поставки 44/2026"

    doc.add_heading("ДОГОВОР ПОСТАВКИ № 44/2026", level=1)
    doc.add_paragraph("г. Воронеж, 15 января 2026 г.")
    doc.add_paragraph(
        "Акционерное общество «Триема», ИНН 3662103003, КПП 366201001, "
        "ОГРН 1023601546902, именуемое в дальнейшем «Поставщик», в лице "
        "генерального директора Иванова Ивана Ивановича, с одной стороны, и"
    )
    doc.add_paragraph(
        "Общество с ограниченной ответственностью «Вектор», ИНН 7707083893, "
        "КПП 770701001, именуемое в дальнейшем «Покупатель», в лице директора "
        "Сидоровой Анны Петровны, с другой стороны, заключили договор о нижеследующем."
    )

    doc.add_heading("1. Реквизиты Поставщика", level=2)
    doc.add_paragraph("Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, оф. 12")
    doc.add_paragraph("Расчётный счёт: 40702810100000000002")
    doc.add_paragraph("БИК: 042007681")
    doc.add_paragraph("Телефон: +7 (473) 250-10-10, e-mail: info@triema.example")

    doc.add_heading("2. Реквизиты Покупателя", level=2)
    doc.add_paragraph("Адрес: 101000, г. Москва, ул. Мясницкая, д. 26")
    doc.add_paragraph("Телефон: 8-910-347-51-07")
    doc.add_paragraph("E-mail: zakupki@vektor.example")

    doc.add_heading("3. Спецификация", level=2)
    table = doc.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    for i, row in enumerate(
        [
            ("Наименование", "Кол-во", "Цена, руб."),
            ("Резистор МЛТ-0,25", "1000", "12 500,00"),
            ("Конденсатор К73-17", "500", "8 300,00"),
        ]
    ):
        for j, val in enumerate(row):
            table.rows[i].cells[j].text = val

    doc.add_heading("4. Подписи", level=2)
    doc.add_paragraph("Поставщик: ______________ И.И. Иванов")
    doc.add_paragraph("Покупатель: ______________ А.П. Сидорова")

    labels = [
        {"type": "org_name", "text": "Акционерное общество «Триема»", "party": "supplier"},
        {"type": "inn", "text": "3662103003", "party": "supplier"},
        {"type": "kpp", "text": "366201001", "party": "supplier"},
        {"type": "ogrn", "text": "1023601546902", "party": "supplier"},
        {"type": "person", "text": "Иванова Ивана Ивановича", "party": "supplier"},
        {"type": "bank_account", "text": "40702810100000000002", "party": "supplier"},
        {"type": "bik", "text": "042007681", "party": "supplier"},
        {"type": "phone", "text": "+7 (473) 250-10-10", "party": "supplier"},
        {"type": "email", "text": "info@triema.example", "party": "supplier"},
        {"type": "address", "text": "394018, г. Воронеж, ул. Кирова, д. 4, оф. 12"},
        {
            "type": "org_name",
            "text": "Общество с ограниченной ответственностью «Вектор»",
            "party": "buyer",
        },
        {"type": "inn", "text": "7707083893", "party": "buyer"},
        {"type": "kpp", "text": "770701001", "party": "buyer"},
        {"type": "person", "text": "Сидоровой Анны Петровны", "party": "buyer"},
        {"type": "phone", "text": "8-910-347-51-07", "party": "buyer"},
        {"type": "email", "text": "zakupki@vektor.example", "party": "buyer"},
        {"type": "address", "text": "101000, г. Москва, ул. Мясницкая, д. 26"},
        {"type": "person", "text": "И.И. Иванов", "party": "supplier"},
        {"type": "person", "text": "А.П. Сидорова", "party": "buyer"},
    ]
    return doc, labels


def contract_02_hard() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Трудный случай: ИНН физлица, ловушки-непроходящие-контрольную-сумму.

    Здесь проверяется, что детектор не ловится на числа той же длины:
    номер накладной из 10 цифр и «ОГРН» из 13 цифр с битой контрольной
    цифрой обязаны быть пропущены. Регулярка без контрольной суммы
    провалит именно этот файл.
    """
    doc = DocxDocument()
    doc.core_properties.author = "Козлов П.А."

    doc.add_heading("АКТ СВЕРКИ ВЗАИМНЫХ РАСЧЁТОВ", level=1)
    doc.add_paragraph(
        "Индивидуальный предприниматель Кузнецов Пётр Алексеевич, "
        "ИНН 500100732259, СНИЛС 112-233-445 95."
    )
    doc.add_paragraph("Накладная № 3662103004 от 12.02.2026.")  # ловушка: битый ИНН
    doc.add_paragraph("Внутренний код операции: 1023601546903.")  # ловушка: битый ОГРН
    doc.add_paragraph("Паспорт 20 04 123456, выдан 10.05.2018.")
    doc.add_paragraph("Контакт: pkuznetsov@example.org")

    labels = [
        {"type": "person", "text": "Кузнецов Пётр Алексеевич", "party": "third_party"},
        {"type": "inn", "text": "500100732259", "party": "third_party"},
        {"type": "snils", "text": "112-233-445 95", "party": "third_party"},
        {"type": "passport", "text": "20 04 123456", "party": "third_party"},
        {"type": "email", "text": "pkuznetsov@example.org", "party": "third_party"},
    ]
    return doc, labels


def contract_03_ner() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Трудные границы Natasha: формы, реквизиты внутри спана и роли."""
    doc = DocxDocument()
    doc.core_properties.author = "Петрова Мария Сергеевна"
    doc.core_properties.title = "Проверка NER"

    doc.add_heading("ПРОТОКОЛ СОГЛАСОВАНИЯ", level=1)
    doc.add_paragraph(
        'ООО "Ромашка" (ИНН 3662103003), в лице Генерального директора '
        "Петровой Марии Сергеевны, подтверждает участие."
    )
    doc.add_paragraph(
        "Поставщик: Общество с ограниченной ответственностью «Вектор», в лице "
        "Сидоровой Анны Петровны."
    )
    doc.add_paragraph("ИП Сидоров С.С. направил документы в ООО «Договор и партнёры».")
    doc.add_paragraph('ООО "Ромашка" (ОКПО 12345678, ИНН 3662103003) участвует.')
    doc.add_paragraph("АО «Актив» (р/с 40702810100000000002 в банке, БИК 042007681) — исполнитель.")
    doc.add_paragraph("ДОГОВОР ПОСТАВКИ")
    doc.add_paragraph("Сидорова Анна Петровна согласовала документы.")
    doc.add_paragraph("Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, оф. 12")

    labels = [
        {"type": "org_name", "text": 'ООО "Ромашка"', "party": "supplier"},
        {"type": "inn", "text": "3662103003", "party": "supplier"},
        {"type": "person", "text": "Петровой Марии Сергеевны", "party": "supplier"},
        {
            "type": "org_name",
            "text": "Общество с ограниченной ответственностью «Вектор»",
            "party": "buyer",
        },
        {"type": "person", "text": "Сидоровой Анны Петровны", "party": "buyer"},
        {"type": "person", "text": "Сидоров С.С.", "party": "third_party"},
        {"type": "org_name", "text": "ООО «Договор и партнёры»", "party": "third_party"},
        {"type": "org_name", "text": "АО «Актив»", "party": "third_party"},
        {"type": "bank_account", "text": "40702810100000000002", "party": "third_party"},
        {"type": "bik", "text": "042007681", "party": "third_party"},
        {"type": "person", "text": "Сидорова Анна Петровна", "party": "buyer"},
        {"type": "address", "text": "394018, г. Воронеж, ул. Кирова, д. 4, оф. 12"},
    ]
    return doc, labels


def contract_04_bankruptcy() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Синтетическая форма договора банкротства с реквизитами в таблице."""
    doc = DocxDocument()
    doc.core_properties.author = "Синтетический корпус"
    doc.core_properties.title = "Договор купли-продажи имущества"

    doc.add_heading("ДОГОВОР КУПЛИ-ПРОДАЖИ ИМУЩЕСТВА", level=1)
    doc.add_paragraph(
        "Продавец, Сидоровой Анны Петровны, 15 февраля 1982 года рождения, "
        "место рождения: г. Орёл, СНИЛС 112-233-445 95, ИНН 500100732259, "
        "адрес регистрации: 302000, г. Орёл, ул. Лесная, д. 7."
    )
    doc.add_paragraph(
        "Должник ООО «Север», в лице финансового управляющего "
        "Кузнецова Петра Алексеевича, действует в рамках конкурсного производства."
    )
    doc.add_paragraph("Определение вынес Арбитражный суд.")
    doc.add_paragraph("Продавца уведомили; Продавцу передан акт; Продавец получил оплату.")
    doc.add_paragraph("Покупатель осмотрел лот; Покупателя уведомили; Покупателю передан акт.")

    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    _set_cell_paragraphs(
        table.cell(0, 0),
        [
            "Продавец: Сидорова Анна Петровна",
            "СНИЛС 112-233-445 95",
            "ИНН 500100732259",
            "Адрес: 302000, г. Орёл, ул. Лесная, д. 7",
        ],
    )
    _set_cell_paragraphs(
        table.cell(0, 1),
        [
            "Покупатель: ______",
            "Паспорт: ______",
            "Адрес: ______",
            "Подпись: ______",
        ],
    )

    # Дата, место рождения и адрес намеренно не размечены: их детекторы — T1.13/T1.14.
    labels = [
        {"type": "person", "text": "Сидоровой Анны Петровны", "party": "seller"},
        {"type": "snils", "text": "112-233-445 95", "party": "seller"},
        {"type": "inn", "text": "500100732259", "party": "seller"},
        {"type": "org_name", "text": "ООО «Север»", "party": "seller"},
        {
            "type": "person",
            "text": "Кузнецова Петра Алексеевича",
            "party": "third_party",
        },
        # T1.11: сущность находится в отдельном абзаце ячейки таблицы.
        {"type": "person", "text": "Сидорова Анна Петровна", "party": "seller"},
        {"type": "address", "text": "302000, г. Орёл, ул. Лесная, д. 7"},
    ]
    return doc, labels


def contract_05_tables() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Табличные крайние случаи: merge и вложенная таблица вне скоупа."""
    doc = DocxDocument()
    doc.core_properties.author = "Синтетический корпус"
    doc.core_properties.title = "Проверка таблиц"

    doc.add_heading("ПРОВЕРКА ТАБЛИЦ", level=1)
    doc.add_paragraph("ООО «Горизонт», ИНН 3662103003, подписало спецификацию.")

    merged = doc.add_table(rows=2, cols=3)
    merged.style = "Table Grid"
    merged.cell(0, 0).merge(merged.cell(0, 1)).text = "Объединённая ячейка: ИНН 3662103003"
    merged.cell(0, 2).text = "Хвост строки"
    merged.cell(1, 0).text = "Обычная ячейка"
    merged.cell(1, 1).text = "Контроль"
    merged.cell(1, 2).text = "Без PII"

    vertical = doc.add_table(rows=2, cols=2)
    vertical.style = "Table Grid"
    vertical.cell(0, 0).merge(vertical.cell(1, 0)).text = "Вертикальное объединение"
    vertical.cell(0, 1).text = "Верхняя ячейка"
    vertical.cell(1, 1).text = "Нижняя ячейка"

    nested_host = doc.add_table(rows=1, cols=1)
    nested_host.style = "Table Grid"
    nested_host.cell(0, 0).text = "Ячейка с вложенной таблицей"
    nested = nested_host.cell(0, 0).add_table(rows=1, cols=1)
    nested.style = "Table Grid"
    nested.cell(0, 0).text = "СНИЛС 112-233-445 95"

    labels = [
        {"type": "org_name", "text": "ООО «Горизонт»", "party": "supplier"},
        {"type": "inn", "text": "3662103003", "party": "supplier"},
    ]
    return doc, labels


def contract_06_address() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Адресные случаи T1.14: достаточные, частичные и отрицательные."""
    doc = DocxDocument()
    doc.core_properties.author = "Синтетический корпус"
    doc.core_properties.title = "Проверка адресов"

    doc.add_heading("ПРОВЕРКА АДРЕСОВ", level=1)
    doc.add_paragraph("Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, оф. 12")
    doc.add_paragraph(
        "Адрес регистрации: 394024, Воронежская область, г Воронеж, пер Здоровья, д 86а, кв 95"
    )
    doc.add_paragraph("Адрес: г. Воронеж, ул. Мира, 12")
    doc.add_paragraph("Адрес: г. Воронеж")
    doc.add_paragraph("г. Воронеж, 15 января 2026 г.")
    doc.add_paragraph("место рождения: гор. Старый Оскол Белгородской обл.")
    doc.add_paragraph("Адрес: 394018, г. Воронеж, ул. Кирова, д. 4, оф. 12, ИНН 3662103003")
    doc.add_paragraph(
        "ИНН: 312822458000 , адрес регистрации по месту жительства: 394024, "
        "Воронежская область, г Воронеж, пер Здоровья, д 86а, кв 95 ) Атараев Б.М., "
        "именуемый в дальнейшем «Продавец»"
    )

    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    _set_cell_paragraphs(
        table.cell(0, 0),
        [
            "адрес регистрации по месту жительства:",
            "309512, Белгородская область, г. Старый Оскол,",
            "мкр. Жукова, д. 20, кв. 15",
        ],
    )

    labels = [
        {"type": "address", "text": "394018, г. Воронеж, ул. Кирова, д. 4, оф. 12"},
        {
            "type": "address",
            "text": "394024, Воронежская область, г Воронеж, пер Здоровья, д 86а, кв 95",
        },
        {"type": "address", "text": "г. Воронеж, ул. Мира, 12"},
        {"type": "address", "text": "г. Воронеж"},
        {"type": "address", "text": "мкр. Жукова, д. 20, кв. 15"},
        {"type": "inn", "text": "3662103003", "party": "supplier"},
        {"type": "inn", "text": "312822458000", "party": "seller"},
        {"type": "person", "text": "Атараев Б.М", "party": "seller"},
    ]
    return doc, labels


def contract_08_roles() -> tuple[DocxDocument, list[dict[str, str]]]:
    """Открытые роли: заказчик и исполнитель, без словаря ролей в коде."""
    doc = DocxDocument()
    doc.add_heading("ДОГОВОР ОКАЗАНИЯ УСЛУГ", level=1)
    doc.add_paragraph(
        "ООО «Северный свет», ИНН 3662103003, именуемое в дальнейшем «Заказчик», с одной стороны, и"
    )
    doc.add_paragraph(
        "ООО «Точный расчёт», ИНН 7707083893, именуемое в дальнейшем «Исполнитель», "
        "с другой стороны, заключили договор."
    )
    doc.add_heading("1. Реквизиты Заказчика", level=2)
    doc.add_paragraph("Расчётный счёт: 40702810100000000002")
    doc.add_heading("2. Реквизиты Исполнителя", level=2)
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    table.cell(0, 0).text = "Телефон: 8-910-347-51-07"
    doc.add_heading("3. Подписи", level=2)
    doc.add_paragraph("Заказчик: ______________ Иванов И.И.")
    doc.add_paragraph("Исполнитель: ______________ Сидоров А.П.")
    labels = [
        {"type": "org_name", "text": "ООО «Северный свет»", "party": "customer"},
        {"type": "inn", "text": "3662103003", "party": "customer"},
        {"type": "bank_account", "text": "40702810100000000002", "party": "customer"},
        {"type": "org_name", "text": "ООО «Точный расчёт»", "party": "contractor"},
        {"type": "inn", "text": "7707083893", "party": "contractor"},
        {"type": "phone", "text": "8-910-347-51-07", "party": "contractor"},
        {"type": "person", "text": "Иванов И.И", "party": "customer"},
        {"type": "person", "text": "Сидоров А.П", "party": "contractor"},
    ]
    return doc, labels


def contract_09_custom() -> tuple[DocxDocument, list[dict[str, str]], list[dict[str, object]]]:
    """Договор с пользовательскими типами (T1.13, шаг 6).

    Два типа, исполнимых офлайн и без LLM: `shipment_date` (`regex` +
    `context`, не критичный) и `product_code` (`literals`, критичный —
    порог recall 1.0 для пользовательского типа обязан проверяться реально,
    design notes 6.8). Стороны и реквизиты — обычные встроенные типы, чтобы
    документ оставался реалистичным договором, а не голым списком custom-полей.
    """
    doc = DocxDocument()
    doc.core_properties.author = "Синтетический корпус"
    doc.core_properties.title = "Договор поставки с пользовательскими типами"

    doc.add_heading("ДОГОВОР ПОСТАВКИ № 9/2026", level=1)
    doc.add_paragraph("г. Воронеж, 5 марта 2026 г.")
    doc.add_paragraph(
        "Общество с ограниченной ответственностью «Техноснаб», ИНН 5001007311, "
        "именуемое в дальнейшем «Поставщик», в лице директора Смирнова Олега "
        "Викторовича, с одной стороны, и"
    )
    doc.add_paragraph(
        "Акционерное общество «Стройимпульс», ИНН 9102003303, именуемое в "
        "дальнейшем «Покупатель», в лице директора Ковалёвой Ирины Николаевны, "
        "с другой стороны, заключили договор о нижеследующем."
    )

    doc.add_heading("1. Спецификация", level=2)
    table = doc.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    for i, row in enumerate(
        [
            ("Код товара", "Наименование"),
            ("SKU-ABC-42", "Резистор МЛТ-0,25"),
            ("SKU-XYZ-77", "Конденсатор К73-17"),
        ]
    ):
        for j, val in enumerate(row):
            table.rows[i].cells[j].text = val

    doc.add_heading("2. Сроки поставки", level=2)
    doc.add_paragraph("Дата отгрузки: 20.03.2026. Поставка осуществляется силами Поставщика.")

    doc.add_heading("3. Подписи", level=2)
    doc.add_paragraph("Поставщик: ______________ О.В. Смирнов")
    doc.add_paragraph("Покупатель: ______________ И.Н. Ковалёва")

    labels = [
        {"type": "contract_number", "text": "9/2026"},
        {
            "type": "org_name",
            "text": "Общество с ограниченной ответственностью «Техноснаб»",
            "party": "supplier",
        },
        {"type": "inn", "text": "5001007311", "party": "supplier"},
        {"type": "person", "text": "Смирнова Олега Викторовича", "party": "supplier"},
        {
            "type": "org_name",
            "text": "Акционерное общество «Стройимпульс»",
            "party": "buyer",
        },
        {"type": "inn", "text": "9102003303", "party": "buyer"},
        {"type": "person", "text": "Ковалёвой Ирины Николаевны", "party": "buyer"},
        {"type": "person", "text": "О.В. Смирнов", "party": "supplier"},
        {"type": "person", "text": "И.Н. Ковалёва", "party": "buyer"},
        {"type": "product_code", "text": "SKU-ABC-42"},
        {"type": "product_code", "text": "SKU-XYZ-77"},
        {"type": "shipment_date", "text": "20.03.2026"},
    ]
    custom_types: list[dict[str, object]] = [
        {
            "id": "shipment_date",
            "title": "Дата отгрузки",
            "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
            "critical": False,
            "detect": {
                "kind": "regex",
                "pattern": r"\d{2}\.\d{2}\.\d{4}",
                "context": ["отгрузк", "поставк"],
            },
        },
        {
            "id": "product_code",
            "title": "Код товара",
            "marker": "[КОД-ТОВАРА-{n}]",
            "critical": True,
            "detect": {
                "kind": "literals",
                "values": ["SKU-ABC-42", "SKU-XYZ-77"],
                "match": "whole_word",
            },
        },
    ]
    return doc, labels, custom_types


def contract_10_roles_dates() -> tuple[
    DocxDocument, list[dict[str, str]], list[dict[str, object]], list[dict[str, str]]
]:
    """Класс D (T1.13.1, шаг 17): роль поверх одинакового формата.

    Одна и та же дата `dd.mm.yyyy` стоит внутри одного абзаца дважды — один
    раз как дата подписания, другой раз как дата отгрузки. Формат обеих
    ролей неразличим, только контекст (соседние слова) говорит, какая
    дата — какая. Четыре пары, а не одна: единственная пара даёт только
    F1 в {0, 0.5, 1.0} и не может ни подтвердить, ни опровергнуть порог 0.9.

    `class_d` в возврате — точный текст каждого абзаца и дата внутри него:
    тест находит нужный `Segment` по точному совпадению текста и вычисляет
    ожидаемые смещения через `str.find` сам, а не хранит их руками (смещения
    разъедутся при любой правке формулировки, а сам текст — нет смысла
    дублировать он и так уже здесь).

    Намеренно без строки «г. Воронеж, DD месяц YYYY г.» вначале, как у других
    фикстур: в реальном договоре эта строка почти всегда и есть дата
    подписания, и включение её сюда без даты рядом (`text.date`-парой) сделало
    бы её нелегитимной ловушкой для `gliner_structure` — модель, пометившая её
    `signing_date`, была бы права по смыслу, а не ошибалась.
    """
    doc = DocxDocument()
    doc.core_properties.author = "Синтетический корпус"
    doc.core_properties.title = "Договор поставки — роли поверх одинакового формата"

    doc.add_heading("ДОГОВОР ПОСТАВКИ № 10/2026", level=1)
    doc.add_paragraph("г. Воронеж")
    doc.add_paragraph(
        "Общество с ограниченной ответственностью «Полюс», ИНН 6317053059, "
        "именуемое в дальнейшем «Поставщик», в лице директора Фёдорова Павла "
        "Сергеевича, с одной стороны, и"
    )
    doc.add_paragraph(
        "Акционерное общество «Меридиан», ИНН 7810123451, именуемое в "
        "дальнейшем «Покупатель», в лице директора Никитиной Елены Олеговны, "
        "с другой стороны, заключили договор о нижеследующем."
    )

    doc.add_heading("1. Даты подписания и отгрузки", level=2)
    class_d_pairs = [
        (
            "Договор считается подписанным сторонами 12.02.2026, а отгрузка "
            "товара по настоящему договору осуществляется также 12.02.2026 — "
            "в тот же день, что и подписание.",
            "12.02.2026",
        ),
        (
            "Стороны подтверждают, что подписание настоящего приложения "
            "состоялось 05.03.2026; фактическая отгрузка партии товара "
            "происходит день в день — 05.03.2026, прямо со склада Поставщика.",
            "05.03.2026",
        ),
        (
            "Датой подписания настоящего договора считается 18.04.2026 года. "
            "Отгрузка первой партии товара назначена на ту же дату — "
            "18.04.2026, без права переноса.",
            "18.04.2026",
        ),
        (
            "Подписание договора сторонами состоялось 09.05.2026. Отгрузка "
            "товара производится в дату подписания, то есть 09.05.2026, без "
            "отсрочки поставки.",
            "09.05.2026",
        ),
    ]
    for text, _date in class_d_pairs:
        doc.add_paragraph(text)

    doc.add_heading("2. Подписи", level=2)
    doc.add_paragraph("Поставщик: ______________ П.С. Фёдоров")
    doc.add_paragraph("Покупатель: ______________ Е.О. Никитина")

    labels: list[dict[str, str]] = [
        {"type": "contract_number", "text": "10/2026"},
        {
            "type": "org_name",
            "text": "Общество с ограниченной ответственностью «Полюс»",
            "party": "supplier",
        },
        {"type": "inn", "text": "6317053059", "party": "supplier"},
        {"type": "person", "text": "Фёдорова Павла Сергеевича", "party": "supplier"},
        {"type": "org_name", "text": "Акционерное общество «Меридиан»", "party": "buyer"},
        {"type": "inn", "text": "7810123451", "party": "buyer"},
        {"type": "person", "text": "Никитиной Елены Олеговны", "party": "buyer"},
        {"type": "person", "text": "П.С. Фёдоров", "party": "supplier"},
        {"type": "person", "text": "Е.О. Никитина", "party": "buyer"},
    ]
    for _text, date in class_d_pairs:
        # Одна и та же строка даты дважды — по разу на роль (см. докстринг).
        labels.append({"type": "shipment_date", "text": date})
        labels.append({"type": "signing_date", "text": date})

    custom_types: list[dict[str, object]] = [
        {
            "id": "shipment_date",
            "title": "Дата отгрузки",
            "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
            "critical": False,
            "detect": {
                "kind": "gliner_structure",
                "label": "дата отгрузки",
                "description": (
                    "Дата фактической отгрузки или поставки товара покупателю, "
                    "а не дата подписания договора"
                ),
                "structure": "поставка",
                "field": "дата_отгрузки",
                "threshold": 0.3,
            },
        },
        {
            "id": "signing_date",
            "title": "Дата подписания",
            "marker": "[ДАТА-ПОДПИСАНИЯ-{n}]",
            "critical": False,
            "detect": {
                "kind": "gliner_structure",
                "label": "дата подписания",
                "description": (
                    "Дата подписания или заключения договора сторонами, а не дата отгрузки товара"
                ),
                "structure": "подписание",
                "field": "дата_подписания",
                "threshold": 0.3,
            },
        },
    ]

    class_d = [{"text": text, "date": date} for text, date in class_d_pairs]

    return doc, labels, custom_types, class_d


def _set_cell_paragraphs(cell, lines: list[str]) -> None:
    cell.paragraphs[0].text = lines[0]
    for line in lines[1:]:
        cell.add_paragraph(line)


#: Имена фикстур, которые пишутся в `OUT_GLINER`, а не в общий корпус.
_GLINER_ONLY = frozenset({"contract_10_roles_dates"})


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    OUT_GLINER.mkdir(parents=True, exist_ok=True)
    for name, builder in (
        ("contract_01", contract_01),
        ("contract_02_hard", contract_02_hard),
        ("contract_03_ner", contract_03_ner),
        ("contract_04_bankruptcy", contract_04_bankruptcy),
        ("contract_05_tables", contract_05_tables),
        ("contract_06_address", contract_06_address),
        ("contract_08_roles", contract_08_roles),
        ("contract_09_custom", contract_09_custom),
        ("contract_10_roles_dates", contract_10_roles_dates),
    ):
        result = builder()
        # Большинство генераторов возвращают (doc, labels); контракты с
        # пользовательскими типами (T1.13, шаг 6) — тройку с готовой
        # секцией `custom_types`, отдельный список не заводим ради одного
        # файла. Класс D (T1.13.1, шаг 17) добавляет четвёртый элемент —
        # позиционную разметку `class_d` для теста-замера F1.
        class_d: list[dict[str, str]] | None
        if len(result) == 4:
            doc, labels, custom_types, class_d = result
        elif len(result) == 3:
            doc, labels, custom_types = result
            class_d = None
        else:
            doc, labels = result
            custom_types = None
            class_d = None
        for p in doc.paragraphs:
            for run in p.runs:
                run.font.size = run.font.size or Pt(11)
        out_dir = OUT_GLINER if name in _GLINER_ONLY else OUT
        save_deterministic(doc, out_dir / f"{name}.docx")
        payload: dict[str, object] = {"entities": labels}
        if custom_types is not None:
            payload["custom_types"] = custom_types
        if class_d is not None:
            payload["class_d"] = class_d
        (out_dir / f"{name}.labels.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{name}.docx — сущностей в разметке: {len(labels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
