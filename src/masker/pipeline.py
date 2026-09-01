"""Единая точка входа в графовый конвейер для вызывающих вне CLI.

Сегодня один потребитель — ``masker.eval``: метрики по размеченному
корпусу считаются по тому же графу, что и CLI, а не по отдельно собранной
цепочке вызовов агентов (иначе метрики мерили бы не то, что реально видит
пользователь). Прогон всегда неинтерактивный (``interactive=False``):
задача — план на выходе, а не диалог с человеком, поэтому ``needs_human``
не запускает паузу (раздел 6 плана T1.5.1) и вызов детерминированно
завершается за один ``invoke``.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from masker.graph.nodes import RunDeps
from masker.graph.serde import plan_from_dict
from masker.model import EntityType, MaskPlan
from masker.run import RunOptions, start_run


def mask_document(path: str | Path, *, types: Iterable[EntityType]) -> MaskPlan:
    """Построить план масок для одного документа через граф целиком.

    Чекпойнтер — ``InMemorySaver``: разовый вызов метрик не обязан
    переживать перезапуск процесса, поэтому нет смысла писать sqlite на
    диск ради него. Каталог артефактов — временный: ``render_node``
    (T1.10, шаг 5) требует ``artifact_dir`` не-``None`` безусловно, но
    ``preview=False`` и пустой ``styles`` не дают ему ничего туда написать.
    """
    requested = frozenset(types)
    types_tuple = (
        None
        if requested == frozenset(EntityType)
        else tuple(sorted(entity_type.value for entity_type in requested))
    )
    options = RunOptions(types=types_tuple, interactive=False, preview=False)

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
