"use client";

// 메인. 로그인하고, 무엇을 하는 서비스인지 읽고, 문장 하나를 넣는 곳이다.
// 지도는 여기에 없다. 계획이 만들어지면 /s/{id} 로 옮겨 가고, 그 주소가 참석자들이 모이는 자리다.
// 되묻기와 핀 확인도 거기서 한다 (09-20 화면 구조 결정).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import AuthGate, { UserBar } from "@/components/AuthGate";
import DemoPreview from "@/components/DemoPreview";
import { captureBase64, MAX_CAPTURE_BYTES } from "@/lib/capture";
import { DEMO_SENTENCE } from "@/lib/demo-preview";
import { authHeaders, useAuth, type AuthState } from "@/lib/auth";
import type { AgentResponse, Preset } from "@/types/agent";

// 일상 약속부터 보인다. 처음에는 현장 방문용 예시 두 개뿐이었다 (09-28: 일반 약속으로 넓힌 뒤에도 남아 있었다)
const EXAMPLES = [
  "토요일 저녁 7시 강남역 근처에서 친구들이랑 고기 먹기로 했어. 나는 수원역에서 지하철, 민수는 잠실역에서 지하철로 와.",
  "일요일 오후 1시까지 거제 장승포항. 사상역 3명은 11시에 가덕휴게소에서 모여서 같이 차로 가고, 창원역 2명은 차로 바로 와.",
  "목요일 오후 2시 여의도 사무실 미팅. 저는 강남역에서 지하철, 박대리는 판교역에서 차로 옵니다. 방문자 등록은 해 뒀습니다.",
];

export default function Home() {
  const auth = useAuth();
  return (
    <main className="app landing">
      <header className="topbar">
        <strong>Converge</strong>
        <span className="muted">모일 자리와 시각 정하기</span>
        {/* 로그인 전에는 감춘다. 눌러 봐야 또 로그인 벽이라 막다른 골목이다 */}
        {auth.status === "signed_in" && (
          <Link href="/my" className="topbar-link">
            내 계획
          </Link>
        )}
        <UserBar auth={auth} />
      </header>
      <div className="landing-body">
        <Intro signedIn={auth.status === "signed_in"} />
        <AuthGate
          auth={auth}
          reason="여기까지가 예시입니다. 내 상황으로 만들려면 로그인하세요."
          preview={<DemoPreview />}
        >
          <Compose auth={auth} />
        </AuthGate>
      </div>
    </main>
  );
}

// 로그인 전에도 보인다 (SDD 2절 09-21 예외). 무엇을 해주는 도구인지 모른 채
// 로그인부터 요구받으면 그 자리에서 나간다.
function Intro({ signedIn }: { signedIn: boolean }) {
  return (
    <section className="intro">
      <h1>모이는 자리와 시각을 문장 하나로 정합니다</h1>
      <p>
        여러 사람이 각자 다른 곳에서 오고, 가는 곳에 출입증이나 방문자 등록이 필요하면 모일 자리가 달라집니다.
        Converge 는 그 절차까지 계산해 집결지와 참석자별 출발 시각을 냅니다.
      </p>
      <ol className="how">
        <li>
          <strong>문장을 넣습니다.</strong> 누가 어디서 무엇을 타고 오는지, 언제 어디서 하는 일인지
        </li>
        <li>
          <strong>링크가 만들어집니다.</strong> 그 주소를 단톡방에 전달합니다
        </li>
        <li>
          <strong>참석자들이 모입니다.</strong> 링크에서 각자 출발지를 고치고 결과를 함께 봅니다
        </li>
      </ol>
      <p className="muted">
        더 자세한 설명은 <Link href="/about">무엇을 해주는 도구인지</Link> 에 있습니다.
      </p>
      {/* 로그인 전에만. 결과 지도가 어떻게 생겼는지 보여 준다. 오른쪽 예시 표와 같은 실행에서 찍었다 (09-28) */}
      {!signedIn && (
        <figure className="intro-map">
          <img
            src="/demo-map.webp"
            width={800}
            height={564}
            alt="예시 지도: 수원·인천·의정부에서 출발하는 세 사람의 핀과 사람별 색 경로선, 1순위 집결지 여의나루역"
            loading="lazy"
          />
          <figcaption className="muted">
            결과 화면에는 이렇게 참석자 핀과 사람마다 다른 색의 경로선, 1순위 집결지가 찍힙니다. 지도 © Kakao
          </figcaption>
        </figure>
      )}
      {!signedIn && (
        <div className="intro-demo">
          <p className="demo-label">
            <span className="badge">예시</span>
            위 이미지는 실제 화면입니다.
          </p>
          <div className="demo-input">
            <span className="demo-input-cap">넣은 문장</span>
            <p>{DEMO_SENTENCE}</p>
          </div>
        </div>
      )}
    </section>
  );
}

