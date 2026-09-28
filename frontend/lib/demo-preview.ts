// 첫 화면에서 로그인 전에 보여 주는 예시 결과 (SDD 2절 09-21 예외).
//
// lib/mock.ts 를 쓰지 않는 이유: 그쪽은 mock-data.json(150KB, 실제 경로 좌표)을 끼고 있어
// 첫 화면 번들에 싣기 무겁고, 서버에서만 import 한다는 전제로 쓰여 있다.
//
// 아래 값은 지어낸 것이 아니라 2026-09-28 에 파이프라인을 실제로 태워 나온 출력을 옮긴 것이다.
// 첫 화면의 지도 캡처(public/demo-map.webp)도 같은 실행에서 찍었다. 표와 지도가 같은 결과여야 한다.
// 경로선 좌표는 표에 쓰지 않아 뺐다 (번들 크기). 예시와 실물이 갈라지면
// 첫인상이 거짓말이 되므로, 결과 화면과 같은 ResultTable 로 그린다.

import type { Participant, Result } from "@/types/agent";

export const DEMO_SENTENCE =
  "토요일 12시 한강공원에서 친구들이랑 고기 구워 먹기로 했어. 나는 수원시청에서 지하철, 민수는 인천시청에서 차로, 지호는 의정부시청에서 지하철로 와. 돈은 나중에 N빵하자.";

export const DEMO_PARTICIPANTS: Participant[] = [
  {
    name: "나",
    origin: "수원시청",
    transport: "transit",
    pickup: null,
    pickup_at: null,
    unfamiliar: false,
    role: "site",
    owner_user_id: null,
  },
  {
    name: "민수",
    origin: "인천시청",
    transport: "car",
    pickup: null,
    pickup_at: null,
    unfamiliar: false,
    role: "colleague",
    owner_user_id: null,
  },
  {
    name: "지호",
    origin: "의정부시청",
    transport: "transit",
    pickup: null,
    pickup_at: null,
    unfamiliar: false,
    role: "colleague",
    owner_user_id: null,
  },
];

export const DEMO_RESULT: Result = {
  candidates: [
    {
      name: "여의나루역 5호선",
      kind: "landmark",
      address: "서울 영등포구 여의동로 지하 343",
      lng: 126.933,
      lat: 37.5271,
      rank: 1,
      access_ok: true,
      switched_from: null,
      reason: "대중교통 이용자가 많은 상황에서 찾기 쉽고 접근성이 좋은 역을 집결지로 정하는 것이 모두에게 가장 효율적입니다.",
      rejected_reason: null
    },
    {
      name: "한강공원",
      kind: "landmark",
      address: "주소 미상",
      lng: 126.9351,
      lat: 37.5264,
      rank: 2,
      access_ok: true,
      switched_from: null,
      reason: "한강공원은 넓은 구역이라 정확한 집결 지점을 특정하기 어렵고, 대중교통 이용자의 이동 시간이 역보다 더 길어집니다.",
      rejected_reason: "넓은 공원 내부보다는 찾기 쉬운 역에서 모이는 것이 일행 모두에게 더 편리합니다."
    }
  ],
  provisional: false,
  per_participant: [
    {
      name: "나",
      candidate_rank: 1,
      transport: "transit",
      duration_min: 95,
      raw_duration_min: 65,
      buffer_min: 30,
      departure_time: "10:24",
      arrive_by: "12:00",
      transfer_count: 2,
      first_train: null,
      last_train: null,
      train_note: null,
      polyline: [],
      via_rendezvous: false,
      via_pickup: false
    },
    {
      name: "민수",
      candidate_rank: 1,
      transport: "car",
      duration_min: 85,
      raw_duration_min: 55,
      buffer_min: 30,
      departure_time: "10:35",
      arrive_by: "12:00",
      transfer_count: null,
      first_train: null,
      last_train: null,
      train_note: null,
      polyline: [],
      via_rendezvous: false,
      via_pickup: false
    },
    {
      name: "지호",
      candidate_rank: 1,
      transport: "transit",
      duration_min: 117,
      raw_duration_min: 87,
      buffer_min: 30,
      departure_time: "10:03",
      arrive_by: "12:00",
      transfer_count: 2,
      first_train: null,
      last_train: null,
      train_note: null,
      polyline: [],
      via_rendezvous: false,
      via_pickup: false
    },
    {
      name: "나",
      candidate_rank: 2,
      transport: "transit",
      duration_min: 99,
      raw_duration_min: 69,
      buffer_min: 30,
      departure_time: "10:20",
      arrive_by: "12:00",
      transfer_count: 2,
      first_train: null,
      last_train: null,
      train_note: null,
      polyline: [],
      via_rendezvous: false,
      via_pickup: false
    },
    {
      name: "민수",
      candidate_rank: 2,
      transport: "car",
      duration_min: 84,
      raw_duration_min: 54,
      buffer_min: 30,
      departure_time: "10:35",
      arrive_by: "12:00",
      transfer_count: null,
      first_train: null,
      last_train: null,
      train_note: null,
      polyline: [],
      via_rendezvous: false,
      via_pickup: false
    },
    {
      name: "지호",
      candidate_rank: 2,
      transport: "transit",
      duration_min: 119,
      raw_duration_min: 89,
      buffer_min: 30,
      departure_time: "10:00",
      arrive_by: "12:00",
      transfer_count: 2,
      first_train: null,
      last_train: null,
      train_note: null,
      polyline: [],
      via_rendezvous: false,
      via_pickup: false
    }
  ],
  rendezvous_departure: null,
  rendezvous_legs: [],
  confidence: 0.8,
  checklist: {
    before: [
      "고기·식재료 (차로 오는 민수)",
      "숯·버너 (차로 오는 민수)",
      "돗자리 (먼저 출발하는 지호)",
      "정산 방법 정하기"
    ],
    onsite: [
      "식기·수저",
      "집게·가위",
      "쓰레기봉투",
      "물",
      "물티슈"
    ]
  },
  model_small: "예시",
  model_large: null,
  prompt_version: "예시",
  routed_to: "small",
  summary_text: [
    "2026-10-03 12:00 한강공원",
    "집결: 여의나루역 5호선 12:00",
    "",
    "출발 시각",
    "",
    "나 (수원시청, 대중교통) 10:24",
    "민수 (인천시청, 차) 10:35",
    "지호 (의정부시청, 대중교통) 10:03",
    "",
    "미리 해둘 것",
    "",
    "고기·식재료 (차로 오는 민수)",
    "숯·버너 (차로 오는 민수)",
    "돗자리 (먼저 출발하는 지호)",
    "정산 방법 정하기",
    "",
    "당일 챙길 것",
    "",
    "식기·수저, 집게·가위, 쓰레기봉투, 물, 물티슈",
  ].join("\n"),
};
