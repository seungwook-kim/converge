// 홈 화면에 설치되게 하는 최소 서비스 워커 (SDD 2절 09-21 PWA 결정).
//
// 캐시를 거의 하지 않는다. 지도·경로·계산이 전부 네트워크라 오프라인 동작은 애초에 안 되고,
// 어설프게 캐시하면 배포한 새 화면 대신 옛 화면이 남는다. 그 사고가 제일 잦다.
//
// 하는 일은 둘뿐이다.
//   1. 설치 가능 조건을 채운다 (브라우저가 fetch 핸들러를 요구한다)
//   2. 네트워크가 끊겼을 때 흰 화면 대신 안내를 보여 준다

const OFFLINE_URL = "/offline.html";
const CACHE = "converge-shell-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(OFFLINE_URL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  // 옛 버전 캐시를 지운다. 이름이 바뀌면 통째로 새로 받는다
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  // 화면 이동만 가로챈다. API·지도·정적 파일은 건드리지 않는다
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(OFFLINE_URL)),
  );
});
