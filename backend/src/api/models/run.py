"""ORM-модель прогона маскирования (хранение в Postgres).

Здесь лежат только метаданные прогона: кто запустил, по какому файлу, в каком
состоянии, где артефакты. Само состояние графа живёт в чекпойнтере LangGraph
под `thread_id` — дублировать его в эту таблицу нельзя, иначе появится второй
источник правды о прогоне.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from api.core.db import Base

#: На Postgres — родные `UUID`/`JSONB` (как в миграции `0003_create_runs`), на
#: прочих диалектах — переносимые аналоги: тесты роутов гоняют те же ORM-модели
#: на sqlite, и дублировать ради этого схему таблицы незачем.
_UUID = sa.Uuid(as_uuid=True)
_JSON = sa.JSON().with_variant(JSONB(), "postgresql")
_TIMESTAMP = sa.DateTime(timezone=True).with_variant(TIMESTAMP(timezone=True), "postgresql")


class RunORM(Base):
    """Строка таблицы `runs` — один прогон одного документа."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False, index=True)
    #: Идентификатор треда графа. Не уникален: один и тот же документ с теми же
    #: опциями даёт тот же `thread_id` (`masker.run.thread_id_for`), а прогонов
    #: по нему может быть заведено несколько — каждый со своим `fresh`.
    thread_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_name: Mapped[str] = mapped_column(String, nullable=False)
    document_name: Mapped[str] = mapped_column(String, nullable=False)
    document_format: Mapped[str] = mapped_column(String, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: Узел графа, уронивший прогон (`RunFailedError.node_hint`), и текст ошибки.
    node_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Префикс артефактов в MinIO (`runs/{run_id}/`); пуст, пока рендер не прошёл.
    artifact_prefix: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Номер последнего целиком опубликованного комплекта артефактов.
    artifact_revision: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(_TIMESTAMP, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(_TIMESTAMP, nullable=True)
