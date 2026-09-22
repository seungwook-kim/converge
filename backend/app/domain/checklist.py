"""준비물 목록과 집결 계획서를 조립한다. (SDD 5절 7-1단계, 4절 Checklist·summary_text)

둘 다 LLM 을 부르지 않는다.
  준비물   skills/converge/rules/checklist.md 에서 조건에 맞는 항목을 꺼내기만 한다.
           지어낸 준비물을 믿고 갔다가 못 들어가면 그날 작업이 통째로 날아간다
  계획서   이미 계산이 끝난 값을 문장으로 잇기만 한다. 모델이 쓰면 숫자가 흔들린다

이 폴더 규칙(domain/CLAUDE.md)대로 네트워크·LLM 호출은 없다. 규칙값은 rules.load_rule 로 읽는다.
"""
from __future__ import annotations

from backend.app.domain.rules import load_rule
from backend.app.schemas.result import Checklist, ParticipantResult, Result
from backend.app.schemas.slots import Slots

# 출입 절차가 있으면 이 목록을 꺼낸다. 프리셋과 무관하게 access.required 가 기준이다
_ACCESS_KEY = "visit_access"

# constraints 값이 그대로 규칙 키가 된다 (checklist.md "조건과 목록").
# 여기 없는 값이 들어와도 무시한다. 모르는 이름으로 목록을 지어내지 않는다
_CONSTRAINT_KEYS = ("luggage", "cook", "outdoor", "host_home", "booking", "split")

_TRANSPORT_WORD = {"car": "차", "transit": "대중교통", "walk": "도보"}
# 합류 뒤 이동은 조사까지 붙여 둔다. "대중교통" + "로" 는 틀린 말이다
_AFTER_WORD = {"car": "차로", "transit": "대중교통으로", "walk": "걸어서"}


def _dedupe(items: list[str]) -> list[str]:
    """순서를 지키면서 중복만 없앤다. 두 목록을 합치면 신분증이 두 번 나온다."""
    return list(dict.fromkeys(items))


def _owner(assign: str | None, carriers: dict[str, str | None], rules: dict) -> str:
    """assign 값 하나를 "(차로 오는 민수)" 같은 꼬리표로 바꾼다. 맡을 사람이 없으면 빈 문자열.

    억지로 배정하지 않는다. 아무도 차로 오지 않는데 누군가를 적으면 그게 더 틀린 말이다.
    """
    if not assign:
        return ""
    name = carriers.get(assign)
    if not name:
        return ""
    template = str(rules.get(f"assign_{assign}", "") or "")
    return f" ({template.format(name=name)})" if template else f" ({name})"


def _items(raw: object, carriers: dict[str, str | None], rules: dict) -> list[str]:
    """규칙 파일의 항목 목록을 문자열 목록으로 편다.

    항목은 두 모양이다 (checklist.md 프론트매터 주석).
      "방문자 등록"                      그냥 문자열
      {item: 고기·식재료, assign: car}   맡을 사람을 붙인다
    """
    out: list[str] = []
    for entry in list(raw or []):
        if isinstance(entry, dict):
            item = str(entry.get("item") or "").strip()
            if not item:
                continue
            out.append(item + _owner(entry.get("assign"), carriers, rules))
        else:
            out.append(str(entry))
    return out


