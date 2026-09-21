"""준비물 목록과 집결 계획서. (SDD 5절 7-1단계)

값은 skills/converge/rules/checklist.md 에서 온다. 여기에 항목 문자열을 적어 두고 비교하면
규칙 파일을 고칠 때마다 테스트가 깨진다. 그래서 "규칙 파일에서 꺼낸 것과 같은가"로 본다.
"""
from __future__ import annotations

from backend.app.domain.checklist import build_checklist, build_summary
from backend.app.domain.rules import load_rule
from backend.app.schemas.result import Candidate, Checklist, ParticipantResult, Result
from backend.app.schemas.slots import Slots

RULES = load_rule("checklist")


def test_절차를_모르면_체크리스트를_만들지_않는다():
    assert build_checklist("visit", None, None, [], has_car=False) is None


def test_절차가_없으면_목록도_없다():
    assert build_checklist("visit", False, None, [], has_car=True) is None


def test_방문자_등록과_신분증을_꺼낸다():
    out = build_checklist("visit", True, True, [], has_car=False)
    assert out is not None
    assert out.before == RULES["visit_access"]["before"]
    assert out.onsite == RULES["visit_access"]["onsite"]


def test_차로_가는_사람이_있으면_차량번호_등록이_붙는다():
    없음 = build_checklist("visit", True, True, [], has_car=False)
    있음 = build_checklist("visit", True, True, [], has_car=True)
    assert 있음 is not None and 없음 is not None
    더해진_것 = set(있음.before) - set(없음.before)
    assert 더해진_것 == set(RULES["visit_access"]["before_if_car"])


def test_신청_전이면_사전_항목_앞에_미완료가_붙는다():
    out = build_checklist("visit", True, False, [], has_car=False)
    assert out is not None
    prefix = RULES["not_applied_prefix"]
    assert all(item.startswith(prefix) for item in out.before)
    # 당일 지참은 미완료가 아니다. 당일 챙기면 되는 것이라 경고를 붙이지 않는다
    assert not any(item.startswith(prefix) for item in out.onsite)


def test_장비가_있으면_반출입_신고서가_더해진다():
    out = build_checklist("visit", True, True, ["luggage"], has_car=False)
    assert out is not None
    assert set(RULES["luggage"]["before"]) <= set(out.before)
    assert set(RULES["luggage"]["onsite"]) <= set(out.onsite)


def test_절차가_없어도_장비는_신고_대상이다():
    out = build_checklist("visit", False, None, ["luggage"], has_car=False)
    assert out is not None
    assert out.before == RULES["luggage"]["before"]


def test_중복_항목은_한_번만_나온다():
    out = build_checklist("visit", True, True, ["luggage"], has_car=True)
    assert out is not None
    assert len(out.before) == len(set(out.before))
    assert len(out.onsite) == len(set(out.onsite))


# ─────────────────────────────────────────────────────────────── 집결 계획서


def _result(**over) -> Result:
    base = dict(
        candidates=[
            Candidate(
                name="문정동 본사",
                kind="hq",
                address="서울 송파구",
                lng=127.12,
                lat=37.48,
                rank=1,
                access_ok=True,
                reason="access.md rendezvous_is_procedure_start: 절차가 시작되는 자리입니다",
            )
        ],
        provisional=False,
        per_participant=[
            ParticipantResult(
                name="나",
                candidate_rank=1,
                transport="transit",
                duration_min=40,
                raw_duration_min=35,
                buffer_min=5,
                departure_time="05:50",
                arrive_by="06:30",
            )
        ],
        confidence=0.8,
        model_small="local/kanana",
        prompt_version="converge/slot-extract@1",
        routed_to="small",
    )
    base.update(over)
    return Result(**base)


def _slots() -> Slots:
    return Slots(
        preset="visit",
        datetime="목요일 14:00",
        purpose="미팅",
        destination="마곡 고객사",
        participants=[dict(name="나", origin="송파구", transport="transit", role="site")],
        access=dict(required=True, applied=False),
    )


def test_계획서는_머리줄과_집결과_출발_시각을_담는다():
    text = build_summary(_slots(), _result())
    assert text.splitlines()[0] == "목요일 14:00 마곡 고객사 미팅"
    assert "집결: 문정동 본사 06:30" in text
    assert "나 (송파구, 대중교통) 05:50" in text


def test_계획서에_준비물이_들어간다():
    result = _result(checklist=Checklist(before=["[미완료] 방문자 등록"], onsite=["신분증", "보안서약서"]))
    text = build_summary(_slots(), result)
    assert "미리 해둘 것" in text
    assert "[미완료] 방문자 등록" in text
    assert "신분증, 보안서약서" in text


def test_준비물이_없으면_그_칸이_빠진다():
    text = build_summary(_slots(), _result())
    assert "미리 해둘 것" not in text
    assert "당일 챙길 것" not in text


def test_일정이_미확정이면_계획서에_적는다():
    text = build_summary(_slots(), _result(provisional=True))
    assert "확정이 아닙니다" in text
