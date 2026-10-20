# 배포

프론트는 Vercel, 백엔드는 Modal, DB 와 로그인은 Supabase 를 쓴다.
Vercel 은 컨테이너를 돌리지 않으므로 Dockerfile 은 Modal 쪽으로 간다 (`modal_app.py` 가 이 파일로 이미지를 만든다).

10-20 결정: 처음 설계는 Cloud Run 이었으나 결제 계정을 새로 열어야 했고(카드 등록) 초과 청구를 막는 하드 한도가 없어
Modal 로 바꿨다. Modal 은 월 무료 크레딧과 지출 한도 $0 으로 카드 청구가 생기지 않는다 (SDD 10절).

운영 중인 주소 (2026-10-20):

| 무엇 | 주소 |
|---|---|
| 화면 | https://converge-meet.vercel.app (converge.vercel.app 은 이미 다른 사람이 쓴다. 처음 주소 converge-ruby 에서 10-20 에 바꿨다) |
| 백엔드 | https://kswook30--converge-api.us-east.modal.run (`/health`, `/mcp`) |
| Supabase | 프로젝트 `converge-seoul` (`ntobehbbxiaurzfyhwgy`) |
| 구글 클라우드 | 프로젝트 `converge-512207` (kswook30 계정), 클라이언트 `converge-web` |
| 카카오 | 앱 "MCP" (ID 1578119) 의 Default JS Key |

```
브라우저
   │
   ▼
Vercel          frontend/ (Next.js). app/api/ 프록시가 백엔드를 부른다
   │            브라우저는 백엔드를 직접 부르지 않는다. 그래서 CORS 설정이 없다
   ▼
Modal           Dockerfile (FastAPI + /mcp). 요청이 없으면 5분 뒤 0대
   │
   ▼
Supabase        Postgres + 구글 로그인
```

---

## 1. Supabase 프로젝트 만들기

### 1-1. 프로젝트 생성

supabase.com 에서 새 프로젝트를 만든다. 리전은 가까운 곳(Northeast Asia)으로.
비밀번호는 DB 접속에 쓰이므로 따로 적어 둔다.

### 1-2. 표 만들기

SQL Editor 에서 `backend/db/001_init.sql` 을 통째로 붙여넣고 실행한다. 표 다섯 개가 생긴다.
001 로 이미 만든 DB 라면 `002_datetime_text.sql`, `003_rendezvous_legs.sql` 도 실행한다 (새 DB 는 001 에 들어 있어 실행해도 그냥 지나간다).

```
sessions  results  request_logs  route_cache  feedback
```

로컬 `docker compose up` 은 같은 파일을 자동으로 실행한다. 두 곳의 스키마가 같아야 한다.

### 1-3. 연결 문자열

Settings > Database > Connection string 에서 **Connection pooling** 쪽 주소를 쓴다.
직접 연결(`db.xxxx.supabase.co`)은 IPv6 만 주므로 서버 호스트에서 닿지 않을 수 있다.

풀러는 포트가 둘이다. **5432(Session) 을 쓴다.**

```
DATABASE_URL=postgresql://postgres.xxxx:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres
```

6543(Transaction) 은 준비된 구문(prepared statement)을 재사용하지 못한다. `services/store.py` 가
asyncpg 풀(`create_pool`)을 그대로 쓰므로 6543 으로 붙이면 두 번째 요청부터
`prepared statement "__asyncpg_stmt_1__" already exists` 로 깨진다. 굳이 6543 을 쓰려면
`create_pool(..., statement_cache_size=0)` 을 같이 넣어야 한다.

서버는 요청마다 프로세스를 새로 만들지 않고 풀을 들고 있으므로 Session 쪽이 맞다.

### 1-4. 구글 로그인 켜기

구글 클라우드 콘솔 > Google 인증 플랫폼에서 한다. **Converge 전용 프로젝트**를 쓴다. 다른 서비스 프로젝트 안에
클라이언트를 만들면 동의 화면에 그 앱 이름이 뜬다.

1. 브랜딩: 앱 이름 `Converge`, 홈페이지 `https://<배포 주소>`, 개인정보처리방침 `https://<배포 주소>/privacy.html`,
   서비스 약관 `https://<배포 주소>/terms.html` (둘 다 `frontend/public/`), 승인된 도메인에 배포 도메인. 이게 채워져야 게시가 된다
