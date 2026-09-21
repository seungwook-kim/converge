"""역의 첫차·막차. 서울 열린데이터광장 지하철 API. (SDD 6절 first_last_train)

바깥 호출은 services/ 에만 둔다 (BACKEND_GUIDE). geo.py·routes.py 와 같은 결로 쓴다.
MCP 도구 mcp_server/tools/first_last_train.py 가 이 파일의 first_last_seoul 을 감싼다.

왜 두 번 부르나 (SDD 6절 "역명→역코드 API 선행"):
  첫차·막차 API 는 역 이름을 받지 않고 내부 코드(STATION_CD, 예: 서울역 1호선 0150)를 받는다.
  외부 코드(FR_CODE, 133)를 넣으면 "데이터 없음"이 온다 (09-18 실측). 그래서 역 정보 API 로 코드를 먼저 얻는다.

API 두 개 (둘 다 http://openapi.seoul.go.kr:8088/{KEY}/json/{서비스}/{시작}/{끝}/...):
  SearchSTNBySubwayLineInfo/1/N/ /{역이름}          → 부분 일치 목록. STATION_CD·LINE_NUM("01호선")·FR_CODE
  SearchFirstAndLastTrainbyLineServiceNew/1/N/{호선}/{상하행}/{요일}/{STATION_CD}
                                                      → FSTT_HRM("052030")·LSTTM_HRM("244800")·행선지
  칸 순서는 호선 → 상하행(1 상행·2 하행) → 요일(1 평일·2 토·3 휴일) → 역코드다. 요일과 상하행을 바꿔 넣으면
  에러 없이 다른 답이 오므로 주의 (09-21 실측으로 순서 확정).

시각은 "HHMMSS" 6자리. 자정 넘는 막차는 24시·25시로 이어 센다 ("244800" = 24:48). 그대로 "HH:MM" 으로 자른다.

부산 (09-21 승인되어 붙임, apis.data.go.kr/B551542/trainTime/getTrainTime):
  서울과 달리 역 조회 API 가 없어 역외부코드(scode)를 레포에 둔다
  (backend/app/data/busan_stations.csv, scripts/fetch_busan_stations.py 가 만든다).
  시각표는 한 역의 전체 열차가 오고, 이른 순서로 오지 않는다. 그래서 요일·방향으로 거른 뒤
  min·max 로 첫차·막차를 고른다. 행선지 칸이 없어 first_to·last_to 는 빈 문자열이다.
"""
from __future__ import annotations

import csv
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

SEOUL_BASE = "http://openapi.seoul.go.kr:8088"
TIMEOUT_SEC = 8.0
STATION_SEARCH_SIZE = 20  # 같은 이름이 호선마다 따로 나온다 (서울역: 1·4·경의선·GTX)

WEEKDAY_TAG = {"weekday": "1", "sat": "2", "holiday": "3"}
DIRECTION_TAG = {"up": "1", "down": "2"}

BUSAN_URL = "https://apis.data.go.kr/B551542/trainTime/getTrainTime"
BUSAN_STATIONS_CSV = Path(__file__).resolve().parents[1] / "data" / "busan_stations.csv"
BUSAN_ROWS = 1200  # 한 역의 하루치 전체. 요일·방향을 여기서 거르므로 넉넉히 받는다
BUSAN_EMPTY_TIME = "00:00:00"  # 실제 열차가 아니라 자리만 채운 행
BUSAN_DAY = {"weekday": "1", "sat": "2", "holiday": "3"}
BUSAN_UPDOWN = {"up": "0", "down": "1"}  # 서울(1·2)과 값이 다르다


class ScheduleFailed(RuntimeError):
    """첫차·막차를 구하지 못했다. 역을 못 찾았거나 API 가 데이터 없음이라 했다."""


def _key() -> str:
    key = os.environ.get("SEOUL_OPENDATA_KEY")
    if not key:
        raise ScheduleFailed("SEOUL_OPENDATA_KEY 가 없습니다")
    return key


