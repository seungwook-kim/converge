"use client";

// public/sw.js 를 등록한다. 이게 있어야 홈 화면에 설치할 수 있다 (SDD 2절 09-21 PWA 결정).
// 실패해도 서비스는 그대로 돈다. 설치가 안 될 뿐이다.

import { useEffect } from "react";

export default function ServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    // 개발 중에는 등록하지 않는다. 고친 화면 대신 옛 화면이 남아 디버깅이 꼬인다
    if (process.env.NODE_ENV !== "production") return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // 설치 기능만 빠진다. 사용자에게 알릴 것이 없다
    });
  }, []);
  return null;
}
