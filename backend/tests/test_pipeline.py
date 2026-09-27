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
    # 한 번만 묻되 누구에게 묻는지는 적는다 (09-27)
    assert out.questions == ["김현장·박업체는 차로 오시나요, 대중교통으로 오시나요?"]


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


def test_확인한_좌표에_출발지_이름이_있으면_슬롯의_출발지도_바꾼다():
    """09-27: 좌표만 바뀌고 계획서에는 옛 출발지 이름이 남았다."""
    req = AgentRequest(
        text="점검",
        confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25, origin="창원중앙역")],
    )
    out = run(req, deps(slots(), pins(confidence=0.5)))
    person = next(p for p in out.slots.participants if p.name == "김현장")
    assert person.origin == "창원중앙역"


def test_확인한_좌표에_출발지_이름이_없으면_슬롯은_그대로다():
    s = slots()
    before = next(p for p in s.participants if p.name == "김현장").origin
    req = AgentRequest(text="점검", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)])
    out = run(req, deps(s, pins(confidence=0.5)))
    assert next(p for p in out.slots.participants if p.name == "김현장").origin == before


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


def test_다시_계산해도_누가_핀을_고쳤는지는_남는다():
    """09-27: 다시 계산하면 참석자를 새로 저장하면서 수정 기록(SDD 7절)이 지워졌다."""
    saved = {}

    async def load_session(_):
        return {
            "user_id": "u1",
            "locked": False,
            "participants": [
                {
                    "name": "김현장",
                    "origin_text": "창원시청",
                    "transport": "car",
                    "role": "site",
                    "owner_user_id": "other",
                    "origin_set_by": "other",
                    "last_edited_by": "u1",
                    "self_edited_at": "2026-09-27T09:00:00+00:00",
                }
            ],
        }

    async def save(**kwargs):
        saved.update(kwargs)
        return "s1"

    req = AgentRequest(
        session_id="s1", text="핀 위치 확인", confirmed_participants=[ParticipantInput(name="김현장", lng=128.7, lat=35.25)]
    )
    run(req, _done_deps(load_session=load_session, save=save), user_id="u1")
    person = next(p for p in saved["participants"] if p["name"] == "김현장")
    assert person["last_edited_by"] == "u1"
    assert person["self_edited_at"] == "2026-09-27T09:00:00+00:00"
    assert person["origin_set_by"] == "other"


def test_처음_저장하면_수정_기록은_비어_있다():
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "s1"

    run(AgentRequest(text="점검"), _done_deps(save=save))
    person = saved["participants"][0]
    assert person["self_edited_at"] is None
    assert person.get("last_edited_by") is None
    assert person["origin_set_by"] == "organizer"


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


def test_화면에_나가는_이유에_규칙_키를_쓰지_않는다():
    """판정 모델 없이 규칙 문구로 채울 때도 access.md 같은 파일 이름·영문 키가 화면에 나가면 안 된다."""
    import re

    for access in (dict(required=True, applied=True), dict(required=False)):
        out = run(AgentRequest(text="점검"), _done_deps(extract_slots=_fixed(slots(datetime="목요일 08:00", access=access))))
        for cand in out.result.candidates:
            for text in (cand.reason, cand.rejected_reason or ""):
                assert ".md" not in text, text
                assert not re.search(r"[a-z]+_[a-z_]+", text), text


def _night_deps(first_last, meet="토요일 01:00"):
    """새벽 약속. 참석자 한 명이 지하철을 탄다. 경로에 부산2호선 구간이 있다."""

    async def build_candidates(*_):
        return [{"name": "서면역", "kind": "landmark", "address": "테스트", "lng": 129.059, "lat": 35.157}]

    async def compute_routes(plans):
        return [
            {
                "key": plan["key"],
                "duration_sec": 1800,
                "polyline": [[128.99, 35.16], [129.05, 35.15]],
                "transfer_count": 0,
                "legs": [
                    {"mode": "WALK", "route": None, "from": "출발지", "to": "사상", "sec": 300},
                    {"mode": "SUBWAY", "route": "부산2호선", "from": "사상", "to": "서면", "sec": 1500},
                ],
            }
            for plan in plans
        ]

    night = slots(
        preset="meeting",
        destination="서면역",
        datetime=meet,
        participants=[dict(name="나", origin="사상역", transport="transit", role="site")],
        access=dict(required=False),
    )
    return deps(
        night,
        pins_out=[
            GeocodedPin(name="나", lng=128.99, lat=35.16, confidence=0.95, kind="participant"),
            GeocodedPin(name="서면역", lng=129.059, lat=35.157, confidence=0.9, kind="destination"),
        ],
        build_candidates=build_candidates,
        compute_routes=compute_routes,
        first_last=first_last,
        save=None,
    )


