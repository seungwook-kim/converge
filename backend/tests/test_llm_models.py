"""슬롯 추출의 모델 시도 순서 (SDD 5절 1단계). 키 없이 돈다 (TEST_GUIDE)."""
from __future__ import annotations

import asyncio
import os

import pytest

from backend.app.schemas.slots import Slots
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


# ── 출입 절차 보정이 추출 결과에 붙는지 (access.md "절차 판정", 09-23) ─────────


def _fake_model(monkeypatch, output: dict):
    """모델이 늘 output 을 JSON 으로 내는 가짜. 프롬프트는 고정 문자열."""
    import json
    from types import SimpleNamespace

    async def create(**_):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(output, ensure_ascii=False)))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_client", lambda _model: client)
    monkeypatch.setattr(llm.langfuse, "get_prompt", lambda _name: ("{{text}}{{previous_slots}}{{preset_hint}}", "1"))
    monkeypatch.setenv("MODEL_SMALL", "google-ai/small")
    monkeypatch.setenv("MODEL_LARGE", "google-ai/large")


def _slot_json(**over):
    base = {
        "preset": "meeting", "datetime": "금요일 18:00", "purpose": "저녁 약속", "destination": "잠실역 앞",
        "participants": [{"name": "나", "origin": "강동구", "transport": "transit", "pickup": None,
                          "pickup_at": None, "unfamiliar": False, "role": "site"}],
        "rendezvous": None, "access": None, "schedule_confirmed": None, "constraints": [],
        "missing": ["access.required"], "out_of_scope": False,
    }
    base.update(over)
    return base


def test_추출_결과의_출입_절차를_문장_단서로_확정한다(monkeypatch):
    # 모델이 역 앞 저녁 약속을 모름으로 둔다(09-23 측정 3/3). 되묻지 않게 절차 없음으로 확정한다
    _fake_model(monkeypatch, _slot_json())
    slots = asyncio.run(llm.extract_slots("금요일 오후 6시 잠실역 앞에서 저녁 약속. 저는 강동구에서 지하철로"))
    assert slots.access is not None and slots.access.required is False
    assert "access.required" not in slots.missing


def test_재질문_답에서_모델이_절차_값을_잃으면_이전_값을_둔다(monkeypatch):
    # 1턴에 방문자 등록을 했다고 정했다. 2턴 답에 절차 이야기가 없다고 다시 되묻지 않는다
    previous = Slots(**_slot_json(destination="여의도 사무실", preset="visit", purpose="미팅",
                                  access={"required": True, "applied": True, "lead_min": None}, missing=[]))
    _fake_model(monkeypatch, _slot_json(destination="여의도 사무실", preset="visit", purpose="미팅"))
    slots = asyncio.run(llm.extract_slots("나는 강동구에서 지하철로 가요", previous))
    assert slots.access is not None and slots.access.required is True and slots.access.applied is True
    assert "access.required" not in slots.missing


def _open_case(monkeypatch, judge_fn):
    """규칙이 못 가르는 문장("성수동에서 만나"). 슬롯 모델은 절차 없음이라 한다."""
    from backend.app.services import access_judge

    _fake_model(monkeypatch, _slot_json(destination="성수동", purpose="만남",
                                        participants=[{"name": "민지", "origin": "신촌", "transport": "transit", "pickup": None,
                                                       "pickup_at": None, "unfamiliar": False, "role": "colleague"}],
                                        access={"required": False, "applied": None, "lead_min": None}, missing=[]))
    monkeypatch.setattr(access_judge, "enabled", lambda: True)
    monkeypatch.setattr(access_judge, "judge", judge_fn)
    llm._last_meta.clear()
    return asyncio.run(llm.extract_slots("토요일 2시 성수동에서 만나. 민지는 신촌에서 지하철"))


def test_규칙이_못_가르면_판단_모델에_이름을_가려_묻는다(monkeypatch):
    seen = {}

    async def judge(text, destination, purpose):
        seen.update(text=text, destination=destination, purpose=purpose)
        return {"choice": "none", "p_none": 0.95, "confidence": 0.9, "probabilities": {"none": 0.95},
                "model": "jev-1.13", "input_tokens": 300, "cost_usd": 0.0000126}

    slots = _open_case(monkeypatch, judge)
    assert slots.access.required is False
    assert "민지" not in seen["text"] and "신촌" not in seen["text"]  # 이름·출발지는 가려서 보낸다
    assert seen["destination"] == "성수동"
    meta = llm.last_meta()
    assert meta["access_basis"] == "judge" and meta["access_judge"]["p_none"] == 0.95


def test_판단_모델_호출이_실패하면_되묻는다(monkeypatch):
    async def judge(*_):
        raise TimeoutError("slow")

    slots = _open_case(monkeypatch, judge)
    assert slots.access is None and "access.required" in slots.missing
    assert llm.last_meta()["access_judge"]["error"] == "TimeoutError"


def test_규칙이_정하면_판단_모델을_부르지_않는다(monkeypatch):
    from backend.app.services import access_judge

    async def judge(*_):
        raise AssertionError("부르면 안 된다")

    _fake_model(monkeypatch, _slot_json())  # 잠실역 앞: 규칙 3순위로 정해진다
    monkeypatch.setattr(access_judge, "enabled", lambda: True)
    monkeypatch.setattr(access_judge, "judge", judge)
    llm._last_meta.clear()
    slots = asyncio.run(llm.extract_slots("금요일 오후 6시 잠실역 앞에서 저녁 약속. 저는 강동구에서 지하철로"))
    assert slots.access.required is False and llm.last_meta()["access_basis"] == "open_place"


