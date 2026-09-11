"""ValidateAgent — независимая проверка обезличенных артефактов на утечки (T1.8, шаг 9).

Три прохода в порядке `raw` → `metadata` → `detector`. `raw`/`metadata`
ищут значения плана в частях контейнера; для PDF со входным файлом `raw`
сверяет количество конкретных вхождений на странице, чтобы публичная
одноимённая дата на другой странице не выглядела утечкой. `metadata`
проверяется целиком. Проходы независимы: рендер, который пропустил одну
замену, обязан попасть и в `raw` (строка ещё лежит на её странице), и в
`detector` (повторная детекция найдёт её снова) — то есть в `leaked` двумя
разными механизмами.

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

import re
from collections.abc import Sequence
from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.ingest.xlsx_ingest import ingest_xlsx
from masker.mask.keys import group_key
from masker.model import ArtifactLayout, Document, Leak, MaskPlan, Replacement, ValidationReport
from masker.refs import entity_sort_key
from masker.validate.certificate import build_certificate
from masker.validate.parts import DocPart, docx_parts, pdf_parts, xlsx_parts
from masker.validate.pdf_layout import artifact_layout


def _collapse(value: str) -> str:
    """Схлопнуть пробелы — вариант сравнения текста, а не байтов.

    Рендер иногда меняет вид пробельных символов вокруг вставленного
    маркера (NBSP, лишний перенос строки); само значение при этом никуда
    не делось и по смыслу утекло, даже если побитово строки чуть разошлись.
    """
    return " ".join(value.split())


class _ValueMatcher:
    """Мультипаттерный поиск: regex на C плюс бор только в точках совпадений.

    11.09.2026: на 457 заменах и 72 частях старый цикл делал до 32 904
    отдельных поисков. Полный обход бором на Python оказался медленнее
    встроенного поиска на PDF, поэтому regex проходит часть на C, а бор
    сохраняет перекрытия только в позициях, где regex уже нашёл кандидат.
    """

    def __init__(self, values: frozenset[str]) -> None:
        self._next: list[dict[str, int]] = [{}]
        self._fail: list[int] = [0]
        self._output: list[set[str]] = [set()]
        self._max_length = max((len(value) for value in values), default=0)
        escaped_values = "|".join(
            re.escape(value) for value in sorted(values, key=len, reverse=True)
        )
        self._candidate = re.compile("(?=" + escaped_values + ")") if values else None
        for value in values:
            if not value:
                continue
            node = 0
            for char in value:
                target = self._next[node].get(char)
                if target is None:
                    target = len(self._next)
                    self._next[node][char] = target
                    self._next.append({})
                    self._fail.append(0)
                    self._output.append(set())
                node = target
            self._output[node].add(value)

        queue = list(self._next[0].values())
        for node in queue:
            self._fail[node] = 0
        for node in queue:
            for char, target in self._next[node].items():
                failure = self._fail[node]
                while failure and char not in self._next[failure]:
                    failure = self._fail[failure]
                self._fail[target] = self._next[failure].get(char, 0)
                self._output[target].update(self._output[self._fail[target]])
                queue.append(target)

    def find(self, text: str) -> set[str]:
        """Вернуть все значения, встретившиеся в тексте, без потери перекрытий."""
        found: set[str] = set()
        if self._candidate is None:
            return found
        for candidate in self._candidate.finditer(text):
            node = 0
            for char in text[candidate.start() : candidate.start() + self._max_length]:
                target = self._next[node].get(char)
                if target is None:
                    break
                node = target
                found.update(self._output[node])
        return found


def _artifact_parts(path: Path) -> tuple[str, list[DocPart]]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "docx", docx_parts(path)
    if suffix == ".pdf":
        return "pdf", pdf_parts(path)
    if suffix == ".xlsx":
        return "xlsx", xlsx_parts(path)
    raise ValueError(f"Validate не умеет читать формат {path.suffix!r}: {path}")


def _ingest(path: Path, fmt: str) -> Document:
    if fmt == "docx":
        return ingest_docx(path)
    if fmt == "pdf":
        return ingest_pdf(path)
    return ingest_xlsx(path)


def _is_metadata_part(fmt: str, name: str) -> bool:
    """Метаданные DOCX/XLSX или объединённая часть PDF ``metadata``."""
    return name.startswith("docProps/") if fmt in ("docx", "xlsx") else name == "metadata"


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
        # И машинный `marker` (контракт eval.py/report), и человекочитаемый
        # `canonical_label` (план М4) — в PDF реально печатается второй (плюс,
        # на тесных местах, более короткая ступень его лестницы отступления,
        # план М1/М4), но `_inside_any_marker`/`_strip_markers` должны узнавать
        # обе формы — иначе смена формулировки маркера ложно всплыла бы как
        # утечка (`_search_detector`) или как шум вёрстки (`layout_diff`).
        markers = tuple(group.marker for group in plan.groups) + tuple(
            group.canonical_label for group in plan.groups if group.canonical_label
        )
        source_is_pdf = source is not None and source.suffix.lower() == ".pdf"

        for artifact in artifacts:
            fmt, parts = _artifact_parts(artifact)
            checked_parts.extend(f"{artifact.name}:{part.name}" for part in parts)
            leaked.extend(self._search_values(artifact, fmt, parts, plan, source=source))

            document = _ingest(artifact, fmt)
            hard, soft = self._search_detector(
                artifact, document, group_id_by_key, markers, plan=plan, source=source
            )
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
        self,
        artifact: Path,
        fmt: str,
        parts: list[DocPart],
        plan: MaskPlan,
        *,
        source: Path | None,
    ) -> list[Leak]:
        if fmt == "pdf" and source is not None and source.suffix.lower() == ".pdf":
            return self._search_pdf_values_by_occurrence(artifact, parts, plan, source)

        values = frozenset(
            replacement.entity.text for replacement in plan.replacements if replacement.entity.text
        )
        matcher = _ValueMatcher(values)
        collapsed_values = {value: _collapse(value) for value in values}
        collapsed_matcher = _ValueMatcher(frozenset(collapsed_values.values()))
        found: list[Leak] = []
        for part in parts:
            kind = "metadata" if _is_metadata_part(fmt, part.name) else "raw"
            collapsed_part_text = _collapse(part.text) if part.text else ""
            # Декодирование только ускоряет предварительный отбор. Решение об
            # утечке всё ещё принимает исходный побайтовый тест ниже, поэтому
            # некорректные байты контейнера не могут дать ложный зелёный итог.
            raw_values = matcher.find(part.raw.decode("utf-8", errors="ignore"))
            text_values = matcher.find(part.text) if part.text else set()
            collapsed_found = collapsed_matcher.find(collapsed_part_text) if part.text else set()
            text_values.update(
                value
                for value, collapsed in collapsed_values.items()
                if collapsed in collapsed_found
            )
            for replacement in plan.replacements:
                value = replacement.entity.text
                if not value:
                    continue
                if value in raw_values and value.encode("utf-8") in part.raw:
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
                if value in text_values:
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

    def _search_pdf_values_by_occurrence(
        self, artifact: Path, parts: list[DocPart], plan: MaskPlan, source: Path
    ) -> list[Leak]:
        """Проверить PDF по конкретным вхождениям, а не по литералу во всём файле.

        11.09.2026: Р26 исключает даты принятия нормативных актов. Если тот
        же литерал есть и в маскируемой дате на другой странице, глобальный
        ``value in PDF`` объявлял публичную ссылку утечкой. Для страниц
        сравниваем число вхождений до/после и ожидаем ровно число замен,
        запланированных на этой странице; metadata по-прежнему проверяется
        побайтово во всём объёме.
        """
        source_by_part = {part.name: part for part in pdf_parts(source)}
        found: list[Leak] = []
        for part in parts:
            kind = "metadata" if _is_metadata_part("pdf", part.name) else "raw"
            if kind == "metadata":
                # Метаданные не имеют координат страницы: там любое значение
                # из плана остаётся утечкой независимо от публичных омонимов.
                for replacement in plan.replacements:
                    value = replacement.entity.text
                    if value and (value.encode("utf-8") in part.raw or value in part.text):
                        found.append(
                            Leak(
                                kind=kind,
                                artifact=artifact.name,
                                part=part.name,
                                entity_type=replacement.entity.type,
                                value=value,
                                ref=replacement.ref,
                                group_id=replacement.group_id,
                                detail="исходная строка найдена в метаданных",
                            )
                        )
                continue

            source_part = source_by_part.get(part.name)
            if source_part is None:
                continue
            page_replacements = [
                replacement
                for replacement in plan.replacements
                if replacement.anchor.fmt == "pdf"
                and int(replacement.anchor.locator[1]) + 1 == int(part.name.removeprefix("page "))
            ]
            by_value: dict[str, list[Replacement]] = {}
            for replacement in page_replacements:
                by_value.setdefault(replacement.entity.text, []).append(replacement)
            for value, replacements in by_value.items():
                if not value:
                    continue
                expected_remaining = max(0, source_part.text.count(value) - len(replacements))
                actual_remaining = part.text.count(value)
                extra = actual_remaining - expected_remaining
                for replacement in replacements[: max(0, extra)]:
                    found.append(
                        Leak(
                            kind=kind,
                            artifact=artifact.name,
                            part=part.name,
                            entity_type=replacement.entity.type,
                            value=value,
                            ref=replacement.ref,
                            group_id=replacement.group_id,
                            detail="запланированное вхождение осталось на странице PDF",
                        )
                    )
        return found

    def _search_detector(
        self,
        artifact: Path,
        document: Document,
        group_id_by_key: dict[str, str],
        markers: tuple[str, ...],
        *,
        plan: MaskPlan,
        source: Path | None,
    ) -> tuple[list[Leak], list[Leak]]:
        entities = self._detector.detect(document).entities
        ordered = sorted(entities, key=entity_sort_key)

        source_pages = (
            {part.name: part.text for part in pdf_parts(source)}
            if source is not None and source.suffix.lower() == ".pdf"
            else {}
        )
        artifact_pages = (
            {part.name: part.text for part in pdf_parts(artifact)} if source_pages else {}
        )
        planned_pdf_counts: dict[tuple[str, str], int] = {}
        for replacement in plan.replacements:
            locator = replacement.anchor.locator
            if replacement.anchor.fmt != "pdf" or not locator or locator[0] != "page":
                continue
            key = (f"page {int(locator[1]) + 1}", replacement.entity.text)
            planned_pdf_counts[key] = planned_pdf_counts.get(key, 0) + 1

        hard: list[Leak] = []
        soft: list[Leak] = []
        for entity in ordered:
            segment = document.segments[entity.segment_order]
            if _inside_any_marker(segment.text, entity.start, entity.end, markers):
                continue
            matched_group_id = group_id_by_key.get(group_key(entity))
            if matched_group_id is not None:
                # 11.09.2026: повторная детекция не должна превращать
                # публичное одноимённое вхождение на другой странице в
                # «утечку». Текстовый проход выше уже доказывает удаление
                # каждого запланированного экземпляра на его странице.
                locator = segment.anchor.locator
                part_name = (
                    f"page {int(locator[1]) + 1}"
                    if segment.anchor.fmt == "pdf" and locator and locator[0] == "page"
                    else ""
                )
                planned_count = planned_pdf_counts.get((part_name, entity.text), 0)
                if part_name:
                    source_count = source_pages.get(part_name, "").count(entity.text)
                    artifact_count = artifact_pages.get(part_name, "").count(entity.text)
                    if artifact_count <= max(0, source_count - planned_count):
                        soft.append(
                            Leak(
                                kind="detector",
                                artifact=artifact.name,
                                part=segment.anchor.label or str(entity.segment_order),
                                entity_type=entity.type,
                                value=entity.text,
                                detail="одноимённое незапланированное вхождение PDF",
                            )
                        )
                        continue
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