async def _seoul_get(client: httpx.AsyncClient, service: str, *segments: str) -> list[dict[str, Any]]:
    """열린데이터광장 호출 한 번. 결과 코드가 INFO-000 이 아니면 예외. 빈 결과는 빈 목록."""
    url = "/".join([SEOUL_BASE, _key(), "json", service, *segments])
    res = await client.get(url)
    res.raise_for_status()
    data = res.json()
    # 키가 틀리면 최상위에 RESULT 만 온다. 정상이면 {서비스명: {RESULT, row}} 다.
    if service not in data:
        msg = data.get("RESULT", {}).get("MESSAGE", "알 수 없는 응답")
        raise ScheduleFailed(f"서울 열린데이터광장: {msg}")
    body = data[service]
    code = body.get("RESULT", {}).get("CODE", "")
    if code == "INFO-200":  # 해당하는 데이터가 없습니다
        return []
    if code != "INFO-000":
        raise ScheduleFailed(f"서울 열린데이터광장 {code}: {body.get('RESULT', {}).get('MESSAGE', '')}")
    return body.get("row", [])


def _line_label(line: str) -> str:
    """"4" → "04호선". 역 정보 API 의 LINE_NUM 표기에 맞춘다. SDD 는 1~9호선만 다룬다."""
    return f"{int(line):02d}호선"


async def find_station(client: httpx.AsyncClient, name: str, line: str) -> dict[str, Any]:
    """역 이름 + 호선 → 역 한 건. 이름은 "서울역"·"서울"·"사당"처럼 온다.

    API 는 부분 일치라 "서울"에 서울대입구도 나온다. 그래서 호선으로 먼저 거르고, 그 안에서
    이름이 정확히 같은 것 → "역"을 뗀 것이 같은 것 → 첫 것 순으로 고른다.
    """
    rows = await _seoul_get(client, "SearchSTNBySubwayLineInfo", "1", str(STATION_SEARCH_SIZE), " ", name)
    same_line = [r for r in rows if r.get("LINE_NUM") == _line_label(line)]
    if not same_line:
        raise ScheduleFailed(f"'{name}' 역을 {int(line)}호선에서 찾지 못했습니다")
    bare = name.rstrip("역")
    for pick in (
        lambda r: r["STATION_NM"] == name,
        lambda r: r["STATION_NM"].rstrip("역") == bare,
    ):
        hit = next((r for r in same_line if pick(r)), None)
        if hit:
            return hit
    return same_line[0]


def _hhmm(hhmmss: str) -> str:
    """"052030" → "05:20". 6자리가 아니면 그대로 돌려준다 (API 가 바뀌어도 죽지 않게)."""
    return f"{hhmmss[:2]}:{hhmmss[2:4]}" if len(hhmmss) == 6 and hhmmss.isdigit() else hhmmss


async def first_last_seoul(
    client: httpx.AsyncClient, station_name: str, line: str, weekday: str, direction: str
) -> dict[str, Any]:
    """서울 지하철 한 역의 첫차·막차. 돌려주는 것:
        {"first": "05:20", "last": "24:48", "line": "1", "first_to": "동두천", "last_to": "동묘앞"}
    first_to·last_to 는 그 열차의 행선지. 막차가 종점까지 안 가는 경우가 있어 현장에선 이게 중요하다.
    """
    if weekday not in WEEKDAY_TAG:
        raise ScheduleFailed(f"weekday 는 {list(WEEKDAY_TAG)} 중 하나여야 합니다")
    if direction not in DIRECTION_TAG:
        raise ScheduleFailed(f"direction 은 {list(DIRECTION_TAG)} 중 하나여야 합니다")

    station = await find_station(client, station_name, line)
    rows = await _seoul_get(
        client,
        "SearchFirstAndLastTrainbyLineServiceNew",
        "1",
        "5",
        str(int(line)),
        DIRECTION_TAG[direction],
        WEEKDAY_TAG[weekday],
        station["STATION_CD"],
    )
    if not rows:
        raise ScheduleFailed(f"{station['STATION_NM']} {int(line)}호선 {direction} {weekday} 시각표가 없습니다")
    row = rows[0]
    return {
        "first": _hhmm(row["FSTT_HRM"]),
        "last": _hhmm(row["LSTTM_HRM"]),
        "line": str(int(line)),
        "first_to": row.get("FSTT_ARVL_STTN", ""),
        "last_to": row.get("LSTTM_ARVL_STTN", ""),
    }


