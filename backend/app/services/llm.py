"""LLM 호출은 이 파일 하나로 모은다. (SDD 5절 1단계, 8절 프롬프트)

라우터나 화면 코드가 openai 를 직접 import 하지 않게 한다. 3차에서 이 파일 내부만 갈아끼우면
나머지는 그대로 돌아간다.

여기서 책임지는 것:
  - 출력 계약 검증 (schemas/slots.py 의 Slots)
  - 실패 시 재시도와 대형 모델 승격 (SDD 5절 1단계 "실패 시")
  - Langfuse 트레이스와 프롬프트 (SDD 8절). 프롬프트를 코드에 문자열로 두지 않는다

소형 모델(GGUF)은 아직 없다 (backend/app/models/ 비어 있음, finetune/ 결과물 대기).
SDD 8절이 "소형 (GGUF) 또는 대형 폴백"을 허용하므로 그때까지는 대형 모델로 추출한다.
어느 모델로 돌았는지는 Result.model_small / routed_to 로 드러난다.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import time
from datetime import date
from typing import Any

from pydantic import ValidationError

from backend.app.observability import langfuse
from backend.app.domain import rules as domain_rules
from backend.app.schemas.slots import Access, Preset, Slots
from backend.app.services import costs as cost_guards

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SLOT_PROMPT = "converge/slot-extract"
VISION_PROMPT = "converge/vision-transcribe"

# SDD 9절 MODEL_LARGE 와 같은 값을 본다
# 쓸 수 있는 모델은 아래 셋뿐이다 (09-28 결정, 10-31 CLAUDE 추가). 평소에는 env 가 고른 모델, 돈이 다 되면 FALLBACK.
#   CLAUDE    Claude API 직접. MODEL_SMALL 로 슬롯 추출을 맡긴다 (10-31)
#   PRIMARY   OpenRouter 유료. 슬롯 추출·판정·캡처 읽기 모두
#   FALLBACK  구글 AI Studio 무료 할당. OpenRouter 크레딧이 떨어지거나(402) 하루 비용 상한에 닿았을 때만
# env(MODEL_SMALL·MODEL_LARGE·MODEL_VISION)에 다른 이름을 적어도 _client 가 거절한다. 로컬 GGUF·Jev 도 못 쓴다
PRIMARY_MODEL = "openai/gpt-4o-mini"
FALLBACK_MODEL = "google-ai/gemini-3.5-flash-lite"
# Claude API 직접 호출 (10-31). SDD 8절 "Claude API 를 붙일 때": Haiku 5.5 하나만, 상위 모델 금지
CLAUDE_MODEL = "anthropic-ai/claude-haiku-5-5"
ALLOWED_MODELS = frozenset({PRIMARY_MODEL, FALLBACK_MODEL, CLAUDE_MODEL})
DEFAULT_LARGE = PRIMARY_MODEL

# 크레딧이 떨어진 것을 한 번 보면 이 시간(초) 동안은 처음부터 FALLBACK 으로 간다. 매번 402 를 맞고 돌아오지 않게
CREDITS_OUT_RETRY_SEC = 3600
_credits_out_until = 0.0
# 하루 비용 상한에 닿은 요청이면 True. 요청 단위라 contextvar 로 둔다 (routers/agent.py 가 켠다)
_request_fallback: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_request_fallback", default=False)


# 마지막 호출에 쓴 모델·프롬프트 버전. Result 를 만들 때(6·8단계) 쓴다
_last_meta: dict[str, Any] = {}


def last_meta() -> dict[str, Any]:
    return dict(_last_meta)


class LlmUnavailable(RuntimeError):
    """키가 없어 LLM 을 부를 수 없다. 파이프라인이 failed 로 답하게 한다."""


class ModelNotAllowed(LlmUnavailable):
    """허용하지 않은 모델이다 (ALLOWED_MODELS). 설정이 틀렸다는 뜻이라 조용히 넘어가지 않는다."""


def effective_model(model: str) -> str:
    """이번 호출에 실제로 쓸 모델. 돈이 다 된 상태면 FALLBACK 으로 바꾼다.

    하루 비용 상한은 모든 모델에 건다. OpenRouter 크레딧 없음(402)은 OpenRouter 로 가는 모델에만 건다.
    Claude·구글은 키와 지갑이 따로라 OpenRouter 가 비었다고 바꿀 이유가 없다 (10-31)
    """
    if _request_fallback.get():
        return FALLBACK_MODEL
    if time.monotonic() < _credits_out_until and _is_openrouter(model):
        return FALLBACK_MODEL
    return model


def use_fallback_for_request() -> contextvars.Token:
    """이 요청은 처음부터 FALLBACK 으로 돈다. 하루 비용 상한에 닿았을 때 routers/agent.py 가 부른다."""
    return _request_fallback.set(True)


def end_request_fallback(token: contextvars.Token) -> None:
    _request_fallback.reset(token)


def reset_fallback() -> None:
    """크레딧 소진 표시를 지운다. 테스트와, 충전 뒤 바로 PRIMARY 로 돌리고 싶을 때."""
    global _credits_out_until
    _credits_out_until = 0.0


def _is_out_of_credits(error: Exception) -> bool:
    """OpenRouter 가 크레딧이 없다고 답했는가 (HTTP 402 Payment Required)."""
    return getattr(error, "status_code", None) == 402


MAX_OUTPUT_TOKENS = 2000


async def _create(model: str, **kwargs: Any) -> tuple[Any, str]:
    """chat.completions.create 를 감싼다. (응답, 실제로 답한 모델) 을 돌려준다.

    슬롯 추출·판정·캡처 읽기가 모두 이 함수로 부른다. PRIMARY 가 크레딧 없음(402)이면 표시를 남기고
    같은 요청을 FALLBACK 으로 한 번 더 보낸다. 실제로 답한 모델을 돌려주는 이유는 비용 계산과
    request_logs 가 그 이름을 봐야 하기 때문이다.
    """
    global _credits_out_until
    model = effective_model(model)
    # 출력 길이 상한. 주입된 지시로 모델이 긴 글을 쓰게 해 비용을 키우는 것을 막는다 (10-20 입력 방어).
    # 슬롯 JSON 은 참석자가 많아도 수백 토큰이다
    kwargs.setdefault("max_tokens", MAX_OUTPUT_TOKENS)
    try:
        res = await _client(model).chat.completions.create(
            model=_api_model(model), **_supported(model, kwargs), **_extra_body(model)
        )
        return res, model
    except Exception as e:  # noqa: BLE001
        if model == FALLBACK_MODEL or not _is_out_of_credits(e):
            raise
    _credits_out_until = time.monotonic() + CREDITS_OUT_RETRY_SEC
    res = await _client(FALLBACK_MODEL).chat.completions.create(
        model=_api_model(FALLBACK_MODEL), **kwargs, **_extra_body(FALLBACK_MODEL)
    )
    return res, FALLBACK_MODEL


GOOGLE_PREFIX = "google-ai/"
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
ANTHROPIC_PREFIX = "anthropic-ai/"
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1/"

# 호출 하나의 상한(초). openai SDK 기본값은 600초에 재시도 2회라, 구글 호출 하나가 멈추면 사용자가
# 5분 넘게 기다리다 502 를 받았다 (09-27, 앞서 09-22 에는 432초). 100회 측정 최대가 21.2초다.
# SDK 재시도는 끄고 재시도·승격은 extract_slots 의 attempt_models() 가 맡는다. LLM_TIMEOUT_SEC 로 바꾼다
LLM_TIMEOUT_SEC = 30.0


def _timeout() -> float:
    try:
        return float(os.environ.get("LLM_TIMEOUT_SEC") or LLM_TIMEOUT_SEC)
    except ValueError:
        return LLM_TIMEOUT_SEC


def _client(model: str = "") -> Any:
    """모델 이름을 보고 어디로 부를지 정한다.

    기본은 OpenRouter 다. 모델 이름이 "google-ai/" 로 시작하면 구글 AI Studio, "anthropic-ai/" 면
    Claude API 로 직접 부른다. 셋 다 OpenAI 호환 엔드포인트라 클라이언트는 주소와 키만 바꾸면 된다.

    구글로 직접 부르는 길을 둔 이유: 무료 할당이 있어서 사이드 프로젝트에서 크레딧 없이 돌릴 수 있다.
    """
    from openai import AsyncOpenAI  # 지연 import: 키 없는 테스트가 이 파일을 건드리지 않게

    if model not in ALLOWED_MODELS:
        raise ModelNotAllowed(f"허용하지 않은 모델입니다: {model} (쓸 수 있는 것: {', '.join(sorted(ALLOWED_MODELS))})")

    if model.startswith(GOOGLE_PREFIX):
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LlmUnavailable("GEMINI_API_KEY 가 없습니다 (aistudio.google.com 에서 발급)")
        return AsyncOpenAI(api_key=key, base_url=GOOGLE_BASE_URL, timeout=_timeout(), max_retries=0)

    if model.startswith(ANTHROPIC_PREFIX):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LlmUnavailable("ANTHROPIC_API_KEY 가 없습니다 (platform.claude.com 에서 발급)")
        return AsyncOpenAI(api_key=key, base_url=ANTHROPIC_BASE_URL, timeout=_timeout(), max_retries=0)

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LlmUnavailable("OPENROUTER_API_KEY 가 없습니다")
    return AsyncOpenAI(api_key=key, base_url=OPENROUTER_BASE_URL, timeout=_timeout(), max_retries=0)


def _extra_body(model: str) -> dict[str, Any]:
    """공급자마다 받는 옵션이 다르다.

    OpenRouter 는 usage.include 를 주면 응답에 실제 과금액을 실어 준다. 구글 엔드포인트는
    그 이름을 모르고 400 으로 거절한다 (09-21 실측). 그래서 OpenRouter 일 때만 붙인다.
    """
    if model.startswith(ANTHROPIC_PREFIX):
        # Haiku 5.5 는 기본으로 보이지 않는 사고 토큰을 쓴다. 슬롯 JSON 한 개에 출력 700~1000 토큰, 4~5초가 들었고
        # 끄면 300 토큰, 1.9초다 (10-31 실측). 회귀셋 정확도는 끈 상태로 쟀다 (docs/measurements.md)
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    if not _is_openrouter(model):
        return {}
    return {"extra_body": {"usage": {"include": True}}}


def _is_openrouter(model: str) -> bool:
    return not model.startswith((GOOGLE_PREFIX, ANTHROPIC_PREFIX))


def _supported(model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Claude API 가 받지 않는 옵션을 뺀다 (10-31 실측, OpenAI 호환 엔드포인트).

    temperature: Haiku 5.5 는 "deprecated for this model" 400 으로 거절한다.
    response_format: json_object 를 받지 않고 json_schema 만 받는다. 빼도 프롬프트가 JSON 만 내라고 하고,
    _parse_json_block 이 코드 블록으로 감싼 JSON 까지 꺼낸다.
    """
    if not model.startswith(ANTHROPIC_PREFIX):
        return kwargs
    return {k: v for k, v in kwargs.items() if k not in ("temperature", "response_format")}