def build_checklist(
    preset: str | None,
    access_required: bool | None,
    access_applied: bool | None,
    constraints: list[str],
    has_car: bool,
    carriers: dict[str, str | None] | None = None,
) -> Checklist | None:
    """조건을 보고 준비물을 꺼낸다. 꺼낼 것이 하나도 없으면 None.

    두 갈래를 합친다 (checklist.md "조건과 목록").
      access_required is True   들어가는 절차 때문에 필요한 것
      constraints 의 값들       하려는 일 때문에 필요한 것. 절차가 없어도 걸린다

    access_required 가 None 이면 절차 쪽은 건너뛴다. 아직 모르는 것을 있다고도 없다고도
    말하지 않는다. 다만 constraints 로 나온 항목은 그대로 낸다. 고기는 절차와 무관하다.

    access_applied is False 면 절차 쪽 사전 항목 앞에 "[미완료] " 를 붙인다.
    하려는 일 쪽에는 붙이지 않는다. 신청이라는 개념이 없다.

    has_car: 참석자 중 차로 오는 사람이 있는가. 차량번호 등록은 그때만 필요하다.
    carriers: assign 값 -> 맡을 사람 이름 ({"car": "민수", "first": "지호"}). 없으면 배정하지 않는다.
    """
    rules = load_rule("checklist")
    carriers = carriers or {}
    access_before: list[str] = []
    before: list[str] = []
    onsite: list[str] = []

    if access_required:
        block = rules.get(_ACCESS_KEY, {})
        access_before += _items(block.get("before"), carriers, rules)
        if has_car:
            access_before += _items(block.get("before_if_car"), carriers, rules)
        onsite += _items(block.get("onsite"), carriers, rules)

    for key in _CONSTRAINT_KEYS:
        if key not in constraints:
            continue
        block = rules.get(key, {})
        before += _items(block.get("before"), carriers, rules)
        onsite += _items(block.get("onsite"), carriers, rules)

    if access_applied is False:
        prefix = str(rules.get("not_applied_prefix", ""))
        access_before = [f"{prefix}{item}" for item in access_before]

    # 절차 항목을 앞에 둔다. 늦으면 아예 못 들어가는 쪽이라 먼저 보여야 한다
    before, onsite = _dedupe(access_before + before), _dedupe(onsite)
    if not before and not onsite:
        return None

    return Checklist(before=before, onsite=onsite)


def pick_carriers(slots: Slots, result: Result) -> dict[str, str | None]:
    """누가 무엇을 맡을지 고른다 (checklist.md "누가 맡나").

      car    차로 오는 사람. 여럿이면 출발이 가장 이른 사람. 오는 길에 들르기 좋다
      first  출발이 가장 이른 사람. 도착 기한은 모두 같으므로 먼저 나서는 사람이 먼저 닿는다

    계산이 끝난 1순위 후보 기준이다. 판단이 아니라 정렬이므로 여기(domain)에 둔다.
    """
    rows = [r for r in result.per_participant if r.candidate_rank == 1 and r.departure_time]
    if not rows:
        return {}
    order = sorted(rows, key=_depart_minutes)
    drivers = [r for r in order if r.transport == "car"]
    return {
        "car": drivers[0].name if drivers else None,
        "first": order[0].name,
    }


def _depart_minutes(row: ParticipantResult) -> int:
    """도착 기한 기준 출발 시각(분). 도착보다 늦은 시각이면 전날 출발이다 (00:30 약속에 23:40 출발)."""
    depart = _minutes(row.departure_time)
    return depart - 24 * 60 if depart > _minutes(row.arrive_by) else depart


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def build_summary(slots: Slots, result: Result) -> str:
    """카톡·메일에 그대로 붙여넣을 한 덩어리 텍스트.

    1순위 후보 기준이다. 표에 있는 값(출발 시각, 도착 기한)을 그대로 옮긴다. 여기서 다시 계산하지 않는다.
    """
    top = next((c for c in result.candidates if c.rank == 1), None)
    rows = [r for r in result.per_participant if r.candidate_rank == 1]
    origins = {p.name: p.origin for p in slots.participants}

    head = " ".join(part for part in (slots.datetime, slots.destination, slots.purpose) if part)
    lines: list[str] = [head] if head else []

    if top and rows:
        gather = f"집결: {top.name} {rows[0].arrive_by}"
        if slots.rendezvous and slots.rendezvous.transport_after:
            word = _AFTER_WORD.get(slots.rendezvous.transport_after, "")
            gather += f", {word} 이동" if word else ""
        lines.append(gather)
    if top and top.switched_from:
        lines.append(f"({top.switched_from} 에서 옮김: {top.reason})")

    if rows:
        lines += ["", "출발 시각", ""]
        for row in rows:
            origin = origins.get(row.name) or "출발지 미정"
            word = _TRANSPORT_WORD.get(row.transport, row.transport)
            line = f"{row.name} ({origin}, {word}) {row.departure_time}"
            if row.via_pickup:
                driver = next((p.pickup for p in slots.participants if p.name == row.name), None)
                if driver:
                    line += f" ({driver} 차 탑승)"
            lines.append(line)

    if result.checklist and result.checklist.before:
        lines += ["", "미리 해둘 것", ""] + list(result.checklist.before)
    if result.checklist and result.checklist.onsite:
        lines += ["", "당일 챙길 것", "", ", ".join(result.checklist.onsite)]

    if result.provisional:
        lines += ["", "일정이 아직 확정이 아닙니다. 확정되면 다시 계산합니다."]

    return "\n".join(lines).strip()
