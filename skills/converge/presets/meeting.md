---
# 일반 약속. 들어가는 데 절차가 없는 자리에서 만난다.
# 코드가 읽는 값은 rules/ 에 있고, 이 파일은 프리셋마다 달라지는 것만 적는다.
preset: meeting
access_required_default: false          # 절차가 없다고 보는 것이 기본. 단서가 있으면 슬롯이 true 로 바꾼다
entry_lead_min_applies: false           # 절차 소요를 빼지 않는다. 약속 시각이 곧 도착 기한이다
buffer_key: buffer_meeting_min          # 여유는 transport.md 의 이 값을 쓴다
candidate_kinds:                        # 집결 후보로 찾을 자리 (SDD 4절 CandidateKind)
  - landmark
  - lobby
checklist_key: null                     # 준비물 목록 없음
---
# 일반 약속

카페에서 보자, 식당 앞에서 보자, 역에서 만나 같이 가자. 들어가는 데 허락이 필요 없는 자리다.

## 이 프리셋에서 달라지는 것

| | 값 | 왜 |
|---|---|---|
| 도착 기한 | 약속 시각 그대로 | 뺄 절차가 없다. 빼 두면 괜히 일찍 나가게 된다 |
| 여유 | `buffer_meeting_min` | 약속 지각은 신뢰 문제라 조금 넉넉히 본다 |
| 후보 | 랜드마크 우선 | 지리를 몰라도 찾는 자리가 먼저다 (`outside_landmark_kinds`) |
| 준비물 | 없음 | 신분증을 챙기라고 알릴 이유가 없다 |

## 판단할 때 보는 것

- 합류 지점을 굳이 만들지 않는다. 전원이 대중교통이면 각자 목적지로 가는 편이 빠르다
  (`no_procedure_all_transit_no_rendezvous`)
- 차로 오는 사람이 누군가를 태우고 가면 그 지점을 경유지로 넣는다. 태워지는 사람의 소요시간은
  탑승 이후 구간만 센다 (`pickup_counts_from_board`)
- 늦게 끝나는 약속이면 막차를 본다. 막차를 넘기면 대중교통 경로 자체가 성립하지 않는다

## 이 프리셋이 아닌 경우

문장에 출입증, 방문자 등록, 안내 데스크, 출입 절차 같은 말이 있으면 `visit` 이다.
단서가 아예 없으면 둘 중 하나로 단정하지 않고 되묻는다 (SDD 5절 1-2).

관련: docs/SDD.md 7절, rules/access.md, rules/transport.md