def _api_model(model: str) -> str:
    """API 에 보낼 이름. 우리 쪽 접두어는 떼고 보낸다."""
    for prefix in (GOOGLE_PREFIX, ANTHROPIC_PREFIX):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


# ── 구글 직접 호출 → OpenRouter 전환 (미리 짜 둔 것. 아직 켜지 않았다) ─────────────────
#
# 09-22·09-23 에 구글 쪽 InternalServerError 와 한 번에 432초 걸린 호출이 있었다.
# 구글이 계속 불안하면 아래 둘 중 하나로 옮긴다.
#
# [1] 수동 전환: 코드 변경 없이 .env 만 바꾼다
#     접두어가 "google-ai/" 가 아니면 _client 가 이미 OpenRouter 로 보낸다. 구글 모델은
#     OpenRouter 에서 "google/<이름>" 이다 (.env.example 참고, 이름은 openrouter.ai/models 에서 확인).
#       MODEL_SMALL=google-ai/gemini-3.5-flash-lite  ->  google/gemini-3.5-flash-lite
#       MODEL_LARGE=google-ai/gemini-3.1-flash-lite  ->  google/gemini-3.1-flash-lite
#     OPENROUTER_API_KEY 는 .env 에 이미 있다. 판정(judge.py)과 캡처(MODEL_VISION)도 같은 _client 를 쓰므로
#     따로 고칠 곳은 없다.
#     단가: costs._GEMINI_RATES 에 google/·google-ai/ 둘 다 같은 값으로 있다 (09-23). 다른 모델로
#           바꾸면 거기나 MODEL_COST_JSON 에 단가를 넣는다. 없으면 비용이 None 이고 상한이 걸리지 않는다.
#
# [2] 자동 폴백: 구글이 5xx·시간 초과로 실패하면 같은 모델을 OpenRouter 로 한 번 더 부른다
#     켜는 조건은 env LLM_FALLBACK_OPENROUTER=1 로 둔다. 무료 할당이 유료 호출로 바뀌기 때문이다.
#     형식 위반(ValidationError)은 폴백 대상이 아니다. 그건 attempt_models() 의 재시도·승격이 맡는다.
#
# FALLBACK_TIMEOUT_S = 30.0  # 432초 호출 대책. openai SDK 기본값은 600초, 재시도 2회다
#
#
# def _openrouter_twin(model: str) -> str | None:
#     """google-ai/<이름> 에 해당하는 OpenRouter 모델 이름. 구글 직접 호출이 아니면 None."""
#     if not model.startswith(GOOGLE_PREFIX):
#         return None
#     return "google/" + model[len(GOOGLE_PREFIX):]
#
#
# def _fallback_enabled() -> bool:
#     return os.environ.get("LLM_FALLBACK_OPENROUTER") == "1" and bool(os.environ.get("OPENROUTER_API_KEY"))
#
#
# async def _create(model: str, **kwargs: Any) -> tuple[Any, str]:
#     """chat.completions.create 를 감싼다. (응답, 실제로 답한 모델) 을 돌려준다.
#
#     extract_slots·transcribe_image·judge.rank 의 create 호출을 이 함수로 바꾸면 세 곳이 함께 폴백한다.
#     실제로 답한 모델을 돌려주는 이유: _last_meta["model"] 과 비용 계산이 OpenRouter 이름을 봐야 한다.
#     """
#     import openai
#
#     try:
#         client = _client(model).with_options(timeout=FALLBACK_TIMEOUT_S, max_retries=0)
#         res = await client.chat.completions.create(model=_api_model(model), **kwargs, **_extra_body(model))
#         return res, model
#     except (openai.InternalServerError, openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError):
#         twin = _openrouter_twin(model)
#         if not twin or not _fallback_enabled():
#             raise
#         # Langfuse 에 폴백했다는 흔적을 남긴다 (어느 호출이 유료로 넘어갔는지 보려고)
#         _last_meta["fallback_from"] = model
#         res = await _client(twin).chat.completions.create(model=twin, **kwargs, **_extra_body(twin))
#         return res, twin
#
#
# 호출부 바꾸는 법 (extract_slots 예시):
#     res, used = await _create(model, messages=messages, temperature=0, response_format={"type": "json_object"})
#     ...
#     "model": used,
#     "cost_usd": cost_guards.estimate_cost_usd(used, tokens_in, tokens_out),
#
# 켜기 전에 할 것:
#   - tests/test_llm.py 에 "구글 5xx 면 OpenRouter 이름으로 한 번 더 부른다", "env 가 없으면 그대로 예외" 두 개
#   - judge.py 는 지금 _client 를 루프 밖에서 한 번 만든다. _create 로 바꾸면 그 줄을 지운다
#   - SDD 9절 env 표에 LLM_FALLBACK_OPENROUTER 추가
# ────────────────────────────────────────────────────────────────────────────────────


