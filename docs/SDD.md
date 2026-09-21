# SDD · Converge 구현 명세

버전 3.0 · 2026.09.21 · 김승욱 · 범용 약속 에이전트: "어디서 몇 시에 만날까"를 문장 하나로 끝낸다

이 문서는 코드를 쓰는 사람과 Claude Code가 따르는 기준이다. 여기 없는 결정은 만들지 말고 물어본다. 스키마·엔드포인트·규칙값을 바꾸려면 이 문서를 먼저 고친다.

---

## 1. 폴더 구조

```
converge/
  CLAUDE.md                   AI 진입점. 언제 무엇을 열지
  CONVERGE.md                 구조 지도. 폴더별 책임과 SDD 절 안내
  AGENTS.md                   CLAUDE.md를 따른다 (Codex·Cursor용)
  README.md                   소개, 실행법, 배포 URL
  EVAL_REPORT.md              평가 기록. 개선 전후를 같은 셋으로 비교한 값만 적는다
  Dockerfile                  루트. 빌드 컨텍스트가 skills/, mcp_server/를 포함해야 하므로
                              빌드 시 HF에서 GGUF를 받아 이미지에 넣는다 (git, LFS 미사용).
                              받는 파일: kimseunguk/converge-slot-extractor 의 kanana_2.1b-Q4_K_M.gguf
                              (1.30 GiB, 검증 40건 Exact Match 85.0%. 공개 저장소라 토큰 없이 받는다)
  docker-compose.yml          api + db(postgres:16). backend/db/를 initdb에 마운트, db healthcheck 후 api 기동
  .env.example                backend용 (9절)
  docs/
    SDD.md  테이블정의서.md
    compare.md              소형 모델 비교 기록 (정확도·지연·비용)
    evidence/                 실행 기록
      langfuse/               대시보드·트레이스 화면
      mcp/                    연결 화면, tool 목록, 호출 결과
  backend/                    FastAPI (Cloud Run)
    BACKEND_GUIDE.md          이 폴더의 경계와 지킬 것
    app/
      main.py                 앱 생성, 라우터 등록, 미들웨어(request_id), /mcp 마운트
      routers/
        agent.py              POST /api/agent
        health.py             GET /health
        session.py            GET /api/sessions      (내 계획 목록, 로그인 필수)
                              GET /api/session/{id}  (공유 링크용 읽기, 로그인 필수)
                              DELETE /api/session/{id}  (주선자 본인만, 즉시 삭제)
                              PATCH /api/session/{id}/participants  (핀 claim·위치 수정. 2절, 7절 핀 소유권)
        internal.py           POST /internal/cleanup (Cloud Scheduler 전용, 토큰)
      schemas/
        slots.py              슬롯 추출 결과 (LLM 출력 계약 1)
        result.py             최종 결과 (LLM 출력 계약 2, API 응답)
        request.py            API 요청
      services/               바깥과 통신하는 것만 둔다
        llm.py                모든 LLM 호출은 여기만. OpenRouter + 로컬 GGUF
        vision.py             캡처 → 텍스트
        geo.py                지오코딩·장소 검색 (MCP 클라이언트 경유)
        routes.py             경로·소요시간 (MCP 클라이언트 경유), 캐시
        judge.py              후보 판정 프롬프트 조립, 대형 모델 호출
        transit_schedule.py   첫차·막차 (서울 열린데이터광장, 부산교통공사. 부산 역코드는 data/)
        pipeline.py           단계 오케스트레이션 (루프 없음, 순차)
        store.py              Postgres 접근(asyncpg, DATABASE_URL), 암호화, expires_at 계산
        auth.py               Supabase 공개키(JWKS)로 JWT 검증 → user_id. 로그인 필수 엔드포인트의 의존성
      domain/                 계산만. 네트워크·LLM 호출 없음. API 키 없이 테스트된다
        CLAUDE.md             난간. 이 폴더 파일을 열면 자동 로드
        rules.py              Skill 규칙 로드, 계산식 (절차 소요·여유·역산·전환 조건)
        checklist.py          준비물 조립(checklist.md에서 꺼냄), 집결 계획서 텍스트 조립
        router.py             소형/대형 선택 규칙
      observability/
        langfuse.py           트레이스·span·프롬프트 조회
      models/                 kanana_2.1b-Q4_K_M.gguf 자리. 빌드 시 채워짐. git에 없음
      data/                   busan_stations.csv (역외부코드 108개. 역 목록 API가 폐기돼 레포에 둔다)
    db/
      001_init.sql          테이블정의서.md의 표 5개. 로컬(compose initdb)과 Supabase(SQL Editor)에 같은 파일을 실행
    tests/
      TEST_GUIDE.md
      fixtures/               spike 샘플 응답 (실제 API 응답 원문)
    requirements.txt
  mcp_server/                 FastMCP. backend/app/main.py에 ASGI로 마운트해 같은 프로세스에서 /mcp 제공
    MCP_GUIDE.md
    server.py                 FastMCP 인스턴스, Bearer 토큰
    tools/
      geocode.py  search_places.py  route_car.py  route_transit.py  first_last_train.py  departure_calc.py
  frontend/                   Next.js (Vercel)
    FRONTEND_GUIDE.md
    .env.example              frontend용 (9절). 브라우저에 노출되는 값만
    package.json  tsconfig.json       Next 16, React 19, TypeScript. 지도 외 UI 라이브러리 없음
    next.config.ts            agentRules: false (next dev 가 이 폴더에 AGENTS.md·CLAUDE.md 를 만들지 않게)
    app/
      layout.tsx              html/body, 전역 CSS 로드
      globals.css             전역 스타일. 핀 커서 규칙(핀 소유권)도 여기
      page.tsx                메인. 로그인·소개·문장 입력만. 지도 없음. 만들면 /s/{id} 로 보낸다
      about/page.tsx          소개 페이지 (서비스 화면과 별도)
      my/page.tsx             내 계획 목록. GET /api/sessions, 줄마다 삭제
      s/[id]/page.tsx         참석자들이 모이는 자리. 지도·되묻기·핀 확인·결과·claim·수정이 전부 여기서.
                              링크는 이 주소 그대로(별도 토큰·단축 없음), 로그인 필요
      api/agent/route.ts      Cloud Run 프록시 (키 숨김)
      api/session/[id]/route.ts               GET 프록시 (공유 링크)
      api/session/[id]/participants/route.ts  PATCH 프록시 (핀 claim·위치 수정)
    components/
      MapView.tsx  ChatPanel.tsx  ParticipantPins.tsx  RouteLines.tsx  ResultTable.tsx  AuthGate.tsx  Progress.tsx
    lib/
      kakao.ts                지도 SDK 로더
      auth.ts                 구글 로그인(Supabase Auth), 토큰 헤더
      proxy.ts                app/api/ 라우트 공용 백엔드 전달
      dev-user.ts             로컬 모드 사용자 id
      mock.ts                 NEXT_PUBLIC_API_BASE 가 없을 때 프록시가 돌려주는 고정 응답
      mock-data.json          mock 시나리오와 실제 경로 좌표
      api-types.ts            backend/app/schemas/에서 생성. 손으로 고치지 않는다
    types/
      agent.ts                2·3·4절 타입을 손으로 옮긴 것. api-types.ts 가 생기면 대체한다
  skills/converge/
    SKILL.md
    rules/  access.md  session.md  transport.md  checklist.md
    presets/  meeting.md  visit.md
    failures.md
    output-contract.md
  evals/
    EVAL_GUIDE.md
    dataset.jsonl             30건
    run_eval.py               Langfuse Dataset 실행·score 기록
  finetune/                   학습 파이프라인
    FINETUNE_GUIDE.md
    data/                     finetune_dataset.jsonl
    gen_dataset.py
  scripts/
    gen_types.sh              schemas/ → frontend/lib/api-types.ts. CI가 어긋남을 검사
    fetch_mock_routes.py      프론트 mock 경로를 카카오모빌리티·TMAP 에서 한 번 받아 저장
    fetch_busan_stations.py   부산 역외부코드 표를 한 번 만들어 backend/app/data/ 에 저장
    mcp_check.py              /mcp 에 MCP 클라이언트로 붙어 도구 목록·호출 결과를 찍는다 (컨테이너 안에서 실행)
```

