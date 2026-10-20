"""POST /api/agent. 파이프라인 입구. (SDD 1절·2절)

이 파일은 "요청 받기 → 로그인 확인 → pipeline.run 부르기 → 상태 코드 정하기"만 한다.
단계 순서와 갈림길은 services/pipeline.py 에 있다 (SDD 5절).

로그인 필수. 토큰이 없거나 틀리면 401 이고, 그 전에 LLM을 부르지 않는다 (비용 방어, SDD 2절).
"""
from __future__ import annotations

import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException

from backend.app.schemas.request import AgentRequest
from backend.app.schemas.result import AgentResponse
from backend.app.services import pipeline
from backend.app.services import costs as cost_guards
from backend.app.services import llm
from backend.app.services.auth import current_user

router = APIRouter(prefix="/api", tags=["agent"])

# 사용자 한 명이 RATE_WINDOW_SEC 동안 부를 수 있는 /api/agent 횟수. 약속 하나에 되묻기·핀 확인까지 해도
# 대여섯 번이다. 서버 메모리에 두므로 컨테이너마다 따로 센다(최대 2대). 정확한 집계가 아니라 폭주를 막는 용도
RATE_LIMIT = 20
RATE_WINDOW_SEC = 600
_calls: dict[str, deque[float]] = {}


def _allow(user_id: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    q = _calls.setdefault(user_id, deque())
    while q and now - q[0] > RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return False
    q.append(now)
    if len(_calls) > 5000:  # 오래 쉰 사용자 기록이 쌓이지 않게
        for uid in [u for u, d in _calls.items() if not d or now - d[-1] > RATE_WINDOW_SEC]:
            _calls.pop(uid, None)
    return True


@router.post("/agent", response_model=AgentResponse)
async def agent(req: AgentRequest, user_id: str = Depends(current_user)) -> AgentResponse:
    """문장 또는 캡처를 받아 집결 계획을 돌려준다.

    실패도 200 으로 돌려준다. stage 가 failed·need_info 로 오는 것이지 HTTP 오류가 아니다.
    화면이 stage 하나로 갈리기 때문이다 (frontend/FRONTEND_GUIDE.md 표).
    HTTP 오류는 권한 문제일 때만 낸다.
    """
    # 사용자별 호출 횟수 상한. LLM 을 부르기 전에 막는다 (10-20 입력 방어)
    if not _allow(user_id):
        raise HTTPException(status_code=429, detail="요청이 너무 잦습니다. 잠시 뒤에 다시 시도해 주세요")
    # 하루 비용 상한에 닿았으면 막지 않고 무료 FALLBACK 모델로 돈다 (09-28 결정, services/llm.py)
    token = llm.use_fallback_for_request() if await _over_daily_limit() else None
    try:
        return await pipeline.run(req, user_id)
    except pipeline.NotYourSession as e:
        raise HTTPException(status_code=403, detail="본인 세션만 이어서 물어볼 수 있습니다") from e
    except pipeline.SessionLocked as e:
        # 약속이 지난 세션. 재계산할 이유가 없고 LLM 비용만 나간다 (SDD 5절 재질문)
        raise HTTPException(status_code=409, detail="약속 날짜가 지나 잠긴 세션입니다") from e
    finally:
        if token is not None:
            llm.end_request_fallback(token)


async def _over_daily_limit() -> bool:
    """일일 상한(41번)에 닿았는가. env 가 비었거나 DB 조회가 실패하면 False (정상 요청을 막지 않는다).

    전에는 닿으면 429 로 막았다. 09-28 부터는 막지 않고 무료 FALLBACK 모델(gemini-3.5-flash-lite)로 돈다.
    """
    limit = cost_guards.daily_limit()
    if limit is None:
        return False
    try:
        from backend.app.services import store

        spent = await store.daily_cost_usd()
    except Exception:  # noqa: BLE001  집계 실패가 정상 요청까지 막지 않게 한다
        return False
    return spent >= limit