2. 대상: 외부, **프로덕션으로 게시**. 테스트 상태면 등록한 테스트 사용자만 로그인된다. 이메일·프로필만 쓰므로 심사는 필요 없다
3. 클라이언트(웹 애플리케이션): 승인된 JavaScript 원본 `https://<배포 주소>`, 승인된 리디렉션 URI 두 개
   ```
   https://<프로젝트>.supabase.co/auth/v1/callback   예비 경로 (NEXT_PUBLIC_GOOGLE_CLIENT_ID 가 없을 때)
   https://<배포 주소>/                                 기본 경로
   ```
4. 클라이언트 ID·보안 비밀번호를 Supabase > Authentication > Providers > Google 에 넣고 켠다. 보안 비밀번호는 생성 창에서 한 번만 보인다
5. 같은 클라이언트 ID 를 Vercel `NEXT_PUBLIC_GOOGLE_CLIENT_ID` 에 넣는다 (4-2). 그러면 구글에서 화면으로 바로 돌아와
   id_token 을 Supabase `signInWithIdToken` 에 넘기고, 계정 선택 화면에 `<프로젝트>.supabase.co` 대신 배포 주소가 뜬다 (`lib/auth.ts`)

Supabase 의 Site URL 과 Redirect URLs 에는 화면 주소를 넣는다.

```
http://localhost:3000/**       로컬
https://<배포 주소>/**          배포
```

### 1-5. 키 가져오기

| 값 | 어디서 | 어디에 쓰나 |
|---|---|---|
| Project URL | Settings > API | 백엔드(`SUPABASE_URL`), 프론트(`NEXT_PUBLIC_SUPABASE_URL`) |
| Publishable key | Settings > API | 프론트(`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`). 공개돼도 되는 값이다 |
| Connection string | Settings > Database | 백엔드(`DATABASE_URL`) |

백엔드는 토큰을 공개키(JWKS)로 검증하므로 비밀 키를 두지 않는다 (`services/auth.py`).

---

## 2. 암호화 키 만들기

참석자 이름·출발지·좌표·경로는 평문으로 저장하지 않는다 (docs/테이블정의서.md 7절).
32바이트 키를 만들어 `ENCRYPTION_KEY` 에 넣는다.

```bash
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

**이 값을 잃어버리면 저장된 세션을 못 읽는다.** 바꾸면 그 전 데이터도 못 읽는다.
새 Supabase 로 옮기는 김에 새로 만들면 된다. 옛 데이터는 어차피 딸려오지 않는다.
운영은 로컬 `.env` 와 같은 키를 Modal 비밀값에 넣었다 (같은 DB 를 쓰므로).

---

## 3. Modal 배포

### 3-1. 준비

```bash
pip install modal
python -m modal token new        # 브라우저로 로그인
```

Modal 대시보드 Settings > Usage & billing 에서 월 지출 한도(Spend limit)를 `$0` 으로 건다.
무료 크레딧이 떨어지면 카드 청구 대신 작업이 멈춘다.

### 3-2. 비밀값 넣기

Modal 대시보드 Secrets 에서 이름 `converge` 로 만든다. 값은 루트 `.env` 와 같은 이름이다 (SDD 9절).

```
OPENROUTER_API_KEY  GEMINI_API_KEY  MODEL_SMALL  MODEL_LARGE  MODEL_VISION
KAKAO_REST_KEY  TMAP_APP_KEY  DATA_GO_KR_KEY  SEOUL_OPENDATA_KEY
LANGFUSE_PUBLIC_KEY  LANGFUSE_SECRET_KEY  LANGFUSE_HOST  LANGFUSE_BASE_URL
DATABASE_URL  SUPABASE_URL  ENCRYPTION_KEY  MCP_TOKEN  INTERNAL_TOKEN
AUTH_REQUIRED=true  JEV_ACCESS=0
FRONTEND_ORIGIN=https://<배포 주소>
MCP_PUBLIC_URL=https://<백엔드 주소>/mcp
```

CLI 로는 `python -m modal secret create converge --force KEY=값 ...` 인데, 키가 셸 기록에 남으므로 대시보드가 낫다.
`--force` 는 통째로 바꾼다. 하나만 바꿀 때도 전부 다시 넣어야 한다.

### 3-3. 올리기

저장소 루트에서 실행한다. 빌드 컨텍스트가 루트여야 `skills/` 와 `mcp_server/` 가 함께 들어간다.

```bash
python -m modal deploy modal_app.py
```

출력의 `https://<워크스페이스>--converge-api.<리전>.modal.run` 이 백엔드 주소다.
요청이 없으면 5분 뒤 0대로 내려가고 과금도 멈춘다. 다음 첫 요청은 콜드 스타트로 느리다 (10-20 측정: `/health` 6.8초).
`.dockerignore` 를 따르므로 `.env` 는 이미지에 들어가지 않는다.

