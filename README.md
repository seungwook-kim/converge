# Converge (컨버지)

**"어디서 몇 시에 만날까"를 문장 하나로 끝내는 약속 에이전트**

여럿이 만날 때 사람이 머리로 하던 계산을 대신한다. 각자 어디서 출발하는지, 무엇을 타는지, 도착해서
무슨 절차를 거쳐야 하는지를 넣으면 집결 장소와 시각, 그리고 **각자 몇 시에 나서야 하는지**를 지도 위에 내놓는다.

개인 사이드 프로젝트 · [github.com/seungwook-kim/converge](https://github.com/seungwook-kim/converge)

| | |
|---|---|
| 서비스 | (배포 전) |
| Agent API | `GET /health` · `POST /api/agent` |
| 설계 | [docs/SDD.md](./docs/SDD.md) · [docs/테이블정의서.md](./docs/테이블정의서.md) |
| 구조 지도 | [CONVERGE.md](./CONVERGE.md) |

---

## 1. 어떤 도구인가

### 문제

약속을 잡을 때 정작 어려운 건 장소가 아니라 시각이다. 지도 앱은 "여기서 저기까지 45분"까지만 알려 준다.
그런데 실제로 필요한 답은 이것이다.

> 나는 몇 시에 나가야 하나.

여기에는 이동 시간 말고도 들어가는 게 있다. 건물에 들어가는 데 걸리는 시간, 방문자 등록 같은 사전 절차,
차 막히는 시간대, 누구를 태우고 가는지, 막차가 몇 시인지. 사람들은 이걸 카톡으로 주고받으며 30분씩 쓴다.

### 해결

상황을 문장으로 넣으면 절차와 경로를 함께 계산해 답을 만든다.

```
입력   "저녁 10시 강남 사무실에서 작업. 나는 송파구, 김대리는 강서구, 둘 다 지하철.
        1층에서 출입증 받고 올라가야 함. 김대리가 강남역에서 먼저 만나자는데?"

출력   합류는 강남역이 아니라 출입증을 받는 1층이 낫습니다.
        김대리  21:05 출발 · 지하철 45분 · 1층 도착 21:50
        나      21:15 출발 · 지하철 35분 · 1층 도착 21:50
        22:00 시작, 출입 절차 10분 전 도착 기준. 작업 후 첫차 05:30
        준비물: 신분증, 방문자 등록(미완료)
        → 지도에 집결지 핀과 두 사람 경로선
```

### 다른 서비스와 다른 점

중간 지점을 찾아주는 서비스는 이미 여럿 있다. Converge는 그 뒤를 본다.

- **출발 시각을 역산한다.** 도착 기한에서 절차 소요, 이동 시간, 여유를 거꾸로 뺀다
- **안 고른 후보와 이유를 같이 보여준다.** "출입 절차가 1층에서 시작되므로 역에서 합류할 이유가 없다"
- **준비물을 사전 신청과 당일 지참으로 나눈다.** 늦으면 되돌릴 수 없는 쪽을 앞에 둔다
- **모르면 되묻는다.** 값을 지어내지 않고 빈칸을 남긴 뒤 질문한다
- **붙여넣을 계획서를 만든다.** 결과를 대화방에 그대로 옮길 수 있다

### 설계 원칙

- **LLM은 입구와 출구에만 둔다.** 문장에서 슬롯을 뽑는 자리(소형 모델)와 집결지 순위·근거를 내는 자리(대형 모델, 필요할 때만). 소요시간·출발 시각·절차 소요는 전부 코드가 계산한다
- **파이프라인은 순차 실행이고 루프가 없다.** 단계마다 Langfuse span을 남기고, 모든 외부 호출에 실패 경로가 있다
- **지식은 RAG가 아니라 문서로 넣는다.** 규칙값의 원본은 `skills/converge/rules/` 이고 코드는 읽기만 한다
- **개인정보는 평문으로 저장하지 않는다.** 이름·출발지·좌표·경로는 암호화해 넣는다

### 처리 흐름

```
브라우저 (지도 + 채팅)
  │  문장 또는 대화 캡처
  ▼
frontend/  Next.js · app/api/agent 프록시 (키는 여기서 멈춘다)
  ▼
backend/   FastAPI · POST /api/agent
  │  services/pipeline.py
  │    0 vision      캡처에서 텍스트            [LLM]
  │    1 extract     텍스트에서 슬롯            [소형 LLM]
  │    2 geocode     지명에서 좌표
  │    3 candidates  집결 후보 찾기
  │    4 routes      참석자 × 후보 소요시간
  │    5 rules       절차 소요·전환 조건         [계산]
  │    6 judge       순위와 이유                [대형 LLM, 필요 시]
  │    7 departure   출발 시각 역산             [계산]
  │    7-1 checklist 준비물·집결 계획서          [계산]
  │    8 store       암호화 저장
  │  2·3·4단계는 같은 프로세스의 /mcp 도구를 쓴다
  ▼
AgentResponse (need_confirm | need_info | done | out_of_scope | failed)
  ▼
지도에 핀·경로선·표
```

단계별 입출력과 실패 처리는 [docs/SDD.md](./docs/SDD.md) 5절에 있다.

---

## 2. 디렉토리 구조

```
.
├── README.md             소개와 실행법 (이 파일)
├── CONVERGE.md           구조 지도. 폴더별 책임
├── CLAUDE.md · AGENTS.md AI 코딩 도구 작업 지침
├── Dockerfile            루트 빌드 (skills/, mcp_server/ 포함)
├── docker-compose.yml    api + db(postgres:16)
├── .env.example          필요한 키 목록 (값 없음)
│
├── backend/              FastAPI
│   ├── app/
│   │   ├── main.py       앱 생성, 라우터 등록, /mcp 마운트
│   │   ├── routers/      /api/agent, /health, /api/session
│   │   ├── schemas/      요청·슬롯·결과 스키마 (출력 계약 원본)
│   │   ├── services/     외부와 통신 (LLM, 지도·경로 API, DB)
│   │   ├── domain/       계산만 (규칙 적용, 출발 시각 역산, 준비물, 모델 라우팅)
│   │   ├── observability/ Langfuse 트레이스
│   │   ├── models/       소형 모델(GGUF) 자리, 빌드 시 채워짐
│   │   └── data/         역 코드표 같은 고정 데이터
│   ├── db/               테이블 생성 SQL
│   └── tests/            API 키 없이 도는 테스트
│
├── mcp_server/           FastMCP. 지도·경로·시각표를 MCP 도구로 제공
├── frontend/             Next.js. 지도·채팅, 공유 링크
├── skills/converge/      규칙 문서 (rules/)
├── evals/                평가셋과 실행 스크립트
├── finetune/             슬롯 추출용 소형 모델 학습 (배포 이미지에 없음)
├── scripts/              타입 생성 등 수동 실행 스크립트
└── docs/                 SDD, 테이블정의서, 측정 기록
```

폴더별 책임과 먼저 읽을 가이드(`*_GUIDE.md`)는 [CONVERGE.md](./CONVERGE.md)에 있다.

---

## 3. 실행

```bash
git clone https://github.com/seungwook-kim/converge.git && cd converge
cp .env.example .env     # 키 채우기
docker compose up        # backend :8000 (/api/agent, /health, /mcp) + db

cd frontend && npm install && npm run dev   # :3000
```

필요한 키는 `.env.example` 참고. Kakao Local·Kakao Mobility·TMAP·공공데이터(첫차막차)·OpenRouter·Langfuse·Supabase.

로컬은 `AUTH_REQUIRED=false` 로 인증 없이 돈다.

백엔드 없이 화면만 보려면 `frontend/.env.local` 에 `NEXT_PUBLIC_KAKAO_JS_KEY` 만 넣고 `npm run dev` 하면 된다.
`NEXT_PUBLIC_API_BASE` 가 없으면 `frontend/lib/mock.ts` 의 고정 응답으로 지도·경로선·결과 표가 그려진다.

### 테스트

```bash
pytest backend/tests     # API 키 없이 실행
```

### 기술 스택

| 영역 | 사용 |
|---|---|
| Backend | FastAPI, Docker |
| Frontend | Next.js, Kakao Map SDK |
| LLM | OpenRouter (대형), 파인튜닝 소형 모델 (GGUF, llama.cpp) |
| 도구 | FastMCP, Kakao Local/Mobility, TMAP, 서울·부산 지하철 공공데이터 |
| 데이터 | PostgreSQL (Supabase), Supabase Auth |
| 관측 | Langfuse (트레이스, Prompt) |

---

## 4. 소형 모델

슬롯 추출은 파인튜닝한 소형 모델이 먼저 맡고, 실패하거나 결과가 미심쩍으면 대형 모델로 넘긴다.
측정 기록은 [docs/compare.md](./docs/compare.md) 에 있다.

| 항목 | 값 |
|---|---|
| 모델 | Kanana-1.5-2.1B-Instruct + QLoRA, Q4_K_M GGUF |
| 학습 데이터 | 911건 |
| 검증 정확도 | exact match 85.5% (62건, fp16 기준) |
| 대형 모델 승격률 | 4건 중 1건 |
| 요청당 비용 | 대형 단독 대비 80% 절감 |

---

## 5. 시크릿

- 키는 `.env` 에만 둔다. `.env` 는 `.gitignore` 에 있다
- 코드에 키를 적지 않는다
- 대화 캡처 원본을 커밋하지 않는다
- 필요한 키 목록은 `.env.example` 에 값 없이 둔다
