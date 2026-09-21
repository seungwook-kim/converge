"""MCP 도구 등록과 계약. (SDD 6절, MCP_GUIDE)

키 없이 돈다 (TEST_GUIDE). 바깥 호출은 monkeypatch 로 가짜 함수를 넣는다. 여기서 보는 것은
"도구가 등록됐는가, 입력·출력 모양이 SDD 6절과 같은가, 서비스 함수에 제대로 넘기는가" 세 가지다.
실제 API 응답이 맞는지는 scripts/ 의 실행 스크립트가 본다.
"""
from __future__ import annotations

import asyncio

import pytest

from mcp_server.server import mcp
from mcp_server.tools import geocode as geocode_tool
from mcp_server.tools import route_car as route_car_tool
from mcp_server.tools import route_transit as route_transit_tool
from mcp_server.tools import search_places as search_places_tool

EXPECTED = {"geocode", "search_places", "route_car", "route_transit", "departure_calc"}


def tools() -> dict:
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def test_도구가_등록된다():
    assert EXPECTED <= set(tools())


def test_설명이_언제_쓰는지를_말한다():
    """모델은 description 만 보고 도구를 고른다 (SDD 6절)."""
    for name, tool in tools().items():
        if name not in EXPECTED:
            continue
        first_line = (tool.description or "").splitlines()[0]
        assert "쓴다" in first_line, f"{name} 의 첫 문장이 용도를 말하지 않는다: {first_line!r}"


def test_입력_이름이_SDD_와_같다():
    got = tools()
    assert set(got["geocode"].input_schema["properties"]) == {"query", "bias_lng", "bias_lat"}
    assert set(got["route_transit"].input_schema["properties"]) == {
        "origin_lng", "origin_lat", "dest_lng", "dest_lat",
    }
    assert "departure_time" in got["route_car"].input_schema["properties"]
    assert "waypoint_lng" in got["route_car"].input_schema["properties"]


def test_geocode_는_기준_좌표를_묶어_넘긴다(monkeypatch):
    """MCP 입력은 숫자 둘, 형 함수는 (lng, lat) 한 묶음이다."""
    from backend.app.schemas.result import GeocodedPin

    seen = {}

    async def fake(client, query, kind="destination", bias=None):
        seen.update(query=query, bias=bias)
        return GeocodedPin(name="창원시청", lng=128.68, lat=35.22, confidence=0.95, kind=kind)

    monkeypatch.setattr(geocode_tool, "geocode_one", fake)
    out = asyncio.run(geocode_tool.geocode("창원시청", 128.6, 35.1))
    assert seen["bias"] == (128.6, 35.1)
    assert (out.lng, out.name, out.confidence) == (128.68, "창원시청", 0.95)


def test_geocode_는_기준_좌표가_없으면_None_으로_넘긴다(monkeypatch):
    from backend.app.schemas.result import GeocodedPin

    seen = {}

    async def fake(client, query, kind="destination", bias=None):
        seen["bias"] = bias
        return GeocodedPin(name="x", lng=127.0, lat=37.5, confidence=0.9, kind=kind)

    monkeypatch.setattr(geocode_tool, "geocode_one", fake)
    asyncio.run(geocode_tool.geocode("서울역"))
    assert seen["bias"] is None


def test_search_places_는_kind_를_검색어로_바꾼다(monkeypatch):
    """지도에 "OO빌딩 정문" 이라는 장소는 없다. 검색어는 짧게, 자리는 좌표로 좁힌다."""
    seen = {}

    async def fake(client, query, center, limit=5):
        seen.setdefault("queries", []).append(query)
        seen["center"] = center
        return [{"place_name": "정문", "road_address_name": "경남", "x": "128.6", "y": "35.1"}]

    monkeypatch.setattr(search_places_tool, "_nearby", fake)
    out = asyncio.run(search_places_tool.search_places(128.6, 35.1, "gate"))
    assert seen["center"] == (128.6, 35.1)
    assert all("진해" not in q for q in seen["queries"])
    assert out.places[0].kind == "gate"


def test_route_car_는_픽업_지점과_출발_시각을_넘긴다(monkeypatch):
    seen = {}

    async def fake(client, origin, dest, waypoint=None, departure_time=None):
        seen.update(origin=origin, dest=dest, waypoint=waypoint, departure_time=departure_time)
        return {"duration_sec": 1800, "polyline": [[128.6, 35.1]], "transfer_count": None}

    monkeypatch.setattr(route_car_tool, "_car", fake)
    out = asyncio.run(
        route_car_tool.route_car(128.6, 35.1, 127.0, 37.5, 128.9, 35.2, "202609210800")
    )
    assert seen["waypoint"] == (128.9, 35.2)
    assert seen["departure_time"] == "202609210800"
    assert out.duration_sec == 1800


def test_route_car_는_경유지가_없으면_None(monkeypatch):
    seen = {}

    async def fake(client, origin, dest, waypoint=None, departure_time=None):
        seen["waypoint"] = waypoint
        return {"duration_sec": 600, "polyline": [], "transfer_count": None}

    monkeypatch.setattr(route_car_tool, "_car", fake)
    asyncio.run(route_car_tool.route_car(128.6, 35.1, 127.0, 37.5))
    assert seen["waypoint"] is None