def model_large() -> str:
    return os.environ.get("MODEL_LARGE", DEFAULT_LARGE)


def model_small() -> str | None:
    """소형 모델 이름. 없으면 None (그때는 대형이 처음부터 맡는다).

    MODEL_SMALL 환경변수만 본다. 로컬 GGUF 는 파일이 있어도 쓰지 않는다 (09-28 결정: 허용한 두 모델만).
    """
    return os.environ.get("MODEL_SMALL") or None


def _transient_errors() -> tuple[type[Exception], ...]:
    try:
        import openai
    except ImportError:  # 키 없는 테스트 환경
        return ()
    return (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError, openai.RateLimitError)


_TRANSIENT = _transient_errors()


def attempt_models() -> list[str]:
    """시도 순서 (SDD 5절 1단계 "스키마 위반 시 재시도 1회 → 대형 모델 승격").

      로컬 GGUF 가 있으면  [소형, 대형]        소형은 한 번만. 같은 입력에 같은 답이 나오므로
                                              (temperature 0) 다시 시도해도 결과가 같다.
                                              09-20 측정: 소형 재시도 때문에 30초 넘게 걸렸다
      원격 소형이 있으면   [소형, 소형, 대형]  응답이 흔들릴 수 있어 한 번 더 시도한다
      소형이 없으면        [대형, 대형]        승격할 곳이 없으니 재시도까지만
    """
    small = model_small()
    large = model_large()
    if not small or small == large:
        return [large, large]
    if small.startswith("local/"):
        return [small, large]
    return [small, small, large]


