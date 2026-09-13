import os

import pytest
from fastapi.testclient import TestClient

from api.core.db import get_db
from api.main import app

# Тесты не должны требовать рабочие PostgreSQL и MinIO: реальные зависимости
# заменяются fixture-ами/моками до первого обращения к ним.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-32-bytes!!!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
os.environ.setdefault("MINIO_SECRET_KEY", "test-secret-key")


#: Нейтральный профиль LLM для веб-тестов. Без него `get_provider()` читает
#: `backend/masker.yaml` РАЗРАБОТЧИКА: стоит переключить его на `gigachat`
#: для живого прогона, и `/api/custom_types/compile` падает в тестах с
#: «не задана переменная окружения GIGACHAT_CREDENTIALS» — на коде, который
#: к этому отношения не имеет. Проверено 14.09.2026.
_NEUTRAL_CONFIG = """\
llm:
  profile: fake
  profiles:
    fake:
      provider: fake
"""


@pytest.fixture(autouse=True)
def neutral_project_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Изолировать веб-тесты от локального `masker.yaml` проекта."""
    config = tmp_path_factory.mktemp("api-config") / "masker.yaml"
    config.write_text(_NEUTRAL_CONFIG, encoding="utf-8")
    monkeypatch.setenv("MASKER_CONFIG", str(config))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    async def mock_get_db():
        yield None

    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)
    app.dependency_overrides[get_db] = mock_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