def test_야간_지하철이면_첫차_막차를_붙이고_끊긴_시간이면_알린다():
    asked = []

    async def first_last(city, station, line, day):
        asked.append((city, station, line, day))
        return {"first": "05:20", "last": "23:30"}

    out = run(AgentRequest(text="새벽 모임"), _night_deps(first_last))
    assert out.stage == "done"
    row = out.result.per_participant[0]
    assert (row.first_train, row.last_train) == ("05:20", "23:30")
    assert row.train_note and "막차" in row.train_note
    assert asked == [("busan", "사상", "2", "sat")]
    assert "막차" in out.result.summary_text  # 계획서에도 남는다
    assert "막차" in out.message


def test_막차_전이면_시각만_붙이고_경고는_없다():
    async def first_last(*_):
        return {"first": "05:20", "last": "24:40"}

    out = run(AgentRequest(text="새벽 모임"), _night_deps(first_last))
    row = out.result.per_participant[0]
    assert (row.first_train, row.last_train) == ("05:20", "00:40")
    assert row.train_note is None


def test_낮_약속이면_첫차_막차를_조회하지_않는다():
    async def first_last(*_):
        raise AssertionError("낮에는 부르지 않는다")

    out = run(AgentRequest(text="점심"), _night_deps(first_last, meet="토요일 12:00"))
    assert out.stage == "done"
    assert out.result.per_participant[0].last_train is None


def test_첫차_막차_조회가_실패해도_결과는_나간다():
    async def first_last(*_):
        raise RuntimeError("API down")

    out = run(AgentRequest(text="새벽 모임"), _night_deps(first_last))
    assert out.stage == "done"
    row = out.result.per_participant[0]
    assert row.last_train is None
    assert row.train_note and "확인하지 못" in row.train_note


def test_범위_밖_날짜면_빠진_정보보다_날짜를_먼저_되묻는다():
    """출발지를 다 답하게 한 뒤에 날짜로 거절하면 헛수고다 (09-23 E2E)."""
    far = (date.today() + timedelta(days=60)).isoformat()
    no_origin = slots(
        datetime=f"{far} 12:00",
        participants=[dict(name="김현장", origin=None, transport=None, role="site")],
        missing=["participants[0].origin", "participants[0].transport"],
    )
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return "db-session-1"

    out = run(AgentRequest(text="점심"), _done_deps(extract_slots=_fixed(no_origin), save=save))
    assert out.stage == "need_info"
    assert "일 안의 약속만" in out.message
    assert out.questions == ["언제 모이나요?"]
    assert saved == {}  # 받을 수 없는 약속을 임시 세션으로 남기지 않는다


def test_지난_날짜도_빠진_정보보다_먼저_되묻는다():
    no_origin = slots(
        datetime="2020-01-01 12:00",
        participants=[dict(name="김현장", origin=None, transport=None, role="site")],
        missing=["participants[0].origin", "participants[0].transport"],
    )
    out = run(AgentRequest(text="점심"), _done_deps(extract_slots=_fixed(no_origin)))
    assert out.stage == "need_info"
    assert "지난" in out.message


def test_범위_밖이면_무엇을_하는_도구인지_알려준다():
    """실시간 질문이 아니어도(메뉴 추천 등) 범위 밖으로 온다. 문구가 한 사례에 묶이면 엉뚱한 답이 된다 (09-23 E2E)."""
    out = run(AgentRequest(text="오늘 저녁 뭐 먹을지 추천해줘"), deps(Slots(out_of_scope=True)))
    assert out.stage == "out_of_scope"
    assert "실시간" not in out.message
    assert "모일 자리" in out.message and "출발 시각" in out.message


