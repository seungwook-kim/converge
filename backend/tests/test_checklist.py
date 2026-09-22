"""준비물 목록과 집결 계획서. (SDD 5절 7-1단계)

값은 skills/converge/rules/checklist.md 에서 온다. 여기에 항목 문자열을 적어 두고 비교하면
규칙 파일을 고칠 때마다 테스트가 깨진다. 그래서 "규칙 파일에서 꺼낸 것과 같은가"로 본다.
"""
from __future__ import annotations

from backend.app.domain.checklist import build_checklist, build_summary, pick_carriers
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


def names(block: dict, key: str) -> set[str]:
    """규칙 파일의 항목에서 이름만 뽑는다. 문자열일 수도, {item, assign} 일 수도 있다."""
    out = set()
    for entry in block.get(key) or []:
        out.add(entry["item"] if isinstance(entry, dict) else entry)
    return out


def stripped(items: list[str]) -> set[str]:
    """붙은 담당자 꼬리표를 떼고 항목 이름만 남긴다."""
    return {item.split(" (")[0] for item in items}


# ─────────────────────────────────────────────── 하려는 일에 딸린 준비물 (09-21 확장)


def test_절차가_없는_친구_모임도_고기를_챙긴다():
    """출입 절차가 없다고 준비물이 없는 게 아니다. 고기는 절차와 무관하다."""
    out = build_checklist("meeting", False, None, ["cook"], has_car=False)
    assert out is not None
    assert stripped(out.before) == names(RULES["cook"], "before")
    assert set(out.onsite) == names(RULES["cook"], "onsite")


def test_절차를_몰라도_하려는_일은_안다():
    """access 가 None 이어도 cook 은 나온다. 모르는 것과 없는 것은 다르다."""
    out = build_checklist("meeting", None, None, ["cook"], has_car=False)
    assert out is not None
    assert stripped(out.before) == names(RULES["cook"], "before")


def test_조건이_겹치면_합치고_중복은_지운다():
    """캠핑에서 고기를 구우면 쓰레기봉투가 두 목록에 다 있다. 한 줄만 남아야 한다."""
    out = build_checklist("meeting", False, None, ["cook", "outdoor"], has_car=False)
    assert out is not None
    assert len(out.onsite) == len(set(out.onsite))
    assert names(RULES["cook"], "onsite") <= set(out.onsite)
    assert names(RULES["outdoor"], "onsite") <= set(out.onsite)


def test_모르는_조건은_무시한다():
    """LLM 이 없는 이름을 만들어 넣어도 목록을 지어내지 않는다."""
    assert build_checklist("meeting", False, None, ["파티게임"], has_car=False) is None


def test_절차_항목이_앞에_온다():
    """늦으면 아예 못 들어가는 쪽이 먼저 보여야 한다."""
    out = build_checklist("visit", True, True, ["cook"], has_car=False)
    assert out is not None
    first = next(iter(names(RULES["visit_access"], "before")))
    assert out.before[0] == first


def test_미완료는_절차_항목에만_붙는다():
    """고기에는 신청이라는 개념이 없다. 미완료를 붙이면 틀린 말이 된다."""
    out = build_checklist("visit", True, False, ["cook"], has_car=False)
    assert out is not None
    prefix = RULES["not_applied_prefix"]
    붙은_것 = {i for i in out.before if i.startswith(prefix)}
    assert stripped({i[len(prefix):] for i in 붙은_것}) == names(RULES["visit_access"], "before")


# ─────────────────────────────────────────────────────────────── 분담


def test_차로_오는_사람에게_무거운_것을_맡긴다():
    out = build_checklist("meeting", False, None, ["cook"], has_car=True,
                          carriers={"car": "민수", "first": "지호"})
    assert out is not None
    맡은_줄 = [i for i in out.before if "민수" in i]
    assert 맡은_줄, out.before
    assert RULES["assign_car"].format(name="민수") in 맡은_줄[0]


def test_맡을_사람이_없으면_이름을_붙이지_않는다():
    """아무도 차로 오지 않는데 누군가를 적으면 그게 더 틀린 말이다."""
    out = build_checklist("meeting", False, None, ["cook"], has_car=False,
                          carriers={"car": None, "first": "지호"})
    assert out is not None
    assert stripped(out.before) == names(RULES["cook"], "before")
    assert all("(" not in item for item in out.before)


def test_담당자는_출발이_이른_사람과_차로_오는_사람이다():
    result = Result(
        candidates=[Candidate(name="한강공원", kind="landmark", address="서울", lng=127.0, lat=37.5,
                              rank=1, access_ok=True, reason="x")],
        provisional=False,
        per_participant=[
            ParticipantResult(name="지호", candidate_rank=1, transport="transit", duration_min=40,
                              raw_duration_min=30, buffer_min=10, departure_time="12:20",
                              arrive_by="13:00"),
            ParticipantResult(name="민수", candidate_rank=1, transport="car", duration_min=30,
                              raw_duration_min=25, buffer_min=5, departure_time="12:30",
                              arrive_by="13:00"),
            ParticipantResult(name="영희", candidate_rank=1, transport="car", duration_min=20,
                              raw_duration_min=15, buffer_min=5, departure_time="12:40",
                              arrive_by="13:00"),
        ],
        confidence=0.9, model_small="x", prompt_version="p@1", routed_to="small",
    )
    slots = Slots(preset="meeting", datetime="토요일 13:00", destination="한강공원",
                  participants=[dict(name="지호", origin="수원", transport="transit", role="site")],
                  access=dict(required=False))
    out = pick_carriers(slots, result)
    assert out["first"] == "지호"      # 가장 이른 출발
    assert out["car"] == "민수"        # 차로 오는 사람 중 가장 이른 출발


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
        destination="마곡 사무실",
        participants=[dict(name="나", origin="송파구", transport="transit", role="site")],
        access=dict(required=True, applied=False),
    )


def test_계획서는_머리줄과_집결과_출발_시각을_담는다():
    text = build_summary(_slots(), _result())
    assert text.splitlines()[0] == "목요일 14:00 마곡 사무실 미팅"
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
