"""소형·대형 선택이 SDD 5절 조건 그대로인지. 계산만이라 키 없이 돈다 (TEST_GUIDE)."""
from __future__ import annotations

from backend.app.domain.router import route
from backend.app.schemas.slots import Access, Rendezvous, Slots


def slots(**over) -> Slots:
    base = dict(
        preset="visit",
        destination="여의도 사무실",
        participants=[
            dict(name="한동료", origin="강남역", transport="transit", role="colleague"),
            dict(name="서현장", origin="수원시청", transport="car", role="site"),
        ],
    )
    base.update(over)
    return Slots(**base)


def test_참석자_둘_이하_단순건은_소형으로_끝낸다():
    assert route(slots()) == "small"


def test_참석자가_셋이면_대형():
    three = slots().participants + [
        Slots(**dict(preset="visit", participants=[dict(name="조업체", origin="부평역", transport="transit", role="vendor")])).participants[0]
    ]
    assert route(slots(participants=[p.model_dump() for p in three])) == "large"


def test_목적지가_없으면_대형():
    assert route(slots(destination=None)) == "large"


def test_제약이_하나라도_있으면_대형():
    assert route(slots(constraints=["arrival_delayed"])) == "large"


def test_집결지가_있으면_대형():
    assert route(slots(rendezvous=Rendezvous(name="문정동 본사", transport_after="car").model_dump())) == "large"


def test_출입조치를_아직_신청하지_않았으면_대형():
    assert route(slots(access=Access(required=True, applied=None, lead_min=15).model_dump())) == "large"
    assert route(slots(access=Access(required=True, applied=False, lead_min=15).model_dump())) == "large"


def test_출입조치를_이미_신청했으면_소형():
    assert route(slots(access=Access(required=True, applied=True, lead_min=15).model_dump())) == "small"


def test_출입조치가_없으면_소형():
    """SDD 5절 small 조건 "출입조치가 없거나 이미 신청됨". 없음(required=false)은 신청할 것이 없다 (09-23 수정).

    applied 만 보면 절차가 없는 약속(applied=None)까지 전부 대형으로 갔다.
    """
    assert route(slots(access=Access(required=False, applied=None, lead_min=None).model_dump())) == "small"


def test_하루_상한에_닿으면_막지_않고_무료_모델로_돈다(monkeypatch):
    """09-28 결정: 429 로 막던 것을 gemini-3.5-flash-lite 로 계속 돌린다."""
    import asyncio

    from backend.app.routers import agent as agent_router
    from backend.app.schemas.request import AgentRequest
    from backend.app.services import llm

    seen = {}

    async def over():
        return True

    async def fake_run(req, user_id):
        seen["model"] = llm.effective_model(llm.PRIMARY_MODEL)
        return "ok"

    monkeypatch.setattr(agent_router, "_over_daily_limit", over)
    monkeypatch.setattr(agent_router.pipeline, "run", fake_run)
    llm.reset_fallback()
    assert asyncio.run(agent_router.agent(AgentRequest(text="점검"), user_id="u1")) == "ok"
    assert seen["model"] == llm.FALLBACK_MODEL
    assert llm.effective_model(llm.PRIMARY_MODEL) == llm.PRIMARY_MODEL  # 요청이 끝나면 되돌아온다
