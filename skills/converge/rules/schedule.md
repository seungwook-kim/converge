---
# 시각과 일정 규칙값. 코드(backend/app/domain/rules.py)가 이 프론트매터를 읽는다.
# 값을 바꾸려면 여기만 고친다. 코드에 숫자를 적지 않는다 (SDD 7절 원칙).
unconfirmed_is_provisional: true        # 약속 시각이 확정이 아니면 결과에 잠정 표시를 단다
bare_hour_afternoon_max: 6              # 오전·새벽 같은 말 없이 "1시"~"6시"만 쓰면 오후로 읽는다 ("1시 도착" = 13시, 09-27)
night_start: "22:00"                    # 이 시각 이후를 야간으로 본다
night_end: "06:00"                      # 이 시각까지가 야간이다
night_check_last_train: true            # 야간에 끝나면 막차를, 넘겼으면 첫차를 같이 알려 준다
train_lookup_lines:                     # 첫차·막차를 조회할 수 있는 노선. TMAP 구간 이름의 앞말과 최대 호선 (SDD 11절)
  수도권: 9
  부산: 4
late_arrival_switch_min: 30             # 참석자 도착이 이만큼 벌어지면 집결 방식을 다시 본다 (access.md switch_if_delay_min 과 같은 값)
---
# 시각과 일정

약속 시각이 확정인지 아닌지, 그 시각이 야간인지가 계산을 가른다.

## 잠정 결과

시각이 아직 정해지지 않았는데 계산을 거절하면 쓸모가 없다. 그래서 잠정으로 계산해 보여 주고
화면에 그렇다고 적는다 (`Result.provisional`). 확정되면 다시 계산한다.

슬롯의 `schedule_confirmed` 가 기준이다.

| 값 | 뜻 | 결과 |
|---|---|---|
| `true` | 시각이 확정됐다 | 그대로 계산 |
| `false` | 아직 안 정해졌다고 말했다 | 계산하되 잠정 표시 |
| `null` | 언급이 없다 | 확정으로 보고 계산. 시각 자체가 없으면 되묻는다 |

## 야간

`night_start` 부터 `night_end` 사이에 끝나는 약속은 귀가가 문제다.

- 끝나는 시각이 막차를 넘기면 대중교통 경로는 성립하지 않는다. 그렇다고 말해야 한다
- 새벽에 끝나면 첫차 시각을 같이 알려 준다. 기다릴지 다른 수단을 쓸지는 사람이 정한다
- 출발이 자정을 넘겨 전날이 되는 경우가 생긴다. 시각만으로는 표현되지 않으므로 `day_offset` 으로 알린다

첫차·막차는 서울 1~9호선과 부산 1~4호선만 볼 수 있다. 그 밖의 노선은 모른다고 말한다.

## 도착이 벌어질 때

참석자들의 도착 시각이 `late_arrival_switch_min` 이상 벌어지면 먼저 온 사람이 오래 서 있게 된다.
출입 절차가 있는 방문이면 절차 안에서 기다리게 하지 말고 밖 랜드마크로 옮긴다 (access.md `switch_if_delay_min`).
절차가 없으면 앉아서 기다릴 자리를 1순위로 올린다.

## 값이 쓰이는 곳

| 키 | 어디서 | 무엇을 |
|---|---|---|
| `unconfirmed_is_provisional` | 7단계 | `Result.provisional` 을 켤지 |
| `night_start`·`night_end` | 7단계 | 야간으로 볼지 |
| `night_check_last_train` | 7단계 | 첫차·막차를 조회할지 |
| `train_lookup_lines` | 7단계 | 어느 노선의 첫차·막차를 조회할지. 그 밖은 조회하지 않는다 |
| `late_arrival_switch_min` | 5단계 | 집결 방식을 다시 볼지 |

관련: docs/SDD.md 7절, rules/access.md, rules/transport.md