def _fill(prompt: str, text: str, previous: Slots | None, preset: Preset | None) -> str:
    """Langfuse 프롬프트의 {{변수}} 를 채운다.

    Langfuse 의 compile 을 쓰지 않고 직접 채우는 이유: 변수 세 개뿐이고, 값이 비었을 때
    "없음"으로 적어 모델이 빈 자리를 지어내지 않게 하려는 것이다.
    """
    return (
        prompt.replace("{{previous_slots}}", previous.model_dump_json() if previous else "없음")
        .replace("{{preset_hint}}", preset or "없음")
        .replace("{{text}}", text)
    )


def _slot_messages(prompt: str, filled: str, previous: Slots | None, preset: Preset | None) -> list[dict[str, str]]:
    """슬롯 추출에 보낼 messages. 되묻기의 답이면 이전 슬롯을 모델 자신의 앞 차례 답으로 둔다.

    10-01: 이전 슬롯을 한 메시지 안의 "## 이전 슬롯" 절로만 주면 gpt-4o-mini·gemini 모두 이번 답만 뽑고
    시각·장소·다른 참석자를 버렸다(3/3). 같은 프롬프트로 앞 차례를 만들고 그 답을 이전 슬롯으로 두면 그 위에
    덧붙인다(4/4, 사람 추가·빼기 포함). 앞 차례의 입력 문장은 남아 있지 않아 자리 표시만 둔다.
    """
    if previous is None:
        return [{"role": "user", "content": filled}]
    return [
        {"role": "user", "content": _fill(prompt, "(앞 대화)", None, preset)},
        {"role": "assistant", "content": previous.model_dump_json()},
        {"role": "user", "content": filled},
    ]


def drop_answered_missing(slots: Slots) -> Slots:
    """되묻기의 답으로 채운 참석자 칸을 missing 에서 뺀다.

    모델이 이전 missing 을 그대로 옮겨 적어, 방금 "지하철로" 라고 답했는데 "차로 오시나요" 를 또 물었다 (10-01).
    출발지·이동수단만 본다. 출입 절차는 _parse 처럼 missing 을 믿는다 (모른다는 답이 더 안전하다).
    """
    keep: list[str] = []
    for path in slots.missing:
        m = re.fullmatch(r"participants\[(\d+)\]\.(origin|transport)", path)
        if m and int(m.group(1)) < len(slots.participants):
            if getattr(slots.participants[int(m.group(1))], m.group(2)) is not None:
                continue
        keep.append(path)
    if keep == slots.missing:
        return slots
    return slots.model_copy(update={"missing": keep})


def _parse_json_block(raw: str) -> dict[str, Any]:
    """모델 출력에서 JSON 객체를 꺼낸다. judge.py 도 같은 파서를 쓴다."""
    body = raw.strip()
    if body.startswith("```"):  # ```json ... ``` 로 감싸 오는 모델이 있다
        body = body.split("```")[1]
        body = body[4:] if body.startswith("json") else body
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON 을 찾지 못했습니다: {raw[:200]!r}")
    return json.loads(body[start : end + 1])


