// 카톡 캡처를 보낼 base64 로 바꾼다. 메인 입력창과 채팅창이 같이 쓴다.
// Vercel 함수는 요청 본문을 4.5MB 까지만 받는다. base64 는 원본보다 4/3 배 커져서 3.3MB 쯤 넘는 캡처는
// 백엔드에 닿기도 전에 413 으로 끊겼다 (10-30). 그보다 크면 브라우저에서 JPEG 로 줄여 보낸다.

export const MAX_CAPTURE_BYTES = 5 * 1024 * 1024; // 고를 수 있는 원본 크기
const MAX_SEND_BASE64 = 4_000_000; // 보내는 base64 글자 수. 문장·JSON 몫을 남긴다
const MAX_WIDTH = 1440; // 휴대폰 캡처 폭. 이보다 좁히면 말풍선 글자가 뭉개진다
const QUALITY = 0.85;
const MAX_TRIES = 5;

function dataUrlOf(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

const base64Of = (dataUrl: string) => dataUrl.split(",")[1] ?? "";

function jpegOf(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("캡처를 줄이지 못했습니다"))), "image/jpeg", quality),
  );
}

export async function captureBase64(file: File): Promise<string> {
  const original = base64Of(await dataUrlOf(file));
  if (original.length <= MAX_SEND_BASE64) return original;

  const bitmap = await createImageBitmap(file);
  try {
    let scale = Math.min(1, MAX_WIDTH / bitmap.width);
    let quality = QUALITY;
    for (let i = 0; i < MAX_TRIES; i += 1) {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d");
      if (!ctx) break;
      // PNG 의 투명한 곳이 JPEG 에서 검게 나오지 않게 흰 바탕을 먼저 깐다
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const out = base64Of(await dataUrlOf(await jpegOf(canvas, quality)));
      if (out.length <= MAX_SEND_BASE64) return out;
      // 아직 크면 크기와 화질을 조금씩 같이 내린다. 긴 스크롤 캡처가 여기까지 온다
      scale *= 0.8;
      quality = Math.max(0.6, quality - 0.1);
    }
  } finally {
    bitmap.close();
  }
  throw new Error("캡처가 너무 큽니다. 대화 부분만 잘라서 올려 주세요");
}
