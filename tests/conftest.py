import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.core.db import get_db

@pytest.fixture
def client():
    async def mock_get_db():
        yield None

    app.dependency_overrides[get_db] = mock_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
