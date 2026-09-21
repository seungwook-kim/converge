"""슬롯 추출의 모델 시도 순서 (SDD 5절 1단계). 키 없이 돈다 (TEST_GUIDE)."""
from __future__ import annotations

import os

import pytest

from backend.app.services import llm


@pytest.fixture(autouse=True)
def _no_local_gguf(monkeypatch):
    """이 파일은 환경변수 기반 시도 순서만 본다. 로컬 GGUF 가 있는 PC 에서도 같은 결과가 나오게 끈다."""
    from backend.app.services import slot_model

    monkeypatch.setattr(slot_model, "available", lambda: False)


@pytest.fixture(autouse=True)
def _env():
    before = {k: os.environ.get(k) for k in ("MODEL_SMALL", "MODEL_LARGE")}
    os.environ["MODEL_LARGE"] = "vendor/large"
    os.environ.pop("MODEL_SMALL", None)
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_소형이_없으면_대형으로_두_번까지만():
    assert llm.attempt_models() == ["vendor/large", "vendor/large"]


def test_소형이_있으면_두_번_시도하고_대형으로_승격한다():
    os.environ["MODEL_SMALL"] = "vendor/small"
    assert llm.attempt_models() == ["vendor/small", "vendor/small", "vendor/large"]


def test_소형과_대형이_같으면_승격하지_않는다():
    os.environ["MODEL_SMALL"] = "vendor/large"
    assert llm.attempt_models() == ["vendor/large", "vendor/large"]


def test_일인칭_이름을_나_로_맞춘다():
    from backend.app.schemas.slots import Slots

    slots = Slots(
        preset="visit",
        destination="창원 사무소",
        participants=[
            dict(name="저", origin="창원시청", transport="car", role="site"),
            dict(name="최동료", origin="마산역", transport="transit", role="colleague"),
        ],
    )
    out = llm.normalize_names(slots)
    assert [p.name for p in out.participants] == ["나", "최동료"]


def test_픽업이_일인칭을_가리키면_같이_바꾼다():
    from backend.app.schemas.slots import Slots

    slots = Slots(
        preset="visit",
        destination="창원 사무소",
        participants=[
            dict(name="제가", origin="창원시청", transport="car", role="site"),
            dict(name="이업체", origin=None, transport="car", role="vendor", pickup="제가", pickup_at="김해시청 앞"),
        ],
    )
    out = llm.normalize_names(slots)
    assert [p.name for p in out.participants] == ["나", "이업체"]
    assert out.participants[1].pickup == "나"


def test_보통_이름은_건드리지_않는다():
    from backend.app.schemas.slots import Slots

    slots = Slots(
        preset="visit",
        destination="여의도 사무실",
        participants=[dict(name="한동료", origin="강남역", transport="transit", role="colleague")],
    )
    assert llm.normalize_names(slots).participants[0].name == "한동료"


def test_로컬_GGUF_가_있으면_그것을_먼저_쓴다(monkeypatch):
    """SDD 8절: 소형은 로컬 GGUF 가 1순위다. 실패하면 대형으로 승격한다."""
    from backend.app.services import slot_model

    monkeypatch.setattr(slot_model, "available", lambda: True)
    monkeypatch.setattr(slot_model, "model_name", lambda: "local/kanana")
    # 로컬은 temperature 0 이라 다시 시도해도 같은 답이 나온다. 한 번만 하고 대형으로 넘긴다
    assert llm.attempt_models() == ["local/kanana", "vendor/large"]


# --- 소형 모델 이름 점검 (09-20 측정에서 호칭이 잘리는 것을 확인하고 붙였다) ---


def test_이름이_온전하면_통과한다():
    from backend.app.services import slot_model

    text = "박업체 과장님이 부산 사상에서 차로 오시면서 김해시청 앞에서 이업체 기사님을 태우고 오십니다."
    slot_model.check_names(text, ["박업체 과장님", "이업체 기사님"])  # 예외가 없으면 통과


def test_호칭이_잘리면_막는다():
    import pytest as _pytest

    from backend.app.services import slot_model

    text = "박업체 과장님이 부산 사상에서 차로 오십니다."
    with _pytest.raises(slot_model.NameTruncated):
        slot_model.check_names(text, ["업체"])


