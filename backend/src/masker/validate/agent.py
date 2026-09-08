"""ValidateAgent — независимая проверка обезличенных артефактов на утечки (T1.8, шаг 9).

Три прохода в порядке `raw` → `metadata` → `detector`. `raw`/`metadata` —
один и тот же побайтовый/текстовый поиск значений плана по всем частям
контейнера; отличается только `kind` итоговой находки, в зависимости от
того, метаданная это часть (`docProps/*`, PDF `metadata`) или нет. Проходы
независимы: рендер, который пропустил одну замену, обязан попасть и в
`raw` (строка ещё лежит в тексте), и в `detector` (повторная детекция найдёт
её снова) — то есть в `leaked` дважды, двумя разными механизмами.

Побайтового поиска недостаточно самого по себе: Word режет значение по
run'ам (`ИНН 36` + `62103003`), и в `word/document.xml` исходная строка
целиком может не встретиться, хотя человек прочитает её как одну. Поэтому
там, где `raw`-поиск ничего не находит, дополнительно ищем по
`DocPart.text` (уже склеенному тексту) — точную строку и её вариант со
схлопнутыми пробелами.

`leaked` vs `residual` — не два имени для одного и того же:
- `leaked` — план обещал убрать это значение, а оно всё ещё читается.
  Провал прогона.
- `residual` — детектор что-то нашёл на повторном проходе, но плану это
  не было обещано: решение человека «оставить» (`Action.KEEP` не попадает
  ни в одну группу плана — см. `mask/agent.py`), незапрошенный тип,
  который никогда не планировалось трогать, или вовсе новая находка
  второго прохода. Не провал, но и не молчание — отчёт должен показать,
  что реально осталось в документе.

Находка, чей текст целиком лежит внутри вхождения маркера плана в том же
сегменте, отбрасывается совсем: маркер — не утечка, даже если локальная
NER-модель ошибочно принимает `[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]` за организацию.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.mask.keys import group_key
from masker.model import ArtifactLayout, Document, Leak, MaskPlan, ValidationReport
from masker.refs import entity_sort_key
from masker.validate.certificate import build_certificate
from masker.validate.parts import DocPart, docx_parts, pdf_parts
from masker.validate.pdf_layout import artifact_layout


def _collapse(value: str) -> str:
    """Схлопнуть пробелы — вариант сравнения текста, а не байтов.

    Рендер иногда меняет вид пробельных символов вокруг вставленного
    маркера (NBSP, лишний перенос строки); само значение при этом никуда
    не делось и по смыслу утекло, даже если побитово строки чуть разошлись.
    """
    return " ".join(value.split())


def _artifact_parts(path: Path) -> tuple[str, list[DocPart]]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "docx", docx_parts(path)
    if suffix == ".pdf":
        return "pdf", pdf_parts(path)
    raise ValueError(f"Validate не умеет читать формат {path.suffix!r}: {path}")


def _ingest(path: Path, fmt: str) -> Document:
    return ingest_docx(path) if fmt == "docx" else ingest_pdf(path)


def _is_metadata_part(fmt: str, name: str) -> bool:
    """`docProps/*` (docx) или ``"metadata"`` (наша часть PDF, `/Info` + XMP)."""
    return name.startswith("docProps/") if fmt == "docx" else name == "metadata"


def _inside_any_marker(text: str, start: int, end: int, markers: tuple[str, ...]) -> bool:
    """Лежит ли `text[start:end]` целиком внутри какого-нибудь вхождения маркера."""
    for marker in markers:
        if not marker:
            continue
        search_from = 0
        while True:
            found_at = text.find(marker, search_from)
            if found_at < 0:
                break
            if found_at <= start and end <= found_at + len(marker):
                return True
            search_from = found_at + 1
    return False


def _sorted_unique(items: list[Leak]) -> tuple[Leak, ...]:
    """Убрать дубликаты и отсортировать — детерминизм отчёта Validate.

    Сортировка по `(artifact, part, kind, entity_type, ref, value)` —
    раздел «Детерминизм» плана T1.6/T1.8: множества в исходной сборке не
    должны просочиться в порядок кортежа.
    """
    seen: set[Leak] = set()
    unique: list[Leak] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    unique.sort(
        key=lambda leak: (
            leak.artifact,
            leak.part,
            leak.kind,
            leak.entity_type,
            leak.ref,
            leak.value,
        )
    )
    return tuple(unique)


class ValidateAgent:
    """Проверяет обезличенные артефакты на утечки исходных данных (T1.8)."""

    def __init__(self, detector: DetectAgent | None = None) -> None:
        # Все три слоя по всем типам: Validate не принимает requested_types,
        # иначе незапрошенный тип никогда не проверялся бы на утечку — см.
        # AGENTS.md и шаг 6 плана T1.6/T1.8.
        self._detector = detector if detector is not None else DetectAgent()

    def validate(
        self,
        plan: MaskPlan,
        artifacts: Sequence[Path],
        *,
        source: Path | None = None,
    ) -> ValidationReport:
        """Проверить перечисленные артефакты на утечки значений из `plan`.

        Классификация `leaked`/`residual` для повторной детекции целиком
        определяется совпадением ключа группы (`group_key(entity) ==
        group.key`) — сущность, которую план не собирался маскировать
        (решение «оставить», незапрошенный тип, новая находка), никогда не
        формирует группу плана и поэтому естественным образом попадает в
        `residual` без дополнительного параметра-фильтра.

        ``source`` — путь к исходному документу (план T2.2.2, шаг 4):
        нужен только для ``ArtifactLayout`` (сохранность текстового слоя
        PDF вне замен) и опционален — без него ``layout`` в отчёте пуст, а
        не падает. Считается только для артефактов и источника с
        расширением ``.pdf``: DOCX не редактируется вырезанием глифов по
        прямоугольнику, там нет геометрии, которую можно перепутать.
        """
        leaked: list[Leak] = []
        residual: list[Leak] = []
        checked_parts: list[str] = []
        layout: list[ArtifactLayout] = []

        group_id_by_key: dict[str, str] = {group.key: group.id for group in plan.groups}
        markers = tuple(group.marker for group in plan.groups)
        source_is_pdf = source is not None and source.suffix.lower() == ".pdf"

        for artifact in artifacts:
            fmt, parts = _artifact_parts(artifact)
            checked_parts.extend(f"{artifact.name}:{part.name}" for part in parts)
            leaked.extend(self._search_values(artifact, fmt, parts, plan))

            document = _ingest(artifact, fmt)
            hard, soft = self._search_detector(artifact, document, group_id_by_key, markers)
            leaked.extend(hard)
            residual.extend(soft)

            if fmt == "pdf" and source_is_pdf:
                assert source is not None  # source_is_pdf гарантирует не-None
                layout.append(artifact_layout(source, artifact, plan, markers=markers))

        leaked_sorted = _sorted_unique(leaked)
        checked_parts_sorted = tuple(sorted(set(checked_parts)))
        certificate = build_certificate(
            plan,
            leaked_sorted,
            checked_parts_sorted,
            tuple(artifacts),
            source=source,
        )
        return ValidationReport(
            leaked=leaked_sorted,
            residual=_sorted_unique(residual),
            checked_artifacts=tuple(artifact.name for artifact in artifacts),
            checked_parts=checked_parts_sorted,
            ok=not leaked,
            layout=tuple(layout),
            certificate=certificate,
        )

    def _search_values(
        self, artifact: Path, fmt: str, parts: list[DocPart], plan: MaskPlan
    ) -> list[Leak]:
        found: list[Leak] = []
        for part in parts:
            kind = "metadata" if _is_metadata_part(fmt, part.name) else "raw"
            collapsed_part_text = _collapse(part.text) if part.text else ""
            for replacement in plan.replacements:
                value = replacement.entity.text
                if not value:
                    continue
                if value.encode("utf-8") in part.raw:
                    found.append(
                        Leak(
                            kind=kind,
                            artifact=artifact.name,
                            part=part.name,
                            entity_type=replacement.entity.type,
                            value=value,
                            ref=replacement.ref,
                            group_id=replacement.group_id,
                            detail="исходная строка найдена побайтово",
                        )
                    )
                    continue
                if part.text and (value in part.text or _collapse(value) in collapsed_part_text):
                    found.append(
                        Leak(
                            kind=kind,
                            artifact=artifact.name,
                            part=part.name,
                            entity_type=replacement.entity.type,
                            value=value,
                            ref=replacement.ref,
                            group_id=replacement.group_id,
                            detail=(
                                "найдена в извлечённом тексте части, но не в "
                                "сырых байтах — значение разрезано (например, "
                                "по run'ам Word)"
                            ),
                        )
                    )
        return found

    def _search_detector(
        self,
        artifact: Path,
        document: Document,
        group_id_by_key: dict[str, str],
        markers: tuple[str, ...],
    ) -> tuple[list[Leak], list[Leak]]:
        entities = self._detector.detect(document).entities
        ordered = sorted(entities, key=entity_sort_key)

        hard: list[Leak] = []
        soft: list[Leak] = []
        for entity in ordered:
            segment = document.segments[entity.segment_order]
            if _inside_any_marker(segment.text, entity.start, entity.end, markers):
                continue
            matched_group_id = group_id_by_key.get(group_key(entity))
            if matched_group_id is not None:
                hard.append(
                    Leak(
                        kind="detector",
                        artifact=artifact.name,
                        part=segment.anchor.label or str(entity.segment_order),
                        entity_type=entity.type,
                        value=entity.text,
                        group_id=matched_group_id,
                        detail=f"совпал ключ группы плана ({matched_group_id})",
                    )
                )
            else:
                soft.append(
                    Leak(
                        kind="detector",
                        artifact=artifact.name,
                        part=segment.anchor.label or str(entity.segment_order),
                        entity_type=entity.type,
                        value=entity.text,
                        detail=(
                            "не входит в план масок: решение «оставить», "
                            "незапрошенный тип или новая находка"
                        ),
                    )
                )
        return hard, soft
