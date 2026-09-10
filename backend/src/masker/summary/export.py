"""Безопасный экспорт карточки: все строки проходят через ``MaskPlan``."""

from __future__ import annotations

from typing import Any, cast

from masker.model import MaskPlan
from masker.summary.model import ContractSummary


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
        key=lambda item: len(item[0]),
        reverse=True,
    )
    return cast(dict[str, Any], _mask_value(summary.model_dump(mode="json"), replacements))


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
