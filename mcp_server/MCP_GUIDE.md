# MCP_GUIDE

FastMCP 서버. `backend/app/main.py`에 ASGI로 마운트되어 같은 프로세스에서 `/mcp`로 제공된다. 별도 실행 없음.

도구는 `backend/app/services/`의 geo·routes·transit_schedule 함수를 감싸 바깥 MCP 클라이언트에 내놓는다.
백엔드 파이프라인은 이 도구를 거치지 않고 서비스 함수를 바로 부른다 (SDD 1절, 10-09).

## 도구 6개

시그니처와 호출 API는 docs/SDD.md 6절이 기준이다.

| 도구 | 언제 쓰나 |
|---|---|
| `geocode` | 지명 텍스트를 좌표로. 기준 좌표 편향으로 동명 지명(서면: 부산/순천)을 가른다 |
| `search_places` | 좌표 주변에서 절차 시작점(정문·로비)이나 랜드마크(역·주차장 입구)를 찾는다 |
| `route_car` | 자동차 경로·소요시간. 출발 시각이 있으면 미래 운행 |
| `route_transit` | 대중교통 경로·환승·요금 |
| `first_last_train` | 역의 첫차·막차. 서울 1~9호선, 부산 |
| `departure_calc` | 도착 기한, 소요시간, 여유, 절차 소요로 출발 시각 역산. 계산만 |

2026-09-21 기준: `geocode` `search_places` `route_car` `route_transit` `first_last_train` `departure_calc` 6개가 등록돼 있다.
`search_places` 는 kind 마다 검색어를 여러 개 순서대로 써 본다. 한 말로는 자주 빈다
(건물 둘레에 그 이름 그대로인 장소가 없어 0건이 되고, "정문"처럼 바꿔야 찾힌다).

## 지킬 것

- `tools/` 파일 하나에 도구 하나. description 한 문장으로 언제 쓰는 도구인지 드러나야 한다. 모델은 그것만 보고 고른다
- 실제 API 호출 코드를 여기 다시 쓰지 않는다. `backend/app/services/`의 함수를 부른다
- 헤더 `Authorization: Bearer {MCP_TOKEN}` 없으면 거부. 브라우저는 `/mcp`를 직접 부르지 않는다
- 응답에 API 키를 싣지 않는다

## 실행 기록

`docs/evidence/mcp/`에 연결 화면, tool 목록, 실제 호출 결과를 남긴다.