---

## 2. 엔드포인트

서비스 전체가 구글 로그인 뒤에 있다. 공유 링크로 결과를 보는 사람도 로그인해야 하고, 익명 열람 경로는 없다.

| 엔드포인트 | 인증 |
|---|---|
| POST /api/agent | 로그인 필수 |
| GET /api/sessions | 로그인 필수. 내가 만든 계획 목록 |
| GET /api/session/{id} | 로그인 필수. 링크만으로는 열람 불가 |
| DELETE /api/session/{id} | 로그인 필수 |
| PATCH /api/session/{id}/participants | 로그인 필수 |
| GET /health | 인증 없음 |
| /mcp | Bearer 토큰 (MCP_TOKEN, 로그인과 별개) |

로그인 필수 엔드포인트는 토큰이 없거나 검증에 실패하면 401. AUTH_REQUIRED=false(9절, 로컬 개발용)일 때만 검증을 건너뛴다.

### POST /api/agent

**로그인 필수.** 헤더 `Authorization: Bearer {Supabase access token}`. services/auth.py가 Supabase 공개키(ES256, jwks.json)로 서명을 검증해 user_id를 꺼낸다. 비밀값을 우리 쪽에 두지 않는다. 없거나 틀리면 401. LLM을 호출하지 않는다 (비용 방어).

요청 (backend/app/schemas/request.py)

```python
class AgentRequest(BaseModel):
    session_id: str | None          # 재질문이면 기존 세션
    text: str | None                # 문장 입력
    image_base64: str | None        # 카톡 캡처 (jpeg/png)
    preset: Literal["meeting", "visit"] | None   # 사용자가 고른 경우
    confirmed_participants: list[ParticipantInput] | None  # 핀 확인 단계에서 수정한 좌표
```

user_id는 본문이 아니라 토큰에서 나온다. Langfuse user_id도 같은 값.

text와 image_base64 중 하나는 필수. confirmed_participants가 오면 슬롯 추출을 건너뛰고 계산부터 시작한다.

응답 (backend/app/schemas/result.py)

```python
class AgentResponse(BaseModel):
    session_id: str
    stage: Literal["need_confirm", "need_info", "done", "out_of_scope", "failed"]
    slots: Slots | None             # 추출·확정된 슬롯. 추출 전에 끊기면 None (failed, need_info 만)
    result: Result | None           # stage == done 일 때
    questions: list[str]            # need_info 일 때 되물을 것
    message: str                    # 화면에 보여줄 한 줄
    trace_id: str
    geocoded: list[GeocodedPin] | None   # need_confirm, done 일 때 지도에 찍을 좌표

class GeocodedPin(BaseModel):
    name: str
    lng: float
    lat: float
    confidence: float
    kind: Literal["participant", "rendezvous", "destination", "pickup"]

class ParticipantInput(BaseModel):   # PATCH 요청에서 claim 만 뺀 모양
    name: str
    lng: float
    lat: float
```

