// POST /api/agent 프록시. 키와 백엔드 주소는 여기서 멈춘다.

import { NextResponse } from "next/server";
import { mockAgent } from "@/lib/mock";
import { apiBase, forward, mockUser, unauthorized } from "@/lib/proxy";
import type { AgentRequest } from "@/types/agent";

// Vercel 함수 실행 시간 한도(초). 기본값에 맡기면 계정 설정에 따라 짧게 끊길 수 있다.
// 콜드 스타트 첫 요청이 18초, LLM 은 호출당 30초까지 기다린다 (docs/measurements.md 10-20, llm.LLM_TIMEOUT_SEC).
// 60초는 Vercel 모든 요금제에서 허용되는 값이다
export const maxDuration = 60;

export async function POST(req: Request): Promise<Response> {
  if (apiBase()) return forward(req, "/api/agent", "POST");

  if (!mockUser(req)) return unauthorized();
  let body: AgentRequest;
  try {
    body = (await req.json()) as AgentRequest;
  } catch {
    return NextResponse.json({ detail: "요청 본문이 JSON 이 아닙니다" }, { status: 400 });
  }
  if (!body.text && !body.image_base64) {
    return NextResponse.json({ detail: "text 또는 image_base64 가 필요합니다" }, { status: 422 });
  }
  await new Promise((r) => setTimeout(r, 400)); // 진행 표시 확인용 지연
  return NextResponse.json(mockAgent(body));
}
