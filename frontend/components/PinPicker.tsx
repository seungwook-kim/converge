"use client";

// 참석자 출발지를 드래그 말고도 고치는 두 가지 길: 지도 클릭, 장소 검색.
// 저장 경로는 드래그와 같다. 좌표를 onMove 로 올리면 페이지가 PATCH 한 번으로 저장한다.
//
// 대상을 먼저 고르게 한 이유: 좌표를 받는 주체가 없으면 지도 클릭은 아무 뜻도 없고,
// 아무나 눌리면 남의 출발지를 실수로 옮기게 된다. 고른 사람이 없으면 리스너 자체를 달지 않는다.

import { useCallback, useEffect, useState } from "react";
import { searchPlaces, type Kakao, type PlaceHit } from "@/lib/kakao";
import { useFoldable } from "@/lib/useFoldable";
import type { ParticipantPin } from "./ParticipantPins";

type SearchState =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "done"; hits: PlaceHit[] }
  | { kind: "error"; text: string };

interface Props {
  kakao: Kakao;
  map: Kakao;
  pins: ParticipantPin[];
  onMove: (name: string, lng: number, lat: number, origin?: string) => void; // origin: 장소 검색이면 그 장소 이름
  onArmedChange: (armed: boolean) => void; // 지도 커서를 바꾸는 건 지도를 가진 MapView 몫이다
}

export default function PinPicker({ kakao, map, pins, onMove, onArmedChange }: Props) {
  const [target, setTarget] = useState<string | null>(null);
  const [armed, setArmed] = useState(false); // 지도 클릭 한 번을 받을 준비가 됐는가
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<SearchState>({ kind: "idle" });
  const [open, setOpen] = useFoldable();

  // 새 응답으로 핀 목록이 바뀌어 고른 사람이 사라지면 대상도 비운다. 없는 사람 좌표를 저장하면 안 된다
  useEffect(() => {
    if (target && !pins.some((p) => p.name === target)) {
      setTarget(null);
      setArmed(false);
    }
  }, [pins, target]);

  useEffect(() => onArmedChange(armed), [armed, onArmedChange]);

  const place = useCallback(
    (lng: number, lat: number, origin?: string) => {
      if (!target) return;
      onMove(target, lng, lat, origin);
    },
    [target, onMove],
  );

  useEffect(() => {
    if (!armed || !target) return; // 준비 상태가 아니면 지도 클릭은 아무 일도 하지 않는다
    const onMapClick = (e: Kakao) => {
      const pos = e.latLng;
      place(pos.getLng(), pos.getLat());
      setArmed(false); // 한 번 찍으면 내린다. 연달아 찍으려면 다시 켜게 해서 오조작을 막는다
    };
    kakao.maps.event.addListener(map, "click", onMapClick);
    return () => kakao.maps.event.removeListener(map, "click", onMapClick);
  }, [kakao, map, armed, target, place]);

  const runSearch = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = query.trim();
      if (!q) return;
      setSearch({ kind: "busy" });
      try {
        setSearch({ kind: "done", hits: await searchPlaces(kakao, q) });
      } catch (err) {
        setSearch({ kind: "error", text: (err as Error).message });
      }
    },
    [kakao, query],
  );

  const pickHit = useCallback(
    (hit: PlaceHit) => {
      place(hit.lng, hit.lat, hit.name); // 출발지 이름도 검색한 장소 이름으로 바꾼다 (09-27)
      // 검색한 곳은 지금 보이는 범위 밖일 수 있다. 옮긴 자리를 눈으로 확인하게 지도를 그쪽으로 옮긴다
      map.setCenter(new kakao.maps.LatLng(hit.lat, hit.lng));
      setSearch({ kind: "idle" });
      setQuery("");
    },
    [kakao, map, place],
  );

  if (pins.length === 0) return null;

  if (!open) {
    return (
      <button type="button" className="map-fold map-fold-top" aria-expanded={false} onClick={() => setOpen(true)}>
        출발지 고치기 ▾
      </button>
    );
  }

  return (
    <div className="pin-picker">
      <button
        type="button"
        className="map-fold-close"
        aria-expanded
        aria-label="출발지 고치기 접기"
        onClick={() => {
          // 접으면 지도 클릭 대기도 끝낸다. 안 보이는 패널이 클릭을 가로채면 안 된다
          setArmed(false);
          setOpen(false);
        }}
      >
        접기
      </button>
      <label className="pin-picker-who">
        출발지를 고칠 사람
        <select
          value={target ?? ""}
          onChange={(e) => {
            setTarget(e.target.value || null);
            setArmed(false);
            setSearch({ kind: "idle" });
          }}
        >
          <option value="">고르지 않음</option>
          {pins.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </label>

      {!target && <p className="hint">사람을 고르면 지도 클릭이나 장소 검색으로 출발지를 지정할 수 있습니다.</p>}

      {target && (
        <>
          <div className="pin-picker-row">
            <button
              type="button"
              className={armed ? "primary" : undefined}
              onClick={() => setArmed((v) => !v)}
            >
              {armed ? "찍기 취소" : "지도 클릭으로 지정"}
            </button>
          </div>

          {armed && (
            <p className="pin-picker-armed" role="status">
              지금 <strong>{target}</strong> 님 위치를 찍는 중입니다. 지도를 클릭하세요.
            </p>
          )}

          <form className="pin-picker-row" onSubmit={runSearch}>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="장소 검색 (예: 시청역)"
              aria-label={`${target} 님 출발지 장소 검색`}
            />
            <button type="submit" disabled={search.kind === "busy" || query.trim() === ""}>
              검색
            </button>
          </form>

          {search.kind === "busy" && <p className="hint">검색 중…</p>}
          {search.kind === "error" && <p className="error">{search.text}</p>}
          {search.kind === "done" && search.hits.length === 0 && (
            <p className="hint">찾지 못했습니다. 다른 말로 검색해 보세요.</p>
          )}
          {search.kind === "done" && search.hits.length > 0 && (
            <ul className="pin-picker-hits">
              {search.hits.map((h) => (
                <li key={h.id}>
                  <button type="button" onClick={() => pickHit(h)}>
                    <span className="strong">{h.name}</span>
                    <span className="muted">{h.address || "주소 없음"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