좌표는 Slots 에 넣지 않는다 (슬롯 계약과 파인튜닝 데이터를 지키기 위해). 지오코딩 결과는 geocoded 로만 나간다. need_confirm 과 done 양쪽에 담는다. done 에서도 집결 후보 외에 참석자 출발 핀을 찍어야 하기 때문이다.

화면은 둘로 나뉜다 (09-20 결정). 메인(/)은 로그인·소개·문장 입력만 하고 지도가 없다. 문장을 넣으면
세션이 만들어지고 /s/{id} 로 보낸다. 되묻기·핀 확인·결과·참석자 수정은 전부 /s/{id} 에서 한다.
그래서 need_info·need_confirm 단계에서도 세션을 draft 로 먼저 저장한다 (5절 8단계).

- need_confirm: 참석자 핀을 지도에 찍고 사용자 확인 대기 (확신도 < 0.8 또는 되묻기 없음)
- need_info: 필수 슬롯 누락 (출발지·이동수단·시각 중 하나). questions에 무엇을 물을지
- done: 후보와 참석자별 결과
- out_of_scope: 실시간 상황 등 범위 밖
- failed: 재시도 후에도 실패. result 없이 후보 핀만 있으면 result.candidates에 rank 없이 담는다. 지오코딩까지 갔으면 geocoded 도 함께 보낸다 (화면이 어디까지 됐는지 보여준다)

### GET /health

로그인 없음. `{"status":"ok","model_loaded":true,"version":"..."}`

### PATCH /api/session/{id}/participants

**로그인 필수.** 참석자가 자기 핀을 고르거나(claim) 위치를 고칠 때 쓴다.

요청: `{ "name": "민수", "lng": 128.98, "lat": 35.16, "claim": false }`
- `claim` 이 true 면 "내가 이 사람이다"를 등록하는 요청이다. owner_user_id 가 비어 있을 때만 성공한다
- `claim` 이 false 면 위치만 고친다. 로그인한 사람이면 누구나 할 수 있다 (7절 핀 소유권)

응답: 갱신된 Slots, 재계산이 끝났으면 새 Result, 그리고 핀별 수정 기록(edits)

```python
class ParticipantEdit(BaseModel):
    name: str                 # 참석자 이름
    edited_by: str | None     # 마지막으로 위치를 고친 사람의 user_id
    edited_at: str | None     # 그 시각 (ISO 8601)
    by_owner: bool            # 그 사람이 이 핀의 주인인가
```

AgentResponse 에도 같은 edits 가 선택적으로 실린다. 공유 링크 화면이 "누가 고쳤는지"를 보여 주기 위해서다.

실패: 이미 소유자가 있는 핀에 claim 하면 409, 잠긴 세션이면 409, 참석자가 없으면 404

### GET /api/sessions

**로그인 필수.** 내가 만든 계획 목록. 주선자 본인 것만(`sessions.user_id` 일치), 최근 순.

```python
class SessionBrief(BaseModel):
    id: str
    preset: Literal["meeting", "visit"]
    status: str                     # draft / pins_confirmed / computed / failed
    purpose: str | None
    destination: str | None         # sessions.destination_name
    meet_at: str | None             # ISO 8601. 없으면 임시 세션
    participant_count: int
    created_at: str
    expires_at: str
    locked: bool
```

참석자 이름과 좌표는 목록에 넣지 않는다. 복호화 비용이 들고, 목록은 어깨너머로 보이기 쉬운 화면이다
(테이블정의서 7절). 이름이 필요하면 그 계획을 열어서 본다.

기본 20건, `?limit=` 로 조절한다. 만료된 세션은 빼고 준다.

### GET /api/session/{id}

**로그인 필수.** 공유 링크용. 링크는 프론트 `/s/{id}` 주소 그대로이고 매직링크·임시 토큰으로 바꾸지 않는다. 링크만으로는 열람할 수 없고 주선자·참석자 누구든 구글 계정으로 로그인해야 한다. 응답은 AgentResponse 와 같은 모양이다. 세션이 있고 만료 전이면 마지막 result를 복호화해 반환. 없으면 404. 로그인한 사람이 그 세션의 참석자인지는 확인하지 않는다. 참석자 ↔ 계정 연결은 7절 핀 소유권을 따른다.

### DELETE /api/session/{id}

**로그인 필수.** 세션의 user_id와 토큰의 user_id가 다르면 403. 즉시 삭제, results는 cascade. 204.

### /mcp

FastMCP Streamable HTTP. 헤더 `Authorization: Bearer {MCP_TOKEN}`. 브라우저에서 직접 호출하지 않는다.

---

## 3. 슬롯 스키마 (LLM 출력 계약 1)

backend/app/schemas/slots.py. 파인튜닝 데이터의 output과 완전히 같아야 한다.

