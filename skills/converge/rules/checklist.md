---
# 준비물 목록. 코드(backend/app/domain/checklist.py)가 이 프론트매터를 읽는다.
# LLM 이 항목을 지어내지 않는다. 조건을 보고 여기서 꺼내기만 한다 (SDD 7절 원칙).
#
# before: 사전 신청. 늦으면 출입 자체가 안 된다
# onsite: 당일 지참. 당일 챙기면 된다
visit_access:                           # 출입 절차가 있는 방문
  before:
    - 방문자 등록
  before_if_car:                        # 참석자 중 차로 오는 사람이 있을 때만
    - 차량번호 등록
  onsite:
    - 신분증
    - 출입증 수령
luggage:                                # constraints 에 luggage 가 있을 때 더한다
  before:
    - 장비 반입 신고
  onsite:
    - 장비
    - 전원 어댑터
not_applied_prefix: "[미완료] "         # access.applied 가 false 면 사전 신청 항목 앞에 붙인다
---
# 준비물

출입 절차가 있는 곳은 당일 신분증만 들고 가서는 못 들어간다. 사전에 신청해야 하는 것과 당일 챙기는 것이
다르고, 늦으면 되돌릴 수 없는 쪽은 앞엣것이다. 지도 앱은 장소만 찍어 주고 이 구분을 하지 않는다.

## 조건과 목록

| 조건 | 꺼내는 키 |
|---|---|
| `access.required == true` | `visit_access` |
| `constraints` 에 `luggage` 포함 | `luggage` (위 목록에 더한다) |
| `access.required == false` | 목록 없음 |
| `access.required == null` | 체크리스트 자체를 만들지 않는다 (아직 모른다) |

`before_if_car` 는 참석자 중 `transport == "car"` 인 사람이 있을 때만 `before` 에 더한다.
차로 가지 않으면 차량 등록이 필요 없다.

`access.applied` 가 false 면 `before` 의 모든 항목 앞에 `not_applied_prefix` 를 붙인다.
신청을 아직 안 했다는 뜻이고, 이 줄이 늦으면 당일 출입이 막힌다.

## 값이 쓰이는 곳

| 키 | 어디서 | 무엇을 |
|---|---|---|
| `visit_access` | 파이프라인 7-1단계 | 출입 절차가 있을 때의 준비물 |
| `luggage` | 같은 곳 | 장비가 있을 때 더하는 항목 |
| `not_applied_prefix` | 같은 곳 | 미완료 표시 |

관련: docs/SDD.md 4절 Checklist, 5절 7-1단계, 7절