# 1인칭을 부르는 말. 모델이 문장 그대로 "저", "제가" 로 뽑아 오면 화면과 결과 표에 그대로 나온다.
# 사람 이름 자리라 한 가지로 맞춘다. 프롬프트에도 "나" 로 두라고 적었지만 모델이 자주 어긴다.
_FIRST_PERSON = {"저", "제", "제가", "저는", "나는", "본인", "me", "I"}
FIRST_PERSON_NAME = "나"


def fill_pickup_transport(slots: Slots) -> Slots:
    """남의 차를 얻어 타는 사람의 이동수단을 운전자 것으로 채운다.

    태워 준다는 말이 있으면 그 사람은 운전자의 차를 탄다. 그런데 모델이 그 칸을 비우고
    missing 에 적는 경우가 있어, 사용자가 "차로 오시나요" 라는 물을 필요 없는 질문을 받는다
    (09-21 실측). 운전자를 찾아 그 값을 그대로 쓰고, missing 에서도 뺀다.
    """
    by_name = {p.name: p for p in slots.participants}
    participants = list(slots.participants)
    filled: set[int] = set()

    for index, person in enumerate(participants):
        if person.transport is not None or not person.pickup:
            continue
        driver = by_name.get(person.pickup)
        transport = driver.transport if driver and driver.transport else "car"
        participants[index] = person.model_copy(update={"transport": transport})
        filled.add(index)

    if not filled:
        return slots
    drop = {f"participants[{i}].transport" for i in filled}
    return slots.model_copy(
        update={
            "participants": participants,
            "missing": [path for path in slots.missing if path not in drop],
        }
    )


def normalize_names(slots: Slots) -> Slots:
    """1인칭 표기를 "나" 하나로 맞춘다. pickup 이 그 사람을 가리키면 그것도 같이 바꾼다."""
    renamed = {p.name: FIRST_PERSON_NAME for p in slots.participants if p.name.strip() in _FIRST_PERSON}
    if not renamed:
        return slots
    participants = [
        p.model_copy(
            update={
                "name": renamed.get(p.name, p.name),
                "pickup": renamed.get(p.pickup, p.pickup) if p.pickup else p.pickup,
            }
        )
        for p in slots.participants
    ]
    return slots.model_copy(update={"participants": participants})


# 옛 학습 데이터의 프리셋 이름. 모델을 다시 학습하기 전까지 이 값이 나온다 (2026-09-21 범용 전환)
LEGACY_PRESETS = ("ship_maintenance", "si_deploy")


def drop_unstated_transports(slots: Slots, text: str) -> Slots:
    """말하지 않은 이동수단을 비우고 되묻게 한다 (transport.md "말하지 않은 이동수단", 09-23).

    차인지 대중교통인지로 출발 시각이 30분 넘게 갈린다. 지어낸 값으로 계산하는 것보다 한 번 묻는 편이 낫다.
    """
    if slots.out_of_scope:
        return slots
    rows = [{"name": p.name, "transport": p.transport, "pickup": p.pickup} for p in slots.participants]
    drop = domain_rules.unstated_transports(text, rows)
    if not drop:
        return slots
    participants = [
        p.model_copy(update={"transport": None}) if i in drop else p for i, p in enumerate(slots.participants)
    ]
    missing = [*slots.missing, *[f"participants[{i}].transport" for i in drop if f"participants[{i}].transport" not in slots.missing]]
    return slots.model_copy(update={"participants": participants, "missing": missing})


def fill_unstated_date(slots: Slots, text: str) -> Slots:
    """시각만 뽑고 날짜 말을 버렸으면 문장의 날짜 말을 앞에 붙인다 (SDD 5절 1단계, 10-09).

    대화 캡처에서 "토요일 점심 되지?" 와 "12시 반에 보자" 가 다른 말풍선이라 "12시 반" 만 나왔다(3/3).
    날짜가 없으면 임시 세션이 되어 기간 판정도 출발 시각 확정도 못 한다. 날짜 말이 둘 이상이면 고르지 않는다.
    """
    if slots.out_of_scope or not slots.datetime:
        return slots
    if domain_rules.parse_meet_date(slots.datetime, date.today()) is not None:
        return slots
    phrase = domain_rules.date_phrase(text)
    if phrase is None:
        return slots
    return slots.model_copy(update={"datetime": f"{phrase} {slots.datetime}"})


def drop_unstated_cook(slots: Slots, text: str, previous: Slots | None = None) -> Slots:
    """직접 해 먹는다는 단서가 없으면 cook 을 지운다 (checklist.md "사 먹는 자리와 해 먹는 자리", 09-27).

    모델이 "고기"만 보고 cook 을 붙여 고깃집 약속에 숯·버너를 준비물로 냈다.
    재질문의 답("저는 강동구에서 지하철로")에는 단서가 없다. 이전 슬롯에서 이미 살아남은 cook 은 둔다.
    """
    from backend.app.domain import checklist as domain_checklist

    if previous is not None and "cook" in (previous.constraints or []):
        return slots
    if slots.out_of_scope or not domain_checklist.unstated_cook(text, list(slots.constraints)):
        return slots
    return slots.model_copy(update={"constraints": [c for c in slots.constraints if c != "cook"]})


