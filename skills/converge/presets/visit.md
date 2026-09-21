---
# 출입 절차가 있는 방문. 들어가는 데 시간이 걸리고, 미리 해둘 것이 있다.
# 코드가 읽는 값은 rules/ 에 있고, 이 파일은 프리셋마다 달라지는 것만 적는다.
preset: visit
access_required_default: true           # 절차가 있다고 보는 것이 기본
entry_lead_min_applies: true            # 약속 시각 앞에 access.md 의 entry_lead_min 을 빼 둔다
buffer_key: buffer_visit_min            # 절차 소요를 따로 빼므로 여유는 조금 줄인다
candidate_kinds:                        # 집결 후보로 찾을 자리 (SDD 4절 CandidateKind)
  - gate
  - lobby
  - hq
checklist_key: visit_access             # rules/checklist.md 에서 꺼낼 준비물 목록
---
# 출입 절차가 있는 방문

방문자 등록을 확인하고 출입증을 받고 안내를 기다린다. 그 시간이 약속 시각 앞에 따로 붙는다.

## 이 프리셋에서 달라지는 것

| | 값 | 왜 |
|---|---|---|
| 도착 기한 | 약속 시각 − `entry_lead_min` | 맞춰야 하는 건 약속 시각이 아니라 절차 시작 시각이다 |
| 여유 | `buffer_visit_min` | 절차 소요를 이미 뺐으므로 여유를 조금 줄인다 |
| 후보 | 절차 시작점 우선 | 정문·1층 로비·본사. 역에서 만나 같이 가도 절차는 거기서 시작된다 |
| 준비물 | `visit_access` | 사전 신청과 당일 지참을 나눠 보여 준다 |

## 판단할 때 보는 것

- 합류 지점은 역이 아니라 절차가 시작되는 자리다 (`rendezvous_is_procedure_start`).
  역 집결은 그 앞 단계일 뿐이라 역산 기준이 되지 못한다
- 참석자 사이 도착이 `switch_if_delay_min` 이상 벌어지면 절차 안에서 기다리게 하지 않고
  밖 랜드마크로 전환한다. 먼저 온 사람이 혼자 서 있게 되는 쪽이 더 나쁘다
- 신청 여부(`access.applied`)를 모르면 되묻는다. 안 했는데 했다고 적으면 당일 출입이 막혀도
  화면이 아무 경고를 안 한다
- 차로 오는 사람이 있으면 차량번호 등록이 준비물에 더 붙는다 (`before_if_car`)
- 장비를 들고 가면 반입 신고가 따로 걸린다. 절차 유무와 별개다 (`constraints` 의 `luggage`)

## 이 프리셋이 아닌 경우

문장이 카페·식당처럼 아무나 들어가는 자리를 가리키면 `meeting` 이다.
사무실이라는 말만 보고 절차가 있다고 단정하지 않는다. 없는 시간을 매번 빼게 된다.

관련: docs/SDD.md 7절, rules/access.md, rules/checklist.md
