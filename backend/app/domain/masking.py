"""관측 기록에서 사람을 가린다 (SDD 5절, 테이블정의서 7절).

DB 에는 참석자 이름·출발지를 암호화해 넣는다. 그런데 Langfuse 트레이스로는 사용자 문장이 그대로
나가고 있었다 (SDD 11절 09-22 결정). 문장 구조는 남겨야 어떤 입력에서 틀렸는지 볼 수 있으므로
통째로 지우지 않고 이름·출발지·탑승지만 번호로 바꾼다.

  "민수는 인천시청에서 차로" → "참석자1는 출발지1에서 차로"

조사가 어색해지는 것은 감수한다. 읽는 사람은 개발자 한 명이다.
"""
from __future__ import annotations

from typing import Any

from backend.app.schemas.slots import Slots


def replacements(slots: Slots | None) -> list[tuple[str, str]]:
    """(원문, 가림말) 목록. 긴 것부터 바꿔야 "김민수" 안의 "민수"가 먼저 바뀌지 않는다."""
    if slots is None:
        return []
    pairs: dict[str, str] = {}
    for index, person in enumerate(slots.participants, start=1):
        if person.name:
            pairs.setdefault(person.name, f"참석자{index}")
        if person.origin:
            pairs.setdefault(person.origin, f"출발지{index}")
        if person.pickup_at:
            pairs.setdefault(person.pickup_at, f"탑승지{index}")
    # 한 글자는 바꾸지 않는다. 문장 곳곳의 같은 글자가 함께 바뀌어 읽을 수 없게 된다. 드물어서 감수한다
    return sorted(((k, v) for k, v in pairs.items() if len(k) >= 2), key=lambda kv: -len(kv[0]))


def mask(value: Any, slots: Slots | None) -> Any:
    """문자열이면 바꾸고, dict·list 면 안쪽 문자열까지 바꾼다. 나머지는 그대로."""
    pairs = replacements(slots)
    return _walk(value, pairs) if pairs else value


def _walk(value: Any, pairs: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for original, alias in pairs:
            value = value.replace(original, alias)
        return value
    if isinstance(value, dict):
        return {key: _walk(item, pairs) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(item, pairs) for item in value]
    return value
