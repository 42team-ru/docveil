"""ORM-модели настроек LLM-профиля (веб-слой, хранение в Postgres)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.core.db import Base


class LLMProfileORM(Base):
    """Профиль LLM, созданный из GUI — строка таблицы `llm_profiles`.

    Встроенные профили из `masker.yaml` (`llm.profiles`) здесь не хранятся —
    только пользовательские; список для GUI сливает оба источника на уровне
    сервиса (`llm_profile_service.list_profiles`). `api_key_env` хранит ИМЯ
    переменной окружения, не сам ключ — тот же принцип, что и в YAML
    (`masker.llm.config.LLMConfig.api_key_env`).
    """

    __tablename__ = "llm_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    api_key_env: Mapped[str] = mapped_column(String, nullable=False)
    #: Реальный секрет, если админ вставил токен в GUI напрямую, а не завёл
    #: переменную окружения на сервере. `None` — поведение как раньше:
    #: значение ищется в `api_key_env` окружения процесса. Наружу (в
    #: `LLMProfileOut`) не отдаётся никогда — только флаг `has_api_key`.
    api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Провайдер-специфичные поля (`openrouter`/`gigachat` секции YAML) — как есть.
    provider_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    #: `{prompt_per_1k, completion_per_1k, currency, verified_at}` — форма `LLMPricing.as_dict()`.
    pricing: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class LLMActiveSettingORM(Base):
    """Синглтон: какой профиль сейчас активен для веб-прогонов.

    Одна строка с фиксированным `id=1`. `source` различает встроенный
    (`profiles` из YAML, `name` — ключ там) от созданного в GUI (`name` —
    `LLMProfileORM.name`). Отсутствие строки означает «не задано» — тогда
    активен профиль по умолчанию из `masker.yaml` (`llm.profile`), как и до
    появления этой настройки.
    """

    __tablename__ = "llm_active_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    source: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
