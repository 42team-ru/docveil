import os

import pytest
from fastapi.testclient import TestClient

# Тесты не должны требовать рабочие PostgreSQL и MinIO: реальные зависимости
# заменяются fixture-ами/моками до первого обращения к ним.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
os.environ.setdefault("MINIO_SECRET_KEY", "test-secret-key")

from api.core.db import get_db
from api.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    async def mock_get_db():
        yield None

    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)
    app.dependency_overrides[get_db] = mock_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
