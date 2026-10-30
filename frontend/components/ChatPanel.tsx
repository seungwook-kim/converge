"use client";

// 채팅창. 문장 입력, 카톡 캡처 업로드, 되묻기(questions) 표시.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { captureBase64, MAX_CAPTURE_BYTES } from "@/lib/capture";
import type { Preset, Stage } from "@/types/agent";
import Progress from "./Progress";

export interface ChatMessage {
  id: number;
  role: "user" | "agent" | "error";
  text: string;
  questions?: string[];
  image?: boolean;
}

export interface ChatSend {
  text: string | null;
  image_base64: string | null;
  preset: Preset | null;
}

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  stage: Stage | null;
  onSend: (input: ChatSend) => void;
  children?: ReactNode; // 입력창 위에 붙는 단계별 버튼
}

export default function ChatPanel({ messages, busy, stage, onSend, children }: Props) {
  const [text, setText] = useState("");
  const [preset, setPreset] = useState<Preset | "">("");
  const [image, setImage] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  // 캡처를 읽는 동안은 busy 가 아직 꺼져 있다. 그사이 Enter 를 또 누르면 같은 말이 두 번 갔다
  const [reading, setReading] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const pickImage = (file: File | null) => {
    setLocalError(null);
    // 파일 칸을 비워 둬야 뺀 캡처를 다시 골라도 onChange 가 온다
    if (fileRef.current) fileRef.current.value = "";
    if (!file) return setImage(null);
    if (!["image/png", "image/jpeg"].includes(file.type)) {
      setLocalError("PNG 또는 JPG 캡처만 올릴 수 있습니다");
      return;
    }
    if (file.size > MAX_CAPTURE_BYTES) {
      setLocalError("캡처가 5MB 를 넘습니다");
      return;
    }
    setImage(file);
  };

  const submit = async () => {
    const trimmed = text.trim();
    if (busy || reading || (!trimmed && !image)) return;
    let image_base64: string | null = null;
    if (image) {
      setReading(true);
      try {
        image_base64 = await captureBase64(image);
      } catch (e) {
        setLocalError((e as Error).message || "캡처를 읽지 못했습니다");
        return;
      } finally {
        setReading(false);
      }
    }
    onSend({ text: trimmed || null, image_base64, preset: preset || null });
    setText("");
    setImage(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <section className="chat">
      <div className="chat-list" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-guide">
            <p>
              <strong>이렇게 입력해 보세요</strong>
            </p>
            <ul>
              <li>누가, 어디서 출발하고, 무엇을 타고 오는지</li>
              <li>가는 곳(예: 강남역 근처 고깃집, 한강공원, 친구 집)과 시각</li>
              <li>있으면 적어도 됩니다: 먼저 모였다가 같이 가는 곳, 태워 줄 사람과 그 지점, 출입증·방문자 등록</li>
            </ul>
            <p className="muted">카톡 대화 캡처를 올려도 됩니다.</p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg msg-${m.role}`}>
            {m.image && <span className="badge">캡처 첨부</span>}
            <p>{m.text}</p>
            {m.questions && m.questions.length > 0 && (
              <ol className="questions">
                {m.questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ol>
            )}
          </div>
        ))}
        {busy && <div className="msg msg-agent pending">계산 중입니다…</div>}
      </div>

      <Progress busy={busy} stage={stage} />

      {children && <div className="chat-actions">{children}</div>}

      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="chat-form-row">
          <select value={preset} onChange={(e) => setPreset(e.target.value as Preset | "")} aria-label="약속 종류">
            <option value="">약속 종류 자동</option>
            <option value="meeting">일반 약속</option>
            <option value="visit">방문 (출입 절차 있음)</option>
          </select>
          <label className="file-btn">
            캡처 올리기
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => pickImage(e.target.files?.[0] ?? null)}
            />
          </label>
          {image && (
            <button type="button" className="link" onClick={() => pickImage(null)}>
              {image.name} 빼기
            </button>
          )}
        </div>
        {localError && <p className="error">{localError}</p>}
        <div className="chat-form-row">
          <textarea
            value={text}
            maxLength={1000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void submit();
              }
            }}
            placeholder="예: 민수는 잠실역에서 차로 와. 지호는 태워 갈게"
            rows={3}
          />
          <button type="submit" disabled={busy || reading || (!text.trim() && !image)}>
            보내기
          </button>
        </div>
      </form>
    </section>
  );
}