리전은 기본(us-east)이다. Supabase·카카오·TMAP 은 한국에 있어 호출마다 왕복 지연이 더 붙는다.

### 3-4. 확인

```bash
curl https://<백엔드 주소>/health                                   # {"status":"ok"}
curl -X POST https://<백엔드 주소>/api/agent -d '{}' -H 'content-type: application/json'   # 401 (로그인 필요)
```

### 3-5. 만료 데이터 청소 (GitHub Actions)

만료된 세션·경로 캐시·90일 지난 로그를 하루 한 번 지운다 (테이블정의서 6절). 이게 없으면
보관 기간이 문서에만 있고 데이터는 쌓인다. Supabase 무료 티어의 7일 미사용 정지도 이 호출이 막는다.

`.github/workflows/cleanup.yml` 이 매일 04:00 KST 에 `POST /internal/cleanup` 을 부른다.
저장소 Settings > Secrets and variables > Actions 에 두 개를 넣는다.

| 이름 | 값 |
|---|---|
| `CONVERGE_API_URL` | 백엔드 주소 (끝 슬래시 없이) |
| `INTERNAL_TOKEN` | Modal 비밀값과 같은 값 |

정기 실행은 기본 브랜치에 있는 워크플로만 돈다. Actions 탭에서 `cleanup` 을 손으로 한 번 돌려 확인한다.
`INTERNAL_TOKEN` 이 비어 있으면 엔드포인트가 503 으로 닫혀 있다.

---

## 4. Vercel 배포

### 4-1. 프로젝트 만들기

깃허브 저장소를 연결하고 **Root Directory 를 `frontend` 로 지정한다.**
저장소 루트에는 Next.js 가 없다.

운영은 CLI 로 만들었다: `cd frontend && vercel link --yes --project converge` 뒤 `vercel env add ... --environment production`,
`vercel --prod`. 카카오 JS 키처럼 `NEXT_PUBLIC_` 값이 키처럼 보이면 CLI 가 `--type config`(공개)를 명시하라고 한다.

### 4-2. 환경변수

| 이름 | 값 |
|---|---|
| `NEXT_PUBLIC_API_BASE` | Modal 백엔드 주소 |
| `NEXT_PUBLIC_KAKAO_JS_KEY` | 카카오 JS 키 |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase 프로젝트 URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable 키 |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | 구글 클라이언트 ID (1-4). 공개 값 |

`NEXT_PUBLIC_` 이 붙은 값만 브라우저로 간다. 백엔드 키는 여기 두지 않는다.

### 4-3. 카카오 콘솔에 도메인 등록

developers.kakao.com > 앱 > 플랫폼 키 > JavaScript 키 > JavaScript SDK 도메인에 배포 도메인을 더한다.

```
http://localhost:3000
https://<배포 주소>
```

등록하지 않으면 지도 SDK 가 401 을 내고 지도만 안 뜬다.

---

## 5. 배포 뒤 확인

순서대로 한 번씩 해 본다.

1. `/health` 가 200 인가
2. 첫 화면에서 구글 로그인이 되는가 (여기서 처음 실제로 돌려 보는 부분이다)
3. 문장을 넣어 결과가 나오는가. 첫 요청은 콜드 스타트로 느리다
4. 지도에 핀과 경로선이 그려지는가 (안 되면 카카오 도메인 등록을 다시 본다)
5. 공유 링크를 다른 브라우저에서 열어 핀을 고칠 수 있는가
6. Langfuse 에 트레이스가 쌓이는가

## 막히면 볼 곳

| 증상 | 원인 |
|---|---|
| 지도만 안 뜬다 | 카카오 콘솔에 배포 도메인 미등록 |
| 로그인 뒤 튕긴다 | Supabase Redirect URLs 에 배포 주소 없음 |
| 401 이 계속 난다 | `SUPABASE_URL` 이 프론트와 백엔드에서 다른 프로젝트를 가리킴 |
| 결과가 failed 로만 온다 | OpenRouter 크레딧 또는 제미나이 할당. `python -m modal app logs converge` 에서 429·402 를 본다 |
| 저장은 되는데 못 읽는다 | `ENCRYPTION_KEY` 가 저장 때와 다르다 |
| 첫 요청만 10초 안팎 걸린다 | 콜드 스타트. 정상이다 |
| 계정 선택 화면에 supabase.co 가 뜬다 | Vercel 에 `NEXT_PUBLIC_GOOGLE_CLIENT_ID` 가 없다 |
| 구글이 redirect_uri_mismatch | 구글 클라이언트 리디렉션 URI 에 `https://<배포 주소>/` 가 없다 (반영에 몇 분 걸릴 수 있다) |