```python
class Participant(BaseModel):
    name: str
    origin: str | None              # 지명 텍스트. 없으면 None
    transport: Literal["car", "transit", "walk"] | None   # 없으면 None, 추측 금지
    pickup: str | None              # 이 사람을 태워 주는 참석자 이름
    pickup_at: str | None           # 태워지는 지점 ("송파구 집 앞", "금천구 역 앞"). 집결지(rendezvous)와 다름
    unfamiliar: bool = False        # 그 일대 지리를 모르는 참석자
    role: Literal["site", "vendor", "client", "colleague"]   # 맞이하는 쪽 / 방문하는 업체 / 상대 조직 / 동료
    owner_user_id: str | None = None  # 이 핀을 소유한 사용자. None 이면 주선자 소유 (LLM 출력에는 없고 서버가 채운다)

class Rendezvous(BaseModel):
    name: str                       # 전원이 모이는 집결지 ("문정동 본사", "건물 정문"). 개인 픽업 지점은 participants[].pickup_at 에 둔다
    transport_after: Literal["car", "transit", "walk"] | None

class Access(BaseModel):
    required: bool                  # 출입 절차(방문자 등록·출입증·인솔)가 있는 곳인가
    applied: bool | None            # 사전 신청 여부. 모르면 None
    lead_min: int | None            # 절차 소요(분). 규칙 파일 기본값으로 채움

class Slots(BaseModel):
    preset: Literal["meeting", "visit"] | None   # out_of_scope 가 True 일 때만 None
    datetime: str | None            # "목요일 08:00", "오늘 22:00"
    purpose: str | None             # "저녁 식사", "정기 점검", "미팅"
    destination: str | None         # "강남 사무실", "여의도 본사". 없으면 None
    participants: list[Participant]
    rendezvous: Rendezvous | None
    access: Access | None
    schedule_confirmed: bool | None # 약속 시각이 확정됐는지. 모르면 None
    constraints: list[str]          # "arrival_delayed", "mutual_deference", "luggage"
    missing: list[str]              # "participants[0].origin", "access.applied", "datetime"
    out_of_scope: bool = False      # 출발 후 실시간 상황
```

검증 규칙 (schemas/slots.py의 validator)
- out_of_scope 가 False 면 participants 1명 이상, preset 은 None 이 아니어야 함
- out_of_scope 가 True 면 preset 은 None, participants 는 빈 목록
- name·origin·purpose·destination에 한글·영문·숫자·공백·일부 기호 외 문자(한자·가나 포함) 있으면 ValidationError
- transport가 None인 참석자가 있으면 missing에 해당 경로가 있어야 함
- pickup 과 pickup_at 은 짝이다. 하나만 있으면 ValidationError
- owner_user_id 는 LLM 출력에 없다. 서버가 핀 확인 단계에서 채운다

---

## 4. 결과 스키마 (LLM 출력 계약 2)

```python
class Candidate(BaseModel):
    name: str                       # "본사 정문", "여의도 사옥 1층 로비", "강남역 2번 출구"
    kind: Literal["gate", "lobby", "landmark", "hq"]   # 정문 / 로비 / 랜드마크 / 본사
    address: str
    lng: float
    lat: float
    rank: int | None                # failed 폴백이면 None
    access_ok: bool                 # 이 지점이 현재 출입 절차 상태로 가능한가
    switched_from: str | None       # 전환 판정이면 원래 집결지
    reason: str                     # 한 줄, 규칙 파일 항목 인용
    rejected_reason: str | None

class ParticipantResult(BaseModel):
    name: str
    candidate_rank: int
    transport: Literal["car", "transit", "walk"]
    duration_min: int               # 여유 포함
    raw_duration_min: int           # API 값
    buffer_min: int
    departure_time: str             # "18:15"
    arrive_by: str                  # 절차 소요를 뺀 도착 기한
    transfer_count: int | None
    first_train: str | None
    last_train: str | None
    polyline: list[list[float]]     # [[lng, lat], ...]
    via_rendezvous: bool
    via_pickup: bool                # 운전자 경로가 이 사람을 태우러 경유하는가

class Checklist(BaseModel):
    before: list[str]               # 사전 신청. 늦으면 출입 자체가 불가. 미신청이면 앞에 "[미완료] "
    onsite: list[str]               # 당일 지참

class Result(BaseModel):
    candidates: list[Candidate]     # 최대 3. 집결지 판정 결과
    provisional: bool               # 약속 시각이 미확정이면 True
    per_participant: list[ParticipantResult]
    rendezvous_departure: str | None   # 집결지에서 출발할 시각
    confidence: float
    checklist: Checklist | None     # 절차가 없거나(required=false) 아직 모르면(access 자체가 없으면) None
    summary_text: str               # 카톡·메일에 붙여넣을 집결 계획서. 코드가 조립. LLM 호출 없음
    model_small: str
    model_large: str | None
    prompt_version: str
    routed_to: Literal["small", "large"]
```

checklist 항목은 LLM이 만들지 않는다. skills/converge/rules/checklist.md 에서 조건에 맞는 것을 코드가 꺼낸다. summary_text 도 코드 조립이다. 지어낸 준비물을 믿고 갔다가 못 들어가면 그날 일정이 통째로 날아가고, 계획서의 숫자가 모델마다 흔들리면 표와 어긋난다.

rejected_reason 은 1순위가 아닌 후보에 반드시 들어간다. 대형 모델이 비워 두면 코드가 규칙 파일 항목을 인용해 채운다 (pipeline._rejected_for). 중간 지점만 찍어 주는 서비스는 탈락한 자리를 말하지 않는다. 왜 그곳이 아닌지가 실제로 합의를 끝내는 문장이다.

LLM(대형)이 만드는 건 candidates의 rank·reason·rejected_reason과 전환 판정(switched_from)뿐이다. 숫자와 access_ok는 코드가 넣는다. 대형 모델 응답은 `{"rankings":[{"candidate_idx":0,"rank":1,"reason":"...","rejected_reason":null}, ...]}` 형태로 받아 Candidate에 합친다.

---

## 5. 파이프라인 (services/pipeline.py)

순차 실행, 루프 없음. 각 단계는 Langfuse span으로 남긴다.

