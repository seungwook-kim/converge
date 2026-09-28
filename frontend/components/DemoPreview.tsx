"use client";

// 로그인 전에 보여 주는 예시 결과 (SDD 2절 09-21 예외).
//
// 결과 화면과 같은 ResultTable 을 그대로 쓴다. 따로 그리면 예시와 실물이 갈라지고,
// 갈라지는 순간 첫인상이 거짓말이 된다.
//
// 지도는 살아 있는 지도 대신 캡처 이미지로 보인다(public/demo-map.webp, 09-28). 카카오 SDK 를 첫 화면에서
// 부르면 도메인 등록이 안 된 곳에서 빈 회색 칸으로 남아 고장으로 보인다. 캡처는 아래 표와 같은 실행에서 찍었다.

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

      <figure className="demo-map">
        <img
          src="/demo-map.webp"
          width={740}
          height={570}
          alt="예시 지도: 수원·인천·의정부에서 출발하는 세 사람의 핀과 이동수단별 경로선, 1순위 집결지 여의나루역"
          loading="lazy"
        />
        <figcaption className="muted">
          결과 화면의 지도. 참석자 핀, 이동수단별 경로선(빨강 자동차, 초록 대중교통), 1순위 집결지가 찍힌다. 지도 © Kakao
        </figcaption>
      </figure>

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
