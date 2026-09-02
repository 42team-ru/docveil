"""JSON-совместимое состояние части графа profile/judge."""

from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    path: str
    fmt: str
    segments: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    profiles: list[dict[str, Any]]
    unassigned: list[str]
    candidates: list[dict[str, Any]]
    #: Число обращений к LLM во время профилирования — не восстанавливается
    #: из ``profiles``/``candidates``, поэтому хранится отдельно.
    llm_calls: int
    verdicts: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    answers: dict[str, str]
    diagnostics: list[str]
    #: Метаданные документа (имя файла, формат) — только JSON-скаляры, без
    #: датаклассов, чтобы состояние оставалось совместимым с чекпойнтером.
    meta: dict[str, Any]
    #: Опции прогона (типы, rules_only, profile, unmask_critical, ...), из
    #: которых считается детерминированный ``thread_id`` — раздел 5 плана T1.5.1.
    options: dict[str, Any]
    #: Вопросы политики (по типам и профилям) — раздел 5 плана T1.5.1.
    policy_questions: list[dict[str, Any]]
    #: Сводка решений для отчёта: режим, счётчики, диагностика.
    decisions: dict[str, Any]
    #: Итоговое действие на каждую ``ref`` после разрешения конфликтов,
    #: включая проигравшие решения (``overridden``) — раздел 4 плана T1.5.1.
    final_actions: list[dict[str, Any]]
    #: Покрытие документа (docx- или pdf-вариант) — раздел 4 плана T1.10.
    coverage: dict[str, Any]
    #: Покрытие запрошенных типов активными детекторами — раздел 4 плана T1.10.
    detection_coverage: dict[str, list[str]]
    #: Сериализованный ``MaskPlan`` (``graph.serde.plan_to_dict``) — раздел 4 плана T1.10.
    plan: dict[str, Any]
    #: Артефакты рендера: ``{"role", "name", "path", "redacting"}`` в фиксированном
    #: порядке ролей (``preview``, ``masked_highlight``, ``masked_black``) — раздел 4
    #: плана T1.10. ``path`` — абсолютный, в ``report`` не попадает.
    artifacts: list[dict[str, Any]]
    #: Итог ``ValidateAgent`` над редактирующими артефактами — раздел 5 плана T1.10.
    validation: dict[str, Any]
    #: Утечки (``dataclasses.asdict(Leak)``) — данные, не исключение, раздел 5 плана T1.10.
    leaked: list[dict[str, Any]]
    #: Спуски по лестнице отступления маркера PDF (план T2.2.1, пачка 5):
    #: узкое поле не вместило полный маркер, показана короткая метка типа
    #: или прямоугольник вовсе без текста — не падение, факт для отчёта.
    render_degradations: list[dict[str, Any]]
    #: Итоговая структура report.json, собранная узлом ``report`` — раздел 7 плана T1.10.
    #: Без абсолютных путей: ``artifacts[].path`` сюда не попадает.
    report: dict[str, Any]
