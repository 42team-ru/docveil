"""CORS: фронт ходит в API со своего источника и с cookie.

Дев-сервер фронта (Vite, 5173) и API (8000) — разные Origin, поэтому без
разрешения браузер режет запрос ещё до отправки. Проверяется и обратное:
чужой источник разрешения не получает — иначе `allow_credentials` отдал бы
refresh-cookie кому угодно.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

DEV_ORIGIN = "http://localhost:5173"


def test_preflight_from_dev_origin_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/api/runs",
        headers={
            "Origin": DEV_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEV_ORIGIN
    # Без этого заголовка браузер не отправит httpOnly-cookie с refresh-токеном.
    assert response.headers["access-control-allow-credentials"] == "true"


def test_simple_request_carries_origin_header(client: TestClient) -> None:
    """Ответ на обычный запрос тоже помечен источником, иначе fetch его не отдаст."""
    response = client.get("/api/runs", headers={"Origin": DEV_ORIGIN})

    assert response.headers["access-control-allow-origin"] == DEV_ORIGIN
    assert "Content-Disposition" in response.headers["access-control-expose-headers"]


def test_foreign_origin_is_not_allowed(client: TestClient) -> None:
    response = client.options(
        "/api/runs",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers
