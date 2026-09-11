# Проверка DOCX через CLI

Один документ:

```bash
.venv/bin/python -m masker.cli contract.docx
```

Несколько документов и свой каталог результата:

```bash
.venv/bin/python -m masker.cli documents/*.docx --out out/check
```

Только выбранные типы или только слой правил:

```bash
.venv/bin/python -m masker.cli contract.docx --types inn,person,org_name
.venv/bin/python -m masker.cli contract.docx --rules-only
```

Для каждого входного файла создаётся каталог `<out>/<имя файла>/`:

- `report.json` — сводка, покрытие документа, сущности и контекстные чанки;
- `preview.docx` — копия документа с точной жёлтой подсветкой находок.

В `report.json` особенно полезны:

- `summary` — количество находок по типам и источникам;
- `chunks` — контекст, размеченный `annotated_text` и список `pii` внутри чанка;
- `detection_coverage` — запрошенные типы, для которых ещё нет детектора;
- `document_coverage` — необработанные таблицы, колонтитулы, сноски и метаданные.

`preview.docx` не является обезличенным документом: исходный текст в нём
сохранён. JSON также содержит исходные PII и контекстные фрагменты. Оба файла
создаются с правами `0600`. До реализации T1.11 CLI также не видит таблицы,
колонтитулы и сноски.
