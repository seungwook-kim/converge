# FRONTEND_GUIDE

Next.js. Vercel에 배포. Root Directory = `frontend`.

## 구조

| 경로 | 무엇 |
|---|---|
| `app/layout.tsx` | html/body, 전역 CSS 로드, manifest 연결, 서비스 워커 등록 |
| `app/globals.css` | 전역 스타일. 핀 커서 규칙(드래그 가능·수정 불가)도 여기 |
| `app/page.tsx` | 메인. 소개(로그인 전에도 보인다)·예시 결과·문장 입력. 지도 없음. 만들면 `/s/{id}` 로 이동하며 첫 응답을 sessionStorage 로 넘긴다 |
| `app/about/page.tsx` | 소개 페이지. 서비스 화면과 별도 |
| `app/my/page.tsx` | 내 계획 목록. `GET /api/sessions`. 줄을 누르면 `/s/{id}`, 줄마다 삭제 |
| `app/s/[id]/page.tsx` | 참석자들이 모이는 자리. 지도·되묻기·핀 확인·결과·claim·수정. 없는 링크면 "잘못된 경로" |
| `app/api/agent/route.ts` | `POST /api/agent` 프록시. 브라우저는 백엔드를 직접 부르지 않는다 |
| `app/api/sessions/route.ts` | `GET /api/sessions` 프록시 (내 계획 목록) |
| `app/api/session/[id]/route.ts` | `GET /api/session/{id}` 와 `DELETE` 프록시 |
| `app/api/session/[id]/participants/route.ts` | `PATCH /api/session/{id}/participants` 프록시 |
| `components/MapView.tsx` | 지도 한 장. stage별 핀 구성, 후보·픽업·목적지 핀, 경로선 토글과 범례, bounds 맞춤 |
| `components/ParticipantPins.tsx` | 참석자 출발지 핀. 누구 핀이든 드래그로 옮긴다 |
| `components/PinPicker.tsx` | 출발지 지정 패널(지도 왼쪽 위). 사람을 고른 뒤 지도 클릭 또는 장소 검색으로 좌표를 찍는다. 저장은 드래그와 같은 `onMove` 경로 |
| `components/RouteLines.tsx` | `per_participant[].polyline`. 이동수단별 색 3가지 |
| `components/ChatPanel.tsx` | 문장 입력, 캡처 업로드, 되묻기 표시, 입력 가이드 |
| `components/ResultTable.tsx` | 집결 후보(순위·근거), 참석자별 출발 시각·소요·여유·첫차, 선택되지 않은 후보와 이유,
  준비물(사전 신청·당일 지참), 집결 계획서와 복사 버튼. 아래 세 칸은 서버가 보낸 값을 꺼내 놓기만 한다 |
| `components/AuthGate.tsx` | 로그인 전에는 `preview`(예시 결과)와 로그인 버튼을 보여준다 |
| `components/DemoPreview.tsx` | 로그인 전 예시 결과. 결과 화면과 같은 `ResultTable`을 쓴다. 따로 그리면 예시와 실물이 갈라진다 |
| `components/ServiceWorker.tsx` | `public/sw.js` 등록. `NODE_ENV`가 production일 때만 |
| `lib/kakao.ts` | 지도 SDK 로더(autoload=false, `libraries=services`, 한 번만), 장소 검색 `searchPlaces`, 핀 이미지 |
| `lib/auth.ts` | 구글 로그인(Supabase Auth), 토큰 헤더. `NEXT_PUBLIC_GOOGLE_CLIENT_ID` 가 있으면 구글에서 이 사이트로 바로 돌아와 id_token 으로 로그인 (10-20) |
| `lib/proxy.ts` | `app/api/` 라우트 공용. `NEXT_PUBLIC_API_BASE`로 전달, 없으면 mock |
| `lib/mock.ts` | 백엔드 없이 화면을 확인할 고정 응답. 입력 문장으로 시나리오(`meeting`·`visit`)와 stage를 고른다(파일 상단 주석). 서버에서만 import |
| `lib/mock-data.json` | mock 시나리오와 실제 경로 좌표. `routes`는 `scripts/fetch_mock_routes.py`가 채운다 |
| `lib/demo-preview.ts` | 로그인 전 예시 결과의 고정값. `mock-data.json`(150KB)을 첫 화면 번들에 싣지 않으려고 따로 둔다 |
| `lib/dev-user.ts` | 로컬 모드 사용자 id. 브라우저 코드는 mock 대신 이 파일을 import 한다 |
| `lib/capture.ts` | 카톡 캡처를 base64 로. Vercel 본문 한도(4.5MB)를 넘으면 브라우저에서 JPEG 로 줄여 보낸다 (10-30) |
| `lib/useFoldable.ts` | 지도 위 패널(출발지 고치기·경로선) 접기 상태. 820px 이하 폭에서는 접힌 채 시작 (10-20) |
| `types/agent.ts` | SDD 2·3·4절 타입을 손으로 옮긴 것. `lib/api-types.ts`가 생기면 대체한다 |
| `lib/api-types.ts` | 생성물. `backend/app/schemas/`에서 `bash scripts/gen_types.sh`로 만든다. 손으로 고치지 않는다 |

