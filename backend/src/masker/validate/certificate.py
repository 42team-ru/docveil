"""Сертификат обезличивания — независимые проверки итогового файла (план М3).

Сертификат — не диагностика, а порог: провал любого пункта роняет ворота
(``masker.eval``), так же безусловно, как ``leaked_total`` или
``layout_removed_chars``. Смысл — не «мы обезличили», а «вот доказательство,
и его можно перепроверить», поэтому каждый пункт даёт человекочитаемый
``detail`` независимо от исхода.

1. ``leak_scan`` — переиспользует уже посчитанный ``ValidateAgent`` побайтовый
   и текстовый поиск (``leaked``): отдельной реализации не заводим, три слоя
   (raw/metadata/detector) уже покрывают текст, XML docx/xlsx, текстовый слой
   PDF и метаданные — см. докстринг ``validate/agent.py``.
2. ``metadata_cleared`` — не верит на слово ``set_metadata({})``/
   ``del_xml_metadata()`` (PDF) и сбросу ``core_properties`` (DOCX): открывает
   уже сохранённый артефакт заново и проверяет, что конкретные поля, которые
   рендер обещает вычистить, действительно пусты.
3. ``width_quantization`` — прямая проверка защиты из плана М1, шаг 5
   (``render/pdf_render.py::_quantize_erase_rect``): ширина каждого
   ``erase_regions`` обязана быть кратна сетке 12pt **или** объяснена
   настоящим соседним символом на странице (единственная легитимная причина
   недокрученного кванта — план М1, правило 5). Проверка независима от
   ``_quantize_erase_rect``/``_free_extension_right``: соседа ищем заново по
   ``page_chars`` источника, а не переиспользуем ту же функцию, которая
   квант посчитала — иначе проверка была бы тавтологией самой себя.
4. ``image_metadata_stripped`` — только для прогонов, начавшихся с картинки
   (план feat-image-ingest, инвариант 1). EXIF итоговой картинки обязан
   содержать только `DPI` (тег 0x011A/0x011B) и `Orientation` (0x0112);
   всё остальное (`Software`, `Artist`, GPS, ICC, thumbnail, XMP) — провал.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pymupdf
from docx import Document as open_docx
from openpyxl import load_workbook

from masker.ingest.pdf_ingest import PageChars, page_chars
from masker.model import Certificate, CertificateCheck, Leak, MaskPlan
from masker.render.pdf_render import _ERASE_WIDTH_GRID, _GEOMETRY_EPS, _LINE_BREAK_RECT
from masker.render.pdf_render import compute_erase_geometry as _compute_erase_geometry

#: Поля ``doc.metadata`` (PDF, синхронизированы с ``/Info``), которые рендер
#: обещает вычистить через ``set_metadata({})`` — см. ``render/pdf_render.py``.
#: ``format``/``encryption`` не входят: это свойства файла (версия PDF,
#: шифрование), а не пользовательские метаданные, и они не считаются
#: ``set_metadata({})`` (пусты в исходнике тоже).
_PDF_METADATA_KEYS: tuple[str, ...] = (
    "author",
    "creator",
    "producer",
    "subject",
    "keywords",
    "title",
    "creationDate",
    "modDate",
    "trapped",
)
#: Свойства ``core_properties`` docx, которые рендер обещает вычистить —
#: см. ``render/docx_redact.py``.
_DOCX_CORE_ATTRS: tuple[str, ...] = (
    "author",
    "last_modified_by",
    "title",
    "subject",
    "keywords",
    "comments",
)
# Синхронизирован с ``render/xlsx_redact.py``: это все изменяемые свойства,
# которые тот обязан очищать перед сохранением книги.
_XLSX_CORE_ATTRS: tuple[str, ...] = (
    "creator",
    "lastModifiedBy",
    "title",
    "subject",
    "keywords",
    "description",
    "category",
)
# ``openpyxl`` записывает это техническое значение, даже если ``creator``
# сброшен в ``None`` перед ``save()``. Это не метаданные исходного автора и
# не может восстановить его личность; любое другое значение — провал очистки.
_XLSX_SAFE_GENERATED_VALUES: dict[str, frozenset[str]] = {
    "creator": frozenset({"openpyxl"}),
}
#: Допуск сравнения границы кванта с реальным символом страницы (план М3,
#: пункт 3). Шире общего геометрического допуска рендера (``_GEOMETRY_EPS``,
#: 0.01pt): здесь сравниваются два независимо посчитанных числа, а не одно и
#: то же значение с самим собой.
_NEIGHBOR_TOLERANCE = _GEOMETRY_EPS * 3
#: Расширения, для которых `image_metadata_stripped` имеет смысл. Список
#: синхронизирован с `masker.ingest.image_meta.SUPPORTED_SUFFIXES` — не
#: импортируем оттуда, чтобы certificate/validate/render оставались слоем
#: над ingest'ом, а не наоборот.
_IMAGE_SUFFIXES: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})
#: EXIF-теги, которые разрешены в итоговой картинке (только они и ничего больше).
#: 0x0112 — Orientation, 0x011A/B — X/Y Resolution (DPI), 0x0128 — ResolutionUnit.
_ALLOWED_EXIF_TAGS: frozenset[int] = frozenset({0x0112, 0x011A, 0x011B, 0x0128})


def _check_leak_scan(leaked: tuple[Leak, ...], checked_parts: tuple[str, ...]) -> CertificateCheck:
    if leaked:
        sample = "; ".join(f"{leak.part}:{leak.entity_type}={leak.value!r}" for leak in leaked[:5])
        more = "" if len(leaked) <= 5 else f" и ещё {len(leaked) - 5}"
        return CertificateCheck(
            name="leak_scan",
            ok=False,
            detail=(
                f"найдено {len(leaked)} утечек в {len(checked_parts)} проверенных частях: "
                f"{sample}{more}"
            ),
        )
    return CertificateCheck(
        name="leak_scan",
        ok=True,
        detail=(
            f"побайтовый и текстовый поиск по {len(checked_parts)} частям контейнера "
            "(текст, XML, /Info, XMP) — утечек не найдено"
        ),
    )


def _metadata_findings_pdf(path: Path) -> list[str]:
    doc = pymupdf.open(str(path))
    try:
        findings = [
            f"{path.name}: metadata[{key!r}]={value!r}"
            for key, value in doc.metadata.items()
            if key in _PDF_METADATA_KEYS and value
        ]
        xmp = doc.get_xml_metadata()
        if xmp:
            findings.append(f"{path.name}: XMP-метаданные не пусты ({len(xmp)} символов)")
        return findings
    finally:
        doc.close()


def _metadata_findings_docx(path: Path) -> list[str]:
    document = open_docx(str(path))
    props = document.core_properties
    return [
        f"{path.name}: core_properties.{attr}={value!r}"
        for attr in _DOCX_CORE_ATTRS
        if (value := getattr(props, attr))
    ]


def _metadata_findings_xlsx(path: Path) -> list[str]:
    workbook = load_workbook(str(path), read_only=True)
    try:
        props = workbook.properties
        return [
            f"{path.name}: properties.{attr}={value!r}"
            for attr in _XLSX_CORE_ATTRS
            if (value := getattr(props, attr))
            and value not in _XLSX_SAFE_GENERATED_VALUES.get(attr, frozenset())
        ]
    finally:
        workbook.close()


def _check_metadata_cleared(artifacts: Sequence[Path]) -> CertificateCheck:
    findings: list[str] = []
    for artifact in artifacts:
        suffix = artifact.suffix.lower()
        if suffix == ".pdf":
            findings.extend(_metadata_findings_pdf(artifact))
        elif suffix == ".docx":
            findings.extend(_metadata_findings_docx(artifact))
        elif suffix == ".xlsx":
            findings.extend(_metadata_findings_xlsx(artifact))
        elif suffix in _IMAGE_SUFFIXES:
            # У картинок метаданные проверяет отдельный пункт
            # `image_metadata_stripped` — здесь пропускаем.
            continue
        else:
            raise ValueError(
                f"сертификат не умеет проверять метаданные формата {suffix!r}: {artifact}"
            )
    if findings:
        return CertificateCheck(
            name="metadata_cleared",
            ok=False,
            detail=f"{len(findings)} незачищенных полей: " + "; ".join(findings),
        )
    return CertificateCheck(
        name="metadata_cleared",
        ok=True,
        detail=(
            f"проверено {len(artifacts)} артефактов — /Info, XMP (PDF) и свойства DOCX/XLSX пусты"
        ),
    )


def _has_real_neighbor_at(chars: PageChars, boundary_x: float, y0: float, y1: float) -> bool:
    """Есть ли на странице настоящий символ, чья граница совпадает с
    ``boundary_x`` на той же строке (по пересечению [y0, y1]).

    Независимое чтение ``page_chars`` источника — не вызывает
    ``_free_extension_right``/``_quantize_erase_rect``, поэтому не тавтология
    той же функции, которая границу посчитала: если однажды квантование
    сломают (например, уберут ``math.ceil``), эта проверка это заметит, а не
    молча согласится с тем же самым числом.
    """
    for box in chars.boxes:
        if box == _LINE_BREAK_RECT:
            continue
        if box.y1 <= y0 or box.y0 >= y1:
            continue  # не пересекается по вертикали — не эта строка
        if abs(box.x0 - boundary_x) <= _NEIGHBOR_TOLERANCE:
            return True
        if abs(box.x1 - boundary_x) <= _NEIGHBOR_TOLERANCE:
            return True
    return False


def verify_width_quantization(
    widths: Sequence[tuple[str, str, int, float, float, float, float]],
    *,
    chars_by_page: dict[int, PageChars],
) -> CertificateCheck:
    """Проверить список готовых ширин на кратность сетке или на настоящего
    соседа (план М3, пункт 3) — независимая от источника геометрии часть
    логики, чтобы её можно было прогнать и на заведомо сфабрикованных данных
    (ключевой тест задачи), не открывая никакой PDF.

    Один элемент ``widths`` — ``(ref, entity_type, page, x0, y0, x1, y1)``.
    """
    violations: list[str] = []
    for ref, entity_type, page, x0, y0, x1, y1 in widths:
        width = x1 - x0
        remainder = width % _ERASE_WIDTH_GRID
        grid_aligned = min(remainder, _ERASE_WIDTH_GRID - remainder) <= _GEOMETRY_EPS
        if grid_aligned:
            continue
        chars = chars_by_page.get(page)
        if chars is not None and _has_real_neighbor_at(chars, x1, y0, y1):
            continue
        violations.append(
            f"{ref} ({entity_type}, стр. {page + 1}): ширина {width:.2f}pt не кратна "
            f"{_ERASE_WIDTH_GRID:.0f}pt и не объяснена соседним символом — "
            "квантование М1 (шаг 5) не применено, ширина может выдавать длину исходника"
        )
    if violations:
        return CertificateCheck(
            name="width_quantization",
            ok=False,
            detail=f"{len(violations)} из {len(widths)}: " + "; ".join(violations),
        )
    return CertificateCheck(
        name="width_quantization",
        ok=True,
        detail=(
            f"проверено {len(widths)} прямоугольников удаления — все кратны "
            f"{_ERASE_WIDTH_GRID:.0f}pt или упираются в соседний символ страницы"
        ),
    )


def _check_width_quantization(
    plan: MaskPlan, source: Path | None, artifacts: Sequence[Path]
) -> CertificateCheck:
    if source is None or source.suffix.lower() != ".pdf":
        return CertificateCheck(
            name="width_quantization", ok=True, detail="не применимо: источник не PDF"
        )
    if not any(artifact.suffix.lower() == ".pdf" for artifact in artifacts):
        return CertificateCheck(
            name="width_quantization", ok=True, detail="не применимо: нет PDF-артефактов"
        )

    geometry = _compute_erase_geometry(source, plan)
    entity_type_by_ref = {repl.ref: repl.entity.type for repl in plan.replacements}
    widths: list[tuple[str, str, int, float, float, float, float]] = []
    for ref, regions in geometry.items():
        entity_type = entity_type_by_ref.get(ref, "")
        for region in regions:
            widths.append(
                (ref, entity_type, region.page, region.x0, region.y0, region.x1, region.y1)
            )
    if not widths:
        return CertificateCheck(
            name="width_quantization", ok=True, detail="нет PDF-замен с геометрией удаления"
        )

    doc = pymupdf.open(str(source))
    try:
        pages_needed = {item[2] for item in widths}
        chars_by_page = {page_num: page_chars(doc[page_num]) for page_num in pages_needed}
    finally:
        doc.close()

    return verify_width_quantization(widths, chars_by_page=chars_by_page)


def _image_exif_findings(path: Path) -> list[str]:
    """Собрать список неразрешённых EXIF/метаданных в готовой картинке.

    Пустой список = метаданные вычищены до `DPI`/`Orientation`, любые
    другие теги (Software, Artist, GPS, ICC-Profile сцены, thumbnail) —
    провал сертификата. Функция открывает файл через Pillow — тот же
    движок, которым его писал `image_export`, что даёт максимально
    честную реконструкцию содержимого EXIF.
    """
    # Ленивый импорт: Pillow тянется в проекте всегда, но модуль
    # certificate историчeски избегал зависимостей вне PyMuPDF/docx/openpyxl.
    from PIL import Image

    findings: list[str] = []
    with Image.open(str(path)) as image:
        exif = image.getexif()
        for tag_id in exif:
            if tag_id not in _ALLOWED_EXIF_TAGS:
                # Название тега (для читаемости) — из справочника Pillow.
                # Отсутствующие в справочнике теги показываем как hex.
                # Импорт локальный: `ExifTags` — часть Pillow.
                from PIL import ExifTags

                tag_name = ExifTags.TAGS.get(tag_id, f"0x{tag_id:04X}")
                findings.append(f"{path.name}: EXIF[{tag_name}]={exif.get(tag_id)!r}")
        # ICC-профиль (PNG iCCP, JPEG APP2 ICC) — тоже метаданные сцены,
        # не имеющие отношения к DPI/ориентации.
        icc = image.info.get("icc_profile")
        if icc:
            findings.append(f"{path.name}: ICC-профиль не пуст ({len(icc)} байт)")
        # PNG-фрагменты `tEXt`/`iTXt` — свободные текстовые метаданные.
        text_meta = image.info.get("Description") or image.info.get("Comment")
        if text_meta:
            findings.append(f"{path.name}: текстовые метаданные не пусты: {text_meta!r}")
    return findings


def _check_image_metadata_stripped(artifacts: Sequence[Path]) -> CertificateCheck:
    """Проверить, что все итоговые картинки очищены до `DPI`+`Orientation`."""
    image_artifacts = [
        artifact for artifact in artifacts if artifact.suffix.lower() in _IMAGE_SUFFIXES
    ]
    if not image_artifacts:
        return CertificateCheck(
            name="image_metadata_stripped",
            ok=True,
            detail="не применимо: среди артефактов нет картинок",
        )
    findings: list[str] = []
    for artifact in image_artifacts:
        findings.extend(_image_exif_findings(artifact))
    if findings:
        return CertificateCheck(
            name="image_metadata_stripped",
            ok=False,
            detail=f"{len(findings)} посторонних полей: " + "; ".join(findings),
        )
    return CertificateCheck(
        name="image_metadata_stripped",
        ok=True,
        detail=(
            f"проверено {len(image_artifacts)} картинок — EXIF содержит только"
            " DPI/Orientation, ICC-профиль и текстовые метаданные пусты"
        ),
    )


def build_certificate(
    plan: MaskPlan,
    leaked: tuple[Leak, ...],
    checked_parts: tuple[str, ...],
    artifacts: Sequence[Path],
    *,
    source: Path | None,
) -> Certificate:
    """Собрать сертификат обезличивания из независимых пунктов (план М3 + image-ingest)."""
    checks = (
        _check_leak_scan(leaked, checked_parts),
        _check_metadata_cleared(artifacts),
        _check_width_quantization(plan, source, artifacts),
        _check_image_metadata_stripped(artifacts),
    )
    return Certificate(ok=all(check.ok for check in checks), checks=checks)