async def settle_access(slots: Slots, text: str, previous: Slots | None) -> Slots:
    """출입 절차를 문장 단서로 확정한다 (access.md "절차 판정", domain/rules.settle_access).

    모델이 같은 문장에 절차 있음·없음·모름을 오간다(09-23 측정 0.78). 역 앞 저녁 약속에 매번
    "출입 절차가 있나요?"를 묻거나, 단서 없는 사무실에 없는 절차 소요를 빼는 일을 막는다.
    재질문의 답이면 문장 단서만 보고, 모델이 이전에 정한 절차 값을 잃었으면 이전 값을 그대로 둔다.

    규칙이 못 가르는 5순위에서만 판단 모델(services/access_judge, Jev)을 부른다. 켜져 있을 때만이고,
    이름·출발지를 가린 문장을 보낸다. 실패하면 "failed" 로 넘겨 되묻게 한다.
    무엇으로 정했는지(access_basis)와 판단 모델 결과(access_judge)는 _last_meta 에 남긴다.
    """
    if slots.out_of_scope:
        return slots
    if not slots.destination and "destination" not in slots.missing:
        # 목적지를 비우고 missing 에도 안 적는 모델이 있다(09-23 gpt-4o-mini). 그대로 가면 지오코딩에서 실패한다
        slots = slots.model_copy(update={"missing": [*slots.missing, "destination"]})
    from backend.app.domain import masking
    from backend.app.services import access_judge

    followup = previous is not None
    model_access = slots.access.model_dump() if slots.access else None

    def settle(judge: Any) -> tuple[dict[str, Any] | None, list[str], str]:
        return domain_rules.settle_access(
            text, slots.destination, slots.purpose, model_access, list(slots.missing), followup, judge
        )

    access, missing, basis = settle(None)
    _last_meta.pop("access_judge", None)
    if basis == "model" and access_judge.enabled():
        started = time.monotonic()
        try:
            result = await access_judge.judge(masking.mask(text, slots), slots.destination, slots.purpose)
        except Exception as e:  # noqa: BLE001  장애가 오답으로 새지 않게 되묻는다
            _last_meta["access_judge"] = {"error": type(e).__name__, "latency_ms": int((time.monotonic() - started) * 1000)}
            access, missing, basis = settle("failed")
        else:
            _last_meta["access_judge"] = {**result, "latency_ms": int((time.monotonic() - started) * 1000)}
            access, missing, basis = settle(result)
    if access is None and followup and previous.access is not None:
        # 답 문장에 절차 이야기가 없는데 모델이 값을 비웠다. 이미 정한 것을 다시 묻지 않는다
        access = previous.access.model_dump()
        missing = [m for m in missing if m != "access.required"]
        if access.get("applied") is None and access.get("required") and "access.applied" in previous.missing:
            missing.append("access.applied")
    _last_meta["access_basis"] = basis
    return slots.model_copy(update={"access": Access(**access) if access else None, "missing": missing})


