import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import ServiceWorker from "@/components/ServiceWorker";
import "./globals.css";

export const metadata: Metadata = {
  title: "Converge",
  description: "여러 사람이 모일 장소와 시각을 문장 하나로 정하는 에이전트",
  manifest: "/manifest.json",
  appleWebApp: { capable: true, title: "Converge", statusBarStyle: "default" },
  icons: { icon: "/icon-192.png", apple: "/apple-touch-icon.png" },
};

// themeColor 는 metadata 가 아니라 viewport 로 간다 (Next 14 부터).
// maximumScale 을 막지 않는다. 확대를 막으면 화면을 키워 보는 사람이 못 읽는다
export const viewport: Viewport = {
  themeColor: "#2d6a4f",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        {children}
        <ServiceWorker />
      </body>
    </html>
  );
}
