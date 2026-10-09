"""FastAPI 진입점. 라우터 등록, DB 연결 수명 관리. (SDD 1절)

LLM 호출은 여기가 아니라 services/llm.py 에, DB 접근은 services/store.py 에 모은다.
3차 프로젝트에서 그 자리에 RAG 그래프가 들어온다. 호출부가 흩어져 있으면 그때 전부 뜯어야 한다.
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.observability import langfuse
from backend.app.routers import agent, internal, session
from backend.app.services import store
from mcp_server.server import mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱이 켜질 때 DB 풀을 열고, 꺼질 때 닫는다.

    켤 때 미리 여는 이유: 첫 요청에서 여는 것보다 "DATABASE_URL이 틀렸다"를 기동 시점에 바로 알 수 있다.
    compose는 db가 healthy가 된 뒤에 api를 띄우므로 (docker-compose.yml depends_on) 여기서 붙을 수 있다.
    """
    await store.get_pool()
    # MCP: 마운트된 하위 앱의 lifespan은 자동으로 안 돌므로 여기서 세션 매니저를 직접 연다 (SDK 문서 run/asgi).
    async with mcp.session_manager.run():
        yield
    await store.close_pool()


app = FastAPI(title="Converge API", lifespan=lifespan)


class RequestIdMiddleware:
    """요청마다 uuid 를 만들어 X-Request-ID 응답 헤더로 낸다 (SDD 1절).

    같은 값이 Langfuse trace id 가 되고, 파이프라인은 그 id 로 request_logs 를 남긴다.
    사용자가 "이 요청이 이상했다" 고 헤더 값을 주면 트레이스와 로그를 바로 찾는다.
    BaseHTTPMiddleware 를 쓰지 않는 이유: /mcp 의 스트리밍 응답을 감싸 버퍼링할 수 있어서 ASGI 로 직접 짠다.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex
        token = langfuse.request_id.set(rid)

        async def send_with_id(message: dict) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", rid.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            langfuse.request_id.reset(token)


# CORS: 브라우저는 다른 주소(프론트 :3000)에서 이 API(:8000)를 부를 때 서버가 "그 주소 허용"이라고
# 답해야만 응답을 넘겨준다. curl·서버 간 호출에는 없는 브라우저 전용 규칙.
# 허용 주소는 FRONTEND_ORIGIN 환경변수. 로컬은 http://localhost:3000, 배포는 Vercel 주소. 쉼표로 여러 개.
# allow_credentials=True: Authorization 헤더(로그인 토큰)를 실어 보낼 수 있게.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],  # 브라우저가 이 헤더를 읽으려면 허용 목록에 있어야 한다
)
# CORS 보다 나중에 붙여 바깥에 둔다. CORS 가 막은 응답에도 id 가 붙는다
app.add_middleware(RequestIdMiddleware)

app.include_router(agent.router)
app.include_router(session.router)
app.include_router(session.list_router)
app.include_router(internal.router)

# MCP 서버. FastAPI 라우트를 다 등록한 뒤, 마지막에 루트 마운트로 붙인다.
# 왜 루트 마운트인가: "/mcp" 에 마운트 + path "/" 로 하면 실제 문은 /mcp/ 가 되고 /mcp 는 307 리다이렉트 (09-18 실측).
# 왜 마지막인가: Starlette는 등록 순서대로 경로를 찾는다. 루트 마운트가 먼저 있으면 /health 까지 삼켜 404가 난다 (09-18 실측).
# 그래서 /health 와 라우터를 전부 등록한 다음 이 줄이 와야 한다. 새 라우트는 이 줄 위에 추가할 것.
# 토큰 검사는 mcp_server/server.py 의 StaticTokenVerifier. /api/* 와는 별개 인증 (SDD: "/api/agent 와 /mcp 를 섞지 않는다").


@app.get("/health")
def health() -> dict:
    """채점자와 배포 환경이 서비스 상태를 확인하는 곳. 로그인 없음 (결정 4). 지우지 않는다 (BACKEND_GUIDE)."""
    return {"status": "ok"}


app.mount("", mcp.streamable_http_app(streamable_http_path="/mcp"))  # 반드시 맨 마지막 (위 주석)
