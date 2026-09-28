"""판정 호출 (SDD 5절 6단계). 모델 호출은 가짜로 바꾼다. 키·네트워크 없이 돈다."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from backend.app.schemas.slots import Slots
from backend.app.services import judge, llm


def _fake_client(outputs):
    """차례로 outputs 를 돌려주는 가짜 OpenAI 클라이언트. 호출마다 토큰 1000/100 을 쓴다."""
    calls = iter(outputs)

    async def create(**_):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(calls)))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100),
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_판정_호출의_토큰과_비용을_재시도까지_합쳐_남긴다(monkeypatch):
    good = json.dumps({"rankings": [
        {"candidate_idx": 0, "rank": 1, "reason": "가깝다", "rejected_reason": None, "switched_from": None},
    ]})
    monkeypatch.setenv("MODEL_LARGE", llm.FALLBACK_MODEL)
    fake = _fake_client(["형식 위반", good])  # 재시도 때도 같은 가짜를 써야 응답이 차례로 나온다
    monkeypatch.setattr(judge.llm, "_client", lambda _model: fake)
    monkeypatch.setattr(judge.langfuse, "get_prompt", lambda _name: ("{{situation}}{{candidates}}{{participants}}{{rules}}", "1"))
    llm._last_meta.clear()

    slots = Slots(preset="meeting", destination="강남 사무실", participants=[dict(name="나", origin="강남역", transport="transit", role="site")])
    candidates = [{"name": "강남역", "kind": "landmark", "address": "테스트", "lng": 127.0, "lat": 37.5}]
    out = asyncio.run(judge.rank(slots, candidates, []))

    assert out[0]["rank"] == 1
    meta = llm.last_meta()
    assert meta["judge_model"] == llm.FALLBACK_MODEL
    assert (meta["judge_tokens_in"], meta["judge_tokens_out"], meta["judge_attempts"]) == (2000, 200, 2)
    assert meta["judge_cost_usd"] is not None and meta["judge_cost_usd"] > 0
