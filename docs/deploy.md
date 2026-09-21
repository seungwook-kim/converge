# 배포

프론트는 Vercel, 백엔드는 Cloud Run, DB 와 로그인은 Supabase 를 쓴다.
Vercel 은 컨테이너를 돌리지 않으므로 Dockerfile 은 Cloud Run 쪽으로 간다.

```
브라우저
   │
   ▼
Vercel          frontend/ (Next.js). app/api/ 프록시가 백엔드를 부른다
   │            브라우저는 백엔드를 직접 부르지 않는다. 그래서 CORS 설정이 없다
   ▼
Cloud Run       Dockerfile (FastAPI + /mcp). 요청이 없으면 0으로 내려간다
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

```
sessions  participants  results  route_cache  request_logs
```

로컬 `docker compose up` 은 같은 파일을 자동으로 실행한다. 두 곳의 스키마가 같아야 한다.

### 1-3. 연결 문자열

Settings > Database > Connection string 에서 **Connection pooling** 쪽 주소를 쓴다.
직접 연결(5432)은 동시 접속 수가 적어 서버리스와 맞지 않는다.

```
DATABASE_URL=postgresql://postgres.xxxx:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
```

### 1-4. 구글 로그인 켜기

Authentication > Providers > Google 을 켠다. 구글 클라우드 콘솔에서 OAuth 클라이언트를 만들어
클라이언트 ID·시크릿을 넣어야 한다.

구글 콘솔의 승인된 리디렉션 URI 에 Supabase 가 알려 주는 주소를 넣는다.

```
https://<프로젝트>.supabase.co/auth/v1/callback
```

Supabase 의 Site URL 과 Redirect URLs 에는 화면 주소를 넣는다. 배포 주소가 나온 뒤에 채운다.

```
http://localhost:3000          로컬
https://<프로젝트>.vercel.app  배포
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

---

## 3. Cloud Run 배포

### 3-1. 준비

```bash
gcloud auth login
gcloud config set project <프로젝트 ID>
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
```

### 3-2. 올리기

저장소 루트에서 실행한다. 빌드 컨텍스트가 루트여야 `skills/` 와 `mcp_server/` 가 함께 들어간다.

```bash
gcloud run deploy converge-api \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --timeout 120
```

`--min-instances 0` 이 요점이다. 요청이 없으면 인스턴스가 내려가고 과금도 멈춘다.
대신 한동안 쓰지 않으면 다음 요청이 콜드 스타트로 5~15초 걸린다.
항상 빠르게 하려면 `--min-instances 1` 인데, 그때부터는 24시간 과금이라 월 $10~15 나온다.

`--allow-unauthenticated` 는 구글 IAM 인증을 끄는 것이다. 우리 인증은 Supabase 토큰으로 따로 한다
(`AUTH_REQUIRED=true`).

### 3-3. 환경변수 넣기

```bash
gcloud run services update converge-api --region asia-northeast3 \
  --set-env-vars "AUTH_REQUIRED=true" \
  --set-env-vars "MODEL_SMALL=google-ai/gemini-3.5-flash-lite" \
  --set-env-vars "MODEL_LARGE=google-ai/gemini-3.1-flash-lite" \
  --set-env-vars "GEMINI_API_KEY=..." \
  --set-env-vars "KAKAO_REST_KEY=..." \
  --set-env-vars "TMAP_APP_KEY=..." \
  --set-env-vars "DATA_GO_KR_KEY=..." \
  --set-env-vars "SEOUL_OPENDATA_KEY=..." \
  --set-env-vars "LANGFUSE_PUBLIC_KEY=..." \
  --set-env-vars "LANGFUSE_SECRET_KEY=..." \
  --set-env-vars "LANGFUSE_HOST=https://cloud.langfuse.com" \
  --set-env-vars "SUPABASE_URL=https://xxxx.supabase.co" \
  --set-env-vars "ENCRYPTION_KEY=..." \
  --set-env-vars "MCP_TOKEN=..." \
  --set-env-vars "^@^DATABASE_URL=postgresql://..."
```

`DATABASE_URL` 은 값에 쉼표가 들어갈 수 있어 구분자를 바꿔 준다(`^@^`). 그게 번거로우면
콘솔 화면에서 넣는 편이 낫다. 키를 셸 기록에 남기고 싶지 않을 때도 콘솔이 낫다.

더 단정하게 하려면 Secret Manager 를 쓴다. 지금 규모에서는 환경변수로 충분하다.

### 3-4. 확인

```bash
curl https://converge-api-xxxx.a.run.app/health
```

---

## 4. Vercel 배포

### 4-1. 프로젝트 만들기

깃허브 저장소를 연결하고 **Root Directory 를 `frontend` 로 지정한다.**
저장소 루트에는 Next.js 가 없다.

### 4-2. 환경변수

| 이름 | 값 |
|---|---|
| `NEXT_PUBLIC_API_BASE` | Cloud Run 주소 |
| `NEXT_PUBLIC_KAKAO_JS_KEY` | 카카오 JS 키 |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase 프로젝트 URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable 키 |

`NEXT_PUBLIC_` 이 붙은 값만 브라우저로 간다. 백엔드 키는 여기 두지 않는다.

### 4-3. 카카오 콘솔에 도메인 등록

developers.kakao.com > 내 애플리케이션 > 플랫폼 > Web 에 배포 도메인을 더한다.

```
http://localhost:3000
https://<프로젝트>.vercel.app
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
| 결과가 failed 로만 온다 | 제미나이 키 또는 하루 할당. Cloud Run 로그에서 429·402 를 본다 |
| 저장은 되는데 못 읽는다 | `ENCRYPTION_KEY` 가 저장 때와 다르다 |
| 첫 요청만 10초 넘게 걸린다 | 콜드 스타트. 정상이다 |