| 단계 | 함수 | 입력 → 출력 | 실패 시 |
|---|---|---|---|
| 0 | vision.extract_text | 이미지 → 텍스트 | 대형 비전 모델 1회 재시도 → 실패면 need_info("캡처를 읽지 못했습니다, 문장으로 입력") |
| 1 | llm.extract_slots | 텍스트(+이전 슬롯) → Slots | 스키마 위반 시 재시도 1회 → 대형 모델 승격 → 실패면 failed |
| 1-1 | 범위 판정 | slots.out_of_scope → out_of_scope 응답 | |
| 1-2 | 누락 판정 | slots.missing 비어 있지 않으면 need_info. 절차 단서가 없어 slots.access 가 통째로 None 이면 코드가 missing 에 "access.required" 를 넣고 되묻는다("이 장소에 출입 절차가 있나요? (출입증·방문자 등록)"). 없다고 답하면 required=false 로 두고 체크리스트를 만들지 않는다 | |
| 1-3 | 기간 판정 | slots.datetime을 시각으로 바꿔 오늘+30일을 넘으면 need_info("30일 안의 약속만 잡을 수 있습니다"). 30은 skills/converge/rules/의 값 | 코드라 실패 없음 |
| 2 | geo.geocode_all | 참석자·집결지·목적지 지명 → 좌표, confidence | 한 명이라도 confidence < 0.8 → need_confirm |
| 2-1 | 핀 확인 | 사용자가 confirmed_participants 반환. 누구 핀이든 고칠 수 있다 (7절 핀 소유권) | |
| 3 | geo.candidates | 집결 후보 생성: 절차 시작점(정문·1층 로비·본사) + 도착 어긋남 시 랜드마크(역·주차장 입구) | 후보 0곳이면 목적지 좌표 자체를 후보로 |
| 4 | routes.compute_all | 참석자 × 후보, 집결지 있으면 2구간, pickup_at 있으면 운전자 경로에 경유지로 추가하고 태워지는 사람은 탑승 이후 구간만 계산. 캐시 확인 후 API | 타임아웃·5xx 백오프 2회 → 실패 참석자만 "조회 실패", 나머지로 진행 |
| 5 | rules.apply | 절차 소요 반영, 출입 절차 상태별 후보 가능 여부(access_ok), 도착 어긋남 전환 조건, 여유·정체 가산 | 코드라 실패 없음 |
| 6 | judge.rank | 후보 표 + 규칙 문서 → rank·reason·switched_from | 스키마 위반 재시도 1회 → 실패면 rules.apply 순으로 rank, reason은 규칙 문구 그대로 |
| 7 | rules.departure | (도착 기한 − 절차 소요) − 소요시간 − 여유 = 출발 시각, 집결지면 2단 역산, 늦은 시각이면 첫차·막차 조회, 시각 미확정이면 provisional | |
| 7-1 | checklist.build_checklist + build_summary | 슬롯의 preset·access·constraints → Checklist (skills/converge/rules/checklist.md 에서 꺼낸다), 결과 표 → summary_text (코드 조립) | 코드라 실패 없음. 절차를 모르면 checklist 는 None |
| 8 | store.save + 응답 | 되묻기·핀 확인 단계에서도 세션을 draft 로 저장한다 (링크가 먼저 있어야 참석자가 모인다). 계산이 끝나면 status=computed 와 results 행. expires_at을 여기서 계산해 넣는다: meet_at 있으면 meet_at+30일, 없으면(임시 세션) created_at+7일. DB 기본값 없음 | |

2026-09-18 기준 구현 상태: 0~2단계와 갈림길(1-1 범위 밖, 1-2 누락, 2-1 핀 확인·핀 소유권)까지 services/pipeline.py 에 있다.
1-3(기간 판정)은 규칙 파일이 생기면 붙인다. 3~8단계는 MCP 도구 6개가 준비되면 채운다. 그때까지 그 자리는 failed 로 끝난다.
pipeline.run 은 바깥 함수를 Deps 로 받는다. 테스트가 키 없이 단계 순서만 검사하기 위해서다 (backend/tests/test_pipeline.py).

### 라우팅 (services/router.py)

```
small: 참석자 <= 2 and destination 있음 and constraints 비어 있음 and rendezvous 없음 and (access 없음 or access.applied == True)
       → 6단계 judge를 건너뛴다. rank는 rules.apply 점수 순, reason은 해당 규칙 문구를 그대로 붙인다. 대형 모델 호출 없음
large: 그 외 전부 → 6단계에서 대형 모델이 rank·reason 생성
소형 모델은 어느 경우든 1단계 슬롯 추출만 담당한다
```

라우팅 전후 비용은 request_logs에서 집계한다.

### 재질문

session_id가 있으면 먼저 잠금 검사: 세션의 user_id가 토큰과 다르면 403, meet_at 다음날 0시가 지났으면 409 (LLM 호출 전). meet_at이 없는 임시 세션은 잠기지 않고, 이번 재질문으로 시각이 들어오면 8단계에서 expires_at을 meet_at+30일로 다시 계산한다. 통과하면 이전 Slots를 1단계 프롬프트에 넣고 "바뀐 것만 갱신"을 지시. 결과는 새 results 행.

---

## 6. MCP 도구 시그니처

도구는 6개다.

