---
# 준비물 목록. 코드(backend/app/domain/checklist.py)가 이 프론트매터를 읽는다.
# LLM 이 항목을 지어내지 않는다. 조건을 보고 여기서 꺼내기만 한다 (SDD 7절 원칙).
#
# before: 미리 해둘 것. 늦으면 되돌릴 수 없다
# onsite: 당일 챙길 것
#
# before 항목은 두 가지 모양을 받는다.
#   "방문자 등록"                       그냥 항목
#   {item: 고기·식재료, assign: car}    누가 맡을지 코드가 정해 이름을 붙인다
# assign 값은 car(차로 오는 사람)와 first(가장 먼저 도착하는 사람) 둘뿐이다.
# 해당하는 사람이 없으면 이름 없이 항목만 나온다.

visit_access:                           # 출입 절차가 있는 방문 (access.required == true)
  before:
    - 방문자 등록
  before_if_car:                        # 참석자 중 차로 오는 사람이 있을 때만
    - 차량번호 등록
  onsite:
    - 신분증
    - 출입증 수령

luggage:                                # constraints 에 luggage
  before:
    - 장비 반입 신고
  onsite:
    - 장비
    - 전원 어댑터

cook:                                   # constraints 에 cook. 구워 먹거나 해 먹는 자리
  before:
    - item: 고기·식재료
      assign: car                       # 부피가 크고 무겁다. 차가 있으면 그쪽이 낫다
    - item: 숯·버너
      assign: car
  onsite:
    - 식기·수저
    - 집게·가위
    - 쓰레기봉투

outdoor:                                # constraints 에 outdoor. 야외·캠핑·공원·한강
  before:
    - item: 돗자리
      assign: first                     # 먼저 도착하는 사람이 자리를 잡는다
  onsite:
    - 물
    - 물티슈
    - 쓰레기봉투

host_home:                              # constraints 에 host_home. 누구 집·집들이·홈파티
  before:
    - item: 먹을 것·마실 것
      assign: car
  onsite:
    - 슬리퍼

booking:                                # constraints 에 booking. 예약해 둔 자리
  before:
    - item: 예약자 이름·시간 확인
      assign: first                     # 먼저 도착하는 사람이 확인해야 자리가 유지된다

split:                                  # constraints 에 split. 회비·N빵
  before:
    - 정산 방법 정하기

not_applied_prefix: "[미완료] "         # access.applied 가 false 면 사전 신청 항목 앞에 붙인다
assign_car: "차로 오는 {name}"          # assign: car 일 때 항목 뒤에 괄호로 붙인다
assign_first: "먼저 도착하는 {name}"    # assign: first 일 때
---
# 준비물

준비물은 두 갈래다.

**들어가는 절차 때문에 필요한 것.** 출입 절차가 있는 곳은 당일 신분증만 들고 가서는 못 들어간다.
사전에 신청해야 하는 것과 당일 챙기는 것이 다르고, 늦으면 되돌릴 수 없는 쪽은 앞엣것이다.

**하려는 일 때문에 필요한 것.** 고기를 구우려면 고기와 불과 집게가 있어야 한다. 야외면 돗자리가
있어야 앉는다. 이건 절차와 무관하고, 일반 약속에서도 그대로 걸린다 (09-21 확장).

지도 앱은 장소만 찍어 주고 둘 다 하지 않는다.

## 조건과 목록

| 조건 | 꺼내는 키 |
|---|---|
| `access.required == true` | `visit_access` |
| `constraints` 에 `luggage` | `luggage` |
| `constraints` 에 `cook` | `cook` |
| `constraints` 에 `outdoor` | `outdoor` |
| `constraints` 에 `host_home` | `host_home` |
| `constraints` 에 `booking` | `booking` |
| `constraints` 에 `split` | `split` |
| 해당하는 것이 하나도 없음 | 체크리스트를 만들지 않는다 |

여러 조건이 겹치면 목록을 합치고 같은 항목은 한 번만 넣는다. 캠핑에서 고기를 구우면
`cook` 과 `outdoor` 가 같이 나오고, 쓰레기봉투는 한 줄만 남는다.

`before_if_car` 는 참석자 중 `transport == "car"` 인 사람이 있을 때만 `before` 에 더한다.
차로 가지 않으면 차량 등록이 필요 없다.

`access.applied` 가 false 면 `visit_access` 의 `before` 항목 앞에 `not_applied_prefix` 를 붙인다.
신청을 아직 안 했다는 뜻이고, 이 줄이 늦으면 당일 출입이 막힌다.

## 누가 맡나

단톡방에서 실제로 막히는 건 "뭘 챙기냐"가 아니라 "누가 사 오냐"다. 이미 계산해 둔 값으로
정할 수 있는 것만 정한다. 나머지는 사람이 정한다.

| assign | 누구 | 왜 |
|---|---|---|
| `car` | 차로 오는 사람. 여럿이면 출발이 가장 이른 사람 | 부피가 크고 무거운 것은 차가 낫다. 오는 길에 들른다 |
| `first` | 도착 기한이 같으므로 출발이 가장 이른 사람 | 자리를 잡거나 확인하는 일은 먼저 닿는 사람 몫이다 |

해당하는 사람이 없으면(아무도 차로 오지 않는 등) 이름 없이 항목만 낸다. 억지로 배정하지 않는다.

## 값이 쓰이는 곳

| 키 | 어디서 | 무엇을 |
|---|---|---|
| `visit_access` | 파이프라인 7-1단계 | 출입 절차가 있을 때의 준비물 |
| `luggage` `cook` `outdoor` `host_home` `booking` `split` | 같은 곳 | 하려는 일에 딸린 준비물 |
| `not_applied_prefix` | 같은 곳 | 미완료 표시 |
| `assign_car` `assign_first` | 같은 곳 | 분담 표기 |

관련: docs/SDD.md 3절 constraints, 4절 Checklist, 5절 7-1단계, 7절
