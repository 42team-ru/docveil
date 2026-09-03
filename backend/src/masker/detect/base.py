"""Расширяемые контракты слоя детекции."""

from __future__ import annotations

from typing import Protocol

from masker.model import Document, Entity, Source


class EntityDetector(Protocol):
    """Подключаемый детектор PII без логики чанков и разрешения конфликтов."""

    name: str
    source: Source
    priority: int
    types: frozenset[str]  # id из EntityTypeRegistry (встроенные — EntityType.value)

    def detect(self, document: Document) -> list[Entity]:
        """Вернуть сущности с локальными смещениями в сегментах документа."""
