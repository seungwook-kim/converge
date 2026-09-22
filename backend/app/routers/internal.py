"""내부 배치 엔드포인트. (SDD 1절·2절, 테이블정의서 6절)

  POST /internal/cleanup   Cloud Scheduler 가 하루 1회. 만료된 세션·캐시·로그를 지운다

로그인이 아니라 INTERNAL_TOKEN 으로 막는다. 부르는 쪽이 사람이 아니라 스케줄러라서다.
토큰이 비어 있으면 아무도 못 부르게 503 으로 닫는다. 빈 값끼리 같다고 통과시키면 누구나 지울 수 있다.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from backend.app.services import store

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/cleanup")
async def cleanup(authorization: str | None = Header(default=None)) -> dict[str, int]:
    expected = os.environ.get("INTERNAL_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_TOKEN 이 설정되지 않았습니다")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="토큰이 맞지 않습니다")
    return await store.cleanup_expired()
