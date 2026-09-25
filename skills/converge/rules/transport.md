---
# 이동·여유 규칙값. 코드(backend/app/domain/rules.py)가 이 프론트매터를 읽는다.
# 값을 바꾸려면 여기만 고친다. 코드에 숫자를 적지 않는다 (SDD 7절 원칙).
buffer_meeting_min: 20           # 일반 약속의 여유(분). 지각이 신뢰 문제인 자리는 넉넉히 본다
buffer_visit_min: 15             # 출입 절차가 있는 방문의 여유(분). 절차 시각 10~20분 전 도착
car_traffic_pct: 15              # 자동차 소요에 얹는 정체 여유(%)
car_traffic_min_min: 10          # 정체 여유의 최소값(분)
car_traffic_rush_pct: 25         # 출퇴근 시간대의 정체 여유(%)
transit_transfer_extra_min: 10   # 환승이 있으면 더 얹는 시간(분)
luggage_requires_car: true       # 장비·짐이 있으면 대중교통으로 보내지 않는다
pickup_wait_min: 5               # 태우는 지점에서 기다리는 시간(분)
pickup_counts_from_board: true   # 태워지는 사람의 소요시간은 탑승 이후 구간만
max_pickup_per_car: 1            # 차 한 대당 픽업 한 명. 다중 픽업 순서 최적화는 범위 밖
route_cache_ttl_hours: 24        # 경로 응답을 캐시에 두는 시간. 길이 하루 뒤에는 달라진다
geocode_cache_ttl_hours: 720     # 지오코딩 응답을 캐시에 두는 시간(30일). 장소 좌표는 잘 안 바뀐다
transport_words:                 # 이동수단을 말했다는 단서. 그 사람 이야기에 하나도 없으면 모델이 채운 이동수단을 지우고 되묻는다 (09-23)
  - 차
  - 자차
  - 운전
  - 지하철
  - 전철
  - 버스
  - 대중교통
  - 기차
  - KTX
  - SRT
  - 택시
  - 걸어
  - 도보
  - 자전거
  - 호선
  - 신분당선
  - 공항철도
  - 경전철
  - 트램
---
# 이동과 여유

지도 앱이 55분이라 해도 환승 대기까지 더하면 실제로는 더 걸린다. 그래서 환승이 있으면 따로 얹는다.
약속 지각은 신뢰 문제라 여유를 크게 잡고, 절차가 있는 방문은 절차 소요를 따로 빼므로 여유를 조금 줄인다.

## 말하지 않은 이동수단

모델이 이동수단을 말하지 않은 사람에게 지하철이나 차를 지어 넣는 경우가 있다(09-23 gpt-4o-mini,
"한지훈씨는 인천에서 옵니다" 3회 중 1회). 차인지 대중교통인지로 출발 시각이 30분 넘게 갈리므로
코드가 한 번 더 본다 (`domain/rules.unstated_transports`).

- 문장을 쉼표·마침표와 "~고", "~며", "~면서" 뒤에서 나눈다
- 그 사람 이름이 나오는 조각에 `transport_words` 가 하나도 없으면 이동수단을 비우고 되묻는다
- "나" 는 "나·저·나는·저는·제가·내가" 로 찾는다
- 태워지는 사람(pickup)은 운전자 것을 따르므로 보지 않는다. 이름이 문장에 없으면 판단하지 않는다

## 값이 쓰이는 곳

| 키 | 어디서 | 무엇을 |
|---|---|---|
| `buffer_meeting_min` | 5·7단계 | 일반 약속(meeting)의 여유 |
| `buffer_visit_min` | 5·7단계 | 출입 절차가 있는 방문(visit)의 여유 |
| `car_traffic_pct`·`car_traffic_min_min`·`car_traffic_rush_pct` | 5단계 | 자동차 소요에 얹는 정체분 |
| `transit_transfer_extra_min` | 5단계 | 환승 1회 이상이면 더한다 |
| `luggage_requires_car` | 5단계 | `constraints` 에 luggage 가 있으면 이동수단 판단에 쓴다 |
| `pickup_wait_min` | 4·5단계 | 운전자 경로에 태우는 시간 |
| `pickup_counts_from_board` | 4단계 | 태워지는 사람 경로를 탑승 지점부터 계산 |
| `max_pickup_per_car` | 4단계 | 한 대가 여러 명을 태우는 경우는 다루지 않는다 |
| `route_cache_ttl_hours` | `services/routes.py` | 같은 구간을 다시 물을 때 API 대신 캐시를 쓴다 |
| `geocode_cache_ttl_hours` | `services/geo.py` | 지오코딩 캐시 보관 시간 |

## 여유는 왜 따로 두나

경로 API 값은 "지금 길이 이렇다"는 예측이다. 늦으면 안 되는 자리일수록 그 예측만 믿을 수 없다.
여유를 소요시간에 섞지 않고 따로 두는 이유는, 화면에서 "경로 38분 + 여유 20분"처럼 근거를 나눠
보여 주기 위해서다 (docs/SDD.md 4절 ParticipantResult).

관련: docs/SDD.md 7절, 5절 4·5·7단계
