"use client";

// 로그인 전에 보여 주는 예시 결과 (SDD 2절 09-21 예외).
//
// 결과 화면과 같은 ResultTable 을 그대로 쓴다. 따로 그리면 예시와 실물이 갈라지고,
// 갈라지는 순간 첫인상이 거짓말이 된다.
//
// 지도는 넣지 않는다. 카카오 SDK 를 첫 화면에서 불러야 하고, 도메인 등록이 안 된 곳에서는
// 그 자리가 빈 회색 칸으로 남아 오히려 고장으로 보인다. 지도는 로그인 뒤 결과 화면에 있다.

import { useState } from "react";
import ResultTable from "@/components/ResultTable";
import { DEMO_PARTICIPANTS, DEMO_RESULT, DEMO_SENTENCE } from "@/lib/demo-preview";

export default function DemoPreview() {
  const [rank, setRank] = useState<number | null>(1);

  return (
    <section className="demo" aria-label="예시 결과">
      <p className="demo-label">
        <span className="badge">예시</span>
        아래는 실제 화면입니다. 눌러 볼 수 있고, 저장되지 않습니다.
      </p>

      <div className="demo-input">
        <span className="demo-input-cap">넣은 문장</span>
        <p>{DEMO_SENTENCE}</p>
      </div>

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
        실제 화면에는 지도와 경로선, 대화방에 붙여넣을 집결 계획서가 함께 나옵니다.
      </p>
    </section>
  );
}
