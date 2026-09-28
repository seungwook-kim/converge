"use client";

// 로그인 전에 보여 주는 예시 결과 (SDD 2절 09-21 예외).
//
// 결과 화면과 같은 ResultTable 을 그대로 쓴다. 따로 그리면 예시와 실물이 갈라지고,
// 갈라지는 순간 첫인상이 거짓말이 된다.
//
// 지도는 여기 넣지 않는다. 캡처 이미지(public/demo-map.webp)는 왼쪽 소개 아래에 둔다 (app/page.tsx Intro, 09-28).
// 살아 있는 카카오 지도는 도메인 등록이 안 된 곳에서 빈 회색 칸으로 남아 고장으로 보인다.

import { useState } from "react";
import ResultTable from "@/components/ResultTable";
import { DEMO_PARTICIPANTS, DEMO_RESULT } from "@/lib/demo-preview";

export default function DemoPreview() {
  const [rank, setRank] = useState<number | null>(1);

  return (
    <section className="demo" aria-label="예시 결과">
      {/* "예시" 표시와 넣은 문장은 왼쪽 지도 아래로 옮겼다 (app/page.tsx Intro, 09-28) */}
      <div className="demo-output">
        <ResultTable
          result={DEMO_RESULT}
          participants={DEMO_PARTICIPANTS}
          selectedRank={rank}
          onSelectRank={setRank}
          compact
        />
      </div>

      {/* 잘라낸 것을 숨기지 않고 말한다. 예시가 전부인 줄 알면 기대가 어긋난다 */}
      <p className="demo-more muted">
        실제 화면에서는 지도를 움직이고 핀을 옮길 수 있고, 대화방에 붙여넣을 집결 계획서가 함께 나옵니다.
      </p>
    </section>
  );
}