## 응답 stage에 따라 화면이 갈린다 (docs/SDD.md 2절)

| stage | 화면 |
|---|---|
| `need_confirm` | `geocoded`의 참석자 핀만. "위치가 맞나요" + 계산 버튼. 확정하면 `confirmed_participants`로 다시 요청 |
| `need_info` | `questions[]`를 채팅에 보여주고 대기 |
| `done` | 후보 핀 + 참석자 핀 + 픽업 핀 + 경로선 + ResultTable. `provisional`이면 "시각 미확정, 잠정" 배지.
  `result.checklist` 가 null 이면 준비물 칸을 아예 만들지 않는다 (절차가 없다는 뜻이 아니라 아직 모른다는 뜻) |
| `out_of_scope` | 범위 밖 안내만 |
| `failed` | 후보 핀과, 지오코딩까지 갔으면 참석자 핀. 안내와 재시도 버튼 |

## 지도 규칙

- 핀 좌표는 `AgentResponse.geocoded`에서만 온다. Slots에는 좌표가 없다
- 집결 후보 종류(`CandidateKind`)는 `gate`(정문·출입구)·`lobby`(로비)·`landmark`(역 등)·`hq`(본사) 네 가지다. 색과 라벨은 `components/MapView.tsx`의 `CANDIDATE_STYLES` 한 곳에만 둔다
- `slots`는 `null`일 수 있다. 캡처를 못 읽거나 슬롯 추출이 깨진 응답(`failed`, `need_info`)이 그렇다. 화면은 `slots?.participants ?? []`로 받는다
- 핀 소유권(SDD 7절, 09-18 변경): 로그인한 사람이면 누구 핀이든 끈다. 소유권은 색 표시일 뿐이다. 내 핀은 초록, 나머지는 파랑, 위치가 불확실하면 주황
- 주선자 재계산 때 `confirmed_participants`에는 모든 참석자 핀을 담는다
- 공유 링크에서 자기 이름을 고르면 PATCH `claim: true`, 핀을 옮기면 `claim: false`. 409는 "이미 다른 사람이 등록했습니다"(claim 충돌)와 잠긴 세션. 수정 자체는 막지 않는다
- 응답의 `edits`로 핀별 마지막 수정자를 받아 "내가 고침 / 본인이 고침 / 다른 사람이 고침"을 참석자 목록에 보여 준다
- 경로선 색은 이동수단(car·transit·walk) 세 가지. 사람마다 색을 바꾸지 않는다
- 선이 겹치면 도보, 대중교통, 자동차 순으로 위에 온다. 자동차 선이 길고 굵어 나머지를 덮기 때문이다
- 참석자 4명 이하면 경로선 기본 켬, 5명 이상이면 기본 끔. 꺼져 있을 때 참석자 핀을 누르면 그 사람 것만 보인다
- `via_pickup`이 true인 참석자는 선을 그리지 않고 픽업 지점에 핀만 찍는다. 좌표는 `geocoded`의 `kind: "pickup"`, 없으면 그 사람 `polyline[0]`(탑승 지점)
- 핀 구성이 바뀌면(새 응답) bounds를 맞춘다. 드래그로는 다시 맞추지 않는다
- 출발지를 고치는 길은 셋이고 저장 경로는 하나다(`MapView`의 `onMove` → PATCH). 드래그는 사람을 고르지 않아도 되고, 지도 클릭과 장소 검색은 `PinPicker`에서 사람을 고른 뒤에만 동작한다. 사람을 고르지 않았거나 "지도 클릭으로 지정"을 켜지 않았으면 지도 클릭 리스너를 아예 달지 않는다(실수로 옮기는 것을 막는다)
- 장소 검색은 카카오 `services.Places().keywordSearch`. 결과는 5개까지, 없으면 "찾지 못했습니다". SDK URL에 `libraries=services`가 빠지면 검색만 죽는다
- mock 경로는 실제 API에서 받아 둔 값이다. mock에서 핀을 옮기면 그 사람 선은 두 점 직선이 된다(백엔드가 붙으면 다시 계산된다). 시나리오 좌표를 바꾸면 `python scripts/fetch_mock_routes.py --force`