function Compose({ auth }: { auth: AuthState }) {
  const router = useRouter();
  const headerKey = JSON.stringify(authHeaders(auth));
  const [text, setText] = useState("");
  const [preset, setPreset] = useState<Preset | "">("");
  const [image, setImage] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileRef = useRef<HTMLInputElement>(null);

  const pickImage = (file: File | null) => {
    setError(null);
    // 파일 칸을 비워 둬야 뺀 캡처를 다시 골라도 onChange 가 온다
    if (fileRef.current) fileRef.current.value = "";
    if (!file) return setImage(null);
    if (!["image/png", "image/jpeg"].includes(file.type)) {
      setError("PNG 또는 JPG 캡처만 올릴 수 있습니다");
      return;
    }
    if (file.size > MAX_CAPTURE_BYTES) {
      setError("캡처가 5MB 를 넘습니다");
      return;
    }
    setImage(file);
  };

  const submit = async () => {
    const trimmed = text.trim();
    if (busy || (!trimmed && !image)) return;
    setBusy(true);
    setSlow(false);
    setError(null);
    // 서버가 요청이 없으면 잠든다(Modal, 5분 쉬면 0대). 깨우는 데 10초 안팎 걸리는데
    // 아무 말이 없으면 고장으로 보인다. 12초를 넘기면 그렇다고 알려 준다
    const slowTimer = setTimeout(() => setSlow(true), 12000);
    try {
      const image_base64 = image ? await captureBase64(image) : null;
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...JSON.parse(headerKey) },
        body: JSON.stringify({
          session_id: null,
          text: trimmed || null,
          image_base64,
          preset: preset || null,
          confirmed_participants: null,
        }),
      });
      if (res.status === 401) throw new Error("로그인이 만료됐습니다. 다시 로그인해 주세요.");
      if (!res.ok) throw new Error(`요청이 실패했습니다 (${res.status}). 잠시 후 다시 시도해 주세요.`);
      const data = (await res.json()) as AgentResponse;

      if (data.stage === "out_of_scope") {
        setError(data.message);
        return;
      }
      if (!data.session_id) {
        // 서버 문구를 먼저 쓴다. LLM 시간 초과·한도 초과도 여기로 오는데 "더 자세히" 를 내면
        // 사용자는 멀쩡한 문장을 고쳐 쓴다 (서버는 "잠시 뒤 다시 시도" 로 구분해 준다)
        setError(data.message || "계획을 만들지 못했습니다. 문장을 조금 더 자세히 적어 주세요.");
        return;
      }
      // 첫 응답을 넘겨 두면 다음 화면이 서버에 다시 묻지 않고 바로 그린다 (되묻기 문구 포함)
      try {
        sessionStorage.setItem(`converge:first:${data.session_id}`, JSON.stringify(data));
      } catch {
        // 저장이 막혀 있어도 /s/{id} 가 서버에서 다시 읽는다
      }
      router.push(`/s/${data.session_id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      clearTimeout(slowTimer);
      setBusy(false);
      setSlow(false);
    }
  };

  return (
    <section className="compose">
        <label className="compose-label" htmlFor="text">
          상황을 적어 주세요
        </label>
        <textarea
          id="text"
          value={text}
          maxLength={1000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={5}
          placeholder="예: 토요일 저녁 7시 강남역에서 고기. 나는 수원역에서 지하철, 민수는 잠실역에서 차로 와"
        />

        <div className="compose-row">
          <select value={preset} onChange={(e) => setPreset(e.target.value as Preset | "")} aria-label="약속 종류">
            <option value="">약속 종류 자동</option>
            <option value="meeting">일반 약속</option>
            <option value="visit">방문 (출입 절차 있음)</option>
          </select>
          <label className="file-btn">
            카톡 캡처 올리기
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => pickImage(e.target.files?.[0] ?? null)}
            />
          </label>
          {image && (
            <button type="button" className="link" onClick={() => pickImage(null)}>
              {image.name} 빼기
            </button>
          )}
          <button
            type="button"
            className="primary"
            disabled={busy || (!text.trim() && !image)}
            onClick={() => void submit()}
          >
            {busy ? "만드는 중…" : "계획 만들기"}
          </button>
        </div>

        {busy && !slow && <p className="muted">문장을 읽고 위치를 찾는 중입니다. 10초쯤 걸립니다.</p>}
        {busy && slow && (
          <p className="muted">
            서버를 깨우는 중입니다. 한동안 아무도 쓰지 않으면 잠들기 때문에 첫 요청만 오래 걸립니다.
          </p>
        )}
        {error && <p className="error">{error}</p>}

        <div className="examples">
          <span className="muted">이렇게 적어도 됩니다</span>
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="example" onClick={() => setText(example)}>
              {example}
            </button>
          ))}
        </div>
    </section>
  );
}
