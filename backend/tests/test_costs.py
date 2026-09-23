"""비용 상한 순수 함수 테스트. 키·DB 없이 돈다."""
from backend.app.services import costs


def test_상한이_비어_있으면_제한_없음(monkeypatch):
    monkeypatch.delenv("COST_LIMIT_USD_PER_REQUEST", raising=False)
    monkeypatch.delenv("DAILY_COST_LIMIT_USD", raising=False)
    assert costs.per_request_limit() is None
    assert costs.daily_limit() is None
    assert costs.over_limit(999.0, None) is False


def test_요청당_상한을_읽는다(monkeypatch):
    monkeypatch.setenv("COST_LIMIT_USD_PER_REQUEST", "0.05")
    assert costs.per_request_limit() == 0.05
    assert costs.over_limit(0.04, 0.05) is False
    assert costs.over_limit(0.05, 0.05) is True


def test_일일_상한을_읽는다(monkeypatch):
    monkeypatch.setenv("DAILY_COST_LIMIT_USD", "1.0")
    assert costs.daily_limit() == 1.0


def test_알려진_모델은_비용을_잰다():
    assert costs.estimate_cost_usd("openai/gpt-4o-mini", 1000, 500) == 0.00045


def test_모르는_모델은_None(monkeypatch):
    monkeypatch.delenv("MODEL_COST_JSON", raising=False)
    assert costs.estimate_cost_usd("unknown/model", 1000, 500) is None


def test_단가표는_env로_덮는다(monkeypatch):
    monkeypatch.setenv("MODEL_COST_JSON", '{"my/model": [1.0, 3.0]}')
    assert costs.estimate_cost_usd("my/model", 1_000_000, 0) == 1.0


def test_지금_쓰는_구글_모델도_비용을_잰다(monkeypatch):
    """단가표에 없으면 None 이 되어 비용 상한이 걸리지 않는다 (09-23 확인)."""
    monkeypatch.delenv("MODEL_COST_JSON", raising=False)
    for model in (
        "google-ai/gemini-3.5-flash-lite",
        "google-ai/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash-lite",
        "google/gemini-3.1-flash-lite",
    ):
        assert costs.estimate_cost_usd(model, 1000, 500) is not None, model


def test_구글_직접과_OpenRouter_는_같은_단가로_잰다(monkeypatch):
    """전환해도 비용 상한이 같은 기준으로 걸리게 한다."""
    monkeypatch.delenv("MODEL_COST_JSON", raising=False)
    direct = costs.estimate_cost_usd("google-ai/gemini-3.5-flash-lite", 1000, 500)
    routed = costs.estimate_cost_usd("google/gemini-3.5-flash-lite", 1000, 500)
    assert direct == routed
