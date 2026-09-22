"use client";

// 로그인 뒤에만 children 을 보여준다. 내 데이터를 읽는 익명 경로는 없다 (SDD 2절).
//
// preview 는 로그인 전에 벽 위에 얹어 두는 것이다 (SDD 2절 09-21 예외). 고정 데이터라
// 서버를 부르지 않는다. 무엇을 해주는 도구인지 모른 채 로그인부터 요구받으면 그 자리에서 나간다.

import type { ReactNode } from "react";
import { signInWithGoogle, signOut, type AuthState } from "@/lib/auth";

interface Props {
  auth: AuthState;
  reason: string;
  preview?: ReactNode;
  children: ReactNode;
}

export default function AuthGate({ auth, reason, preview, children }: Props) {
  if (auth.status === "loading") {
    return <div className="gate">로그인 상태를 확인하는 중…</div>;
  }
  if (auth.status === "misconfigured") {
    return (
      <div className="gate">
        <p>로그인 설정이 없어 서비스를 열 수 없습니다.</p>
        <p className="muted">NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY 를 확인하세요.</p>
      </div>
    );
  }
  if (auth.status === "signed_out") {
    return (
      /* 한 덩어리로 감싼다. 첫 화면이 2열 그리드라 형제로 두면 칸이 어긋난다 */
      <div className="gate-stack">
        {preview}
        <div className="gate">
          <p>{reason}</p>
          <button type="button" className="primary" onClick={() => void signInWithGoogle()}>
            구글로 로그인하고 시작하기
          </button>
          <p className="muted">계획을 만들고 링크로 공유하려면 로그인이 필요합니다.</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

export function UserBar({ auth }: { auth: AuthState }) {
  // 로그인 전에도 상단바에 버튼을 둔다. 아래 카드까지 스크롤해야만 로그인할 수 있으면,
  // 예시를 다 읽을 생각이 없는 사람은 들어올 길이 없다 (09-21)
  if (auth.status === "signed_out") {
    return (
      <span className="userbar">
        <button type="button" className="primary topbar-cta" onClick={() => void signInWithGoogle()}>
          구글로 시작하기
        </button>
      </span>
    );
  }
  if (auth.status !== "signed_in") return null;
  return (
    <span className="userbar">
      {auth.local ? (
        <span className="badge badge-warn">로컬 모드 · 인증 없음</span>
      ) : (
        <button type="button" className="link" onClick={() => void signOut()}>
          로그아웃
        </button>
      )}
    </span>
  );
}
