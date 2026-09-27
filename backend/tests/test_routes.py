"""services/routes.py 의 "너무 가까움" 처리. 바깥 API 를 부르지 않는다."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from backend.app.domain import rules
from backend.app.services import routes

SEONGSU = (127.056067, 37.544589)
NEAR = (127.0575, 37.5447)  # 약 130m


class _Client:
    """httpx.AsyncClient 대신. 정해 둔 JSON 을 돌려준다."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    async def post(self, url: str, **_: Any) -> httpx.Response:
        return httpx.Response(200, json=self.body, request=httpx.Request("POST", url))

    async def get(self, url: str, **_: Any) -> httpx.Response:
        return httpx.Response(200, json=self.body, request=httpx.Request("GET", url))


def test_도보_시간은_거리에_비례하고_같은_자리면_0이다() -> None:
    assert rules.walk_seconds(SEONGSU, SEONGSU) == 0
    near = rules.walk_seconds(NEAR, SEONGSU)
    far = rules.walk_seconds((127.0600, 37.5447), SEONGSU)
    assert 0 < near < far
    # 130m 남짓을 분당 67m, 우회 30% 로 걸으면 2~3분이다 (transport.md)
    assert 60 <= near <= 240


def test_대중교통이_너무_가깝다고_하면_도보로_계산한다(monkeypatch) -> None:
    """09-27: TMAP 이 status 11 을 주면 경로 실패로 그 사람이 결과에서 빠졌다. 130m 에서도 그랬다."""
    monkeypatch.setenv("TMAP_APP_KEY", "test")
    client = _Client({"result": {"message": "출발지와 도착지가 너무 가까움", "status": 11}})
    out = asyncio.run(routes.route_one(client, "transit", NEAR, SEONGSU))  # type: ignore[arg-type]
    assert out["duration_sec"] == rules.walk_seconds(NEAR, SEONGSU)
    assert out["transfer_count"] == 0
    assert out["legs"][0]["mode"] == "WALK"
    assert out["polyline"] == [list(NEAR), list(SEONGSU)]


def test_자동차가_5m_안이라고_하면_도보로_계산한다(monkeypatch) -> None:
    monkeypatch.setenv("KAKAO_REST_KEY", "test")
    client = _Client({"routes": [{"result_code": 104, "result_msg": "출발지와 도착지가 5 m 이내"}]})
    out = asyncio.run(routes.route_one(client, "car", SEONGSU, SEONGSU))  # type: ignore[arg-type]
    assert out["duration_sec"] == 0


def test_다른_경로_없음은_그대로_실패다(monkeypatch) -> None:
    monkeypatch.setenv("TMAP_APP_KEY", "test")
    client = _Client({"result": {"message": "경로 없음", "status": 14}})
    try:
        asyncio.run(routes.route_one(client, "transit", NEAR, SEONGSU))  # type: ignore[arg-type]
    except routes.RouteFailed:
        return
    raise AssertionError("가깝다는 이유가 아니면 실패로 올려야 한다")
