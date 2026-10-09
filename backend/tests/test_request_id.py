"""request_id 미들웨어 (SDD 1절 main.py). DB·키 없이 돈다.

응답 헤더 X-Request-ID 와 Langfuse trace id 가 같은 값이어야 request_logs(trace id 를 쓴다)와 이어진다.
"""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.observability import langfuse

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_응답마다_X_Request_ID_를_붙인다():
    # lifespan(DB 풀)을 돌리지 않으려고 with 없이 쓴다
    client = TestClient(app)
    first = client.get("/health").headers.get("x-request-id")
    second = client.get("/health").headers.get("x-request-id")
    assert first and HEX32.match(first)
    assert second and first != second


def test_트레이스_id_는_요청_id_를_따른다(monkeypatch):
    monkeypatch.setattr(langfuse, "_get_client", lambda: None)  # 키 없이
    token = langfuse.request_id.set("ab" * 16)
    try:
        with langfuse.trace("agent") as tr:
            assert tr.id == "ab" * 16
    finally:
        langfuse.request_id.reset(token)


def test_요청_밖에서는_트레이스_id_를_새로_만든다(monkeypatch):
    # 평가 스크립트처럼 HTTP 요청 없이 파이프라인을 부를 때
    monkeypatch.setattr(langfuse, "_get_client", lambda: None)
    with langfuse.trace("agent") as tr:
        assert HEX32.match(tr.id)