| tool | 입력 | 출력 | 호출 API |
|---|---|---|---|
| geocode | query: str, bias_lng: float, bias_lat: float, radius_m: int = 20000 | {lng, lat, name, address, confidence, alternatives[]} | 카카오 로컬 키워드 검색 (x, y, radius). 지하철역 우선 규칙 |
| search_places | lng, lat, radius_m, kind: "gate" or "landmark", limit: int | [{name, address, lng, lat, kind}] | 카카오 로컬 키워드 검색 (정문·출입구·역). lobby 는 목적지 건물 자체라 검색하지 않는다 |
| route_car | origin: [lng, lat], destination: [lng, lat], departure_time: "yyyyMMddHHmm" or None, waypoint: [lng, lat] or None | {duration_sec, distance_m, polyline[], toll, fare_taxi} | 카카오모빌리티 미래 운행(시각 있음) / 자동차 길찾기(없음) |
| route_transit | origin, destination | {duration_sec, transfer_count, walk_m, fare, polyline[], legs[]} | TMAP 대중교통 |
| first_last_train | station_name: str, city: "seoul" or "busan", weekday: "weekday" or "sat" or "holiday", direction | {first: "05:30", last: "00:48", last_next_day: bool, line, station} | 서울: 열린데이터광장 `SearchLastTrainTimeByIDService` (역명→`SearchInfoBySubwayNameService`로 STATION_CD 선행, 1~9호선). 부산: `apis.data.go.kr/B551542/trainTime/getTrainTime` (역외부코드는 레포 CSV `backend/app/data/busan_stations.csv`). 양쪽 다 전체 시각표를 받아 우리가 min·max로 고른다 |
| departure_calc | arrive_by: "HH:MM", duration_sec, buffer_min, access_lead_min | {depart_at: "HH:MM", arrive_by_adjusted: "HH:MM", day_offset: int} | 계산. day_offset은 출발이 전날이면 -1 (자정을 넘기는 약속에서 생긴다, 09-18 추가) |

### 첫차·막차 API 에서 걸린 것 (2026-09-20 실측)

두 API 모두 "첫차·막차"를 주지 않는다. 그 역의 시각표를 통째로 준다. 세 가지를 우리가 처리한다.

- 순서가 보장되지 않는다. 부산은 04:00~07:00 으로 걸러도 첫 행이 06:14 인데 그 안에 05:06 이 있었다. 첫 행을 첫차로 보면 틀린다. min·max 로 고른다
- 24시를 넘겨 적는다. 막차가 `24:37:40` 로 온다. 스키마는 HH:MM(00~23)만 받으므로(4절) `00:37` + `last_next_day: true` 로 나눈다
- `00:00:00` 더미 행이 섞인다. 빼지 않으면 첫차가 00:00 이 된다

서울 서비스 이름은 `SearchLastTrainTimeByIDService` 다. `SearchFirstAndLastTrainbyIdService` 는 존재하지 않는 이름이고, 없는 이름을 부르면 열린데이터광장이 `ERROR-500`("서버 오류")을 돌려준다. 서버 장애가 아니다.
서울은 이름 자체가 "서울역" 인 역이 있어 "역"을 무조건 떼면 못 찾는다. 준 이름 그대로 먼저 찾고 안 되면 뗀 말로 찾는다.

`route_car` 는 `departure_time` 이 있으면 카카오모빌리티 미래 운행(`/v1/future/directions`)으로 간다. 같은 구간에서 값이 달라지는 것을 확인했다 (09-20 실측: 즉시 1280초, 다음 날 08:00 기준 1388초).

route_transit 이 부르는 TMAP 대중교통은 초당 호출 제한이 있어 연속 호출 시 429 THROTTLED 가 온다 (scripts/fetch_mock_routes.py 에서 확인). 간격을 두거나 재시도로 처리한다.

description은 "언제 쓰는 도구인지"가 한 문장에 드러나게 쓴다. 예: first_last_train은 "약속이 늦은 시각이라 막차를 넘길지, 끝나고 첫차를 기다려야 할지 볼 때 쓴다".

---

## 7. 규칙값 (skills/converge/rules/)

코드(rules.py)와 문서가 같은 값을 가져야 한다. 값은 문서가 기준이고 코드는 문서를 읽어 로드한다(yaml 프론트매터). 상식 수준 규칙(공평성, 중간 지점 등)은 두지 않는다. 각 파일은 그 값이 왜 그 값인지를 본문에 적는다.

| 파일 | 키 | 값 | 무엇을 |
|---|---|---|---|
| access.md | entry_lead_min | 15 | 출입 절차 소요(분). 방문자 확인·출입증 수령·안내. 절차가 없으면 0 |
| access.md | rendezvous_is_procedure_start | true | 합류 지점은 역이 아니라 절차가 시작되는 곳 |
| access.md | switch_if_delay_min | 30 | 도착이 이만큼 어긋나면 절차를 포기하고 밖에서 만난다 |
| access.md | outside_landmark_kinds | 역, 정문 앞, 주차장 입구 | 전환했을 때 찾을 자리의 종류 |
| access.md | no_procedure_all_transit_no_rendezvous | true | 절차 없고 전원 대중교통이면 합류 불필요 |
| session.md | register_within_days | 30 | 약속이 오늘 + 이 일수 안이어야 세션을 만든다 (5절 1-3) |
| session.md | retain_after_meet_days | 30 | 약속 뒤 보관 기간. expires_at 계산 |
| session.md | draft_retain_days | 7 | 약속 시각이 없는 임시 세션의 보관 기간 |
| session.md | lock_after_meet | next_day | 약속 다음날 0시부터 수정 잠금 |
| transport.md | buffer_meeting_min | 20 | 일반 약속(meeting)의 여유 |
| transport.md | buffer_visit_min | 15 | 출입 절차가 있는 방문(visit)의 여유. 절차 소요를 따로 빼므로 조금 줄인다 |
| transport.md | car_traffic_pct | 15 | 자동차 소요에 얹는 정체 여유(%) |
| transport.md | car_traffic_min_min | 10 | 정체 여유의 최소값(분) |
| transport.md | car_traffic_rush_pct | 25 | 출퇴근 시간대의 정체 여유(%) |
| transport.md | transit_transfer_extra_min | 10 | 환승이 있으면 더 얹는 시간 |
| transport.md | luggage_requires_car | true | 장비·짐이 있으면 대중교통으로 보내지 않는다 |
| transport.md | pickup_wait_min | 5 | 태우는 지점에서 기다리는 시간 |
| transport.md | pickup_counts_from_board | true | 태워지는 사람의 소요시간은 탑승 이후 구간만 |
| transport.md | max_pickup_per_car | 1 | 차 1대당 1명. 다중 픽업 순서 최적화는 범위 밖 |
| transport.md | route_cache_ttl_hours | 24 | 경로 응답 캐시 보관 시간 (테이블정의서 4절) |
| transport.md | geocode_cache_ttl_hours | 720 | 지오코딩 응답 캐시 보관 시간 |
| checklist.md | visit_access | 방문자 등록(+차로 가면 차량번호), 신분증·출입증 수령 | 출입 절차가 있을 때의 준비물 |
| checklist.md | luggage | 장비 반입 신고, 장비·전원 어댑터 | 장비는 절차와 별도로 걸린다 |
| checklist.md | not_applied_prefix | "[미완료] " | 신청 전 항목은 늦으면 되돌릴 수 없다 |

