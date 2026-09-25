"""Jev 1회당 토큰·비용 측정용. 가상 예문 5건만 부르고 멈춘다. 경로는 .env 의 JEV_PROVIDER.

  python evals/jev_neuron_probe.py

- 반복 호출하지 않는다. 5건, 한 번씩.
- 예문은 지어낸 문장이다. 실제 이름·주소가 없다.
- 키는 .env 에서만 읽고 출력하지 않는다 (CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN).
- 끝나면 "몇 건, 입력·출력 몇 토큰" 을 요약한다. Cloudflare 대시보드
  (Workers AI > 사용량)의 Neurons 증가분을 이 합계로 나누면 토큰당 Neuron 이 나온다.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
# 경로는 .env 의 JEV_PROVIDER 를 따른다 (typesafe: TypeSafe 또는 Vercel AI Gateway 의 TypeSafe 호환 API, cloudflare)
os.environ.setdefault("JEV_TIMEOUT_SEC", "20")  # 실제 지연을 재려고 넉넉히 둔다. 운영 기본은 2.5초

from backend.app.services import access_judge  # noqa: E402

# (가린 문장, 목적지, 목적). 파이프라인이 보내는 모양 그대로 이름은 가림말로 둔다
SAMPLES = [
    ("[참석자1]과 토요일 2시 성수동에서 만나", "성수동", "만남"),
    ("금요일 7시 강남역 근처 고깃집에서 회식. [참석자1] 수원 차, [참석자2] 신림 지하철", "강남역 근처 고깃집", "회식"),
    ("수요일 3시 여의도 사무실에서 미팅. [참석자1]은 강남에서 지하철", "여의도 사무실", "미팅"),
    ("목요일 11시 구청 민원 상담. 1층에서 방문자 등록을 해야 합니다", "구청", "민원 상담"),
    ("일요일 12시 [참석자1] 집들이. 다들 지하철로 와", "[참석자1] 집", "집들이"),
]


async def main() -> None:
    missing = access_judge._missing_keys()
    if missing:
        sys.exit(f"{', '.join(missing)} 가 .env 에 없습니다")
    sent, tokens_in, tokens_out, failures = 0, 0, 0, []
    for text, destination, purpose in SAMPLES:
        started = time.monotonic()
        try:
            out = await access_judge.judge(text, destination, purpose)
        except access_judge.JevError as e:
            failures.append(type(e).__name__)
            print(f"실패 {type(e).__name__}: {e}")
            break  # 실패하면 멈춘다. 주소·권한·할당량 문제는 계속 보내도 같은 실패다
        sent += 1
        tokens_in += out["input_tokens"]
        tokens_out += out["output_tokens"]
        print(
            f"{destination:<12} choice={out['choice']:<8} p_none={out['p_none']:.2f} "
            f"confidence={out['confidence']:.2f} in={out['input_tokens']} out={out['output_tokens']} "
            f"{int((time.monotonic() - started) * 1000)}ms model={out['model']}"
        )
    print("\n요약")
    print(f"  성공 {sent}건 / 시도 {sent + len(failures)}건  실패 {failures or '없음'}")
    print(f"  입력 {tokens_in} 토큰, 출력 {tokens_out} 토큰 (합 {tokens_in + tokens_out})")
    if sent:
        print(f"  1건 평균 입력 {tokens_in / sent:.0f}, 출력 {tokens_out / sent:.0f} 토큰")
    print(f"  경로 {access_judge.provider()}  base_url {os.environ.get('TYPESAFE_BASE_URL', '(기본)')}")
    print("  Cloudflare 면 대시보드 Neurons 증가분 ÷ 위 토큰 합 = 토큰당 Neuron. Vercel 이면 대시보드 사용량에 비용이 찍힌다")


if __name__ == "__main__":
    asyncio.run(main())
