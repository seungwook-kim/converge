"""캡처 읽기 (SDD 5절 0단계). 모델은 가짜로 바꾼다. 키 없이 돈다 (TEST_GUIDE)."""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest

from backend.app.services import llm, vision

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).decode()
JPG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 40).decode()


def test_PNG_JPG_를_앞_바이트로_알아본다():
    assert vision.detect_mime(PNG) == ("image/png", PNG)
    assert vision.detect_mime(JPG)[0] == "image/jpeg"


def test_data_URL_앞부분이_붙어_와도_받는다():
    assert vision.detect_mime(f"data:image/png;base64,{PNG}") == ("image/png", PNG)


def test_이미지가_아니면_모델을_부르기_전에_막는다():
    with pytest.raises(vision.NotAnImage):
        vision.detect_mime(base64.b64encode(b"GIF89a" + b"\x00" * 40).decode())


class _FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))], usage=None)


@pytest.fixture
def fake(monkeypatch):
    def install(*replies):
        client = _FakeClient(replies)
        monkeypatch.setattr(llm, "_client", lambda _model="": client)
        monkeypatch.setattr(llm.langfuse, "get_prompt", lambda name: ("대화를 옮겨 적어라", f"{name}@1"))
        monkeypatch.setenv("MODEL_VISION", "vendor/vision")
        return client

    return install


def test_캡처를_텍스트로_옮긴다(fake):
    client = fake("민수: 토요일 12시 한강공원")
    out = asyncio.run(vision.extract_text(PNG))
    assert out == "민수: 토요일 12시 한강공원"
    sent = client.calls[0]
    assert sent["model"] == "vendor/vision"
    assert sent["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_한_번_실패하면_같은_모델로_다시_해_본다(fake):
    client = fake(RuntimeError("429"), "지호: 7시 강남역")
    assert asyncio.run(vision.extract_text(JPG)) == "지호: 7시 강남역"
    assert len(client.calls) == 2


def test_대화가_없는_이미지면_실패로_본다(fake):
    fake("", "")
    with pytest.raises(ValueError):
        asyncio.run(vision.extract_text(PNG))


def test_MODEL_VISION_이_없으면_대형_모델로_읽는다(monkeypatch):
    monkeypatch.delenv("MODEL_VISION", raising=False)
    monkeypatch.setenv("MODEL_LARGE", "vendor/large")
    assert llm.model_vision() == "vendor/large"