def test_목적지가_비면_되묻는다(monkeypatch):
    # gpt-4o-mini 가 "판교역 근처" 를 비우고 missing 에도 안 적었다. 그대로 가면 지오코딩에서 실패한다 (09-23)
    _fake_model(monkeypatch, _slot_json(destination=None, missing=[]))
    slots = asyncio.run(llm.extract_slots("판교역 근처에서 스터디 하려는데 시간은 아직입니다. 저는 분당에서 지하철"))
    assert "destination" in slots.missing


def test_소형이_시간_초과면_다음_차례로_넘어간다(monkeypatch):
    """09-27: 구글 호출 하나가 멈추면 SDK 기본값(600초, 재시도 2회)대로 5분 넘게 기다렸다."""
    import json
    from types import SimpleNamespace

    import httpx
    import openai

    calls: list[str] = []

    def client_for(model):
        async def create(**kwargs):
            calls.append(model)
            if model == "google-ai/small":
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_slot_json(), ensure_ascii=False)))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
            )

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(llm, "_client", client_for)
    monkeypatch.setattr(llm.langfuse, "get_prompt", lambda _name: ("{{text}}{{previous_slots}}{{preset_hint}}", "1"))
    monkeypatch.setenv("MODEL_SMALL", "google-ai/small")
    monkeypatch.setenv("MODEL_LARGE", "google-ai/large")

    slots = asyncio.run(llm.extract_slots("금요일 오후 6시 잠실역 앞에서 저녁 약속. 저는 강동구에서 지하철로"))
    assert slots.destination == "잠실역 앞"
    assert calls[-1] == "google-ai/large"  # 소형이 멈추면 대형으로 넘어가 답을 받는다


def test_클라이언트는_시간_제한을_걸고_SDK_재시도를_끈다(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("LLM_TIMEOUT_SEC", raising=False)
    client = llm._client("google-ai/small")
    assert client.timeout == llm.LLM_TIMEOUT_SEC
    assert client.max_retries == 0

    monkeypatch.setenv("LLM_TIMEOUT_SEC", "12")
    assert llm._client("google-ai/small").timeout == 12.0


def test_해_먹는다는_말이_없으면_모델이_붙인_cook_을_지운다(monkeypatch):
    _fake_model(monkeypatch, _slot_json(constraints=["cook"], purpose="고기 먹기", destination="강남역 근처"))
    slots = asyncio.run(llm.extract_slots("금요일 오후 6시 강남역 근처에서 고기 먹기. 저는 강동구에서 지하철로"))
    assert "cook" not in slots.constraints


def test_바베큐면_cook_을_남긴다(monkeypatch):
    _fake_model(monkeypatch, _slot_json(constraints=["cook", "outdoor"], purpose="바베큐", destination="한강공원"))
    slots = asyncio.run(llm.extract_slots("금요일 오후 6시 한강공원에서 바베큐. 저는 강동구에서 지하철로"))
    assert "cook" in slots.constraints


def test_재질문_답에_단서가_없어도_이전에_남은_cook_은_지우지_않는다(monkeypatch):
    """처음 문장에 바베큐가 있어 남은 cook 을, 출발지만 답한 문장 때문에 지우면 안 된다."""
    from backend.app.schemas.slots import Slots

    _fake_model(monkeypatch, _slot_json(constraints=["cook", "booking"], purpose="바베큐", destination="강남역"))
    previous = Slots.model_validate(_slot_json(constraints=["cook", "booking"], purpose="바베큐", destination="강남역"))
    slots = asyncio.run(llm.extract_slots("저는 강동구에서 지하철로 가요", previous))
    assert "cook" in slots.constraints


def test_태우는_곳만_알고_누가_태우는지_모르면_둘_다_비우고_되묻는다():
    """09-27: "2명은 하단에 태워서" 에 pickup_at 만 채워 짝 규칙에 걸려 세 번 다 실패했다."""
    import json

    data = _slot_json()
    data["participants"].append({"name": "하단 2명", "origin": "하단", "transport": None, "pickup": None,
                                 "pickup_at": "하단", "unfamiliar": False, "role": "colleague"})
    data["missing"] = ["participants[1].transport"]
    slots = llm._parse(json.dumps(data, ensure_ascii=False))
    rider = slots.participants[1]
    assert (rider.pickup, rider.pickup_at) == (None, None)
    assert "participants[1].pickup" in slots.missing


def test_집결지의_선택_칸은_되묻지_않는다():
    """transport_after 는 없으면 차, time 은 없으면 역산 (SDD 3절). 모델이 missing 에 적어도 뺀다."""
    import json

    data = _slot_json(rendezvous={"name": "낚시벨리", "transport_after": None, "members": [], "time": None})
    data["missing"] = ["access.required", "rendezvous.transport_after", "rendezvous.time", "rendezvous.members"]
    slots = llm._parse(json.dumps(data, ensure_ascii=False))
    assert not any(m.startswith("rendezvous.") for m in slots.missing)