# ── 부산 ────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def busan_stations() -> list[dict[str, str]]:
    """역외부코드 표. 파일이 없으면 빈 목록이고, 조회는 그 자리에서 실패한다."""
    if not BUSAN_STATIONS_CSV.exists():
        return []
    with BUSAN_STATIONS_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _bare(name: str) -> str:
    """"서면역", "서면(2)", "서면 역" 을 모두 "서면" 으로.

    표에는 환승역이 호선별로 따로 있다("서면(1)", "서면(2)"). 사람은 그냥 "서면역"이라고 말한다.
    """
    return re.sub(r"\(.*?\)", "", name).replace("역", "").replace(" ", "").strip()


def busan_station_code(name: str, line: str = "") -> tuple[str, str]:
    """역 이름 → (scode, 호선). 호선을 주면 그 호선으로, 없으면 번호가 작은 쪽(대개 본선)을 쓴다."""
    target = _bare(name)
    hits = [row for row in busan_stations() if _bare(row["name"]) == target]
    if not hits:
        raise ScheduleFailed(f"부산 도시철도에서 '{name}' 역을 찾지 못했습니다")
    if line:
        same = [row for row in hits if row["line"] == str(int(line))]
        if not same:
            raise ScheduleFailed(f"'{name}' 역은 부산 {int(line)}호선에 없습니다")
        hits = same
    best = min(hits, key=lambda row: int(row["line"]))
    return best["scode"], best["line"]


def _minutes(hhmmss: str) -> int:
    """"24:37:40" → 1477. 24시 넘김을 그대로 분으로 센다. 크기 비교에 쓴다."""
    return int(hhmmss[:2]) * 60 + int(hhmmss[3:5])


async def first_last_busan(
    client: httpx.AsyncClient, station_name: str, line: str, weekday: str, direction: str
) -> dict[str, Any]:
    """부산 도시철도 한 역의 첫차·막차. 돌려주는 모양은 first_last_seoul 과 같다.

    시각표가 이른 순서로 오지 않아 순서를 믿지 않고 min·max 로 고른다.
    행선지 칸이 없어 first_to·last_to 는 빈 문자열이다.
    """
    if weekday not in BUSAN_DAY:
        raise ScheduleFailed(f"weekday 는 {list(BUSAN_DAY)} 중 하나여야 합니다")
    if direction not in BUSAN_UPDOWN:
        raise ScheduleFailed(f"direction 은 {list(BUSAN_UPDOWN)} 중 하나여야 합니다")

    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        raise ScheduleFailed("DATA_GO_KR_KEY 가 없습니다")

    scode, found_line = busan_station_code(station_name, line)
    res = await client.get(
        BUSAN_URL,
        params={"serviceKey": key, "act": "json", "scode": scode, "pageNo": 1, "numOfRows": BUSAN_ROWS},
    )
    res.raise_for_status()
    items = ((res.json().get("body") or {}).get("items") or {}).get("item") or []
    if isinstance(items, dict):  # 한 건이면 목록이 아니라 그대로 온다
        items = [items]

    day, updown = BUSAN_DAY[weekday], BUSAN_UPDOWN[direction]
    times = [
        row["arrtime"]
        for row in items
        if row.get("dayType") == day and row.get("updown") == updown and row.get("arrtime") != BUSAN_EMPTY_TIME
    ]
    if not times:
        raise ScheduleFailed(f"{station_name} 부산 {found_line}호선 {direction} {weekday} 시각표가 없습니다")

    first, last = min(times, key=_minutes), max(times, key=_minutes)
    return {
        "first": first[:5],
        "last": last[:5],
        "line": found_line,
        "first_to": "",
        "last_to": "",
    }
