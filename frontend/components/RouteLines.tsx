"use client";

// 참석자별 경로선 (per_participant[].polyline). 색은 이동수단 세 가지뿐이고 사람마다 바꾸지 않는다.

import { useEffect } from "react";
import type { Kakao } from "@/lib/kakao";
import type { ParticipantResult, RendezvousLeg, Transport } from "@/types/agent";

// layer: 겹칠 때 위에 올라오는 순서. 자동차 선은 길고 굵어 대중교통·도보 선을 덮기 쉽다
export const ROUTE_STYLES: Record<Transport, { color: string; label: string; style: string; layer: number }> = {
  car: { color: "#e11d48", label: "자동차", style: "solid", layer: 1 },
  transit: { color: "#059669", label: "대중교통", style: "solid", layer: 2 },
  walk: { color: "#7c3aed", label: "도보", style: "shortdash", layer: 3 },
};

interface Props {
  kakao: Kakao;
  map: Kakao;
  rows: ParticipantResult[];
  highlighted: string | null;
  // 두 단계 집결의 집결지 → 후보 구간. 여럿이 함께 가는 길이라 굵은 점선으로 구분한다 (09-27)
  legs?: RendezvousLeg[];
}

export const GROUP_LEG_STYLE = { style: "dash", weight: 7, label: "집결지에서 함께 이동" };

export default function RouteLines({ kakao, map, rows, highlighted, legs = [] }: Props) {
  useEffect(() => {
    const lines = rows
      .filter((r) => r.polyline.length > 1)
      .map((r) => {
        const s = ROUTE_STYLES[r.transport];
        return new kakao.maps.Polyline({
          map,
          path: r.polyline.map(([lng, lat]) => new kakao.maps.LatLng(lat, lng)),
          strokeWeight: highlighted === r.name ? 7 : 5,
          strokeColor: s.color,
          strokeOpacity: highlighted && highlighted !== r.name ? 0.35 : 0.85,
          strokeStyle: s.style,
          zIndex: highlighted === r.name ? 10 : s.layer,
        });
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
  }, [kakao, map, rows, highlighted, legs]);

  return null;
}