def _parse(raw: str) -> Slots:
    """모델 출력을 Slots 로 검증한다. 어긋나면 ValidationError 가 위로 올라간다.

    옛 프리셋 이름은 여기서 새 값으로 바꾼다. 스키마가 거르기 전에 바꿔야 멀쩡한 답이
    이름 때문에 실패로 처리되지 않는다.
    """
    data = _parse_json_block(raw)

    # 범위 밖이라면서 참석자를 뽑아 놓는 경우가 있다 (09-21 실측). 스키마는 그 모순을 막고,
    # 막히면 멀쩡한 문장까지 failed 로 끝난다. 그래서 둘 중 하나로 정리한 뒤 검증에 넘긴다.
    #   참석자가 있으면  문장에 조율할 내용이 있다는 뜻이다. 범위 밖 표시를 내린다
    #   참석자가 없으면  범위 밖이 맞다고 보고 preset 을 비운다
    if data.get("out_of_scope"):
        if data.get("participants"):
            data["out_of_scope"] = False
        else:
            data["preset"] = None
            data["participants"] = []

    # 값을 채워 놓고 같은 칸을 missing 에도 적는 경우가 있다 (09-21 실측:
    # "방문자 등록을 해야 합니다" -> applied=false 인데 missing 에 access.applied).
    # 모델 스스로 모순이고, 둘 중 missing 이 맞다. 모른다고 말한 칸을 값으로 믿으면
    # 되묻지 않고 틀린 계산으로 넘어간다. 값을 비우고 되묻는 쪽이 안전하다.
    missing = data.get("missing") or []
    access = data.get("access")
    if isinstance(access, dict):
        if "access.applied" in missing:
            access["applied"] = None
        if "access.required" in missing:
            data["access"] = None

    # 태우는 방향을 거꾸로 적는 경우가 있다 (10-01 회귀셋 5번, gpt-4o-mini 5번 중 1번).
    #   운전자 항목에 pickup=자기 이름   태워지는 사람(이동수단·태우기 둘 다 빈 사람)이 하나면 그쪽으로 옮긴다
    #   운전자 항목에 pickup=태워지는 사람  같은 식으로 방향을 바꾼다. 대상이 이미 이동수단이 있으면 모르는 것이라 두지 않는다
    # 누구인지 못 정하면 반쪽 정보로 보고 비운 뒤 되묻는다 (아래 반쪽 규칙과 같은 길)
    pickers = [p for p in (data.get("participants") or []) if isinstance(p, dict)]
    for index, person in enumerate(pickers):
        if not (person.get("pickup") and person.get("pickup_at")):
            continue
        target_name = person["pickup"]
        if target_name == person.get("name"):
            riders = [q for q in pickers if q is not person and not q.get("transport") and not q.get("pickup")]
            rider = riders[0] if len(riders) == 1 else None
        else:
            rider = next((q for q in pickers if q.get("name") == target_name), None)
            if rider is None or rider.get("transport") or rider.get("pickup") or person.get("transport") != "car":
                continue  # 정상 방향(태워지는 사람 항목에 운전자 이름)이거나 판단할 수 없다
        if rider is not None:
            rider["pickup"], rider["pickup_at"] = person.get("name"), person["pickup_at"]
            person["pickup"] = person["pickup_at"] = None
        else:
            person["pickup"] = person["pickup_at"] = None
            if f"participants[{index}].pickup" not in missing:
                missing.append(f"participants[{index}].pickup")

    # 태우는 곳만 알고 누가 태우는지 모르면(또는 그 반대) pickup_at 만 채워 온다 (09-27 실제 캡처
    # "2명은 하단에 태워서"). 스키마는 둘을 짝으로만 받아 재시도·대형까지 모두 실패했다.
    # 반쪽은 믿지 않고 둘 다 비운 뒤 되묻는다("누가 어디서 태우나요?")
    for index, person in enumerate(data.get("participants") or []):
        if isinstance(person, dict) and bool(person.get("pickup")) != bool(person.get("pickup_at")):
            person["pickup"] = person["pickup_at"] = None
            path = f"participants[{index}].pickup"
            if path not in missing:
                missing.append(path)
    # 이동수단을 비워 놓고 missing 에 안 적는 경우가 있다 (09-28 gpt-4o-mini, 회귀셋 5·7번). 스키마가 막아
    # 재시도·대형까지 모두 실패했다. 검증 전에 정리한다.
    #   태워지는 사람  운전자의 차를 탄다. 운전자 이동수단(없으면 car)으로 채운다 (fill_pickup_transport 와 같은 규칙)
    #   그 밖         모르는 것이므로 missing 에 적어 되묻는다. 지어 넣지 않는다
    people = [p for p in (data.get("participants") or []) if isinstance(p, dict)]
    by_name = {p.get("name"): p for p in people}
    for index, person in enumerate(people):
        if person.get("transport") is not None:
            continue
        if person.get("pickup") and person.get("pickup_at"):
            driver = by_name.get(person.get("pickup")) or {}
            person["transport"] = driver.get("transport") or "car"
            missing = [m for m in missing if m != f"participants[{index}].transport"]
        elif f"participants[{index}].transport" not in missing:
            missing.append(f"participants[{index}].transport")

    # 출발지를 비워 놓고 missing 에 안 적는 경우가 있다 (10-09 대화 캡처, 3/3). 두면 4단계가 그 사람을
    # 경로 계산에서 조용히 뺀다. 태워지는 사람은 탑승 지점부터 세므로 묻지 않는다 (pipeline._drop_needless 와 같은 기준)
    for index, person in enumerate(people):
        path = f"participants[{index}].origin"
        if not person.get("origin") and not person.get("pickup_at") and path not in missing:
            missing.append(path)

    # 집결지의 모인 뒤 이동수단·시각·모이는 사람은 비어도 계산된다(없으면 차, 역산, 한 단계 계산. SDD 3절).
    # 모델이 missing 에 적으면 "정보가 더 필요합니다" 같은 두루뭉술한 질문만 나간다 (09-27)
    missing = [m for m in missing if not m.startswith("rendezvous.")]
    data["missing"] = missing

    if data.get("preset") in LEGACY_PRESETS:
        # 옛 값에는 일반 약속에 해당하는 것이 없었다. 절차가 있다고 본 경우만 visit 으로 옮기고,
        # 절차가 없거나 아직 모르면 meeting 으로 둔다. visit 으로 몰면 없는 절차 소요를 빼게 된다
        access = data.get("access") or {}
        data["preset"] = "visit" if access.get("required") is True else "meeting"
    return fill_pickup_transport(Slots.model_validate(data))


