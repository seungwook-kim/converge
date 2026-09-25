"""출입 절차 판단 모델(TypeSafe Jev). access.md "절차 판정" 5순위에서만 부른다 (09-23).

왜 있나:
  규칙(단서 단어·목적지 종류·일상 약속)으로 못 가르는 문장이 남는다. 예: "성수동에서 만나".
  그 구간을 슬롯 추출 모델 값 하나에 맡기면 같은 문장에 답이 흔들린다(09-23 측정).
  Jev 는 생성하지 않고 보기 중 하나를 확률과 함께 고르는 판단 전용 모델이라 이 자리에 맞다.

틀렸을 때 피해를 막는 장치 (판정은 domain/rules.settle_access 가 한다):
  - "없음" 만 확률이 access.md judge_none_min_probability 이상일 때 받는다. 못 미치면 되묻는다
  - "있음" 을 만들지 못한다. 있다고 보면 되묻기로 바꾼다
  - 실패·시간 초과·한도 초과면 되묻는다 (llm.py 가 예외를 "failed" 로 바꾼다)
  - 추정으로 "없음" 을 정했으면 결과 안내에 그렇다고 적는다 (pipeline)
  - 이름을 가린 문장만 보낸다. 장소 이름은 남는다

부르는 길은 둘이다 (JEV_PROVIDER). 판단 모델과 질문 형식은 같다.
  typesafe    TypeSafe SDK. TYPESAFE_API_KEY 가 필요하다. TYPESAFE_BASE_URL 을 Vercel AI Gateway 의
              TypeSafe 호환 API(https://ai-gateway.vercel.sh/typesafe)로, TYPESAFE_DEFAULT_MODEL 을
              typesafe-ai/jev 로 두면 Vercel 키로 부른다. 09-23 가상 예문 5건 성공, 1건 평균 입력 483 토큰
  cloudflare  Cloudflare Workers AI 의 typesafe/jev. CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN 이 필요하다.
              TypeSafe 신규 가입이 막혀 대신 쓴다(09-23). 제휴 모델이라 무료 Neurons 가 아니라
              AI Gateway 선불 잔액에서 빠진다. 잔액이 없으면 402 (09-23 실측)

켜는 법: 위 키와 JEV_ACCESS=1. 하나라도 없으면 부르지 않고 지금 동작 그대로다.
실패는 종류별 예외(JevConfigError, JevAuthError, JevQuotaError, JevTimeout, JevUnavailable)로 올린다.
llm.py 가 받아서 되묻기로 넘긴다. 어느 실패든 "절차 없음" 으로 새지 않는다.
바깥 호출이라 services/ 에 둔다 (BACKEND_GUIDE).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

_log = logging.getLogger(__name__)
# 모델 이름은 본문 "model" 에 넣는다. 주소 뒤에 붙이면 400 "no route for that uri" 다 (09-23 실측)
CLOUDFLARE_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run"
CLOUDFLARE_MODEL = "typesafe/jev"
# 무료 할당량을 넘었을 때 오는 말. 상태 코드가 429 가 아닐 수도 있어 문구로도 가른다 (첫 실측에서 확인)
_QUOTA_WORDS = ("neuron", "allocation", "quota", "exceed")


class JevError(RuntimeError):
    """판단 모델 호출 실패. 종류는 아래 하위 클래스로 나눈다."""


class JevConfigError(JevError):
    """키가 없다. 어느 환경변수가 없는지 메시지에 적는다."""


class JevAuthError(JevError):
    """토큰이 틀렸거나 권한이 없다 (401, 403). Workers AI Read, Edit 권한이 필요하다."""


class JevQuotaError(JevError):
    """할당량·잔액 부족. 429 거나, Cloudflare 가 402 "insufficient balance" 를 낸 경우다.

    Jev 는 Cloudflare 제휴 모델이라 Workers AI 무료 Neurons 가 아니라 AI Gateway 선불 잔액(Unified
    Billing)에서 빠진다. 잔액이 없으면 첫 호출부터 402 다 (09-23 실측)."""


class JevTimeout(JevError):
    """TIMEOUT_SEC 안에 답이 없었다."""


class JevUnavailable(JevError):
    """그 밖의 실패 (5xx, 연결 실패, 응답 모양이 다름 등)."""

# 요청 하나가 늘어지면 사용자가 기다린다. 한 번만, 짧게 부르고 실패는 되묻기로 넘긴다.
# JEV_TIMEOUT_SEC 로 바꾼다 (Cloudflare 첫 호출이 2.5초를 넘은 적이 있다, 09-23 실측)
TIMEOUT_SEC = 2.5


def _timeout() -> float:
    try:
        return float(os.environ.get("JEV_TIMEOUT_SEC") or TIMEOUT_SEC)
    except ValueError:
        return TIMEOUT_SEC
QUESTION = "access"

# 한국어도 받지만 영어 정확도가 가장 높다는 공식 문서 권고대로 질문과 보기는 영어로 쓴다 (입력만 한국어)
INSTRUCTIONS = (
    "A group is meeting at the place in this Korean message. "
    "Before the meeting, do they have to go through an entry procedure to get into that place "
    "(visitor registration, entry badge, ID check, security desk)?"
)
CRITERIA = {
    "none": "No procedure. Anyone can walk in, or they meet outdoors or in a public spot "
    "(street, station, square, cafe, restaurant, bar, park, neighborhood).",
    "required": "An entry procedure is needed, such as visitor registration, a badge, an ID check or a security desk.",
    "unknown": "Cannot tell from the message. It could go either way, so the user should be asked.",
}

# 공식 단가 (2026-09): 입력 100만 토큰당 0.042달러, 출력 무료
INPUT_USD_PER_TOKEN = 0.042 / 1_000_000


def provider() -> str:
    return os.environ.get("JEV_PROVIDER", "typesafe")


def _missing_keys() -> list[str]:
    names = ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"] if provider() == "cloudflare" else ["TYPESAFE_API_KEY"]
    return [name for name in names if not os.environ.get(name)]


def enabled() -> bool:
    """키가 있고 스위치를 켰을 때만 쓴다. 기본은 꺼져 있다 (골든셋으로 확인하기 전까지)."""
    return os.environ.get("JEV_ACCESS") == "1" and not _missing_keys()


def _transport() -> httpx.AsyncBaseTransport | None:
    """테스트가 가짜 응답으로 바꾸는 자리. 평소에는 None(실제 네트워크)."""
    return None


def _client() -> Any:
    from typesafe_sdk import AsyncTypeSafeClient  # 지연 import: 키 없는 테스트가 SDK 를 건드리지 않게

    return AsyncTypeSafeClient()


async def judge(masked_text: str, destination: str | None, purpose: str | None) -> dict[str, Any]:
    """문장, 목적지, 목적으로 절차 여부를 고른다. 실패하면 JevError 하위 예외를 올린다.

    돌려주는 것: {"choice", "p_none", "confidence", "probabilities", "model", "provider",
                "input_tokens", "output_tokens", "cost_usd"}. cost_usd 는 Cloudflare 면 None 이다
                (Neurons 로 과금되고 토큰당 환산율이 공개돼 있지 않다).
    호출마다 판단값, 확률, 확신도, 토큰, 소요 시간을 로그 한 줄로 남긴다. 문장은 남기지 않는다.
    """
    missing = _missing_keys()
    if missing:
        raise JevConfigError(f"{', '.join(missing)} 가 없습니다 (JEV_PROVIDER={provider()})")
    state = {"message": masked_text, "destination": destination or "", "purpose": purpose or ""}
    started = time.monotonic()
    out = await (_judge_cloudflare(state) if provider() == "cloudflare" else _judge_typesafe(state))
    _log.info(
        "jev provider=%s choice=%s p_none=%.3f confidence=%.3f input_tokens=%s output_tokens=%s latency_ms=%d",
        out["provider"], out["choice"], out["p_none"], out["confidence"],
        out["input_tokens"], out["output_tokens"], int((time.monotonic() - started) * 1000),
    )
    return out


def _result(answer: dict[str, Any], model: str | None, usage: dict[str, Any], provider_name: str) -> dict[str, Any]:
    probabilities = {k: float(v) for k, v in dict(answer.get("probabilities") or {}).items()}
    tokens_in = int(usage.get("input_tokens") or 0)
    return {
        "choice": answer["choice"],
        "p_none": probabilities.get("none", 0.0),
        "confidence": float(answer.get("confidence") or 0.0),
        "probabilities": probabilities,
        "model": model,
        "provider": provider_name,
        "input_tokens": tokens_in,
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cost_usd": tokens_in * INPUT_USD_PER_TOKEN if provider_name == "typesafe" else None,
    }


async def _judge_cloudflare(state: dict[str, Any]) -> dict[str, Any]:
    """Cloudflare Workers AI REST. 응답은 {"result": {...}} 봉투에 오거나 바로 온다. 둘 다 읽는다."""
    url = CLOUDFLARE_URL.format(account=os.environ["CLOUDFLARE_ACCOUNT_ID"])
    question = {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}
    # 공식 curl 그대로 입력은 "input" 안에 둔다. 밖에 두면 400 "invalid request body: input" (09-23 실측)
    body = {"model": CLOUDFLARE_MODEL, "input": {"state": state, "questions": {QUESTION: question}}}
    headers = {"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"]}
    try:
        async with httpx.AsyncClient(timeout=_timeout(), transport=_transport()) as client:
            res = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as e:
        raise JevTimeout(f"{_timeout()}초 안에 답이 없었습니다") from e
    except httpx.HTTPError as e:
        raise JevUnavailable(f"연결 실패: {type(e).__name__}") from e

    try:
        data = res.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if res.status_code >= 400 or data.get("success") is False:
        messages = " ".join(str(err.get("message", "")) for err in data.get("errors") or []).lower()
        detail = f"HTTP {res.status_code} {messages[:200]}"
        if res.status_code in (401, 403):
            raise JevAuthError(detail)
        if res.status_code in (402, 429) or any(word in messages for word in _QUOTA_WORDS):
            raise JevQuotaError(detail)
        raise JevUnavailable(detail)

    payload = data.get("result", data)
    answer = (payload.get("answers") or {}).get(QUESTION) if isinstance(payload, dict) else None
    if not answer or "choice" not in answer:
        raise JevUnavailable("응답에 answers.access 가 없습니다")
    return _result(answer, payload.get("model"), payload.get("usage") or {}, "cloudflare")


async def _judge_typesafe(state: dict[str, Any]) -> dict[str, Any]:
    """TypeSafe SDK. SDK 예외를 같은 종류의 JevError 로 바꿔 올린다."""
    import typesafe_sdk as ts

    questions = {QUESTION: ts.Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)}
    try:
        async with _client() as client:
            res = await client.system_one(
                state, questions, retry=ts.RetryPolicy(max_retries=0, timeout=_timeout()), timeout=_timeout()
            )
    except ts.TypeSafeAuthenticationError as e:
        raise JevAuthError(str(e)) from e
    except ts.TypeSafeRateLimitError as e:
        raise JevQuotaError(str(e)) from e
    except ts.TypeSafeAPITimeoutError as e:
        raise JevTimeout(str(e)) from e
    except ts.TypeSafeError as e:
        raise JevUnavailable(f"{type(e).__name__}: {e}") from e
    answer = res.choices[QUESTION]
    usage = {"input_tokens": getattr(res.usage, "input_tokens", 0), "output_tokens": getattr(res.usage, "output_tokens", 0)}
    return _result(
        {"choice": answer.choice, "confidence": answer.confidence, "probabilities": dict(answer.probabilities)},
        res.model, usage, "typesafe",
    )
