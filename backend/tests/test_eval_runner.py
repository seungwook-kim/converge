"""평가 실행기의 채점 로직. (evals/run_eval.py)

돌리는 쪽(파이프라인·모델)은 건드리지 않고 채점만 본다. 키 없이 돈다 (TEST_GUIDE).
채점이 틀리면 개선 전후 비교가 통째로 거짓이 되므로 여기서 잡는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.schemas.result import AgentResponse, Candidate, ParticipantResult, Result
from backend.app.schemas.slots import Slots
from evals.run_eval import (
    check_contract,
    expected_slots,
    expected_stage,
    score_row,
    slot_value,
    summarize,
)


def slots(**over) -> Slots:
    base = dict(
        preset="meeting",
        datetime="토요일 14:00",
        destination="강남역 근처",
        participants=[dict(name="나", origin="수원", transport="car", role="site")],
        access=dict(required=False),
    )
    base.update(over)
    return Slots(**base)


def response(**over) -> AgentResponse:
    base = dict(
        session_id="s1", stage="need_info", slots=slots(),
        questions=["몇 시에 만나나요?"], message="몇 가지가 더 필요합니다", trace_id="t1",
    )
    base.update(over)
    return AgentResponse(**base)


def done_result(**over) -> Result:
    base = dict(
        candidates=[
            Candidate(name="강남역", kind="landmark", address="서울", lng=127.02, lat=37.49,
                      rank=1, access_ok=True, reason="찾기 쉬운 자리입니다"),
        ],
        provisional=False,
        per_participant=[
            ParticipantResult(name="나", candidate_rank=1, transport="car", duration_min=40,
                              raw_duration_min=30, buffer_min=10, departure_time="13:10",
                              arrive_by="14:00"),
        ],
        confidence=0.9, model_small="local/x", prompt_version="p@1", routed_to="small",
    )
    base.update(over)
    return Result(**base)


# ─────────────────────────────────────────────────────────── 기대값 읽기


def test_기대값은_세_가지_모양을_받는다():
    """문항마다 채점 범위가 다르다. 비어 있으면 돌려만 보고 점수를 매기지 않는다."""
    assert expected_stage("done") == "done"
    assert expected_stage({"stage": "need_info"}) == "need_info"
    assert expected_stage("") is None
    assert expected_stage(None) is None
    assert expected_slots({"stage": "done", "slots": {"preset": "visit"}}) == {"preset": "visit"}
    assert expected_slots("done") == {}


def test_점으로_쓴_경로를_따라간다():
    """access.required 처럼 한 단계 안쪽 값도 문항에서 지목할 수 있어야 한다."""
    s = slots()
    assert slot_value(s, "preset") == "meeting"
    assert slot_value(s, "access.required") is False
    assert slot_value(s, "없는칸") is None
    assert slot_value(None, "preset") is None


# ─────────────────────────────────────────────────────────── 계약 검사


def test_정상_응답에는_지적할_것이_없다():
    assert check_contract(response()) == []
    assert check_contract(response(stage="done", result=done_result(), message="끝")) == []


def test_스키마가_막지_못하는_구멍을_잡는다():
    """AgentResponse 의 검증을 우회해 만든다.

    실제로는 스키마가 먼저 막지만, 그 검증이 느슨해지거나 응답을 손으로 조립하는 자리가 생기면
    평가에서 걸려야 한다. 화면이 stage 하나만 보고 갈라지기 때문이다.
    """
    def raw(**over):
        base = dict(session_id="s1", stage="need_info", slots=slots(), result=None,
                    questions=[], message="", trace_id="t1", geocoded=None, edits=None)
        base.update(over)
        return AgentResponse.model_construct(**base)

    problems = " ".join(check_contract(raw()))
    assert "questions" in problems and "message" in problems
    assert any("result" in p for p in check_contract(raw(stage="done", message="끝")))
    assert any("좌표" in p for p in check_contract(raw(stage="need_confirm", message="확인해 주세요")))


def test_탈락_이유가_없으면_잡는다():
    """1순위가 아닌 후보에 이유가 없으면 화면이 왜 그곳이 아닌지 말하지 못한다."""
    result = done_result(candidates=[
        Candidate(name="강남역", kind="landmark", address="서울", lng=127.02, lat=37.49,
                  rank=1, access_ok=True, reason="1순위"),
        Candidate(name="역삼역", kind="landmark", address="서울", lng=127.03, lat=37.50,
                  rank=2, access_ok=True, reason="2순위"),
    ])
    out = check_contract(response(stage="done", result=result, message="끝"))
    assert any("탈락 이유" in problem for problem in out)


def test_순위가_겹치면_잡는다():
    result = done_result(candidates=[
        Candidate(name="A", kind="landmark", address="서울", lng=127.02, lat=37.49,
                  rank=1, access_ok=True, reason="x", rejected_reason=None),
    ])
    # rank 를 스키마가 막으므로 검사는 per_participant 쪽으로 본다
    empty = done_result(per_participant=[])
    assert any("참석자별 결과" in p for p in check_contract(response(stage="done", result=empty, message="끝")))
    assert check_contract(response(stage="done", result=result, message="끝")) == []


# ─────────────────────────────────────────────────────────── 채점과 요약


def test_기대값이_없으면_점수를_매기지_않는다():
    """사람이 정답을 안 쓴 문항까지 점수에 넣으면 숫자가 거짓이 된다."""
    out = score_row({"expected": ""}, response())
    assert out["stage_ok"] is None
    assert out["slot_ok"] is None
    assert out["contract_ok"] is True   # 계약은 정답과 무관하게 본다


def test_기대한_단계와_슬롯을_같이_본다():
    out = score_row({"expected": {"stage": "need_info", "slots": {"preset": "meeting"}}}, response())
    assert out["stage_ok"] is True and out["slot_ok"] is True

    wrong = score_row({"expected": {"stage": "done", "slots": {"preset": "visit"}}}, response())
    assert wrong["stage_ok"] is False and wrong["slot_ok"] is False
    assert wrong["slots"][0]["got"] == "meeting"


def test_요약은_채점한_문항만_센다():
    results = [
        {"seconds": 1.0, "stage_ok": True, "slot_ok": None, "contract_ok": True, "cost_usd": 0.01},
        {"seconds": 3.0, "stage_ok": False, "slot_ok": True, "contract_ok": True, "cost_usd": 0.02},
        {"seconds": 2.0, "stage_ok": None, "slot_ok": None, "contract_ok": False, "cost_usd": 0.0},
        {"error": "boom", "seconds": 0.5},
    ]
    out = summarize(results)
    assert out["문항"] == 4 and out["실행 실패"] == 1
    assert out["단계 채점 문항"] == 2 and out["단계 정확도"] == 0.5
    assert out["슬롯 채점 문항"] == 1 and out["슬롯 정확도"] == 1.0
    assert out["계약 준수율"] == round(2 / 3, 3)
    assert out["비용 합계"] == 0.03


def test_슬롯_값은_저장할_수_있는_모양으로_준다():
    """결과를 파일로 남기므로 Pydantic 객체가 그대로 나오면 저장이 터진다 (09-21 실측)."""
    import json

    got = slot_value(slots(), "access")
    assert isinstance(got, dict) and got["required"] is False
    json.dumps(got)   # 여기서 예외가 나면 안 된다
