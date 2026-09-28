import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // next dev 가 frontend/AGENTS.md, CLAUDE.md 를 만들지 않게 한다. AI 규칙은 루트 CLAUDE.md 하나다
  agentRules: false,
  // 개발 서버 왼쪽 아래 "N" 표시를 끈다. 화면 확인·캡처에 끼어든다 (09-28). 배포 빌드에는 원래 없다
  devIndicators: false,
};

export default nextConfig;
