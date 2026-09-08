"""Единая точка входа в графовый конвейер для вызывающих вне CLI.

Два потребителя, две точки входа:

- ``mask_document`` — голый ``MaskPlan`` без рендера (``styles=()``,
  ``preview=False``): годится, когда нужны только найденные сущности и
  решения политики, а не файлы на диске (метрики P/R/F1 по типам).
- ``mask_and_validate`` — оба редактирующих рендера (``marker``,
  ``blackbox``) плюс ``ValidateAgent`` поверх них, артефакты остаются на
  диске до выхода из ``with``-блока (T2.2.1, шаг 3): раньше рендер и
  validation были доступны только внутри графа, а любой внешний
  потребитель (``masker.eval``) не мог отличить «план построен верно» от
  «план построен верно, но рендер утёк» — отсюда Д7: PDF физически не
  участвовал в метриках, и утечки, которые ``ValidateAgent`` уже находил,
  никем не читались.

Прогон всегда неинтерактивный (``interactive=False``): задача — план (и,
во втором случае, проверенные артефакты) на выходе, а не диалог с
человеком, поэтому ``needs_human`` не запускает паузу (раздел 6 плана
T1.5.1) и вызов детерминированно завершается за один ``invoke``.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from masker.graph.nodes import RunDeps
from masker.graph.serde import plan_from_dict
from masker.model import EntityType, MaskPlan, ValidationReport
from masker.run import RunOptions, start_run
from masker.validate import ValidateAgent


def _types_tuple(types: Iterable[EntityType]) -> tuple[str, ...] | None:
    requested = frozenset(types)
    if requested == frozenset(EntityType):
        return None
    return tuple(sorted(entity_type.value for entity_type in requested))


def mask_document(path: str | Path, *, types: Iterable[EntityType]) -> MaskPlan:
    """Построить план масок для одного документа через граф целиком.

    Чекпойнтер — ``InMemorySaver``: разовый вызов метрик не обязан
    переживать перезапуск процесса, поэтому нет смысла писать sqlite на
    диск ради него. Каталог артефактов — временный: ``render_node``
    (T1.10, шаг 5) требует ``artifact_dir`` не-``None`` безусловно, но
    ``preview=False`` и пустой ``styles`` не дают ему ничего туда написать.
    """
    options = RunOptions(types=_types_tuple(types), interactive=False, preview=False)

    with tempfile.TemporaryDirectory(prefix="masker-pipeline-") as scratch:
        deps = RunDeps(artifact_dir=Path(scratch))
        outcome = start_run(
            path,
            options,
            checkpointer_factory=lambda: InMemorySaver(),
            deps=deps,
        )

    if outcome.status != "done":
        # needs_human обязан пропустить паузу при interactive=False (раздел 6
        # плана T1.5.1) — раз это не так, это дефект графа, а не документа.
        raise RuntimeError(
            f"неинтерактивный прогон {path} неожиданно приостановился "
            f"(thread_id={outcome.thread_id!r})"
        )
    return plan_from_dict(outcome.state["plan"])


@dataclass(frozen=True, slots=True)
class MaskResult:
    """Результат прогона с обоими редактирующими рендерами и их проверкой.

    ``artifacts`` — пути только редактирующих файлов (``masked_black.*``,
    ``masked_highlight.*``), не ``preview.*`` (тот не редактируется и не
    должен проверяться на утечку — см. ``validate_node``). Пути валидны,
    пока не закрыт ``with``-блок ``mask_and_validate``: каталог, в котором
    они лежат, временный и удаляется при выходе.

    ``render_degradations`` — то же, что и в ``report.json`` (``render_node``,
    ``graph/nodes.py``): один элемент на каждую замену PDF-стиля ``marker``,
    для которой лестница отступления реально спустилась со ступени (пустой
    ``fallback_reason`` — канонический маркер без сокращений — сюда не
    попадает). Нужен ``masker.eval.inconsistent_marker_count`` (план М4) —
    точная проверка «какой текст реально показан для этой замены», а не
    догадка по вхождению подстроки в текст артефакта.
    """

    plan: MaskPlan
    validation: ValidationReport
    artifacts: tuple[Path, ...]
    render_degradations: tuple[dict[str, Any], ...] = ()


@contextmanager
def mask_and_validate(
    path: str | Path,
    *,
    types: Iterable[EntityType],
    custom_types: Iterable[Mapping[str, Any]] = (),
) -> Iterator[MaskResult]:
    """Построить план, отрендерить оба редактирующих артефакта и проверить их.

    В отличие от ``mask_document``, каталог артефактов не выбрасывается
    сразу после ``invoke`` — он живёт до конца ``with``-блока, чтобы
    вызывающий (``masker.eval``, метрики ``leaked_total``/
    ``duplicate_markers``, T2.2.1 шаг 3) мог прочитать содержимое файлов,
    а не только пересчитанные вручную числа.

    ``custom_types`` — уже скомпилированные JSON-спеки пользовательских
    типов (T1.13, шаг 6), тот же формат, что и в ``RunOptions.custom_types``:
    сырые словари, а не ``CustomTypeSpec``. Пустой по умолчанию — обычный
    прогон без пользовательских типов не меняет поведение.
    """
    options = RunOptions(
        types=_types_tuple(types),
        interactive=False,
        preview=False,
        styles=("marker", "blackbox"),
        custom_types=tuple(dict(item) for item in custom_types),
    )

    with tempfile.TemporaryDirectory(prefix="masker-pipeline-") as scratch:
        deps = RunDeps(artifact_dir=Path(scratch))
        outcome = start_run(
            path,
            options,
            checkpointer_factory=lambda: InMemorySaver(),
            deps=deps,
        )

        if outcome.status != "done":
            raise RuntimeError(
                f"неинтерактивный прогон {path} неожиданно приостановился "
                f"(thread_id={outcome.thread_id!r})"
            )

        plan = plan_from_dict(outcome.state["plan"])
        artifacts = tuple(
            Path(str(item["path"]))
            for item in outcome.state.get("artifacts", [])
            if item.get("redacting")
        )
        validation = ValidateAgent().validate(plan, artifacts, source=Path(path))
        render_degradations = tuple(outcome.state.get("render_degradations", []))
        yield MaskResult(
            plan=plan,
            validation=validation,
            artifacts=artifacts,
            render_degradations=render_degradations,
        )
