"""부산 도시철도 역외부코드 표를 한 번 만들어 저장한다. (SDD 6절 first_last_train)

왜 필요한가:
  부산교통공사 열차시각표 API(B551542/trainTime)는 역을 `scode`(역외부코드)로만 받는다.
  사람은 "서면역"이라고 말하지 "219"라고 말하지 않는다. 그 사이를 이을 표가 필요하다.
  역 목록을 주는 API 는 없다 (getStationList, getStationInfo 둘 다 "해당 오픈API 서비스가 없거나
  폐기됨", 09-20 실측). 그래서 코드 범위를 훑어 이름을 받아 적는다.

코드 규칙:
  1xx = 1호선, 2xx = 2호선, 3xx = 3호선, 4xx = 4호선 (신평 101, 안평 414 가 API 문서의 예시다).

결과: backend/app/data/busan_stations.csv (scode, name, line)
호출은 한 번만 하면 된다. 역이 늘면 그때 다시 돌린다.

    python scripts/fetch_busan_stations.py
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

URL = "https://apis.data.go.kr/B551542/trainTime/getTrainTime"
OUT = ROOT / "backend" / "app" / "data" / "busan_stations.csv"

# 훑을 범위. 넉넉하게 잡고 빈 코드는 건너뛴다
RANGES = {1: range(101, 145), 2: range(201, 250), 3: range(301, 325), 4: range(401, 420)}
GAP_SEC = 0.2  # 공공데이터포털은 초당 호출 제한이 있다. 한 번 만드는 표라 천천히 간다


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.split(" #")[0].strip().strip('"')


def probe(client: httpx.AsyncClient | httpx.Client, key: str, scode: int) -> tuple[str, str] | None:
    """그 코드의 역 이름과 호선. 없으면 None."""
    params = {
        "serviceKey": key,
        "pageNo": 1,
        "numOfRows": 1,
        "day": 1,
        "updown": 0,
        "stime": "0400",
        "etime": "2600",
        "enum": 1,
        "act": "json",
        "scode": scode,
    }
    res = client.get(URL, params=params, timeout=20.0)
    if res.status_code != 200:
        return None
    body = res.json().get("body") or {}
    items = (body.get("items") or {}).get("item") or []
    if not items:
        return None
    row = items[0]
    return row["sname"], row["line"]


def main() -> int:
    load_env()
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        print("DATA_GO_KR_KEY 가 없다")
        return 1

    rows: list[dict[str, str]] = []
    with httpx.Client() as client:
        for line_no, codes in RANGES.items():
            found = 0
            for scode in codes:
                try:
                    hit = probe(client, key, scode)
                except Exception as e:  # noqa: BLE001  한 코드가 실패해도 나머지를 계속 본다
                    print(f"  {scode} 실패 {type(e).__name__}: {e}")
                    continue
                if hit:
                    name, line = hit
                    rows.append({"scode": str(scode), "name": name, "line": line})
                    found += 1
                time.sleep(GAP_SEC)
            print(f"{line_no}호선 {found}개")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["scode", "name", "line"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n{len(rows)}개 역 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
