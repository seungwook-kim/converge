---
# 출입 절차 규칙값. 코드(backend/app/domain/rules.py)가 이 프론트매터를 읽는다.
# 값을 바꾸려면 여기만 고친다. 코드에 숫자를 적지 않는다 (SDD 7절 원칙).
entry_lead_min: 15                      # 출입 절차 소요(분). 방문자 확인·출입증 수령·안내를 받는 시간
rendezvous_is_procedure_start: true     # 합류 지점은 역이 아니라 절차가 시작되는 곳
switch_if_delay_min: 30                 # 도착이 이만큼 어긋나면 절차를 포기하고 밖에서 만난다
outside_landmark_kinds:                 # 절차 밖에서 만날 때 쓰는 자리
  - 역
  - 정문 앞
  - 주차장 입구
no_procedure_all_transit_no_rendezvous: true  # 절차가 없고 전원 대중교통이면 합류 자체가 불필요
---
# 출입 절차

들어가는 데 시간이 걸리는 곳이 있다. 방문자 등록을 확인하고 출입증을 받고 안내를 기다리는 시간이다.
그래서 역산 기준은 약속 시각이 아니라 그 절차가 시작되는 자리에 도착해야 하는 시각이다.

## 값이 쓰이는 곳

| 키 | 어디서 | 무엇을 |
|---|---|---|
| `entry_lead_min` | 파이프라인 5·7단계 | 약속 시각 앞에 빼 두는 절차 소요. 절차가 없으면 0 으로 본다 |
| `rendezvous_is_procedure_start` | 3단계 후보 생성 | 후보 1순위를 역이 아니라 정문·로비로 잡는다 |
| `switch_if_delay_min` | 5단계 | 도착 어긋남이 이 값을 넘으면 밖 랜드마크로 전환 판정 |
| `outside_landmark_kinds` | 3단계 | 전환했을 때 찾을 자리의 종류 |
| `no_procedure_all_transit_no_rendezvous` | 5단계 | 합류 지점을 만들지 말지 |

## 왜 절차 시작점인가

역에서 만나 같이 들어가려 해도 출입 절차는 정문이나 1층에서 시작된다. 역 집결은 그 앞 단계일 뿐이라
계산 기준이 되지 못한다. 절차가 시작되는 자리를 기준으로 역산해야 늦지 않는다.

관련: docs/SDD.md 7절, 5절 5·7단계