프리셋 (presets/)

| 키 | meeting (일반 약속) | visit (출입 절차가 있는 방문) |
|---|---|---|
| access.required 기본 | false | true |
| candidate_kinds | landmark, lobby | gate, lobby, hq |
| entry_lead_min 적용 | 안 함 (0) | 함 |
| buffer | buffer_meeting_min | buffer_visit_min |
| checklist | 없음 | visit_access (+ luggage) |

preset 은 사용자가 고르거나(AgentRequest.preset) 슬롯 추출이 문장에서 판정한다. 절차 단서가 아예 없으면
지어내지 않고 되묻는다 (5절 1-2). 프리셋마다 달라지는 값은 `skills/converge/presets/meeting.md`,
`visit.md` 의 프론트매터에 있고, 공통 규칙값은 `rules/` 에 있다.

### 핀 소유권 (2026-09-18 변경: 표시용으로만 둔다)

참석자가 각자 들어와 자기 위치를 찍을 수 있다. 다 모일 때까지 기다리지 않고, 들어온 사람 위치로 바로 계산한다.

| 상황 | owner_user_id | 수정 권한 |
|---|---|---|
| 주선자가 문장으로 입력해 만든 핀 | None | 로그인한 누구나 |
| 참석자가 공유 링크로 들어와 자기라고 고른 핀 | 그 사람의 user_id | 로그인한 누구나 |

- owner_user_id 는 "이 핀이 누구 것인가"를 나타내는 표시일 뿐이다. 수정을 막지 않는다
- 참석자는 공유 링크를 열고 구글 로그인한 뒤 참석자 목록에서 자기를 한 번 고른다(claim). 그 시점에 owner_user_id 가 채워진다. 고르지 않아도 결과는 볼 수 있고 핀도 옮길 수 있다
- 이미 주인이 있는 핀에 다른 사람이 claim 하면 409. 한 사람을 두 계정이 동시에 자기라고 할 수는 없다
- 링크를 아는 로그인 사용자는 누구나 들어온다. 참석자 정원으로 막지 않는다. 사람이 늘거나 바뀌는 일이 흔하기 때문이다. 없는 링크와 만료된 링크만 404 이고, 화면은 "잘못된 경로"로 알린다
- 위치 수정은 링크를 열 수 있는 사람이면 누구나 한다. 현장에서 "저 사람 거기서 출발 안 해요"를 옆 사람이 고쳐 주는 편이 빠르기 때문이다. 대신 링크를 아는 사람은 남의 출발지도 바꿀 수 있다는 뜻이라, 화면에 그 안내를 둔다
- 누가 마지막에 고쳤는지 남긴다. participants_enc 의 last_edited_by(user_id)와 self_edited_at(시각). 화면은 "본인이 고침 / 다른 사람이 고침"으로 보여 준다
- 약속 날짜가 지난 세션은 잠긴다. 그때는 누구도 고치지 못한다 (409)
- 새 위치가 들어오면 그 세션의 결과를 다시 계산하지 않는다. 좌표만 바꾼다. 다시 계산할지는 주선자가 정한다 (LLM 비용이 드는 일을 참석자 조작으로 자동으로 일으키지 않는다)

---

## 8. 프롬프트

Langfuse Prompt 이름과 역할. 코드에 문자열로 두지 않는다.

| 이름 | 모델 | 역할 |
|---|---|---|
| converge/slot-extract | 소형 (GGUF) 또는 대형 폴백 | 텍스트 → Slots JSON. GBNF 문법 강제. 출입 절차·집결지·픽업·참석자 역할 추출. 범위 밖이면 out_of_scope true 에 preset null |
| converge/vision-transcribe | Gemini Flash | 캡처 → 대화 텍스트 (이름·시각·말풍선 유지) |
| converge/judge | Sonnet 5 | 후보 표 + 규칙 문서 → rankings JSON (rank·reason·switched_from) |
| converge/eval-judge | GPT-5.6 Luna | reason이 규칙과 계산값에 부합하는지 0~2점 |

---

## 9. 환경변수

루트 `.env.example` (backend, compose)