def test_지어낸_이름도_막는다():
    import pytest as _pytest

    from backend.app.services import slot_model

    with _pytest.raises(slot_model.NameTruncated):
        slot_model.check_names("최동료는 마산역에서 옵니다.", ["김현장"])


def test_일인칭은_건너뛴다():
    from backend.app.services import slot_model

    # 문장에는 "저는" 인데 코드가 "나" 로 바꾼다. 원문에 없다고 막으면 안 된다
    slot_model.check_names("저는 창원시청에서 차로 갑니다.", ["나"])


def test_띄어쓰기_차이는_넘어간다():
    from backend.app.services import slot_model

    slot_model.check_names("한 동료는 강남역에서 옵니다.", ["한동료"])


def test_옛_프리셋_값은_절차_유무로_옮긴다():
    """재학습 전까지 모델이 ship_maintenance·si_deploy 를 낸다 (2026-09-21 범용 전환).

    절차가 있다고 본 경우만 visit 이다. 전부 visit 으로 몰면 일반 약속에서도 절차 소요를 빼게 된다.
    """
    from backend.app.services import llm

    def slots_from(preset, access):
        import json
        return llm._parse(json.dumps({
            "preset": preset, "datetime": "토요일 14:00", "purpose": "모임",
            "destination": "강남역", "participants": [
                {"name": "나", "origin": "수원시청", "transport": "car", "pickup": None,
                 "pickup_at": None, "unfamiliar": False, "role": "site"}],
            "rendezvous": None, "access": access, "schedule_confirmed": True,
            "constraints": [], "missing": [] if access is not None else ["access.required"],
            "out_of_scope": False,
        }, ensure_ascii=False))

    assert slots_from("si_deploy", {"required": True, "applied": True, "lead_min": None}).preset == "visit"
    assert slots_from("ship_maintenance", {"required": False, "applied": None, "lead_min": None}).preset == "meeting"
    assert slots_from("si_deploy", None).preset == "meeting"
    # 새 값은 그대로 지나간다
    assert slots_from("visit", {"required": True, "applied": True, "lead_min": None}).preset == "visit"


def test_범위_밖_표시와_내용이_어긋나면_정리한다():
    """모델이 참석자를 뽑아 놓고 범위 밖이라고 하는 경우가 있다 (09-21 실측).

    스키마가 그 모순을 막기 때문에 그대로 두면 멀쩡한 문장이 failed 로 끝난다.
    """
    import json

    from backend.app.services import llm

    def parse(**over):
        base = {
            "preset": "si_deploy", "datetime": None, "purpose": None, "destination": None,
            "participants": [], "rendezvous": None, "access": None,
            "schedule_confirmed": None, "constraints": [], "missing": [], "out_of_scope": True,
        }
        base.update(over)
        return llm._parse(json.dumps(base, ensure_ascii=False))

    # 참석자가 없으면 범위 밖이 맞다. preset 을 비운다
    empty = parse()
    assert empty.out_of_scope is True and empty.preset is None

    # 참석자가 있으면 조율할 내용이 있다는 뜻이다. 범위 밖 표시를 내린다
    person = {"name": "나", "origin": "수원", "transport": "car", "pickup": None,
              "pickup_at": None, "unfamiliar": False, "role": "site"}
    filled = parse(participants=[person], destination="판교역 근처", missing=["datetime"])
    assert filled.out_of_scope is False
    assert filled.preset == "meeting" and filled.missing == ["datetime"]


def test_얻어_타는_사람의_이동수단은_운전자_것으로_채운다():
    """태워 준다는 말이 있으면 그 사람은 운전자 차를 탄다. 물을 필요가 없다 (09-21 실측)."""
    from backend.app.services.llm import fill_pickup_transport
    from backend.app.schemas.slots import Slots

    slots = Slots(
        preset="meeting",
        datetime="내일 19:00",
        destination="성수동",
        participants=[
            dict(name="나", origin=None, transport=None, role="site",
                 pickup="이대리님", pickup_at="광진구 역 앞"),
            dict(name="이대리님", origin="노원구", transport="car", role="colleague"),
        ],
        access=dict(required=False),
        missing=["participants[0].transport", "participants[0].origin"],
    )
    out = fill_pickup_transport(slots)
    assert out.participants[0].transport == "car"
    assert "participants[0].transport" not in out.missing
    # 출발지는 그대로 둔다. 그건 파이프라인이 따로 판단한다
    assert "participants[0].origin" in out.missing
