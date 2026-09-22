"""파이프라인 단계 순서와 갈림길 (SDD 5절 표).

바깥 호출은 전부 가짜 함수로 바꾼다. 키도, 네트워크도 필요 없다 (TEST_GUIDE).
여기서 보는 것은 "어떤 상황에서 어느 stage 로 빠지는가" 하나다.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from backend.app.schemas.request import AgentRequest, ParticipantInput
from backend.app.schemas.result import GeocodedPin
from backend.app.schemas.slots import Slots
from backend.app.services import pipeline


def slots(**over) -> Slots:
    base = dict(
        preset="visit",
        destination="창원 사무소",
        participants=[dict(name="김현장", origin="창원시청", transport="car", role="site")],
        # access 가 없으면 1-2 단계가 "출입 절차가 있나요"를 되묻는다. 계산까지 가는 시나리오라 채워 둔다
        access=dict(required=True, applied=True),
    )
    base.update(over)
    return Slots(**base)


def pins(confidence: float = 0.95) -> list[GeocodedPin]:
    return [
        GeocodedPin(name="김현장", lng=128.68, lat=35.22, confidence=confidence, kind="participant"),
        GeocodedPin(name="창원 사무소", lng=128.668, lat=35.143, confidence=0.9, kind="destination"),
    ]


def deps(slots_out: Slots, pins_out=None, **over) -> pipeline.Deps:
    async def extract_slots(*_):
        return slots_out

    async def geocode_all(*_):
        return pins_out if pins_out is not None else pins()

    base = dict(extract_slots=extract_slots, geocode_all=geocode_all)
    base.update(over)
    return pipeline.Deps(**base)


def run(req: AgentRequest, d: pipeline.Deps, user_id: str = "u1"):
    return asyncio.run(pipeline.run(req, user_id, d))


def test_범위_밖이면_out_of_scope_로_끝난다():
    out = run(AgentRequest(text="지금 막히는지 알려줘"), deps(Slots(out_of_scope=True)))
    assert out.stage == "out_of_scope"
    assert out.result is None
    assert out.trace_id  # Langfuse 가 꺼져 있어도 trace_id 는 있다


def test_누락이_있으면_need_info_로_되묻는다():
    s = slots(
        participants=[dict(name="김현장", origin="창원시청", transport=None, role="site")],
        missing=["participants[0].transport", "datetime"],
        datetime=None,
    )
    out = run(AgentRequest(text="목요일 점검"), deps(s))
    assert out.stage == "need_info"
    assert len(out.questions) == 2


def test_같은_종류의_누락은_질문을_한_번만_한다():
    s = slots(
        participants=[
            dict(name="김현장", origin="창원시청", transport=None, role="site"),
            dict(name="박업체", origin="부산 사상", transport=None, role="vendor"),
        ],
        missing=["participants[0].transport", "participants[1].transport"],
    )
    out = run(AgentRequest(text="점검"), deps(s))
    assert out.questions == ["차로 오시나요, 대중교통으로 오시나요?"]


def test_확신도가_낮으면_need_confirm_으로_멈추고_핀을_보낸다():
    out = run(AgentRequest(text="점검"), deps(slots(), pins(confidence=0.5)))
    assert out.stage == "need_confirm"
    assert out.geocoded is not None and len(out.geocoded) == 2


def test_확인한_좌표가_오면_그_좌표로_바꾸고_확신도를_올린다():
    req = AgentRequest(
        text="점검", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)]
    )
    out = run(req, deps(slots(), pins(confidence=0.5)))
    assert out.stage != "need_confirm"
    pin = next(p for p in out.geocoded if p.name == "김현장")
    assert (pin.lng, pin.lat, pin.confidence) == (128.7, 35.25, 1.0)


def test_남의_핀도_고칠_수_있다():
    """09-18 결정: 소유권은 표시용이고 수정은 막지 않는다 (SDD 7절)."""
    s = slots(
        participants=[dict(name="김현장", origin="창원시청", transport="car", role="site", owner_user_id="other")]
    )
    req = AgentRequest(text="점검", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)])
    out = run(req, deps(s, pins(confidence=0.5)))
    pin = next(p for p in out.geocoded if p.name == "김현장")
    assert (pin.lng, pin.lat) == (128.7, 35.25)


def test_내_핀은_고칠_수_있다():
    s = slots(
        participants=[dict(name="김현장", origin="창원시청", transport="car", role="site", owner_user_id="u1")]
    )
    req = AgentRequest(text="점검", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)])
    assert run(req, deps(s, pins(confidence=0.5)), user_id="u1").stage != "need_confirm"


def test_슬롯_추출이_실패하면_failed():
    async def boom(*_):
        raise ValueError("스키마 위반")

    out = run(AgentRequest(text="점검"), pipeline.Deps(extract_slots=boom))
    assert out.stage == "failed"


def test_캡처를_읽지_못하면_문장으로_다시_받는다():
    async def boom(*_):
        raise RuntimeError("비전 모델 실패")

    out = run(AgentRequest(image_base64="abc"), pipeline.Deps(extract_text=boom))
    assert out.stage == "need_info"
    assert out.questions


def test_지오코딩이_실패하면_failed():
    async def boom(*_):
        raise RuntimeError("카카오 응답 없음")

    out = run(AgentRequest(text="점검"), deps(slots(), geocode_all=boom))
    assert out.stage == "failed"


def test_아직_구현하지_않은_단계는_조용히_넘어가지_않는다():
    # 3~8단계가 비어 있는 동안에는 failed 로 끝난다. 나중에 채우면 이 테스트를 done 으로 바꾼다
    out = run(AgentRequest(text="점검"), deps(slots()))
    assert out.stage == "failed"
    assert out.geocoded is not None


def test_세션_id_를_첫_요청에서_만든다():
    out = run(AgentRequest(text="점검"), deps(slots()))
    assert out.session_id and len(out.session_id) >= 16


def test_세션_id_가_오면_그대로_쓴다():
    out = run(AgentRequest(session_id="keep-me", text="점검"), deps(slots()))
    assert out.session_id == "keep-me"


def _done_deps(**over) -> pipeline.Deps:
    """done 까지 가는 가짜 단계들. 외부 호출 없이 3~8단계를 흉내 낸다."""

    async def build_candidates(*_):
        return [
            {"name": "정문", "kind": "gate", "address": "테스트", "lng": 128.67, "lat": 35.14},
            {"name": "창원중앙역", "kind": "landmark", "address": "테스트", "lng": 128.69, "lat": 35.15},
        ]

    async def compute_routes(plans):
        return [
            {
                "key": plan["key"],
                "duration_sec": 1800,
                "polyline": [[128.68, 35.22], [128.67, 35.14]],
                "transfer_count": None,
            }
            for plan in plans
        ]

    base = dict(build_candidates=build_candidates, compute_routes=compute_routes)
    base.update(over)
    return deps(slots(datetime="목요일 08:00"), **base)


def test_계산이_끝나면_저장하고_세션_id_를_돌려준다():
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "db-session-1"

    out = run(AgentRequest(text="점검"), _done_deps(save=save))
    assert out.stage == "done"
    assert out.session_id == "db-session-1"  # DB 가 만든 id 를 쓴다
    assert saved["session_id"] is None  # 새 세션이라 None 으로 넘긴다
    assert saved["participants"][0]["origin_text"] == "창원시청"
    assert saved["participants"][0]["lng"] == 128.68


def test_저장에_실패해도_결과는_보여_준다():
    async def boom(**_):
        raise RuntimeError("DB 없음")

    out = run(AgentRequest(text="점검"), _done_deps(save=boom))
    assert out.stage == "done"
    assert out.result is not None


def test_남의_세션으로_재질문하면_막는다():
    async def load_session(_):
        return {"user_id": "other", "locked": False, "participants": []}

    with pytest.raises(pipeline.NotYourSession):
        run(AgentRequest(session_id="s1", text="점검"), _done_deps(load_session=load_session))


def test_잠긴_세션이면_막는다():
    async def load_session(_):
        return {"user_id": "u1", "locked": True, "participants": []}

    with pytest.raises(pipeline.SessionLocked):
        run(AgentRequest(session_id="s1", text="점검"), _done_deps(load_session=load_session), user_id="u1")


def test_재질문이면_이전_슬롯을_추출에_넘긴다():
    seen = {}

    async def load_session(_):
        return {
            "user_id": "u1",
            "locked": False,
            "preset": "visit",
            "purpose": "레이더 정기점검",
            "destination_name": "창원 사무소",
            "participants": [{"name": "김현장", "origin": "창원시청", "transport": "car", "role": "site"}],
            "constraints": [],
        }

    async def extract_slots(text, previous, preset):
        seen["previous"] = previous
        return slots(datetime="목요일 08:00")

    d = _done_deps(load_session=load_session, extract_slots=extract_slots)
    run(AgentRequest(session_id="s1", text="출입조치 했어요"), d, user_id="u1")
    assert seen["previous"] is not None
    assert seen["previous"].destination == "창원 사무소"


def test_되묻기_단계에서도_세션을_만든다():
    """메인에서 문장만 받고 /s/{id} 로 보내려면 링크가 먼저 있어야 한다 (화면 구조, 09-20)."""
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "draft-session-1"

    s = slots(
        participants=[dict(name="김현장", origin="창원시청", transport=None, role="site")],
        missing=["participants[0].transport"],
    )
    out = run(AgentRequest(text="점검"), deps(s, save=save))
    assert out.stage == "need_info"
    assert out.session_id == "draft-session-1"
    assert saved["status"] == "draft"
    assert saved["result"] is None  # 아직 계산 전이라 결과는 없다


def test_핀_확인_단계에서도_세션을_만든다():
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "draft-session-2"

    out = run(AgentRequest(text="점검"), deps(slots(), pins(confidence=0.5), save=save))
    assert out.stage == "need_confirm"
    assert out.session_id == "draft-session-2"
    assert saved["status"] == "draft"
    assert saved["participants"][0]["lng"] == 128.68  # 찾아 둔 좌표는 함께 저장한다


def test_계산이_끝나면_준비물과_계획서가_채워진다():
    """7-1단계. 규칙 파일에서 꺼낸 준비물과 코드가 조립한 계획서 (SDD 5절 7-1)."""
    out = run(AgentRequest(text="점검"), _done_deps())
    assert out.stage == "done" and out.result is not None
    assert out.result.checklist is not None
    assert out.result.checklist.before and out.result.checklist.onsite
    assert "출발 시각" in out.result.summary_text
    assert "미리 해둘 것" in out.result.summary_text


def test_절차를_모르면_출입_절차를_되묻는다():
    """access 가 통째로 없으면 슬롯 스키마를 건드리지 않고 코드가 되묻는다 (SDD 5절 1-2)."""
    out = run(AgentRequest(text="점검"), deps(slots(access=None)))
    assert out.stage == "need_info"
    assert any("출입 절차가 있나요" in q for q in out.questions)


def test_탈락한_후보에는_이유가_붙는다():
    """2순위 이하는 rejected_reason 이 비어 있으면 안 된다 (SDD 4절)."""
    out = run(AgentRequest(text="점검"), _done_deps())
    assert out.result is not None
    뒤 = [c for c in out.result.candidates if c.rank and c.rank > 1]
    assert 뒤 and all(c.rejected_reason for c in 뒤)


def test_태워지는_사람의_출발지는_묻지_않는다():
    """소요시간을 탑승 지점부터 세므로 출발지가 없어도 계산이 된다 (transport.md)."""
    s = slots(
        participants=[
            dict(name="이대리님", origin="노원구", transport="car", role="colleague"),
            dict(name="나", origin=None, transport="car", role="site",
                 pickup="이대리님", pickup_at="광진구 역 앞"),
        ],
        missing=["participants[1].origin"],
    )
    out = run(AgentRequest(text="태우고 감"), _done_deps(extract_slots=None) if False else deps(s))
    assert out.stage != "need_info"


def test_픽업이_아니면_출발지를_묻는다():
    s = slots(
        participants=[
            dict(name="이대리님", origin="노원구", transport="car", role="colleague"),
            dict(name="나", origin=None, transport="car", role="site"),
        ],
        missing=["participants[1].origin"],
    )
    out = run(AgentRequest(text="어디서 출발"), deps(s))
    assert out.stage == "need_info"
    assert any("어디서 출발" in q for q in out.questions)


def test_지난_날짜면_되묻는다():
    out = run(AgentRequest(text="점검"), _done_deps(extract_slots=_fixed(slots(datetime="2020-01-01 08:00"))))
    assert out.stage == "need_info"
    assert "지난" in out.message


def test_등록_범위를_넘는_날짜면_되묻는다():
    far = (date.today() + timedelta(days=90)).isoformat()
    out = run(AgentRequest(text="점검"), _done_deps(extract_slots=_fixed(slots(datetime=f"{far} 08:00"))))
    assert out.stage == "need_info"
    assert "일 안의 약속만" in out.message


def test_날짜를_읽으면_약속_시각을_저장한다():
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "db-session-1"

    out = run(AgentRequest(text="점검"), _done_deps(save=save))  # "목요일 08:00"
    assert out.stage == "done"
    assert saved["meet_at"] is not None
    assert saved["meet_at"].strftime("%A %H:%M") == "Thursday 08:00"


def test_날짜가_없으면_임시_세션으로_저장한다():
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "db-session-1"

    out = run(AgentRequest(text="점검"), _done_deps(save=save, extract_slots=_fixed(slots(datetime="저녁 7시"))))
    assert out.stage == "done"
    assert saved["meet_at"] is None


def _fixed(value: Slots):
    async def extract_slots(*_):
        return value

    return extract_slots


def test_캡처를_읽으면_그_텍스트로_슬롯을_뽑는다():
    seen = {}

    async def extract_text(_):
        return "민수: 목요일 8시"

    async def extract_slots(text, *_):
        seen["text"] = text
        return slots()

    run(AgentRequest(image_base64="abc", text="나는 차로 가"), deps(slots(), extract_text=extract_text, extract_slots=extract_slots))
    # 캡처가 먼저, 함께 적은 문장이 뒤에 붙는다
    assert seen["text"] == "민수: 목요일 8시\n나는 차로 가"


def test_공유_링크로_다시_열어도_준비물과_계획서가_나온다():
    """results 표에는 준비물·계획서 칸이 없다. 다시 열 때 조립하지 않으면 사라진다 (09-22 화면 E2E)."""
    from backend.app.services import session_store

    out = run(AgentRequest(text="점검"), _done_deps(extract_slots=_fixed(slots(datetime="목요일 08:00", constraints=["cook"]))))
    assert out.result.checklist is not None
    stored = out.result.model_dump(exclude={"checklist", "summary_text"})
    row = {
        "preset": "visit",
        "destination_name": "창원 사무소",
        "access": {"required": True, "applied": True},
        "constraints": ["cook"],
        "participants": [{"name": "김현장", "origin_text": "창원시청", "transport": "car", "role": "site"}],
    }
    again = session_store.to_agent_response("s1", row, stored).result
    assert again.checklist == out.result.checklist
    assert again.summary_text


def test_캡처_비용도_요청당_상한에_센다(monkeypatch):
    """이미지는 대형 모델이 읽는다. 슬롯 추출 비용만 보면 상한을 넘겨도 판정 모델을 부른다."""
    from backend.app.services import llm

    async def extract_text(_):
        llm._last_meta.update({"vision_cost_usd": 0.04})
        return "민수: 목요일 8시"

    monkeypatch.setattr(pipeline.cost_guards, "per_request_limit", lambda: 0.03)
    monkeypatch.setattr(pipeline.model_router, "route", lambda _s: "large")
    seen = {}

    def over_limit(spent, cap):
        seen["spent"] = spent
        return True

    monkeypatch.setattr(pipeline.cost_guards, "over_limit", over_limit)
    run(AgentRequest(image_base64="abc"), _done_deps(extract_text=extract_text))
    assert seen["spent"] >= 0.04


def test_추출_실패_오류에_모델_출력을_남기지_않는다(monkeypatch):
    from contextlib import contextmanager

    spans = []

    class FakeSpan:
        def __init__(self):
            self.input = self.output = self.error = None

    class FakeTrace:
        id = "t1"

        @contextmanager
        def span(self, name, **_):
            s = FakeSpan()
            spans.append((name, s))
            yield s

    @contextmanager
    def trace(*_a, **_k):
        yield FakeTrace()

    monkeypatch.setattr(pipeline.langfuse, "trace", trace)

    async def boom(*_):
        raise ValueError("participants.0.name 민수 인천시청 형식 위반")

    run(AgentRequest(text="점검"), pipeline.Deps(extract_slots=boom))
    error = dict(spans)["extract"].error
    assert error == "ValueError"