```
OPENROUTER_API_KEY=      # OpenRouter 대시보드
KAKAO_REST_KEY=          # 카카오 개발자 콘솔
TMAP_APP_KEY=            # SK오픈API
DATA_GO_KR_KEY=          # 첫차·막차
DATABASE_URL=postgresql://app:app@db:5432/app   # 로컬 compose 기본값. 운영은 Supabase 연결 문자열
SUPABASE_URL=            # 프로젝트 주소. 토큰 서명을 공개키(/auth/v1/.well-known/jwks.json)로 검증. 비밀값 없음
AUTH_REQUIRED=true       # 로컬 개발용으로만 false. 배포 환경에서는 항상 true
ENCRYPTION_KEY=          # 32바이트 base64, AES-256-GCM
LANGFUSE_PUBLIC_KEY=     # Langfuse Cloud
LANGFUSE_SECRET_KEY=     # Langfuse Cloud
LANGFUSE_HOST=           # https://cloud.langfuse.com
MCP_TOKEN=               # /mcp Bearer 토큰
INTERNAL_TOKEN=          # /internal/cleanup
MODEL_SMALL_PATH=backend/app/models/kanana_2.1b-Q4_K_M.gguf   # HF kimseunguk/converge-slot-extractor (공개). 빌드 시 받는다
MODEL_SMALL=            # 비우면 처음부터 대형으로 추출한다. 로컬 GGUF 서빙이 붙기 전 임시로 OpenRouter 소형 모델을 넣어 볼 때 쓴다
MODEL_LARGE=anthropic/claude-sonnet-5
MODEL_VISION=google/gemini-3.8-flash
MODEL_EVAL_JUDGE=openai/gpt-5.6-luna
COST_LIMIT_USD_PER_REQUEST=0.05
DAILY_COST_LIMIT_USD=1.0       # 하루 합계 상한. 비우면 제한 없음 (41번)
```

`frontend/.env.example` (브라우저에 노출되는 값만)

```
NEXT_PUBLIC_SUPABASE_URL=       # Supabase 프로젝트 URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=  # sb_publishable_... (공개 가능, RLS 전제). 옛 anon 키는 2026년 말까지만
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_KAKAO_JS_KEY=       # 카카오 지도 SDK (NEXT_PUBLIC_ 없으면 브라우저에 안 넘어감)
```

supabase-py는 쓰지 않는다. 백엔드는 DATABASE_URL로 Postgres에 직접 붙고, Supabase는 운영 DB와 로그인(Auth)으로만 쓴다.

---

## 10. 실행

```
cp .env.example .env
docker compose up          # backend:8000 (/api/agent, /health, /mcp 모두 여기) + db:5432 (postgres:16, backend/db/ 자동 실행)
cd frontend && npm run dev # :3000, NEXT_PUBLIC_API_BASE=http://localhost:8000
```

Cloud Run 서비스는 하나다 (backend에 MCP 마운트). 프론트는 Vercel. 카카오 콘솔에 Vercel 도메인과 localhost:3000을 등록한다.

---

## 11. 미확정

| 항목 | 상태 | 확인 방법 |
|---|---|---|
| 지하철 첫차·막차 | 확인됨 | 서울교통공사 첫차·막차 API(1~9호선만, 민자 노선 제외), 부산교통공사 열차시각표 API. 공공데이터포털 키 하나. 부산 역외부코드 CSV를 레포에 둠 |
| TMAP 대중교통 도착 시각 지정 | 미확인 | 문서의 요청 파라미터 확인. 없으면 현재 기준 소요시간으로 역산 |
| OpenRouter 슬롯 추출 통과율 | 일부 확인 (09-18) | 크레딧 충전 완료. openai/gpt-4o-mini 로 converge/slot-extract v2 실호출, 참석자·픽업·누락 추출 통과 (11초, 재시도 없음). 평가셋 30건 기준 통과율은 미측정 |
| 소형 모델 최종 선택 | 결정 (09-18) | kanana_2.1b-Q4_K_M.gguf (HF kimseunguk/converge-slot-extractor, 공개). 검증 40건 Exact Match 85.0%. 대안은 qwen3_1.7b 45.0%, qwen3_0.6b 47.5% |
| compose db healthcheck | 적용됨 (09-17) | pg_isready healthcheck + depends_on condition: service_healthy. backend/db/를 initdb에 마운트 |
| requirements.txt asyncpg | 적용됨 (09-17) | 주석 해제. SQLAlchemy 안 씀, asyncpg 직접. DATABASE_URL은 postgresql:// |
| 다른 기기에서 로컬 재현 | 미확인 | .env.example 만으로는 못 돈다. LLM·카카오·TMAP 키가 있어야 하고, 없을 때 어디까지 도는지 README에 적는다 |
| Supabase 프로젝트 | 해결 (09-18) | `converge_agent` 생성. 표 5개·RLS 마이그레이션 완료 |
| 구글 OAuth 동의 화면 | 설정됨, 테스트 모드 (09-18) | 테스트 사용자 등록, 리디렉트 localhost:3000/**. 브라우저 로그인 → 토큰 → 백엔드 검증 실측. 남은 것은 프로덕션 전환과 Vercel 주소 추가로, 배포할 때 한다 |
| Langfuse 트레이스의 참석자 이름·출발지 | 미검토 | 평문으로 들어간다. 마스킹 여부 미정 |
| 로컬 확인용 서버 | 임시 (09-18) | backend/app/main.py 는 DATABASE_URL 과 Supabase 공개키가 있어야 뜬다. 그 전까지 POST /api/agent 만 띄우는 임시 서버로 화면을 확인했다. DB 설정이 들어오면 임시 서버를 버린다 |
