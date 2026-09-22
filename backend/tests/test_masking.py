"""Langfuse 로 나가는 기록에서 사람을 가린다 (domain/masking.py). 키 없이 돈다."""
from __future__ import annotations

from backend.app.domain import masking
from backend.app.schemas.slots import Slots


def _slots() -> Slots:
    return Slots(
        preset="meeting",
        destination="한강공원",
        participants=[
            dict(name="민수", origin="인천시청", transport="car", role="colleague"),
            dict(name="김지호", origin="의정부시청", transport="transit", role="colleague"),
            dict(name="나", origin="수원시청", transport="transit", role="colleague"),
            dict(name="유진", pickup="민수", pickup_at="강남역 2번 출구", transport="car", role="colleague"),
        ],
    )


def test_이름과_출발지를_번호로_바꾼다():
    text = "민수는 인천시청에서 차로, 김지호는 의정부시청에서 지하철"
    assert masking.mask(text, _slots()) == "참석자1는 출발지1에서 차로, 참석자2는 출발지2에서 지하철"


def test_탑승지도_가린다():
    assert masking.mask("유진은 강남역 2번 출구에서 탄다", _slots()) == "참석자4은 탑승지4에서 탄다"


def test_목적지는_남긴다():
    # 목적지는 DB 에도 평문으로 두는 공개 장소다. 지우면 어느 장소에서 틀렸는지 못 본다
    assert "한강공원" in masking.mask("토요일 한강공원", _slots())


def test_안쪽_문자열까지_바꾼다():
    out = masking.mask({"rankings": [{"reason": "민수가 늦어서"}], "n": 3}, _slots())
    assert out == {"rankings": [{"reason": "참석자1가 늦어서"}], "n": 3}


def test_한_글자_이름은_바꾸지_않는다():
    # "나" 를 바꾸면 "나중에" 같은 말까지 깨진다
    assert masking.mask("나중에 정산", _slots()) == "나중에 정산"


def test_슬롯이_없으면_그대로():
    assert masking.mask("민수", None) == "민수"
