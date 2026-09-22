"""캡처 → 텍스트 (SDD 5절 0단계).

LLM 호출은 llm.transcribe_image 가 한다 (모든 LLM 호출은 llm.py). 여기서는 호출 전후 검사만 한다.
  - 무슨 이미지인지 앞 바이트로 확인한다. 화면이 PNG·JPG 만 보내지만 요청은 누구나 만들 수 있다
  - 화면이 data URL 앞부분을 떼고 보내지만, 붙은 채 와도 받는다
"""
from __future__ import annotations

import base64
import binascii

from backend.app.services import llm

_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}


class NotAnImage(ValueError):
    """PNG·JPG 가 아니다. 모델을 부르기 전에 막는다 (비용 방어)."""


def detect_mime(image_base64: str) -> tuple[str, str]:
    """(mime, 앞부분을 뗀 base64). PNG·JPG 가 아니면 NotAnImage."""
    data = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
    try:
        head = base64.b64decode(data[:32] + "=" * (-len(data[:32]) % 4), validate=False)
    except (binascii.Error, ValueError) as e:
        raise NotAnImage("base64 가 아닙니다") from e
    for signature, mime in _SIGNATURES.items():
        if head.startswith(signature):
            return mime, data
    raise NotAnImage("PNG 또는 JPG 캡처만 읽습니다")


async def extract_text(image_base64: str) -> str:
    mime, data = detect_mime(image_base64)
    return await llm.transcribe_image(data, mime)
