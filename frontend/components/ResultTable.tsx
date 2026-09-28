"use client";

// done 결과 표. 집결 후보(순위·근거)와 선택한 후보 기준 참석자별 출발 시각·소요시간·여유·첫차.
// 아래에 세 칸을 더 둔다: 선택되지 않은 후보와 그 이유, 준비물, 붙여넣을 집결 계획서.
// 세 칸 모두 서버가 이미 만들어 보낸 값을 꺼내 놓기만 한다. 화면에서 다시 계산하지 않는다.

import { useState } from "react";
import type { Participant, Result } from "@/types/agent";
import { CANDIDATE_STYLES } from "./MapView";
import { ROUTE_STYLES, personColor } from "./RouteLines";

interface Props {
  result: Result;
  participants: Participant[];
  selectedRank: number | null;
  onSelectRank: (rank: number) => void;
  // 첫 화면 예시용. 집결 후보와 출발 시각까지만 보인다 (SDD 2절 09-21 예외).
  // 탈락 이유는 후보 목록에 이미 붙어 있어 아래 칸이 같은 말을 두 번 하고,
  // 계획서 전문은 그 하나로 화면 두 개를 밀어낸다. 결과 화면에서는 둘 다 나온다
  compact?: boolean;
  rendezvousName?: string | null; // 두 단계 집결의 집결지 이름. 표에 "OO 집결" 로 적는다 (09-27)
}

function basis(p: Participant | undefined, viaPickup: boolean, viaRendezvous: boolean, gather?: string | null): string {
  if (viaPickup && p?.pickup) {
    const ride = `${p.pickup} 님 차로 ${p.pickup_at ?? "픽업 지점"}에서 탑승`;
    return viaRendezvous && gather ? `${ride}, ${gather} 집결` : ride;
  }
  if (viaRendezvous) return gather ? `${gather}에 먼저 모임 (도착 기한은 집결 시각)` : "집결지를 거쳐 이동";
  return "출발지에서 바로 이동";
}

export default function ResultTable({
  result,
  participants,
  selectedRank,
  onSelectRank,
  compact = false,
  rendezvousName = null,
}: Props) {
  const ranked = [...result.candidates].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const current = result.candidates.find((c) => c.rank === selectedRank) ?? null;
  const rows = result.per_participant.filter((r) => r.candidate_rank === selectedRank);

  return (
    <section className="result">
      {result.provisional && <div className="badge badge-warn">시각 미확정, 잠정</div>}

      <h3>집결 후보</h3>
      <ol className="candidates">
        {ranked.map((c) => (
          <li key={c.name}>
            <button
              type="button"
              className={`cand ${c.rank === selectedRank ? "active" : ""}`}
              disabled={c.rank === null}
              onClick={() => c.rank !== null && onSelectRank(c.rank)}
            >
              <span className="cand-rank" style={{ background: CANDIDATE_STYLES[c.kind].fill }}>
                {c.rank ?? "-"}
              </span>
              <span className="cand-body">
                <strong>{c.name}</strong>
                <span className="muted">
                  {" "}
                  {CANDIDATE_STYLES[c.kind].label}
                  {c.access_ok ? "" : " · 출입 절차상 지금은 불가"}
                </span>
                {c.switched_from && <span className="muted"> · {c.switched_from}에서 전환</span>}
                <span className="reason">{c.reason}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>

      {current && rows.length > 0 && (
        <>
          <h3>
            {current.name} 기준 출발 시각
            {result.rendezvous_departure && (
              <span className="muted">
                {" "}
                · {rendezvousName ?? "집결지"} 출발 {result.rendezvous_departure}
              </span>
            )}
          </h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>참석자</th>
                  <th>이동</th>
                  <th>출발</th>
                  <th>소요</th>
                  <th>여유</th>
                  <th>도착 기한</th>
                  <th>첫차·막차</th>
                  <th>근거</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const p = participants.find((x) => x.name === r.name);
                  return (
                    <tr key={r.name}>
                      <td>{r.name}</td>
                      <td>
                        <span className="dot" style={{ background: personColor(participants.map((x) => x.name), r.name) }} />
                        {ROUTE_STYLES[r.transport].label}
                        {r.transfer_count !== null && r.transport === "transit" && ` · 환승 ${r.transfer_count}`}
                      </td>
                      <td className="strong">{r.departure_time}</td>
                      <td>
                        {r.duration_min}분 <span className="muted">(경로 {r.raw_duration_min}분)</span>
                      </td>
                      <td>{r.buffer_min}분</td>
                      <td>{r.arrive_by}</td>
                      <td>
                        {r.first_train || r.last_train ? `${r.first_train ?? "-"} / ${r.last_train ?? "-"}` : "-"}
                        {/* 야간에 지하철이 끊기거나 조회를 못 했으면 그 칸에서 바로 보이게 한다 */}
                        {r.train_note && <div className="error">{r.train_note}</div>}
                      </td>
                      <td>{basis(p, r.via_pickup, r.via_rendezvous, rendezvousName)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {current && rows.length === 0 && <p className="muted">이 후보에 대한 참석자별 계산이 없습니다.</p>}

      {!compact && <RejectedList result={result} />}
      <ChecklistBox result={result} />
      {!compact && <SummaryBox text={result.summary_text} />}
    </section>
  );
}

function RejectedList({ result }: { result: Result }) {
  // 왜 저기는 안 되는지를 말하지 않으면 현장에서 바로 되묻는다. 이유는 서버가 규칙 파일을 인용해 넣는다
  const rejected = result.candidates
    .filter((c) => c.rejected_reason)
    .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  if (rejected.length === 0) return null;
  return (
    <>
      <h3>선택되지 않은 후보</h3>
      <ul className="rejected">
        {rejected.map((c) => (
          <li key={c.name}>
            <strong>{c.name}</strong>
            {c.access_ok ? "" : <span className="badge badge-warn">출입 불가</span>}
            <span className="reason muted">{c.rejected_reason}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function ChecklistBox({ result }: { result: Result }) {
  // 절차를 모르면(checklist 가 null) 아무 말도 하지 않는다. 없다고 말하는 것과 다르다
  const list = result.checklist;
  if (!list || (list.before.length === 0 && list.onsite.length === 0)) return null;
  return (
    <>
      <h3>준비물</h3>
      <div className="checklist">
        {list.before.length > 0 && (
          <div>
            <h4>미리 해둘 것</h4>
            <ul>
              {list.before.map((item) => (
                <li key={item} className={item.startsWith("[미완료]") ? "todo" : undefined}>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}
        {list.onsite.length > 0 && (
          <div>
            <h4>당일 챙길 것</h4>
            <ul>
              {list.onsite.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </>
  );
}

function SummaryBox({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  if (!text) return null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <>
      <h3>
        집결 계획서
        <button type="button" className="copy" onClick={copy}>
          {copied ? "복사함" : "복사"}
        </button>
      </h3>
      <pre className="summary">{text}</pre>
    </>
  );
}
