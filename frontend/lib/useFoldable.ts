"use client";

// 지도 위 패널(출발지 고치기, 경로선)을 접고 펴는 상태.
// 좁은 화면(휴대폰)에서는 접힌 채로 시작한다. 지도가 화면 절반 남짓이라 패널 둘이 지도를 덮고 서로 겹친다 (10-20).
// 처음 그릴 때는 펼친 상태로 두고 화면 폭은 effect 에서 본다. 서버 렌더와 첫 화면이 어긋나지 않게 하려는 것이다.

import { useEffect, useState } from "react";

export const NARROW_QUERY = "(max-width: 820px)"; // globals.css 의 .split 이 세로로 바뀌는 폭과 같다

export function useFoldable() {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (window.matchMedia(NARROW_QUERY).matches) setOpen(false);
  }, []);
  return [open, setOpen] as const;
}
