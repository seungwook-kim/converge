"use client";

// 구글 로그인(Supabase Auth). 서비스 전체가 로그인 뒤에 있다 (SDD 2절).
// Supabase 설정이 없을 때 로그인 없이 쓰는 로컬 모드는 개발 서버(next dev)에서만 켜진다.
// 이 경우 백엔드도 AUTH_REQUIRED=false 여야 한다. 배포 빌드에서 설정이 없으면 화면이 막힌다.

import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { LOCAL_USER_ID } from "@/lib/dev-user";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
// Supabase 가 anon 키를 publishable 키로 바꿨다. 둘 다 받는다. 새로 만든 프로젝트는 publishable 쪽이다.
// 이름 하나가 어긋나면 로그인이 조용히 꺼진 채로 배포된다 (09-21: 코드와 .env.example 이 서로 달랐다)
const publishableKey =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const authConfigured = Boolean(url && publishableKey);
export const localMode = !authConfigured && process.env.NODE_ENV !== "production";

// 구글 직접 로그인 (10-20, SDD 9절). 구글에서 이 사이트(origin + "/")로 바로 돌아오게 해서
// 계정 선택 화면에 supabase.co 대신 이 사이트 주소가 뜨게 한다. 주소 # 뒤의 id_token 을 signInWithIdToken 으로 넘긴다.
// nonce 는 구글에 해시를, Supabase 에 원문을 준다. 비어 있으면 Supabase 콜백을 거치는 예전 방식.
const googleClientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
const GOOGLE_STATE_KEY = "converge.google.state";
const GOOGLE_NONCE_KEY = "converge.google.nonce";
const GOOGLE_RETURN_KEY = "converge.google.return";

type GoogleReturn = { idToken: string; nonce: string; back: string } | { error: string };
let googleReturn: GoogleReturn | null | undefined;

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

// 구글에서 돌아온 주소면 # 뒤를 꺼내고 지운다. Supabase 클라이언트가 주소를 읽기 전에 불러야 한다
function takeGoogleReturn(): GoogleReturn | null {
  if (googleReturn !== undefined) return googleReturn;
  googleReturn = null;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const state = params.get("state");
  if (!state?.startsWith("g_")) return null;
  const store = storage();
  const expected = store?.getItem(GOOGLE_STATE_KEY);
  const nonce = store?.getItem(GOOGLE_NONCE_KEY);
  const back = store?.getItem(GOOGLE_RETURN_KEY) || "/";
  store?.removeItem(GOOGLE_STATE_KEY);
  store?.removeItem(GOOGLE_NONCE_KEY);
  store?.removeItem(GOOGLE_RETURN_KEY);
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  const idToken = params.get("id_token");
  if (params.get("error") || !idToken) googleReturn = { error: "구글 로그인을 취소했거나 마치지 못했습니다" };
  else if (state !== expected || !nonce) googleReturn = { error: "로그인 확인에 실패했습니다. 다시 시도해 주세요" };
  else googleReturn = { idToken, nonce, back: back.startsWith("/") && !back.startsWith("//") ? back : "/" };
  return googleReturn;
}

function randomHex(bytes = 16): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

let client: SupabaseClient | null = null;
function supabase(): SupabaseClient | null {
  if (!authConfigured) return null;
  if (!client) {
    takeGoogleReturn();
    client = createClient(url as string, publishableKey as string);
  }
  return client;
}

export type AuthState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "misconfigured" }
  | { status: "signed_in"; userId: string; token: string | null; local: boolean };

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>(() =>
    localMode
      ? { status: "signed_in", userId: LOCAL_USER_ID, token: null, local: true }
      : authConfigured
        ? { status: "loading" }
        : { status: "misconfigured" },
  );

  useEffect(() => {
    const sb = supabase();
    if (!sb) return;
    const apply = (session: Session | null) =>
      setState(
        session
          ? { status: "signed_in", userId: session.user.id, token: session.access_token, local: false }
          : { status: "signed_out" },
      );
    const back = takeGoogleReturn();
    // 구글 토큰을 넘기는 동안에는 로그인 화면이 비치지 않게 loading 으로 둔다
    let pending = Boolean(back && "idToken" in back);
    const { data } = sb.auth.onAuthStateChange((_event, session) => {
      if (!pending) apply(session);
    });
    if (back && "idToken" in back) {
      sb.auth
        .signInWithIdToken({ provider: "google", token: back.idToken, nonce: back.nonce })
        .then(({ data: res }) => {
          // 로그인 버튼을 누른 화면(예: 공유 링크 /s/{id})으로 되돌린다. 구글은 항상 "/" 로 돌려보낸다
          if (res.session && back.back !== window.location.pathname + window.location.search) {
            window.location.replace(back.back);
            return;
          }
          pending = false;
          apply(res.session);
        })
        .catch(() => {
          pending = false;
          apply(null);
        });
    } else {
      sb.auth.getSession().then(({ data: res }) => apply(res.session));
    }
    return () => data.subscription.unsubscribe();
  }, []);

  return state;
}

export async function signInWithGoogle(): Promise<void> {
  const sb = supabase();
  if (!sb) return;
  const store = storage();
  if (googleClientId && store) {
    const nonce = randomHex();
    const state = "g_" + randomHex();
    store.setItem(GOOGLE_NONCE_KEY, nonce);
    store.setItem(GOOGLE_STATE_KEY, state);
    store.setItem(GOOGLE_RETURN_KEY, window.location.pathname + window.location.search);
    const params = new URLSearchParams({
      client_id: googleClientId,
      redirect_uri: window.location.origin + "/",
      response_type: "id_token",
      scope: "openid email profile",
      nonce: await sha256Hex(nonce),
      state,
      prompt: "select_account",
    });
    window.location.assign("https://accounts.google.com/o/oauth2/v2/auth?" + params.toString());
    return;
  }
  await sb.auth.signInWithOAuth({
    provider: "google",
    // 해시는 뺀다. 지난 로그인의 #access_token 이 남아 있으면 새 토큰이 그 뒤에 붙어 세션을 못 읽는다 (09-27)
    options: { redirectTo: window.location.origin + window.location.pathname + window.location.search },
  });
}

export async function signOut(): Promise<void> {
  await supabase()?.auth.signOut();
}

export function authHeaders(auth: AuthState): Record<string, string> {
  if (auth.status === "signed_in" && auth.token) {
    return { Authorization: `Bearer ${auth.token}` };
  }
  return {};
}
