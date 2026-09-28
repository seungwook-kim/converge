"use client";

// 참석자별 경로선 (per_participant[].polyline).
// 색은 사람마다, 모양은 이동수단마다 다르다 (09-28). 전에는 이동수단 세 가지 색뿐이라 대중교통으로 오는 사람이
// 여럿이면 모두 같은 초록이었고, 카카오 바탕의 도로(주황·빨강)·공원(초록)과도 섞였다.

import { useEffect } from "react";
import type { Kakao } from "@/lib/kakao";
import type { ParticipantResult, RendezvousLeg, Transport } from "@/types/agent";

// 이동수단은 선 모양으로 가른다. color 는 사람 색을 모를 때(집결지 무리 구간 등)만 쓴다.
// layer: 겹칠 때 위에 올라오는 순서. 자동차 선은 길고 굵어 대중교통·도보 선을 덮기 쉽다
export const ROUTE_STYLES: Record<Transport, { color: string; label: string; style: string; layer: number }> = {
  car: { color: "#334155", label: "자동차", style: "solid", layer: 1 },
  transit: { color: "#334155", label: "대중교통", style: "solid", layer: 2 },
  walk: { color: "#334155", label: "도보", style: "shortdash", layer: 3 },
};

// 사람 색. 카카오 바탕의 도로(주황·노랑)·공원(초록)·물(하늘)과 겹치지 않는 색만 쓴다. 앞 셋끼리 가장 멀다
export const PERSON_COLORS = ["#2563eb", "#c026d3", "#0d9488", "#dc2626", "#7c3aed", "#92400e", "#db2777", "#1e3a8a"];

// 참석자 순서(슬롯 순서)로 색을 고정한다. 후보를 바꿔도 같은 사람은 같은 색이다
export function personColor(names: string[], name: string): string {
  const index = names.indexOf(name);
  return PERSON_COLORS[(index < 0 ? 0 : index) % PERSON_COLORS.length];
}

interface Props {
  kakao: Kakao;
  map: Kakao;
  rows: ParticipantResult[];
  highlighted: string | null;
  names?: string[]; // 참석자 순서. 사람 색을 정한다
  // 두 단계 집결의 집결지 → 후보 구간. 여럿이 함께 가는 길이라 굵은 점선으로 구분한다 (09-27)
  legs?: RendezvousLeg[];
}

export const GROUP_LEG_STYLE = { style: "dash", weight: 7, label: "집결지에서 함께 이동" };

export default function RouteLines({ kakao, map, rows, highlighted, legs = [], names = [] }: Props) {
  useEffect(() => {
    const lines = rows
      .filter((r) => r.polyline.length > 1)
      .flatMap((r) => {
        const s = ROUTE_STYLES[r.transport];
        const path = r.polyline.map(([lng, lat]) => new kakao.maps.LatLng(lat, lng));
        const on = highlighted === r.name;
        const dim = Boolean(highlighted) && !on;
        const weight = on ? 7 : 5;
        // 흰 테두리를 먼저 깐다. 지도 위 도로색에 묻히지 않게 한다
        const casing = new kakao.maps.Polyline({
          map,
          path,
          strokeWeight: weight + 4,
          strokeColor: "#ffffff",
          strokeOpacity: dim ? 0.3 : 0.9,
          strokeStyle: "solid",
          zIndex: on ? 9 : s.layer,
        });
        const line = new kakao.maps.Polyline({
          map,
          path,
          strokeWeight: weight,
          strokeColor: personColor(names, r.name),
          strokeOpacity: dim ? 0.35 : 0.95,
          strokeStyle: s.style,
          zIndex: on ? 10 : s.layer,
        });
        return [casing, line];
      });
    const groupLines = legs
      .filter((leg) => leg.polyline.length > 1)
      .map(
        (leg) =>
          new kakao.maps.Polyline({
            map,
            path: leg.polyline.map(([lng, lat]) => new kakao.maps.LatLng(lat, lng)),
            strokeWeight: GROUP_LEG_STYLE.weight,
            strokeColor: ROUTE_STYLES[leg.transport].color,
            strokeOpacity: highlighted ? 0.35 : 0.9,
            strokeStyle: GROUP_LEG_STYLE.style,
            zIndex: 4,
          }),
      );
    return () => [...lines, ...groupLines].forEach((line) => line.setMap(null));
  }, [kakao, map, rows, highlighted, legs, names]);

  return null;
}
