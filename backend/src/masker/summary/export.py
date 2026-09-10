"""Безопасный экспорт карточки: все строки проходят через ``MaskPlan``."""

from __future__ import annotations

from typing import Any, cast

from masker.model import MaskPlan
from masker.summary.model import ContractSummary


class SummaryLeakError(RuntimeError):
    """Карточка уносит исходное значение мимо маскировки документа."""


def export_summary(summary: ContractSummary, plan: MaskPlan) -> dict[str, Any]:
    """Вернуть JSON-карточку, не содержащую ни одной активной исходной маски.

    Замены берутся из единственного источника политики — ``MaskPlan``. Это
    включает и ручные маски: они становятся ``Replacement`` точно так же,
    как автоматические находки. Более длинные строки заменяются первыми,
    чтобы короткая маска не разрезала значение другой маски.
    """
    replacements = sorted(
        (
            (replacement.entity.text, replacement.marker)
            for replacement in plan.replacements
            if replacement.entity.text
        ),
        key=lambda item: (-len(item[0]), item[0], item[1]),
    )
    raw = summary.model_dump(mode="json")
    # Проверяем исходную карточку точным байтовым поиском, как ValidateAgent
    # делает для частей артефакта, а затем применяем тот же MaskPlan. Это
    # важно именно для ответа модели: он создаётся из оригинала и иначе
    # обходит рендер.
    contains_leak = _contains_byte_leak(raw, replacements)
    exported = _mask_value(raw, replacements)
    # Вторая маскировка — защитная: если два значения пересекаются или
    # пришёл нестандартный вложенный объект, в пакет не уедет точная строка.
    if contains_leak or _contains_byte_leak(exported, replacements):
        exported = _mask_value(exported, replacements)
    if _contains_byte_leak(exported, replacements):
        # Сюда попасть нельзя: `_mask_value` заменяет ВСЕ вхождения точной
        # строки, и одного прохода достаточно. Но если исходное значение всё
        # же уцелело, оно уедет в `report.json` мимо всех проверок артефакта —
        # это утечка, а не косметика (AGENTS.md, «Утечки нет»). Молчать здесь
        # хуже, чем упасть: упавший прогон видно, утёкший ИНН — нет.
        raise SummaryLeakError(
            "карточка сохранила исходное значение замаскированной сущности "
            "после применения плана масок"
        )
    return cast(dict[str, Any], exported)


def _contains_byte_leak(value: Any, replacements: list[tuple[str, str]]) -> bool:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return any(original.encode("utf-8") in encoded for original, _ in replacements)
    if isinstance(value, list):
        return any(_contains_byte_leak(item, replacements) for item in value)
    if isinstance(value, dict):
        return any(_contains_byte_leak(item, replacements) for item in value.values())
    return False


def _mask_value(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for original, marker in replacements:
            value = value.replace(original, marker)
        return value
    if isinstance(value, list):
        return [_mask_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _mask_value(item, replacements) for key, item in value.items()}
    return value
