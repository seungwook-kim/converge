"""준비물 목록과 집결 계획서를 조립한다. (SDD 5절 7-1단계, 4절 Checklist·summary_text)

둘 다 LLM 을 부르지 않는다.
  준비물   skills/converge/rules/checklist.md 에서 조건에 맞는 항목을 꺼내기만 한다.
           지어낸 준비물을 믿고 갔다가 못 들어가면 그날 작업이 통째로 날아간다
  계획서   이미 계산이 끝난 값을 문장으로 잇기만 한다. 모델이 쓰면 숫자가 흔들린다

이 폴더 규칙(domain/CLAUDE.md)대로 네트워크·LLM 호출은 없다. 규칙값은 rules.load_rule 로 읽는다.
"""
from __future__ import annotations

from backend.app.domain.rules import load_rule
from backend.app.schemas.result import Checklist, Result
from backend.app.schemas.slots import Slots

# 프리셋별로 꺼낼 규칙 키 (checklist.md 프론트매터)
# 출입 절차가 있으면 이 목록을 꺼낸다. 프리셋과 무관하게 access.required 가 기준이다
_ACCESS_KEY = "visit_access"

_TRANSPORT_WORD = {"car": "차", "transit": "대중교통", "walk": "도보"}
# 합류 뒤 이동은 조사까지 붙여 둔다. "대중교통" + "로" 는 틀린 말이다
_AFTER_WORD = {"car": "차로", "transit": "대중교통으로", "walk": "걸어서"}


def _dedupe(items: list[str]) -> list[str]:
    """순서를 지키면서 중복만 없앤다. 두 목록을 합치면 신분증이 두 번 나온다."""
    return list(dict.fromkeys(items))


def build_checklist(
    preset: str | None,
    access_required: bool | None,
    access_applied: bool | None,
    constraints: list[str],
    has_car: bool,
) -> Checklist | None:
    """조건을 보고 준비물을 꺼낸다. 없으면 None.

      access_required is None  아직 모른다. 목록을 만들지 않는다 (있다고도 없다고도 말하지 않는다)
      access_required is True  프리셋에 맞는 목록을 꺼낸다
      constraints 에 luggage   장비 항목을 더한다. 절차가 없어도 장비 반출입은 따로 걸린다
      access_applied is False  사전 신청 항목 앞에 "[미완료] " 를 붙인다

    has_car: 참석자 중 차로 오는 사람이 있는가. 차량번호 등록은 그때만 필요하다.
    """
    if access_required is None:
        return None

    rules = load_rule("checklist")
    before: list[str] = []
    onsite: list[str] = []

    if access_required:
        block = rules.get(_ACCESS_KEY, {})
        before += list(block.get("before") or [])
        if has_car:
            before += list(block.get("before_if_car") or [])
        onsite += list(block.get("onsite") or [])

    if "luggage" in constraints:
        block = rules.get("luggage", {})
        before += list(block.get("before") or [])
        onsite += list(block.get("onsite") or [])

    before, onsite = _dedupe(before), _dedupe(onsite)
    if not before and not onsite:
        return None

    if access_applied is False:
        prefix = str(rules.get("not_applied_prefix", ""))
        before = [f"{prefix}{item}" for item in before]

    return Checklist(before=before, onsite=onsite)


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