def test_route_transit_는_환승_횟수와_구간을_그대로_준다(monkeypatch):
    """legs 는 호선 판단에 쓴다. first_last_train 에 넘길 호선을 여기서 읽는다."""

    async def fake(client, origin, dest):
        return {
            "duration_sec": 3300,
            "polyline": [[127.0, 37.5]],
            "transfer_count": 2,
            "legs": [{"mode": "SUBWAY", "route": "수도권4호선", "from": "사당", "to": "서울역", "sec": 900}],
        }

    monkeypatch.setattr(route_transit_tool, "_transit", fake)
    out = asyncio.run(route_transit_tool.route_transit(127.0, 37.5, 126.9, 37.56))
    assert (out.duration_sec, out.transfer_count) == (3300, 2)
    assert out.legs[0].route == "수도권4호선"


def test_키가_없으면_그_자리에서_알린다(monkeypatch):
    """조용히 0 을 돌려주지 않는다. 계산이 그 값을 믿고 굴러가면 더 나쁘다."""
    from backend.app.services import geo

    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    with pytest.raises(geo.GeocodeFailed):
        geo._key()


# ─────────────────────────────────────────────────────────── first_last_train

def test_first_last_train_도_등록된다():
    assert "first_last_train" in tools()


def test_부산_역_이름을_코드로_바꾼다():
    """표는 backend/app/data/busan_stations.csv. 역 목록 API 가 폐기돼 저장소에 둔다 (SDD 6절)."""
    from backend.app.services import transit_schedule as ts

    if not ts.busan_stations():
        pytest.skip("역 코드표가 없다 (scripts/fetch_busan_stations.py)")
    code, line = ts.busan_station_code("서면역")
    assert code.isdigit() and line in ("1", "2", "3", "4")
    # "서면역", "서면", "서면(2)" 는 같은 역이다
    assert ts.busan_station_code("서면")[0] == code


def test_없는_역은_그_자리에서_알린다():
    from backend.app.services import transit_schedule as ts

    if not ts.busan_stations():
        pytest.skip("역 코드표가 없다")
    with pytest.raises(ts.ScheduleFailed):
        ts.busan_station_code("있을 리 없는역")


def test_24시_넘김을_그대로_센다():
    """API 는 막차를 "24:37:40" 으로 준다. 크기 비교는 24시를 이어 세야 맞다."""
    from backend.app.services import transit_schedule as ts

    assert ts._minutes("24:37:40") > ts._minutes("23:46:10")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """httpx.AsyncClient 대신. 부산 시각표 응답 한 벌을 돌려준다."""

    def __init__(self, rows):
        self._rows = rows

    async def get(self, url, params=None):
        return _FakeResponse({"body": {"items": {"item": self._rows}}})


def _row(arrtime, day="1", updown="0"):
    return {"arrtime": arrtime, "dayType": day, "updown": updown}


def test_순서를_믿지_않고_최소_최대로_고른다(monkeypatch):
    """이른 순서로 오지 않는다. 첫 행을 첫차로 보면 틀린다 (09-20 실측)."""
    from backend.app.services import transit_schedule as ts

    monkeypatch.setenv("DATA_GO_KR_KEY", "x")
    monkeypatch.setattr(ts, "busan_station_code", lambda name, line="": ("123", "1"))
    client = _FakeClient([_row("06:14:40"), _row("05:06:00"), _row("24:37:40"), _row("23:10:00")])
    out = asyncio.run(ts.first_last_busan(client, "서면역", "", "weekday", "up"))
    assert (out["first"], out["last"], out["line"]) == ("05:06", "24:37", "1")
    assert (out["first_to"], out["last_to"]) == ("", "")  # 부산은 행선지 칸이 없다


def test_빈_행은_열차로_세지_않는다(monkeypatch):
    """"00:00:00" 은 자리만 채운 행이다. 빼지 않으면 첫차가 00:00 이 된다."""
    from backend.app.services import transit_schedule as ts

    monkeypatch.setenv("DATA_GO_KR_KEY", "x")
    monkeypatch.setattr(ts, "busan_station_code", lambda name, line="": ("123", "1"))
    client = _FakeClient([_row("00:00:00"), _row("05:30:00"), _row("00:00:00"), _row("23:50:00")])
    assert asyncio.run(ts.first_last_busan(client, "서면역", "", "weekday", "up"))["first"] == "05:30"

    empty = _FakeClient([_row("00:00:00"), _row("00:00:00")])
    with pytest.raises(ts.ScheduleFailed):
        asyncio.run(ts.first_last_busan(empty, "서면역", "", "weekday", "up"))


def test_요일_방향_값을_검사한다():
    from backend.app.services import transit_schedule as ts

    with pytest.raises(ts.ScheduleFailed):
        asyncio.run(ts.first_last_busan(_FakeClient([]), "서면역", "", "화요일", "up"))
    with pytest.raises(ts.ScheduleFailed):
        asyncio.run(ts.first_last_busan(_FakeClient([]), "서면역", "", "weekday", "옆으로"))


def test_first_last_train_은_city_로_서울_부산을_가른다(monkeypatch):
    from mcp_server.tools import first_last_train as tool

    async def fake_busan(client, station_name, line, weekday, direction):
        assert (station_name, weekday, direction) == ("서면역", "weekday", "up")
        return {"first": "05:37", "last": "24:37", "line": "1", "first_to": "", "last_to": ""}

    monkeypatch.setattr(tool, "first_last_busan", fake_busan)
    out = asyncio.run(tool.first_last_train("서면역", "", "up", city="busan"))
    assert (out.first, out.last, out.line) == ("05:37", "24:37", "1")
