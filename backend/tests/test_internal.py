"""POST /internal/cleanup 인증 (SDD 2절). DB 없이 돈다 (TEST_GUIDE)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import internal
from backend.app.services import store


@pytest.fixture
def client(monkeypatch):
    async def cleanup_expired():
        return {"sessions": 2, "route_cache": 0, "request_logs": 0, "feedback": 0}

    monkeypatch.setattr(store, "cleanup_expired", cleanup_expired)
    app = FastAPI()
    app.include_router(internal.router)
    return TestClient(app)


def test_토큰이_맞으면_지우고_건수를_돌려준다(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_TOKEN", "s3cret")
    res = client.post("/internal/cleanup", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200
    assert res.json()["sessions"] == 2


def test_토큰이_틀리면_401(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_TOKEN", "s3cret")
    assert client.post("/internal/cleanup", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/internal/cleanup").status_code == 401


def test_토큰이_설정되지_않았으면_아무도_못_부른다(client, monkeypatch):
    monkeypatch.delenv("INTERNAL_TOKEN", raising=False)
    assert client.post("/internal/cleanup", headers={"Authorization": "Bearer "}).status_code == 503
