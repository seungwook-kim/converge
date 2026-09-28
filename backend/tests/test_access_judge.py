"""출입 절차 판단 모델(Jev) 호출 (access.md 5순위, 09-23). 가짜 클라이언트로 돈다. 키·네트워크 없음."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.services import access_judge


class _FakeClient:
    """system_one 을 흉내 낸다. 받은 state·questions 를 남기고, 정해 둔 답이나 예외를 낸다."""

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.seen = answer, error, {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def system_one(self, state, questions, **kwargs):
        self.seen = {"state": state, "questions": questions, **kwargs}
        if self.error:
            raise self.error
        return SimpleNamespace(
            model="jev-1.13",
            usage=SimpleNamespace(input_tokens=400, output_tokens=0),
            choices={"access": SimpleNamespace(choice=self.answer[0], confidence=self.answer[1], probabilities=self.answer[2])},
        )


def test_키가_없거나_스위치가_꺼져_있으면_쓰지_않는다(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("JEV_ACCESS", "1")
    assert access_judge.enabled() is False
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    monkeypatch.setenv("JEV_ACCESS", "0")
    assert access_judge.enabled() is False
    monkeypatch.setenv("JEV_ACCESS", "1")
    # 09-28 결정: 허용한 LLM 은 두 개뿐이라 키와 스위치가 있어도 쓰지 않는다
    assert access_judge.enabled() is False


def _typesafe_env(monkeypatch):
    monkeypatch.delenv("JEV_PROVIDER", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")


def test_판단_결과를_확률과_함께_돌려준다(monkeypatch):
    _typesafe_env(monkeypatch)
    fake = _FakeClient(answer=("none", 0.91, {"none": 0.93, "required": 0.02, "unknown": 0.05}))
    monkeypatch.setattr(access_judge, "_client", lambda: fake)
    out = asyncio.run(access_judge.judge("[참석자1] 성수동에서 만나", "성수동", "만남"))
    assert out["choice"] == "none" and out["p_none"] == 0.93 and out["confidence"] == 0.91
    assert out["model"] == "jev-1.13" and out["input_tokens"] == 400
    assert out["cost_usd"] == pytest.approx(400 * 0.042 / 1_000_000)
    # 보낸 것: 가린 문장·목적지·목적. 보기에는 사람 검토용 "unknown" 이 있다
    assert fake.seen["state"] == {"message": "[참석자1] 성수동에서 만나", "destination": "성수동", "purpose": "만남"}
    assert set(fake.seen["questions"]["access"].criteria) == {"none", "required", "unknown"}
    # 오래 기다리지 않는다. 재시도하지 않는다 (요청 하나가 늘어지면 사용자가 기다린다)
    assert fake.seen["retry"].max_retries == 0 and fake.seen["retry"].timeout <= 3


def test_호출이_실패하면_예외를_올린다(monkeypatch):
    _typesafe_env(monkeypatch)
    fake = _FakeClient(error=TimeoutError("slow"))
    monkeypatch.setattr(access_judge, "_client", lambda: fake)
    with pytest.raises(TimeoutError):
        asyncio.run(access_judge.judge("성수동에서 만나", "성수동", "만남"))


# ── Cloudflare Workers AI 경로 (TypeSafe 신규 가입이 막혀 대신 쓴다, 09-23) ─────────
import httpx  # noqa: E402

CF_ENV = {"JEV_PROVIDER": "cloudflare", "CLOUDFLARE_ACCOUNT_ID": "a" * 32, "CLOUDFLARE_API_TOKEN": "t" * 40, "JEV_ACCESS": "1"}


def _cf(monkeypatch, handler, **env):
    for key, value in {**CF_ENV, **env}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(access_judge, "_transport", lambda: httpx.MockTransport(handler))


def _cf_ok(body, envelope=True):
    def handler(request):
        _cf_ok.seen = request
        return httpx.Response(200, json={"result": body, "success": True, "errors": []} if envelope else body)
    return handler


JEV_BODY = {
    "model": "jev-1.13.0",
    "answers": {"access": {"type": "choice", "choice": "none", "confidence": 0.88,
                           "probabilities": {"none": 0.9, "required": 0.03, "unknown": 0.07}}},
    "usage": {"input_tokens": 426, "output_tokens": 73},
}


def test_클라우드플레어_경로는_계정과_토큰이_있을_때만_켠다(monkeypatch):
    _cf(monkeypatch, _cf_ok(JEV_BODY))
    assert access_judge.enabled() is False  # 09-28: 허용 목록 밖이라 계정·토큰이 있어도 끈다
    _cf(monkeypatch, _cf_ok(JEV_BODY), CLOUDFLARE_API_TOKEN=None)
    assert access_judge.enabled() is False
    _cf(monkeypatch, _cf_ok(JEV_BODY), JEV_ACCESS="0")
    assert access_judge.enabled() is False


def test_클라우드플레어로_묻고_같은_모양으로_돌려준다(monkeypatch):
    _cf(monkeypatch, _cf_ok(JEV_BODY))
    out = asyncio.run(access_judge.judge("[참석자1] 성수동에서 만나", "성수동", "만남"))
    assert (out["choice"], out["p_none"], out["confidence"]) == ("none", 0.9, 0.88)
    assert (out["model"], out["input_tokens"], out["output_tokens"]) == ("jev-1.13.0", 426, 73)
    assert out["provider"] == "cloudflare"
    req = _cf_ok.seen
    # 모델 이름은 주소가 아니라 본문에 넣는다. 주소에 붙이면 "no route for that uri" (09-23 실측)
    assert str(req.url) == f"https://api.cloudflare.com/client/v4/accounts/{'a' * 32}/ai/run"
    assert req.headers["authorization"] == "Bearer " + "t" * 40
    import json as _json
    body = _json.loads(req.content)
    # 문서 curl 그대로: {"model", "input": {"state", "questions"}} (09-23 실측, input 이 없으면 400)
    assert body["model"] == "typesafe/jev"
    assert body["input"]["state"]["destination"] == "성수동"
    assert body["input"]["questions"]["access"]["type"] == "choice"
    assert set(body["input"]["questions"]["access"]["criteria"]) == {"none", "required", "unknown"}


def test_응답이_봉투_없이_와도_읽는다(monkeypatch):
    _cf(monkeypatch, _cf_ok(JEV_BODY, envelope=False))
    assert asyncio.run(access_judge.judge("성수동에서 만나", "성수동", "만남"))["choice"] == "none"


def test_키가_없으면_무엇이_없는지_말한다(monkeypatch):
    _cf(monkeypatch, _cf_ok(JEV_BODY), CLOUDFLARE_ACCOUNT_ID=None)
    with pytest.raises(access_judge.JevConfigError, match="CLOUDFLARE_ACCOUNT_ID"):
        asyncio.run(access_judge.judge("성수동에서 만나", "성수동", "만남"))


@pytest.mark.parametrize(
    "status, payload, error",
    [
        (401, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}, "JevAuthError"),
        (403, {"success": False, "errors": [{"code": 10000, "message": "Forbidden"}]}, "JevAuthError"),
        (429, {"success": False, "errors": [{"code": 3036, "message": "daily free allocation of 10,000 neurons exceeded"}]}, "JevQuotaError"),
        (400, {"success": False, "errors": [{"code": 3036, "message": "You have used up your daily free allocation of 10,000 neurons"}]}, "JevQuotaError"),
        (500, {"success": False, "errors": [{"code": 3001, "message": "internal"}]}, "JevUnavailable"),
        # 09-23 실측: Jev 는 제휴 모델이라 무료 Neurons 가 아니라 AI Gateway 선불 잔액에서 빠진다
        (402, {"success": False, "errors": [{"code": 2003, "message": "insufficient balance; add money to your gateway or use byok"}]}, "JevQuotaError"),
    ],
)
def test_인증_할당량_그밖의_실패를_나눈다(monkeypatch, status, payload, error):
    _cf(monkeypatch, lambda _req: httpx.Response(status, json=payload))
    with pytest.raises(getattr(access_judge, error)):
        asyncio.run(access_judge.judge("성수동에서 만나", "성수동", "만남"))


def test_시간이_넘으면_시간_초과로_나눈다(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    _cf(monkeypatch, handler)
    with pytest.raises(access_judge.JevTimeout):
        asyncio.run(access_judge.judge("성수동에서 만나", "성수동", "만남"))