def test_역_이름이_역으로_끝나도_역을_한_번만_붙인다():
    """TMAP 은 "사상" 과 "부산역" 을 섞어 준다. "부산역역" 이 나오면 안 된다 (09-23 실측)."""

    async def first_last(*_):
        return {"first": "05:20", "last": "23:30"}

    d = _night_deps(first_last)
    original = d.compute_routes

    async def compute_routes(plans):
        out = await original(plans)
        for r in out:
            r["legs"][1]["from"] = "부산역"
        return out

    d.compute_routes = compute_routes
    note = run(AgentRequest(text="새벽 모임"), d).result.per_participant[0].train_note
    assert note.startswith("부산역 막차")


def test_새_세션은_Langfuse_세션과_같은_id_로_저장한다(monkeypatch):
    """DB 가 id 를 새로 만들면 Langfuse 세션과 어긋나 되묻기와 답변이 다른 세션으로 갈라진다 (09-23 적재 확인)."""
    traced = {}
    real_trace = pipeline.langfuse.trace

    def spy(name, **kwargs):
        traced.update(kwargs)
        return real_trace(name, **kwargs)

    monkeypatch.setattr(pipeline.langfuse, "trace", spy)
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return kwargs["new_id"]

    out = run(AgentRequest(text="점검"), _done_deps(save=save))
    assert saved["session_id"] is None  # 새 세션이다
    assert saved["new_id"] == traced["session_id"] == out.session_id
    assert len(out.session_id) == 36  # DB 의 uuid 컬럼에 그대로 들어가는 모양


def test_저장된_적_없는_세션_id_로_답하면_그_id_로_새로_만든다():
    """날짜 되묻기는 세션을 남기지 않는다. 그 id 로 답이 오면 없는 행을 갱신하려다 저장이 사라졌다 (09-23)."""
    saved = {}

    async def save(**kwargs):
        saved.update(kwargs)
        return kwargs["new_id"] or kwargs["session_id"]

    async def load_session(_):
        return None

    sid = "3f0c2a4e-1b2c-4d5e-8f90-123456789abc"
    out = run(AgentRequest(session_id=sid, text="토요일로 할게"), _done_deps(save=save, load_session=load_session))
    assert out.stage == "done"
    assert saved["session_id"] is None and saved["new_id"] == sid
    assert out.session_id == sid


def test_판정_기록에는_판정_호출의_모델과_비용이_남는다(monkeypatch):
    """judge 행이 슬롯 추출의 모델·토큰을 그대로 복사하고 있었다. 하루 비용 합계가 틀어진다 (09-23 적재 확인)."""
    from backend.app.services import llm, request_log

    rows = []

    async def write(**kwargs):
        rows.append(kwargs)

    monkeypatch.setattr(request_log, "write", write)
    monkeypatch.setattr(pipeline.model_router, "route", lambda _slots: "large")
    llm._last_meta.clear()
    llm._last_meta.update({"model": "google-ai/small-x", "tokens_in": 2000, "tokens_out": 300, "cost_usd": 0.001})

    async def rank(*_):
        # judge.rank 가 하는 일을 흉내 낸다: 자기 값을 judge_ 접두어로 남긴다
        llm._last_meta.update(
            {"judge_model": "google-ai/large-y", "judge_tokens_in": 900, "judge_tokens_out": 120,
             "judge_cost_usd": 0.0004, "judge_attempts": 1}
        )
        return [
            {"candidate_idx": 0, "rank": 1, "reason": "가깝다", "rejected_reason": None, "switched_from": None, "model": "google-ai/large-y"},
            {"candidate_idx": 1, "rank": 2, "reason": "멀다", "rejected_reason": "멀다", "switched_from": None, "model": "google-ai/large-y"},
        ]

    async def extract_slots(*_):
        return slots(datetime="목요일 08:00")

    run(AgentRequest(text="점검"), _done_deps(rank=rank, extract_slots=extract_slots))
    judge_row = next(r for r in rows if r["stage"] == "judge")
    assert judge_row["model_or_api"] == "google-ai/large-y"
    assert (judge_row["tokens_in"], judge_row["tokens_out"], judge_row["cost_usd"]) == (900, 120, 0.0004)
    assert judge_row["provider"] == "google"  # google-ai/ 는 구글 직접 호출이다


