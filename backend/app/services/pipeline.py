"""파이프라인. 0~8단계를 순서대로 부른다. 루프 없음. (SDD 5절 표가 기준)

이 파일이 하는 일은 "순서와 갈림길"뿐이다. 실제 계산은 domain/ 이, 바깥 호출은 같은 폴더의
vision·llm·geo·routes·judge·store 가 한다. 여기에 계산식이나 httpx 호출을 넣지 않는다 (BACKEND_GUIDE).

단계마다 Langfuse span 을 하나 남긴다. 어디서 끊겼는지 트레이스만 보고 알 수 있어야 한다 (필수 조건 4).

Deps 로 바깥 함수를 받는 이유:
  테스트가 키 없이 돌아야 한다 (TEST_GUIDE). 기본값은 진짜 서비스지만, 테스트는 가짜 함수를 넣어
  단계 순서와 갈림길만 검사한다.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from backend.app.domain import checklist as domain_checklist
from backend.app.domain import masking
from backend.app.domain import router as model_router
from backend.app.domain import rules as domain_rules
from backend.app.observability import langfuse
from backend.app.schemas.request import AgentRequest
from backend.app.schemas.result import AgentResponse, Candidate, GeocodedPin, ParticipantResult, Result
from backend.app.schemas.slots import Participant, Slots
from backend.app.services import costs as cost_guards

# 확신도가 이보다 낮은 핀이 하나라도 있으면 사용자에게 확인을 받는다 (SDD 5절 2단계)
GEOCODE_CONFIRM_BELOW = 0.8


class NotYourSession(Exception):
    """남의 세션으로 재질문했다. 라우터가 403 으로 바꾼다 (SDD 5절 재질문)."""


class SessionLocked(Exception):
    """약속이 지나 잠긴 세션이다. 라우터가 409 로 바꾼다 (SDD 5절 재질문). LLM 을 부르기 전에 막는다."""


@dataclass
class Deps:
    """단계가 부르는 바깥 함수들. 이름과 순서는 SDD 5절 표와 같다."""

    extract_text: Callable[[str], Awaitable[str]] | None = None  # 0 vision
    extract_slots: Callable[..., Awaitable[Slots]] | None = None  # 1 llm
    geocode_all: Callable[..., Awaitable[list[GeocodedPin]]] | None = None  # 2 geo
    build_candidates: Callable[..., Awaitable[Any]] | None = None  # 3 geo
    compute_routes: Callable[..., Awaitable[Any]] | None = None  # 4 routes
    apply_rules: Callable[..., Any] | None = None  # 5 domain/rules
    rank: Callable[..., Awaitable[Any]] | None = None  # 6 judge (없으면 규칙 점수 순)
    departure: Callable[..., Any] | None = None  # 7 domain/rules
    first_last: Callable[..., Awaitable[dict[str, str]]] | None = None  # 7 야간 첫차·막차 (transit_schedule)
    save: Callable[..., Awaitable[str]] | None = None  # 8 store
    load_session: Callable[..., Awaitable[Any]] | None = None  # 재질문: 이전 세션 읽기
    previous_slots: Slots | None = None  # 재질문이면 이전 슬롯 (SDD 5절 재질문)
    extras: dict[str, Any] = field(default_factory=dict)


def _answer(
    session_id: str,
    stage: str,
    slots: Slots | None,
    trace_id: str,
    message: str,
    questions: list[str] | None = None,
    geocoded: list[GeocodedPin] | None = None,
    result: Result | None = None,
) -> AgentResponse:
    return AgentResponse(
        session_id=session_id,
        stage=stage,  # type: ignore[arg-type]
        slots=slots,
        result=result,
        questions=questions or [],
        message=message,
        trace_id=trace_id,
        geocoded=geocoded,
    )


async def run(req: AgentRequest, user_id: str, deps: Deps | None = None) -> AgentResponse:
    """요청 하나를 끝까지 처리한다. 돌아오는 stage 가 화면을 정한다 (SDD 2절)."""
    deps = deps or Deps()
    # 세션 id 는 첫 요청에서 만든다. 8단계 저장이 붙으면 이 값으로 행을 만들고, 그 전에도
    # 재질문(이전 슬롯 유지)과 Langfuse session_id 가 이어지도록 해야 한다 (SDD 5절 재질문, 22번)
    # 새 세션이면 이 id 를 그대로 DB 행의 id 로 쓴다. DB 가 따로 만들면 Langfuse 세션과 어긋나
    # 되묻기와 답변이 다른 세션으로 갈라진다 (09-23 적재 확인). 그래서 uuid 모양으로 만든다
    session_id = req.session_id or str(uuid.uuid4())
    # 테스트가 넣지 않은 단계는 진짜 서비스로 채운다
    for stage_name in (
        "extract_text",
        "extract_slots",
        "geocode_all",
        "build_candidates",
        "compute_routes",
        "rank",
        "first_last",
        "save",
        "load_session",
    ):
        if getattr(deps, stage_name) is None:
            setattr(deps, stage_name, _default(stage_name))

    is_new_session = req.session_id is None

    with langfuse.trace("agent", user_id=user_id, session_id=session_id, preset=req.preset) as tr:
        text = req.text or ""

        # 재질문이면 이전 슬롯을 읽어 1단계 프롬프트에 넣는다 (SDD 5절 재질문)
        if not is_new_session and deps.previous_slots is None:
            with tr.span("load_session") as span:
                try:
                    deps.previous_slots = await _load_previous(deps, session_id, user_id)
                    span.output = {"found": deps.previous_slots is not None}
                    # 저장된 적 없는 id 다(날짜 되묻기·범위 밖은 세션을 남기지 않는다). 없는 행을 갱신하면
                    # 저장이 조용히 사라지므로 같은 id 로 새로 만든다 (09-23)
                    if deps.previous_slots is None and deps.load_session is not None:
                        is_new_session = True
                except (NotYourSession, SessionLocked):
                    raise
                except Exception as e:  # noqa: BLE001  저장소가 없어도 계산은 이어 간다
                    span.error = str(e)

        # 0. 캡처 → 텍스트. 실패하면 문장으로 다시 받는다
        # 캡처 읽기 비용. 슬롯 추출 비용과 합쳐 요청당 상한을 본다. 이미지를 대형 모델로 읽으므로
        # 요청에서 가장 비싼 호출일 수 있다 (41번 비용 방어)
        vision_cost_usd = 0.0
        if req.image_base64:
            with tr.span("vision") as span:
                started = time.monotonic()
                try:
                    transcript = await _call(deps.extract_text, req.image_base64)
                    # 캡처와 함께 적은 문장이 있으면 뒤에 붙인다. 캡처에 없는 사정을 덧붙이는 경우다
                    text = f"{transcript}\n{text}" if text.strip() else transcript
                    span.output = {"chars": len(transcript)}
                    vision_cost_usd = float(_llm_meta().get("vision_cost_usd") or 0.0)
                    await _log_llm("vision", tr.id, session_id, started, "ok", meta=_vision_meta())
                except Exception as e:  # noqa: BLE001
                    # 오류 문구에 모델 출력이 섞일 수 있다. 가림말을 만들 슬롯이 없으니 종류만 남긴다
                    span.error = type(e).__name__
                    await _log_llm("vision", tr.id, session_id, started, "error", type(e).__name__, meta=_vision_meta())
                    return _answer(
                        session_id,
                        "need_info",
                        None,
                        tr.id,
                        "캡처를 읽지 못했습니다. 문장으로 입력해 주세요.",
                        questions=["언제, 어디서, 누가 어디서 출발해 모이나요?"],
                    )

        # 1. 텍스트 → 슬롯
        # 입력 문장은 추출이 끝난 뒤 이름·출발지를 가려서 남긴다 (domain/masking.py).
        # 추출에 실패하면 가림말을 만들 수 없으니 길이만 남긴다
        with tr.span("extract") as span:
            started = time.monotonic()
            span.input = {"chars": len(text)}
            try:
                slots = await _call(deps.extract_slots, text, deps.previous_slots, req.preset)
                span.input = {"text": masking.mask(text, slots)[:200]}
                span.output = masking.mask(slots.model_dump(exclude={"participants"}), slots)
                await _log_llm("extract", tr.id, session_id, started, "ok")
            except Exception as e:  # noqa: BLE001
                # 스키마 위반 오류 문구에는 모델 출력 원문(이름·출발지)이 들어 있다. 종류만 남긴다
                span.error = type(e).__name__
                await _log_llm("extract", tr.id, session_id, started, "error", type(e).__name__)
                return _answer(session_id, "failed", None, tr.id, "요청을 이해하지 못했습니다. 다시 입력해 주세요.")

        # 1-1. 범위 밖. 무엇을 하는 도구인지 알려준다 (output-contract.md).
        # 실시간 질문만 오는 게 아니다(메뉴 추천 등, 09-23). 이유를 모르므로 한 사례에 묶인 말을 하지 않는다
        if slots.out_of_scope:
            return _answer(
                session_id,
                "out_of_scope",
                slots,
                tr.id,
                "여러 사람이 모일 자리와 각자의 출발 시각을 정하는 일만 합니다. "
                "언제, 어디서 모이는지와 누가 어디서 무엇을 타고 오는지 적어 주세요.",
            )

        # 1-3. 기간 판정. 지난 날짜거나 오늘+N일을 넘으면 되묻는다. N 은 session.md 의 값이다.
        # 1-2(누락 되묻기)보다 먼저 본다. 받을 수 없는 날짜인데 출발지부터 다 답하게 하면 헛수고다 (09-23 E2E).
        # 번호는 SDD 5절 표 그대로 두고 순서만 앞당겼다
        # 날짜를 못 읽으면 판정하지 않는다. 시각만 있는 약속("저녁 7시")도 계산은 할 수 있어야 한다
        with tr.span("period") as span:
            today = domain_rules.today_local(datetime.now(timezone.utc))
            meet_date = domain_rules.parse_meet_date(slots.datetime, today)
            problem = domain_rules.meet_window_problem(meet_date, today) if meet_date else None
            if meet_date and not problem and domain_rules.meet_time_passed(
                meet_date, domain_rules.parse_meet_time(slots.datetime), today, datetime.now(timezone.utc)
            ):
                problem = "오늘 그 시각은 이미 지났습니다. 약속 날짜를 다시 알려 주세요."
            span.output = {"date": meet_date.isoformat() if meet_date else None, "ok": problem is None}
        if problem:
            return _answer(session_id, "need_info", slots, tr.id, problem, questions=["언제 모이나요?"])

        # 1-2. 필수 슬롯 누락
        # 절차 단서가 아예 없으면 슬롯의 access 가 통째로 None 으로 온다. 그 상태로 계산하면
        # 준비물도 역산 기준도 못 정하므로 되묻는다 (SDD 5절 1-2, 7-1). 슬롯 스키마는 건드리지 않는다.
        # Access.required 는 bool 필수라 "모름"을 담을 자리가 없고, 바꾸면 파인튜닝 출력 계약이 깨진다
        if slots.access is None and not slots.out_of_scope and "access.required" not in slots.missing:
            slots.missing = [*slots.missing, "access.required"]
        slots.missing = _drop_needless(slots)
        if slots.missing:
            session_id = await _persist_quietly(
                deps,
                tr,
                session_id=session_id,
                is_new=is_new_session,
                user_id=user_id,
                slots=slots,
                pins=[],
                status="draft",
            )
            is_new_session = False
            return _answer(
                session_id,
                "need_info",
                slots,
                tr.id,
                "계산하려면 몇 가지가 더 필요합니다.",
                questions=_questions_for(slots.missing),
            )

        # 2. 지오코딩
        with tr.span("geocode") as span:
            try:
                pins = await _call(deps.geocode_all, slots)
                span.output = {"pins": len(pins)}
            except Exception as e:  # noqa: BLE001
                span.error = str(e)
                return _answer(session_id, "failed", slots, tr.id, "위치를 찾지 못했습니다. 지명을 다시 알려 주세요.")

        # 2-1. 확신도가 낮으면 핀 확인. 사용자가 고친 좌표는 confirmed_participants 로 다시 온다
        unsure = [p for p in pins if p.kind == "participant" and p.confidence < GEOCODE_CONFIRM_BELOW]
        if unsure and not req.confirmed_participants:
            session_id = await _persist_quietly(
                deps,
                tr,
                session_id=session_id,
                is_new=is_new_session,
                user_id=user_id,
                slots=slots,
                pins=pins,
                status="draft",
            )
            is_new_session = False
            return _answer(
                session_id,
                "need_confirm",
                slots,
                tr.id,
                "출발 위치가 맞나요? 핀을 끌어서 고친 뒤 계산을 누르세요.",
                geocoded=pins,
            )
        if req.confirmed_participants:
            # 누구 핀이든 고칠 수 있다 (SDD 7절, 09-18 결정). 소유권은 표시용이다
            pins = _apply_confirmed(pins, req.confirmed_participants)

        # 3. 집결 후보
        with tr.span("candidates") as span:
            try:
                raw_candidates = await _call(deps.build_candidates, slots, pins)
                span.output = {"count": len(raw_candidates)}
            except Exception as e:  # noqa: BLE001
                span.error = str(e)
                return _answer(session_id, "failed", slots, tr.id, "집결 후보를 찾지 못했습니다.", geocoded=pins)

        # 4. 참석자 × 후보 경로
        with tr.span("routes") as span:
            plans = _route_plans(slots, pins, raw_candidates)
            try:
                routes = await _call(deps.compute_routes, plans)
            except Exception as e:  # noqa: BLE001
                span.error = str(e)
                routes = []
            failed_names = sorted({r["key"][1] for r in routes if r.get("error")})
            span.output = {
                "요청": len(plans),
                "실패": len([r for r in routes if r.get("error")]),
                "실패자": masking.mask(failed_names, slots),
            }

        # 6. 판정. 소형 경로(SDD 5절 라우팅 small)면 대형 모델을 부르지 않는다.
        # 요청당 상한(41번)을 넘었어도 대형을 생략하고 규칙 점수 순서로 간다.
        rankings: list[dict[str, Any]] | None = None
        routed_to = model_router.route(slots)
        spent_usd = float(_llm_meta().get("cost_usd") or 0.0) + vision_cost_usd
        cap = cost_guards.per_request_limit()
        if routed_to == "large" and cost_guards.over_limit(spent_usd, cap):
            with tr.span("judge") as span:
                span.output = {"skipped": "비용 상한 초과", "spent_usd": spent_usd, "cap_usd": cap}
        elif routed_to == "large":
            with tr.span("judge") as span:
                started = time.monotonic()
                try:
                    rankings = await _call(
                        deps.rank, slots, _judge_candidates(raw_candidates, slots), _judge_rows(routes, slots)
                    )
                    span.output = {"rankings": masking.mask(rankings, slots)}
                    await _log_llm("judge", tr.id, session_id, started, "ok", routed_to=routed_to, meta=_judge_meta())
                except Exception as e:  # noqa: BLE001
                    await _log_llm("judge", tr.id, session_id, started, "error", type(e).__name__, routed_to, _judge_meta())
                    # 판정이 실패해도 멈추지 않는다. 규칙 점수 순서로 대신 채운다 (SDD 5절 6단계)
                    span.error = str(e)
                    rankings = None

        # 5·7. 규칙 적용과 출발 시각 역산
        with tr.span("rules") as span:
            meet_at = domain_rules.parse_meet_time(slots.datetime)
            if meet_at is None:
                return _answer(
                    session_id,
                    "need_info",
                    slots,
                    tr.id,
                    "몇 시에 시작하는지 알려 주세요.",
                    questions=["몇 시에 시작하나요?"],
                    geocoded=pins,
                )
            result = _build_result(slots, raw_candidates, routes, meet_at, rankings, routed_to)
            span.output = {"후보": len(result.candidates), "참석자행": len(result.per_participant)}

        # 7-2. 야간 대중교통이면 탑승역의 첫차·막차 (schedule.md night_check_last_train).
        # 끊긴 시간에 타야 하는 사람은 표·계획서·안내 문장에 알린다. 조회가 실패해도 결과는 낸다
        if domain_rules.load_rule("schedule")["night_check_last_train"]:
            with tr.span("trains") as span:
                span.output = await _attach_trains(result, raw_candidates, routes, meet_date, deps.first_last)

        if not result.per_participant:
            return _answer(session_id, "failed", slots, tr.id, "경로를 구하지 못했습니다. 잠시 후 다시 시도해 주세요.", geocoded=pins)

        # 7-1. 준비물과 집결 계획서. 둘 다 코드가 조립한다. LLM 을 부르지 않는다 (SDD 5절 7-1단계)
        with tr.span("checklist") as span:
            access = slots.access
            result.checklist = domain_checklist.build_checklist(
                preset=slots.preset,
                access_required=access.required if access else None,
                access_applied=access.applied if access else None,
                constraints=slots.constraints,
                has_car=any(p.transport == "car" for p in slots.participants),
                # 누가 뭘 맡을지는 출발 시각이 나온 뒤라야 정해진다. 그래서 7단계 다음이다
                carriers=domain_checklist.pick_carriers(slots, result),
            )
            result.summary_text = domain_checklist.build_summary(slots, result)
            span.output = {
                "사전 신청": len(result.checklist.before) if result.checklist else 0,
                "당일 지참": len(result.checklist.onsite) if result.checklist else 0,
                "계획서 줄": result.summary_text.count("\n") + 1,
            }

        # 8. 저장
        session_id = await _persist_quietly(
            deps,
            tr,
            session_id=session_id,
            is_new=is_new_session,
            user_id=user_id,
            slots=slots,
            pins=pins,
            result=result,
        )

        first = min((c.rank for c in result.candidates if c.rank), default=None)
        top = next((c for c in result.candidates if c.rank == first), None)
        arrive_by = result.per_participant[0].arrive_by
        # 경로를 못 구한 사람은 표에서 빠진다. 말없이 빼면 "왜 저 사람만 없지"가 되므로 알린다
        done_names = {r.name for r in result.per_participant}
        missing_people = [p.name for p in slots.participants if p.name not in done_names]
        stranded = [r.name for r in result.per_participant if r.candidate_rank == first and r.train_note and "막차" in r.train_note]
        return _answer(
            session_id,
            "done",
            slots,
            tr.id,
            (f"{top.name}에서 {arrive_by} 까지 모이는 안을 1순위로 제안합니다." if top else "결과를 정리했습니다.")
            + (f" {', '.join(missing_people)} 님은 경로를 조회하지 못해 표에서 빠졌습니다." if missing_people else "")
            + (f" {', '.join(stranded)} 님은 지하철 막차가 끊긴 시간에 타야 합니다." if stranded else ""),
            geocoded=pins,
            result=result,
        )


def _default(name: str) -> Callable[..., Any] | None:
    """Deps 에 안 넣은 단계는 진짜 서비스를 쓴다. import 는 부를 때 한다.

    지연 import 인 이유: 테스트가 가짜 함수만 넣고 돌 때 openai·httpx 를 건드리지 않게 하려는 것이다.
    아직 파일이 없는 단계(3~8)는 None 이라 _call 이 그 자리에서 실패한다.
    """
    if name == "extract_text":
        from backend.app.services import vision

        return vision.extract_text
    if name == "extract_slots":
        from backend.app.services import llm

        return llm.extract_slots
    if name == "geocode_all":
        from backend.app.services import geo

        return geo.geocode_all
    if name == "build_candidates":
        from backend.app.services import geo

        return geo.build_candidates
    if name == "compute_routes":
        from backend.app.services import routes

        return routes.compute_all
    if name == "rank":
        from backend.app.services import judge

        return judge.rank
    if name == "first_last":
        from backend.app.services import transit_schedule

        return transit_schedule.first_last_either
    if name in ("save", "load_session"):
        # DB 설정이 없으면 import 자체가 실패한다. 그때는 저장 없이 계산만 한다
        try:
            from backend.app.services import session_store
        except Exception:  # noqa: BLE001
            return None
        return session_store.save if name == "save" else session_store.load_session
    return None


async def _call(fn: Callable[..., Any] | None, *args: Any) -> Any:
    """아직 없는 단계를 부르면 그 자리에서 실패한다. 조용히 건너뛰지 않는다."""
    if fn is None:
        raise NotImplementedError("이 단계는 아직 구현 전입니다")
    out = fn(*args)
    if hasattr(out, "__await__"):
        return await out
    return out


def _drop_needless(slots: Slots) -> list[str]:
    """계산에 필요 없는 누락은 되묻지 않는다.

    지금은 한 가지다. 남의 차를 얻어 타는 사람은 출발지를 몰라도 된다. 그 사람의 소요시간은
    태우는 지점부터 세기 때문이다 (transport.md pickup_counts_from_board). 그런데도 물으면
    사용자는 "그건 왜 묻지" 싶은 질문에 답해야 한다.
    """
    needless: set[str] = set()
    for index, person in enumerate(slots.participants):
        if person.pickup_at and not person.origin:
            needless.add(f"participants[{index}].origin")
    return [path for path in slots.missing if path not in needless]


def _questions_for(missing: list[str]) -> list[str]:
    """누락된 슬롯 경로를 사람 말 질문으로 바꾼다 (SDD 2절 need_info).

    문구를 코드에 두는 이유: 이건 프롬프트가 아니라 화면 문구다. LLM을 부르지 않는다.
    """
    questions: list[str] = []
    for path in missing:
        if path.endswith(".origin"):
            questions.append("어디서 출발하시나요?")
        elif path.endswith(".transport"):
            questions.append("차로 오시나요, 대중교통으로 오시나요?")
        elif path == "datetime":
            questions.append("몇 시에 시작하나요?")
        elif path == "access.required":
            # 절차가 있는지 자체를 모르면 준비물도 역산 기준도 정할 수 없다 (SDD 5절 7-1단계)
            questions.append("이 장소에 출입 절차가 있나요? (출입증·방문자 등록·출입조치)")
        elif path == "access.applied":
            questions.append("출입조치(또는 방문 신청)는 해 두셨나요?")
        else:
            questions.append(f"{path} 를 알려 주세요.")
    # 같은 질문이 사람 수만큼 반복되지 않게 한 번씩만
    return list(dict.fromkeys(questions))


def _apply_confirmed(pins: list[GeocodedPin], confirmed: list[Any]) -> list[GeocodedPin]:
    """사용자가 핀을 끌어 고친 좌표로 바꾼다. 고친 핀은 확신도 1.0 (SDD 5절 2-1)."""
    fixed = {c.name: c for c in confirmed}
    out: list[GeocodedPin] = []
    for pin in pins:
        hit = fixed.get(pin.name) if pin.kind == "participant" else None
        out.append(
            GeocodedPin(name=pin.name, lng=hit.lng, lat=hit.lat, confidence=1.0, kind=pin.kind) if hit else pin
        )
    return out


async def _log_llm(
    stage: str,
    request_id: str,
    session_id: str,
    started: float,
    status: str,
    error_type: str | None = None,
    routed_to: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """LLM 단계 한 줄. 모델·토큰·비용은 services/llm.py 가 마지막 호출에서 남긴 값을 쓴다.

    라우팅 전후 비용을 비교하려면 어느 모델을 얼마에 불렀는지가 요청 단위로 남아야 한다
    (체크리스트 40번). 로컬 GGUF 는 비용 0 이라 그 차이가 그대로 드러난다.
    """
    from backend.app.services import llm, request_log

    meta = meta if meta is not None else llm.last_meta()
    await request_log.write(
        request_id=request_id,
        session_id=session_id or None,
        stage=stage,
        provider=_provider_of(meta.get("model")),
        model_or_api=meta.get("model"),
        latency_ms=int((time.monotonic() - started) * 1000),
        status=status,
        tokens_in=meta.get("tokens_in"),
        tokens_out=meta.get("tokens_out"),
        cost_usd=meta.get("cost_usd"),
        error_type=error_type,
        retry_no=max(0, int(meta.get("attempts", 1)) - 1),
        routed_to=routed_to,
    )


def _provider_of(model: str | None) -> str:
    """request_logs.provider. 모델 이름의 접두어가 어디로 불렀는지 정한다 (services/llm.py _client 와 같은 기준)."""
    name = str(model or "")
    if name.startswith("local/"):
        return "local"
    if name.startswith("google-ai/"):
        return "google"
    return "openrouter"


def _judge_meta() -> dict[str, Any]:
    """판정 한 줄의 모델·토큰·비용. judge.py 가 judge_ 접두어로 따로 남긴다.

    넘기지 않으면 _log_llm 이 직전 슬롯 추출 값을 그대로 쓴다. 그러면 판정 비용이 빠지고 추출 비용이
    두 번 세져 하루 상한이 틀어진다 (09-23 적재 확인).
    """
    meta = _llm_meta()
    return {
        "model": meta.get("judge_model"),
        "tokens_in": meta.get("judge_tokens_in"),
        "tokens_out": meta.get("judge_tokens_out"),
        "cost_usd": meta.get("judge_cost_usd"),
        "attempts": meta.get("judge_attempts", 1),
    }


def _vision_meta() -> dict[str, Any]:
    """캡처 읽기 한 줄의 모델·토큰·비용. llm.py 는 vision_ 접두어로 따로 남긴다 (슬롯 추출 값과 섞이지 않게).

    request_logs 에 남겨야 하루 상한(DAILY_COST_LIMIT_USD)이 이 비용까지 센다.
    """
    meta = _llm_meta()
    return {
        "model": meta.get("vision_model"),
        "tokens_in": meta.get("vision_tokens_in"),
        "tokens_out": meta.get("vision_tokens_out"),
        "cost_usd": meta.get("vision_cost_usd"),
        "attempts": meta.get("vision_attempts", 1),
    }


def _pin_of(pins: list[GeocodedPin], name: str, kind: str) -> GeocodedPin | None:
    return next((p for p in pins if p.kind == kind and p.name == name), None)


def _route_plans(slots: Slots, pins: list[GeocodedPin], candidates: list[Any]) -> list[dict[str, Any]]:
    """참석자 × 후보로 경로 요청 목록을 만든다 (SDD 5절 4단계).

    태워지는 사람은 탑승 지점부터 계산하고(transport.md pickup_counts_from_board),
    태워 주는 사람 경로에는 그 지점을 경유지로 넣는다.
    """
    riders = {p.pickup: p for p in slots.participants if p.pickup and p.pickup_at}
    plans: list[dict[str, Any]] = []

    for index, cand in enumerate(candidates):
        dest = (cand["lng"], cand["lat"])
        for person in slots.participants:
            origin_pin = _pin_of(pins, person.name, "participant")
            waypoint = None

            if person.pickup and person.pickup_at:  # 태워지는 사람
                board = _pin_of(pins, person.pickup_at, "pickup")
                if board is None:
                    continue
                origin: tuple[float, float] = (board.lng, board.lat)
            else:
                if origin_pin is None:
                    continue
                origin = (origin_pin.lng, origin_pin.lat)
                rider = riders.get(person.name)  # 이 사람이 누군가를 태우는가
                if rider and rider.pickup_at:
                    board = _pin_of(pins, rider.pickup_at, "pickup")
                    if board is not None:
                        waypoint = (board.lng, board.lat)

            plans.append(
                {
                    "key": (index, person.name),
                    "transport": person.transport or "car",
                    "origin": origin,
                    "dest": dest,
                    "waypoint": waypoint,
                }
            )
    return plans


def _llm_meta() -> dict[str, Any]:
    """마지막 슬롯 추출에 쓴 모델·프롬프트 버전. 결과에 남겨 무엇으로 돌았는지 보이게 한다."""
    try:
        from backend.app.services import llm

        return llm.last_meta()
    except Exception:  # noqa: BLE001  기록용이라 실패해도 계산을 막지 않는다
        return {}


def _judge_candidates(raw_candidates: list[dict[str, Any]], slots: Slots) -> list[dict[str, Any]]:
    """판정 프롬프트에 넣을 후보 목록. access_ok 는 코드가 정한 값을 그대로 알려 준다."""
    applied = slots.access.applied if slots.access else None
    return [
        {**cand, "access_ok": domain_rules.access_ok(cand["kind"], applied)} for cand in raw_candidates
    ]


def _judge_rows(routes: list[dict[str, Any]], slots: Slots) -> list[dict[str, Any]]:
    """판정 프롬프트에 넣을 참석자별 소요. 실패한 조회는 빼고 준다."""
    transport_of = {p.name: (p.transport or "car") for p in slots.participants}
    rows: list[dict[str, Any]] = []
    for route in routes:
        if route.get("error"):
            continue
        index, name = route["key"]
        rows.append(
            {
                "candidate_idx": index,
                "name": name,
                "transport": transport_of.get(name, "car"),
                "raw_duration_min": round(route["duration_sec"] / 60),
                "transfer_count": route.get("transfer_count"),
            }
        )
    return rows


def _build_result(
    slots: Slots,
    raw_candidates: list[Any],
    routes: list[dict[str, Any]],
    meet_at: str,
    rankings: list[dict[str, Any]] | None = None,
    routed_to: str = "small",
) -> Result:
    """5·6·7단계를 합쳐 Result 를 만든다.

    순위는 두 갈래다 (SDD 5절 6단계).
      rankings 가 있으면  대형 모델이 낸 rank·reason·rejected_reason·switched_from 을 그대로 쓴다
      없으면              규칙 점수 순서(domain/rules.candidate_score)와 규칙 문구로 채운다
    숫자와 access_ok 는 어느 쪽이든 코드가 넣는다.
    """
    preset = slots.preset
    access_required = bool(slots.access and slots.access.required)
    applied = slots.access.applied if slots.access else None
    lead = domain_rules.lead_min(preset, access_required)
    buffer = domain_rules.buffer_min(preset)
    by_key = {r["key"]: r for r in routes if not r.get("error")}

    judged = {row["candidate_idx"]: row for row in (rankings or [])}

    # 도착이 어긋나면 절차를 포기하고 밖에서 만난다 (access.md switch_if_delay_min)
    switched = domain_rules.switch_outside(slots.constraints)
    if switched:
        access_required = False  # 절차 시작점 우선을 끄고 랜드마크를 앞세운다
    if judged:
        scored = sorted(enumerate(raw_candidates), key=lambda pair: judged[pair[0]]["rank"])
    else:
        scored = sorted(
            enumerate(raw_candidates),
            key=lambda pair: domain_rules.candidate_score(pair[1]["kind"], access_required),
            reverse=True,
        )
    # 전환했다면 원래 1순위였을 자리를 switched_from 에 남긴다. 화면이 "어디서 옮겼는지" 보여 준다
    original_top = None
    if switched:
        original = sorted(
            raw_candidates,
            key=lambda c: domain_rules.candidate_score(c["kind"], True),
            reverse=True,
        )
        original_top = original[0]["name"] if original else None

    candidates: list[Candidate] = []
    rows: list[ParticipantResult] = []

    for rank, (index, cand) in enumerate(scored, start=1):
        ok = domain_rules.access_ok(cand["kind"], applied)
        verdict = judged.get(index)
        if verdict:
            reason = verdict["reason"]
            rejected = verdict["rejected_reason"] or _rejected_for(cand["kind"], ok, rank, access_required)
            switched_from = verdict["switched_from"]
        else:
            reason = _reason_for(cand["kind"], access_required, ok, switched and rank == 1)
            rejected = _rejected_for(cand["kind"], ok, rank, access_required)
            switched_from = (
                original_top if (switched and rank == 1 and cand["name"] != original_top) else None
            )
        candidates.append(
            Candidate(
                name=cand["name"],
                kind=cand["kind"],
                address=cand["address"] or "주소 미상",
                lng=cand["lng"],
                lat=cand["lat"],
                rank=rank,
                access_ok=ok,
                switched_from=switched_from,
                reason=reason,
                rejected_reason=rejected,
            )
        )

        for person in slots.participants:
            route = by_key.get((index, person.name))
            if route is None:
                continue
            transport = person.transport or "car"
            raw_min = round(route["duration_sec"] / 60)
            extra = domain_rules.traffic_extra_min(raw_min, transport, route.get("transfer_count"))
            total = raw_min + extra + buffer
            calc = domain_rules.calc_departure(meet_at, route["duration_sec"], extra + buffer, lead)
            rows.append(
                ParticipantResult(
                    name=person.name,
                    candidate_rank=rank,
                    transport=transport,
                    duration_min=total,
                    raw_duration_min=raw_min,
                    buffer_min=extra + buffer,
                    departure_time=calc["depart_at"],
                    arrive_by=calc["arrive_by_adjusted"],
                    transfer_count=route.get("transfer_count"),
                    first_train=None,
                    last_train=None,
                    polyline=[(float(x), float(y)) for x, y in route["polyline"]],
                    via_rendezvous=False,
                    via_pickup=bool(person.pickup and person.pickup_at),
                )
            )

    return Result(
        candidates=candidates,
        provisional=domain_rules.is_provisional(slots.schedule_confirmed),
        per_participant=rows,
        rendezvous_departure=None,
        confidence=0.8,
        model_small=_llm_meta().get("model", "unknown"),
        model_large=(rankings[0].get("model") if rankings else None),
        prompt_version=_llm_meta().get("prompt_version", "converge/slot-extract"),
        routed_to="large" if rankings else "small",
    )


async def _attach_trains(
    result: Result,
    raw_candidates: list[Any],
    routes: list[dict[str, Any]],
    meet_date: Any,
    first_last: Callable[..., Awaitable[dict[str, str]]] | None,
) -> dict[str, Any]:
    """야간 대중교통 행마다 첫 지하철 탑승역의 첫차·막차를 붙인다 (SDD 5절 7단계, schedule.md 야간).

    출발이나 도착 기한이 야간(night_start~night_end)에 걸린 대중교통 행만 본다. 낮에는 부르지 않는다.
    탑승역이 여럿이면(환승) 끊긴 곳이 하나라도 있으면 그 역 값을 쓴다. 없으면 첫 탑승역 값을 쓴다.
    같은 역·호선·요일은 한 번만 조회한다. 참석자 × 후보만큼 부르면 공공 API 한도를 금방 쓴다.
    조회가 실패하면 시각은 비우고 "확인하지 못했다"고 적는다. 모른다고 말하는 편이 조용히 빠지는 것보다 낫다.
    """
    if first_last is None:
        return {"skipped": "조회 함수 없음"}
    day = domain_rules.day_type(meet_date)
    index_of = {cand["name"]: i for i, cand in enumerate(raw_candidates)}
    rank_to_index = {c.rank: index_of.get(c.name) for c in result.candidates}
    by_key = {r["key"]: r for r in routes if not r.get("error")}
    looked: dict[tuple[str, str, str], dict[str, str] | None] = {}
    counts = {"야간행": 0, "조회": 0, "끊김": 0, "실패": 0}

    for row in result.per_participant:
        if row.transport == "car":
            continue
        if not (domain_rules.is_night(row.departure_time) or domain_rules.is_night(row.arrive_by)):
            continue
        route = by_key.get((rank_to_index.get(row.candidate_rank), row.name))
        boardings = domain_rules.subway_boardings((route or {}).get("legs"), row.departure_time)
        if not boardings:
            continue
        counts["야간행"] += 1

        chosen: tuple[dict[str, Any], dict[str, str]] | None = None
        for board in boardings:
            key = (board["city"], board["station"], board["line"])
            if key not in looked:
                counts["조회"] += 1
                try:
                    looked[key] = await first_last(board["city"], board["station"], board["line"], day)
                except Exception:  # noqa: BLE001  공공 API 장애·역 이름 불일치
                    looked[key] = None
            times = looked[key]
            if times is None:
                continue
            if domain_rules.train_missed(board["board_min"], times["first"], times["last"]):
                chosen = (board, times)
                break
            chosen = chosen or (board, times)

        if chosen is None:
            counts["실패"] += 1
            row.train_note = "야간 지하철 첫차·막차를 확인하지 못했습니다. 직접 확인해 주세요"
            continue
        board, times = chosen
        row.first_train = domain_rules.clock(times["first"])
        row.last_train = domain_rules.clock(times["last"])
        if domain_rules.train_missed(board["board_min"], times["first"], times["last"]):
            counts["끊김"] += 1
            station = board["station"].removesuffix("역")  # TMAP 은 "사상" 과 "부산역" 을 섞어 준다
            row.train_note = (
                f"{station}역 막차({row.last_train})가 끊긴 뒤에 타야 합니다. "
                f"첫차는 {row.first_train}입니다. 차나 택시를 알아 두세요"
            )
    return counts


def _rejected_for(kind: str, ok: bool, rank: int, access_required: bool) -> str | None:
    """왜 이 후보가 1순위가 아닌가. 1순위면 None (SDD 4절 Candidate.rejected_reason).

    지도 앱은 장소만 찍어 주고 탈락한 자리를 말하지 않는다. "저기는 왜 안 되는데"가 바로 나오므로
    규칙의 근거를 한 줄로 남긴다. 화면에 그대로 나가므로 규칙 키는 주석에만 둔다 (SDD 4절, 09-22).

    대형 모델이 이유를 냈으면 그쪽을 쓰고, 비었을 때만 이 문구가 들어간다.
    """
    if not ok:
        return "출입 절차가 끝나지 않아 지금은 쓸 수 없는 자리입니다"
    if rank == 1:
        return None
    if access_required and kind not in ("gate", "lobby", "hq"):
        # access.md rendezvous_is_procedure_start
        return "출입 절차가 시작되는 자리가 아니라, 여기서 모여도 결국 절차 앞에서 다시 기다립니다"
    if not access_required and kind in ("gate", "lobby"):
        # access.md no_procedure_all_transit_no_rendezvous
        return "출입 절차가 없어 건물 앞에 미리 모일 이유가 없습니다"
    return "1순위보다 이동이 멀거나 합류 이점이 작습니다"


def _reason_for(kind: str, access_required: bool, ok: bool, switched: bool = False) -> str:
    """순위 이유 한 줄. 규칙의 근거를 사람 말로 쓰고 규칙 키는 주석에만 둔다 (SDD 4절 Candidate.reason).

    대형 모델이 붙기 전까지는 규칙 문구를 그대로 쓴다 (SDD 5절 6단계 "실패면 규칙 문구 그대로").
    """
    if not ok:
        return "출입 절차가 끝나지 않아 지금은 쓸 수 없는 자리입니다"
    if switched:
        # access.md switch_if_delay_min
        return "도착 시각이 많이 어긋나 안에서 기다리지 않고 밖에서 먼저 만납니다"
    if access_required and kind in ("gate", "lobby", "hq"):
        # access.md rendezvous_is_procedure_start
        return "출입 절차가 여기서 시작되니 여기서 모이면 기다림이 가장 적습니다"
    if kind == "landmark":
        # access.md outside_landmark_kinds
        return "처음 가는 사람도 찾기 쉬운 자리입니다"
    return "목적지에서 가장 가까운 자리입니다"


# ─────────────────────────────────────────────────────────────────────────────
# 세션 (SDD 5절 재질문, 8단계 store.save)
# ─────────────────────────────────────────────────────────────────────────────


async def _load_previous(deps: Deps, session_id: str, user_id: str) -> Slots | None:
    """재질문이면 이전 세션을 읽는다. 없으면 None.

    먼저 잠금과 주인을 본다. 남의 세션이면 403, 약속이 지난 세션이면 409 다. 둘 다 LLM 을 부르기 전에
    막는다 (SDD 5절 재질문, 비용 방어).
    """
    if deps.load_session is None:
        return None
    row = await deps.load_session(session_id)
    if row is None:
        return None
    if row.get("user_id") and row["user_id"] != user_id:
        raise NotYourSession(session_id)
    if row.get("locked"):
        raise SessionLocked(session_id)
    from backend.app.services import session_store

    return session_store.slots_from_session(row)


async def _persist_quietly(
    deps: Deps,
    tr: Any,
    *,
    session_id: str,
    is_new: bool,
    user_id: str,
    slots: Slots,
    pins: list[GeocodedPin],
    result: Result | None = None,
    status: str = "computed",
) -> str:
    """저장을 시도하고 실패는 삼킨다. 저장이 안 돼도 화면은 결과를 보여 준다.

    돌려주는 값은 최종 session_id 다. 새 세션이면 DB 가 만든 id 로 바뀐다.
    """
    with tr.span("store") as span:
        try:
            saved = await _persist(
                deps,
                session_id=session_id,
                is_new=is_new,
                user_id=user_id,
                slots=slots,
                result=result,
                trace_id=tr.id,
                pins=pins,
                status=status,
            )
            span.output = {"session_id": saved, "status": status}
            return saved
        except Exception as e:  # noqa: BLE001
            span.error = str(e)
            return session_id


async def _persist(
    deps: Deps,
    *,
    session_id: str,
    is_new: bool,
    user_id: str,
    slots: Slots,
    result: Result | None,
    trace_id: str,
    pins: list[GeocodedPin],
    status: str = "computed",
) -> str:
    """세션(과 결과가 있으면 결과)을 저장하고 최종 session_id 를 돌려준다 (SDD 5절 8단계).

    결과가 없어도 저장한다. 되묻기·핀 확인 단계에서도 링크가 있어야 참석자들이 그 주소에 모여
    이어서 답할 수 있기 때문이다 (화면 구조: 메인은 문장만 받고, 나머지는 /s/{id} 에서 한다).

    DB 가 없으면 저장만 건너뛰고 화면은 그대로 간다. 저장 실패는 Langfuse span 에 남는다.
    """
    if deps.save is None:
        return session_id
    dest = next((p for p in pins if p.kind == "destination"), None)
    return await deps.save(
        session_id=None if is_new else session_id,
        new_id=session_id if is_new else None,
        user_id=user_id,
        slots=slots,
        participants=_participants_for_store(slots, pins),
        result=result,
        trace_id=trace_id,
        status=status,
        destination=(dest.lng, dest.lat) if dest else None,
        meet_at=_meet_at(slots),
    )


def _meet_at(slots: Slots) -> datetime | None:
    """저장할 약속 시각 (SDD 5절 8단계). 날짜를 못 읽었거나 등록 범위 밖이면 None 이고 임시 세션으로 남는다."""
    today = domain_rules.today_local(datetime.now(timezone.utc))
    meet_date = domain_rules.parse_meet_date(slots.datetime, today)
    if meet_date is None or domain_rules.meet_window_problem(meet_date, today):
        return None
    return domain_rules.meet_at_local(meet_date, domain_rules.parse_meet_time(slots.datetime))


def _participants_for_store(slots: Slots, pins: list[GeocodedPin]) -> list[dict[str, Any]]:
    """저장용 참석자 평문 구조 (테이블정의서 1절 participants_enc).

    좌표는 슬롯이 아니라 지오코딩 결과에 있으므로 여기서 이름으로 붙여 넣는다.
    """
    coords = {p.name: p for p in pins if p.kind == "participant"}
    out: list[dict[str, Any]] = []
    for person in slots.participants:
        pin = coords.get(person.name)
        out.append(
            {
                "name": person.name,
                "origin_text": person.origin,
                "lng": pin.lng if pin else None,
                "lat": pin.lat if pin else None,
                "transport": person.transport,
                "pickup": person.pickup,
                "pickup_at": person.pickup_at,
                "unfamiliar": person.unfamiliar,
                "role": person.role,
                "confirmed": bool(pin and pin.confidence >= 1.0),
                "owner_user_id": person.owner_user_id,
                "origin_set_by": "self" if person.owner_user_id else "organizer",
                "self_edited_at": None,
            }
        )
    return out