async def extract_slots(
    text: str,
    previous: Slots | None = None,
    preset: Preset | None = None,
) -> Slots:
    """문장 → Slots. 스키마를 어기면 한 번 더 시도한다 (SDD 5절 1단계).

    재시도 때는 무엇이 틀렸는지 모델에 붙여 준다. 그래도 어기면 예외를 올리고, 파이프라인이 failed 로 답한다.
    """
    prompt, version = langfuse.get_prompt(SLOT_PROMPT)
    filled = _fill(prompt, text, previous, preset)
    models = attempt_models()

    last_error: Exception | None = None
    for attempt, model in enumerate(models, start=1):
        # 로컬 GGUF 차례면 학습 때와 같은 프롬프트로 부른다 (services/slot_model.py).
        # Langfuse 프롬프트는 대형 모델용이라 여기서는 쓰지 않는다. 형식을 바꾸면 학습 효과가 사라진다
        if model.startswith("local/"):
            # 허용 목록에 없다 (09-28). model_small() 이 더는 로컬을 내지 않지만, 누가 env 에 적어도 막는다
            raise ModelNotAllowed(f"허용하지 않은 모델입니다: {model}")

        messages = _slot_messages(prompt, filled, previous, preset)
        if attempt > 1 and last_error is not None:
            messages.append(
                {
                    "role": "user",
                    "content": f"방금 출력이 형식을 어겼습니다: {last_error}. 형식을 지켜 JSON 만 다시 출력하세요.",
                }
            )
        # 클라이언트는 모델마다 고른다. 소형은 구글, 대형은 OpenRouter 처럼 섞일 수 있다
        try:
            res, model = await _create(
                model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except _TRANSIENT as e:
            # 시간 초과·연결 끊김·5xx·429 는 다음 차례(재시도 → 대형)로 넘긴다. 형식 위반과 같은 길이다
            last_error = e
            continue
        raw = res.choices[0].message.content or ""
        usage = getattr(res, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            slots = _parse(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_error = e
            continue
        if previous is not None:
            slots = drop_answered_missing(slots)
        slots = await settle_access(drop_unstated_cook(drop_unstated_transports(normalize_names(slots), text), text, previous), text, previous)
        slots = fill_unstated_date(slots, text)
        # 사용자가 프리셋을 골랐으면 그 값이 우선이다 (SDD 2절 AgentRequest.preset)
        if preset and not slots.out_of_scope and slots.preset != preset:
            slots = slots.model_copy(update={"preset": preset})
        # Result.model_small / prompt_version 은 6단계에서 함께 채운다. 그때 이 값을 쓰려면
        # 반환형을 (Slots, 모델, 프롬프트 버전) 으로 넓힌다 (SDD 4절)
        _last_meta.update(
            {
                "model": model,
                "prompt_version": version,
                "attempts": attempt,
                "escalated": model == model_large() and attempt > 1 and models[0] != model_large(),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_guards.estimate_cost_usd(model, tokens_in, tokens_out),
            }
        )
        return slots

    raise last_error if last_error else RuntimeError("슬롯 추출에 실패했습니다")


def model_vision() -> str:
    """캡처를 읽을 모델 (SDD 9절 MODEL_VISION). 비어 있으면 대형 모델이 읽는다. 그 모델이 이미지를 받아야 한다."""
    return os.environ.get("MODEL_VISION") or model_large()


async def transcribe_image(image_base64: str, mime: str) -> str:
    """캡처 → 대화 텍스트 (SDD 5절 0단계, 8절 converge/vision-transcribe).

    같은 모델로 한 번 더 시도한다. 둘 다 실패하면 예외를 올리고, 파이프라인이 문장으로 다시 받는다.
    약속과 무관한 이미지면 모델이 빈 문자열을 낸다. 그것도 실패로 본다 (없는 대화를 지어내지 않게).
    """
    prompt, version = langfuse.get_prompt(VISION_PROMPT)
    model = model_vision()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_base64}"}},
            ],
        }
    ]
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            res, model = await _create(model, messages=messages, temperature=0)
        except LlmUnavailable:
            raise
        except Exception as e:  # noqa: BLE001  네트워크·429 는 한 번 더 해 본다
            last_error = e
            continue
        text = (res.choices[0].message.content or "").strip()
        usage = getattr(res, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        _last_meta.update(
            {
                "vision_model": model,
                "vision_prompt_version": version,
                "vision_attempts": attempt,
                "vision_tokens_in": tokens_in,
                "vision_tokens_out": tokens_out,
                "vision_cost_usd": cost_guards.estimate_cost_usd(model, tokens_in, tokens_out),
            }
        )
        if text:
            return text
        last_error = ValueError("캡처에서 약속 대화를 찾지 못했습니다")
    raise last_error if last_error else RuntimeError("캡처를 읽지 못했습니다")


async def _run_local(text: str) -> str:
    """로컬 GGUF 호출. CPU 에서 20초쯤 걸리므로 이벤트 루프를 막지 않게 스레드로 돌린다."""
    from backend.app.services import slot_model

    return await asyncio.to_thread(slot_model.extract_json, text)


def _finish(
    slots: Slots,
    preset: Preset | None,
    model: str,
    version: str,
    attempt: int,
    models: list[str],
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> Slots:
    """공통 마무리. 프리셋을 맞추고, 이름을 다듬고, 무엇으로 얼마에 뽑았는지 남긴다.

    로컬 GGUF 는 토큰 요금이 없어 비용이 0 이다. 그 차이가 라우팅 전후 비교의 핵심이라
    (SDD 5절 라우팅, 체크리스트 40번) 모델 이름과 함께 그대로 남긴다.
    """
    slots = normalize_names(slots)
    # 사용자가 프리셋을 골랐으면 그 값이 우선이다 (SDD 2절 AgentRequest.preset)
    if preset and not slots.out_of_scope and slots.preset != preset:
        slots = slots.model_copy(update={"preset": preset})
    local = model.startswith("local/")
    _last_meta.update(
        {
            "model": model,
            "prompt_version": "finetune/kanana" if local else version,
            "attempts": attempt,
            "escalated": model == model_large() and attempt > 1 and models[0] != model_large(),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": 0.0 if local else cost_guards.estimate_cost_usd(model, tokens_in, tokens_out),
        }
    )
    return slots