def test_제공자_이름은_모델_접두어로_정한다():
    assert pipeline._provider_of("google-ai/gemini-3.5-flash-lite") == "google"
    assert pipeline._provider_of("local/kanana") == "local"
    assert pipeline._provider_of("anthropic/claude-sonnet-5") == "openrouter"
    assert pipeline._provider_of(None) == "openrouter"


def _judged_deps(basis, judge_meta=None, required=False):
    """슬롯 추출이 access 를 basis 로 정했다고 흉내 낸다 (llm.settle_access 가 _last_meta 에 남기는 값)."""
    from backend.app.services import llm

    async def extract_slots(*_):
        llm._last_meta.update({"access_basis": basis})
        if judge_meta is not None:
            llm._last_meta["access_judge"] = judge_meta
        else:
            llm._last_meta.pop("access_judge", None)
        return slots(datetime="목요일 08:00", access=dict(required=required, applied=None if not required else True))

    return _done_deps(extract_slots=extract_slots)


def test_추정으로_절차_없음을_정했으면_완료_안내에_알린다():
    out = run(AgentRequest(text="점검"), _judged_deps("judge", {"choice": "none", "p_none": 0.95}))
    assert out.stage == "done"
    assert "출입 절차가 없는 곳으로 보고 계산했습니다" in out.message


def test_규칙으로_정한_절차_없음은_알리지_않는다():
    out = run(AgentRequest(text="점검"), _judged_deps("open_place"))
    assert "출입 절차가 없는 곳으로" not in out.message


def test_판단_모델_호출은_요청_기록에_남는다(monkeypatch):
    from backend.app.services import request_log

    rows = []

    async def write(**kwargs):
        rows.append(kwargs)

    monkeypatch.setattr(request_log, "write", write)
    meta = {"choice": "none", "p_none": 0.95, "confidence": 0.9, "model": "jev-1.13", "input_tokens": 300, "cost_usd": 0.0000126}
    run(AgentRequest(text="점검"), _judged_deps("judge", meta))
    row = next(r for r in rows if r["stage"] == "access_judge")
    assert (row["provider"], row["model_or_api"], row["tokens_in"], row["status"]) == ("typesafe", "jev-1.13", 300, "ok")
    assert row["cost_usd"] == 0.0000126

    rows.clear()
    run(AgentRequest(text="점검"), _judged_deps("judge", {"error": "TimeoutError"}))
    row = next(r for r in rows if r["stage"] == "access_judge")
    assert (row["status"], row["error_type"]) == ("error", "TimeoutError")


def test_목적지를_되묻는_말이_있다():
    assert pipeline._questions_for(["destination"]) == ["어디서 모이나요?"]


def test_질문에_누구에게_묻는지_적는다():
    """09-27 실제 캡처: 무리가 셋인데 "차로 오시나요?"만 물어 누구 얘기인지 몰랐다."""
    from backend.app.schemas.slots import Participant

    people = [
        Participant.model_construct(name="완호 창고지 3명"),
        Participant.model_construct(name="하단 2명"),
        Participant.model_construct(name="나머지 2명"),
    ]
    qs = pipeline._questions_for(
        ["participants[0].transport", "participants[1].pickup", "participants[1].pickup_at", "participants[2].origin"],
        people,
    )
    assert qs == [
        "완호 창고지 3명은 차로 오시나요, 대중교통으로 오시나요?",
        "하단 2명은 누가 어디서 태우나요?",
        "나머지 2명은 어디서 출발하시나요?",
    ]


def test_말하는_사람에게는_이름_없이_묻는다():
    from backend.app.schemas.slots import Participant

    people = [Participant.model_construct(name="나"), Participant.model_construct(name="민수")]
    assert pipeline._questions_for(["participants[0].origin"], people) == ["어디서 출발하시나요?"]
    assert pipeline._questions_for(["participants[1].origin"], people) == ["민수는 어디서 출발하시나요?"]
    both = pipeline._questions_for(["participants[0].origin", "participants[1].origin"], people)
    assert both == ["본인·민수는 어디서 출발하시나요?"]


def test_모르는_경로는_내부_이름을_내보내지_않는다():
    qs = pipeline._questions_for(["participants[0].unknown_field"])
    assert qs and all("participants[" not in q for q in qs)
