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


def test_geocode_all_keeps_slot_order_and_survives_one_failure(monkeypatch) -> None:
    # 출발지는 한꺼번에 찾는다. 늦게 끝난 것이 있어도 핀 순서는 슬롯 순서이고, 한 명이 실패해도 나머지는 산다
    from backend.app.schemas.slots import Slots

    places = {"강남역": (127.02, 37.49), "잠실역": (127.10, 37.51), "사당역": (126.98, 37.47)}

    async def fake_keyword(client, query, size=geo.SEARCH_SIZE):
        await asyncio.sleep(0.02 if query == "강남역" else 0)  # 첫 사람이 가장 늦게 끝나게
        if query in places:
            return [_doc(query, *places[query], "SW8")]
        return []

    monkeypatch.setattr(geo, "_kakao_keyword", fake_keyword)
    slots = Slots(
        preset="meeting",
        participants=[
            {"name": "나", "origin": "강남역", "transport": "transit", "role": "colleague"},
            {"name": "친구", "origin": "없는곳", "transport": "transit", "role": "colleague"},
            {"name": "동생", "origin": "잠실역", "transport": "car", "role": "colleague",
             "pickup": "나", "pickup_at": "사당역"},
        ],
    )
    pins = asyncio.run(geo.geocode_all(slots))
    assert [(p.kind, p.name) for p in pins] == [
        ("participant", "나"),
        ("participant", "동생"),
        ("pickup", "사당역"),
    ]


def test_geocode_all_searches_destination_together_but_picks_near_it(monkeypatch) -> None:
    # 목적지도 다른 지명과 한꺼번에 검색한다. 그래도 같은 이름이 두 곳이면 목적지 둘레를 고른다 (10-31)
    from backend.app.schemas.slots import Slots

    started: list[str] = []
    gate = asyncio.Event()

    async def fake_keyword(client, query, size=geo.SEARCH_SIZE):
        started.append(query)
        if len(started) == 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), 1)  # 목적지 검색이 끝나기를 기다리면 여기서 멈춘다
        if query == "창원시청":
            return [_doc("창원시청", 128.68, 35.23)]
        return [_doc("마산역", 126.67, 37.64, "SW8"), _doc("마산역", 128.57, 35.23, "SW8")]  # 김포 쪽, 창원 쪽

    monkeypatch.setattr(geo, "_kakao_keyword", fake_keyword)
    slots = Slots(
        preset="meeting",
        destination="창원시청",
        participants=[{"name": "나", "origin": "마산역", "transport": "transit", "role": "colleague"}],
    )
    pins = asyncio.run(geo.geocode_all(slots))
    assert [p.kind for p in pins] == ["destination", "participant"]
    assert pins[1].lng == 128.57


def _slots(access_required: bool | None):
    from backend.app.schemas.slots import Slots

    access = None if access_required is None else {"required": access_required, "applied": True}
    return Slots(
        preset="visit" if access_required else "meeting",
        destination="거제 장승포항",
        participants=[{"name": "나", "origin": "부산역", "transport": "car", "role": "site"}],
        access=access,
    )


def _dest_pins():
    from backend.app.schemas.result import GeocodedPin

    return [GeocodedPin(name="거제 장승포항", lng=128.72, lat=34.87, confidence=0.95, kind="destination")]


def test_절차가_없으면_정문을_찾지_않고_목적지를_첫_후보로_둔다(monkeypatch):
    """09-27: 절차 없는 약속에 학교·아파트 정문이 1순위로 나왔다 ("거제도애광원 정문")."""
    asked: list[str] = []

    async def fake_nearby(client, query, center, limit=5, radii=()):
        asked.append(query)
        if query == geo.STATION_SUFFIX:
            return [_doc("장승포역", 128.73, 34.88, "SW8")]
        return [_doc("거제도애광원 정문", 128.70, 34.86)]

    monkeypatch.setattr(geo, "_nearby", fake_nearby)
    cands = asyncio.run(geo.build_candidates(_slots(False), _dest_pins()))
    assert [c["name"] for c in cands] == ["거제 장승포항", "장승포역"]
    assert all(q == geo.STATION_SUFFIX for q in asked)  # 정문·출입구는 묻지 않는다
    assert cands[0]["kind"] == "landmark"


def test_절차가_있으면_건물_1층이_먼저다(monkeypatch):
    async def fake_nearby(client, query, center, limit=5, radii=()):
        return []

    monkeypatch.setattr(geo, "_nearby", fake_nearby)
    cands = asyncio.run(geo.build_candidates(_slots(True), _dest_pins()))
    assert cands[0]["kind"] == "lobby"