## 지킬 것

- `components/` 안에서 fetch하지 않는다. 페이지가 `app/api/` 라우트만 부른다
- preset 값은 `meeting`(일반 약속)과 `visit`(출입 절차가 있는 방문) 둘뿐이다. 화면 라벨은 `app/page.tsx`, `components/ChatPanel.tsx`, `app/my/page.tsx` 세 곳에 있다
- 브라우저에 나가는 키는 `NEXT_PUBLIC_KAKAO_JS_KEY`와 Supabase publishable key뿐이다. 카카오 REST 키는 프론트에 없다
- 카카오맵 외 지도 라이브러리를 쓰지 않는다
- 서비스 전체가 로그인 뒤에 있다. 내 데이터를 읽는 익명 경로를 만들지 않는다. 첫 화면의 소개와 예시 결과만 예외이고(SDD 2절), 그것도 `lib/demo-preview.ts`의 고정값이라 서버를 부르지 않는다. Supabase 설정 없이 로그인을 건너뛰는 로컬 모드는 `next dev`에서만 켜지고(백엔드는 `AUTH_REQUIRED=false`), 배포 빌드에서는 화면이 막힌다
- 환경변수는 `frontend/.env.local` (루트 `.env`와 별개). `NEXT_PUBLIC_API_BASE`가 없으면 `lib/mock.ts`로 답한다
- 즉각 피드백, 오류 안내, 입력 가이드 세 가지가 화면에 있어야 한다 (가이드 8-3). 실패 화면은 데모 영상에 필요하다
- 실제 기관명·회사명을 예시 문구에 쓰지 않는다. 예시는 "창원 사무소", "여의도 사무실" 수준까지만
- `next.config.ts`의 `agentRules: false`를 지우지 않는다. 지우면 `next dev`가 이 폴더에 AGENTS.md, CLAUDE.md를 만든다

## PWA (09-21 결정)

`public/manifest.json`, `public/sw.js`, `public/offline.html`, 아이콘 3개. 홈 화면에 설치되고
주소창 없이 뜨는 것까지다. **오프라인 동작은 하지 않는다.** 지도·경로·계산이 전부 네트워크다.

`sw.js`는 일부러 아무것도 캐시하지 않는다. 화면을 캐시하면 배포한 새 화면 대신 옛 화면이
남는 사고가 난다. 하는 일은 설치 조건을 채우는 것과, 연결이 끊겼을 때 흰 화면 대신
`offline.html`을 보여주는 것뿐이다.

테마색(`#2d6a4f`)과 아이콘은 `app/globals.css`의 `--accent`와 맞춘다. 색을 바꾸면
`manifest.json`, `app/layout.tsx`의 `viewport.themeColor`, `offline.html` 세 곳을 같이 고친다.

## 개인정보처리방침·약관 (10-20)

`public/privacy.html`, `public/terms.html`. 구글 로그인 앱을 프로덕션으로 게시하려면 구글 브랜딩에 두 링크가 있어야 한다.
수집 항목·처리 업체·보관 기간이 바뀌면(예: 새 외부 API, 테이블정의서 6절 변경) 같이 고친다.

## 설정 파일

- `package.json`, `tsconfig.json`: Next 16, React 19, TypeScript. 지도 외 UI 라이브러리를 넣지 않는다
- `next.config.ts`: `agentRules: false`
- `.env.example`: 브라우저에 나가는 값만. 실제 값은 `.env.local`(커밋 금지). 값을 비웠을 때 어떻게 도는지는 그 파일 주석에 있다

## 실행

`cd frontend && npm install && npm run dev` (:3000). 카카오 콘솔 > 플랫폼 > Web에 `http://localhost:3000`과 Vercel 도메인을 등록해야 지도가 뜬다.
