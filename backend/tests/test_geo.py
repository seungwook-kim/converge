"""services/geo.py 의 검색어 다듬기와 자리 고르기. 카카오를 부르지 않는다."""
from __future__ import annotations

import asyncio
from typing import Any

from backend.app.services import geo


def _doc(name: str, x: float, y: float, code: str = "") -> dict[str, Any]:
    return {"place_name": name, "address_name": "", "road_address_name": "", "x": str(x), "y": str(y),
            "category_group_code": code}


def test_tail_word_is_dropped_before_search() -> None:
    # "근처" 는 장소 이름이 아니다. 그대로 검색하면 이름이 비슷한 엉뚱한 가게가 걸린다 (09-27)
    assert geo._variants("성수역 근처")[0] == "성수역"
    assert "성수역 근처" not in geo._variants("성수역 근처")
    assert geo._variants("김해시청 앞")[0] == "김해시청"


def test_query_without_tail_word_is_kept() -> None:
    assert geo._variants("성수역")[0] == "성수역"
    assert geo._variants("여의도 사무실")[:2] == ["여의도 사무실", "여의도"]
    # 한 낱말뿐이면 꼬리말처럼 보여도 떼지 않는다
    assert geo._variants("앞") == ["앞"]


def test_geocode_one_uses_core_place_and_keeps_confidence(monkeypatch) -> None:
    seen: list[str] = []

    async def fake_keyword(client, query, size=geo.SEARCH_SIZE):
        seen.append(query)
        if query == "성수역":
            return [_doc("성수역 2호선", 127.056, 37.544, "SW8")]
        return [_doc("엉뚱한 카페", 127.068, 37.545)]

    monkeypatch.setattr(geo, "_kakao_keyword", fake_keyword)
    pin = asyncio.run(geo.geocode_one(None, "성수역 근처", "destination"))  # type: ignore[arg-type]

    assert seen[0] == "성수역"
    assert (pin.lng, pin.lat) == (127.056, 37.544)
    assert pin.name == "성수역 근처"  # 화면에는 사람이 쓴 말을 그대로 보인다
    # 꼬리말만 뗀 것은 같은 자리다. 확인 질문으로 넘기지 않는다
    assert pin.confidence >= 0.8
