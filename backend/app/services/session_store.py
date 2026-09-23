"""파이프라인과 store.py 사이. (SDD 5절 8단계, 재질문)

store.py 는 표 단위 함수(create_session, update_session, save_result)를 준다. 파이프라인은
"이번 요청을 저장해 줘" 하나만 알면 된다. 그 사이를 이 파일이 맡는다.

store.py 는 DB 접근만 한다. 여기서 부르기만 하고 모양 변환은 이 파일이 맡는다.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from backend.app.domain import checklist as domain_checklist
from backend.app.domain import rules
from backend.app.schemas.result import AgentResponse, GeocodedPin, ParticipantEdit, Result
from backend.app.schemas.slots import Participant, Rendezvous, Slots
from backend.app.services import store


async def load_session(session_id: str) -> dict[str, Any] | None:
    """재질문이 읽는 세션 한 건. 잠금 여부까지 붙여 준다."""
    row = await store.get_session(session_id)
    if row is None:
        return None
    return {**row, "locked": store.is_locked(row.get("meet_at"))}


async def save(
    *,
    session_id: str | None,
    user_id: str,
    slots: Slots,
    participants: list[dict[str, Any]],
    result: Result | None,
    trace_id: str,
    status: str = "computed",
    destination: tuple[float | None, float | None] | None = None,
    meet_at: datetime | None = None,
    new_id: str | None = None,
) -> str:
    """세션과 결과를 저장하고 session_id 를 돌려준다.

    session_id 가 None 이면 새 세션을 만든다. new_id 가 오면 그 값을 행의 id 로 쓴다 (파이프라인이
    Langfuse 세션에 먼저 쓴 id 와 맞추려는 것이다). 없으면 DB 가 만든다.
    이미 있는 세션이면 참석자 좌표와 상태만 갱신한다.

    meet_at: 파이프라인이 슬롯의 날짜를 읽어 넘긴다 (SDD 5절 1-3). 못 읽었으면 None 이고
    임시 세션으로 남아 보관 기간 7일을 따른다 (테이블정의서 6절). 들어오면 expires_at 도 다시 계산된다.
    """
    dest = destination if destination is not None else _destination(result)
    if session_id is None:
        session_id = await store.create_session(
            session_id=new_id,
            user_id=user_id,
            preset=slots.preset or "meeting",
            participants=participants,
            meet_at=meet_at,
            purpose=slots.purpose,
            destination_name=slots.destination,
            destination_lng=dest[0],
            destination_lat=dest[1],
            rendezvous=slots.rendezvous.model_dump() if slots.rendezvous else None,
            access=slots.access.model_dump() if slots.access else None,
            schedule_confirmed=slots.schedule_confirmed,
            constraints=slots.constraints,
        )
    await store.update_session(session_id, participants=participants, status=status, meet_at=meet_at)
    # 결과가 없으면(되묻기·핀 확인 중) 세션만 남긴다. 링크를 먼저 만들어 줘야 참석자들이 모일 수 있다
    if result is not None:
        await store.save_result(
            session_id=session_id,
            candidates=[c.model_dump() for c in result.candidates],
            per_participant=[r.model_dump() for r in result.per_participant],
            routed_to=result.routed_to,
            model_small=result.model_small,
            model_large=result.model_large,
            prompt_version=result.prompt_version,
            rendezvous_departure=result.rendezvous_departure,
            provisional=result.provisional,
            trace_id=trace_id,
            confidence=result.confidence,
        )
    return session_id


def _destination(result: Result | None) -> tuple[float | None, float | None]:
    """목적지 좌표 자리. 지금은 1순위 후보 좌표를 쓴다 (목적지 핀과 후보가 같은 건물일 때가 많다)."""
    top = next((c for c in result.candidates if c.rank == 1), None) if result else None
    return (top.lng, top.lat) if top else (None, None)


# ─────────────────────────────────────────────────────────────────────────────
# 저장된 세션 → 화면이 아는 모양 (SDD 2절 GET /api/session/{id})
# ─────────────────────────────────────────────────────────────────────────────
# 공유 링크 화면은 POST /api/agent 응답과 같은 모양(AgentResponse)을 그린다. 표 컬럼으로 흩어져
# 저장된 것을 여기서 다시 모은다. 화면 두 개가 같은 렌더링 코드를 쓰게 하려는 것이다.

# 저장된 좌표의 확신도. 저장까지 갔다는 것은 이미 확인을 거쳤다는 뜻이라 확인 단계로 되돌리지 않는다
CONFIRMED_CONFIDENCE = 1.0
STORED_CONFIDENCE = 0.9


def slots_from_session(row: dict[str, Any]) -> Slots:
    """저장된 세션을 Slots 로 되돌린다. 재질문 프롬프트와 공유 링크 화면이 쓴다.

    검증을 거치지 않는 이유: 저장 당시에 통과한 값이고, 지금은 참고 자료이기 때문이다.
    사람이 쓴 시각 표현("목요일 아침 8시")은 표에 남지 않는다. 대신 meet_at 에서 되살린다.
    비우면 재질문 때마다 시각을 다시 묻는다 (09-22 실측). 날짜 없이 시각만 말한 약속은 meet_at 이
    없어 여전히 비어 있다.
    """
    return Slots.model_construct(
        preset=row.get("preset"),
        datetime=_datetime_text(row.get("meet_at")),
        purpose=row.get("purpose"),
        destination=row.get("destination_name"),
        participants=[Participant.model_construct(**_participant_fields(p)) for p in row.get("participants") or []],
        rendezvous=_rendezvous(row.get("rendezvous")),
        access=row.get("access"),
        schedule_confirmed=row.get("schedule_confirmed"),
        constraints=row.get("constraints") or [],
        missing=[],
        out_of_scope=False,
    )


def _rendezvous(stored: dict[str, Any] | None) -> Rendezvous | None:
    """저장된 집결지(rendezvous_enc 복호화본). 비우면 다시 연 계획서에서 "집결: OO, 차로 이동" 이 빠진다."""
    if not stored:
        return None
    return Rendezvous.model_construct(name=stored.get("name"), transport_after=stored.get("transport_after"))


def _datetime_text(meet_at: datetime | None) -> str | None:
    """meet_at → "2026-09-23 19:00". 0시는 시각을 몰라 넣은 값이라 날짜만 (domain/rules.meet_at_local)."""
    if meet_at is None:
        return None
    local = meet_at.astimezone(ZoneInfo(rules.load_rule("session")["timezone"]))
    if (local.hour, local.minute) == (0, 0):
        return local.strftime("%Y-%m-%d")
    return local.strftime("%Y-%m-%d %H:%M")


def _participant_fields(stored: dict[str, Any]) -> dict[str, Any]:
    """저장 구조(테이블정의서 1절)에서 슬롯 필드만 골라낸다. 좌표는 geocoded 로 따로 나간다."""
    return {
        "name": stored.get("name"),
        "origin": stored.get("origin_text"),
        "transport": stored.get("transport"),
        "pickup": stored.get("pickup"),
        "pickup_at": stored.get("pickup_at"),
        "unfamiliar": bool(stored.get("unfamiliar")),
        "role": stored.get("role") or "colleague",
        "owner_user_id": stored.get("owner_user_id"),
    }


def pins_from_session(row: dict[str, Any]) -> list[GeocodedPin]:
    """저장된 좌표를 지도 핀으로. 참석자와 목적지만 남아 있다 (후보 좌표는 결과 안에 있다)."""
    pins: list[GeocodedPin] = []
    for stored in row.get("participants") or []:
        if stored.get("lng") is None or stored.get("lat") is None:
            continue
        pins.append(
            GeocodedPin(
                name=stored["name"],
                lng=stored["lng"],
                lat=stored["lat"],
                confidence=CONFIRMED_CONFIDENCE if stored.get("confirmed") else STORED_CONFIDENCE,
                kind="participant",
            )
        )
    if row.get("destination_lng") is not None and row.get("destination_lat") is not None:
        pins.append(
            GeocodedPin(
                name=row.get("destination_name") or "목적지",
                lng=row["destination_lng"],
                lat=row["destination_lat"],
                confidence=STORED_CONFIDENCE,
                kind="destination",
            )
        )
    return pins


def result_from_row(row: dict[str, Any] | None) -> Result | None:
    """저장된 결과를 Result 로. 모양이 어긋나면 None (화면이 결과 없이라도 열리게 한다)."""
    if not row:
        return None
    try:
        return Result.model_validate(
            {
                "candidates": row.get("candidates") or [],
                "per_participant": row.get("per_participant") or [],
                "provisional": bool(row.get("provisional")),
                "rendezvous_departure": row.get("rendezvous_departure"),
                "confidence": row.get("confidence") if row.get("confidence") is not None else 0.0,
                "model_small": row.get("model_small") or "unknown",
                "model_large": row.get("model_large"),
                "prompt_version": row.get("prompt_version") or "unknown",
                "routed_to": row.get("routed_to") or "small",
            }
        )
    except Exception:  # noqa: BLE001  저장된 옛 모양이면 결과만 비운다
        return None


def edits_from_session(row: dict[str, Any]) -> list[ParticipantEdit]:
    """핀별 마지막 수정 기록. 아직 아무도 안 고쳤으면 빈 항목으로 둔다 (SDD 7절)."""
    out: list[ParticipantEdit] = []
    for stored in row.get("participants") or []:
        editor = stored.get("last_edited_by")
        out.append(
            ParticipantEdit(
                name=stored.get("name", ""),
                edited_by=editor,
                edited_at=stored.get("self_edited_at"),
                by_owner=bool(editor and editor == stored.get("owner_user_id")),
            )
        )
    return out


def _rebuild_checklist(slots: Slots, result: Result) -> None:
    """준비물과 집결 계획서를 다시 조립한다 (SDD 5절 7-1단계와 같은 함수).

    results 표에는 두 칸이 없다. 계획을 만들면 화면이 곧바로 /s/{id} 로 옮겨 이 경로로 다시 읽으므로,
    조립하지 않으면 사용자는 준비물을 한 번도 못 본다 (09-22 화면 E2E). 둘 다 슬롯과 결과만으로
    정해지는 코드 조립이라 저장하지 않고 매번 만든다.
    """
    access = slots.access if isinstance(slots.access, dict) else (slots.access.model_dump() if slots.access else {})
    result.checklist = domain_checklist.build_checklist(
        preset=slots.preset,
        access_required=access.get("required"),
        access_applied=access.get("applied"),
        constraints=slots.constraints,
        has_car=any(p.transport == "car" for p in slots.participants),
        carriers=domain_checklist.pick_carriers(slots, result),
    )
    result.summary_text = domain_checklist.build_summary(slots, result)


def to_agent_response(session_id: str, row: dict[str, Any], result_row: dict[str, Any] | None) -> AgentResponse:
    """공유 링크 응답. POST /api/agent 와 같은 모양이라 화면이 그대로 그린다 (SDD 2절)."""
    result = result_from_row(result_row)
    slots = slots_from_session(row)
    if result is not None:
        _rebuild_checklist(slots, result)
    # 결과가 있으면 done, 아직 계산 전이면 핀 확인 단계로 본다. 초안 세션(되묻기 중)도 같은 화면에서
    # 이어서 답하므로 참석자 핀만 먼저 보여 주면 된다
    return AgentResponse(
        session_id=session_id,
        stage="done" if result else "need_confirm",
        slots=slots,
        result=result,
        questions=[],
        message=(
            "주선자가 공유한 집결 계획입니다."
            if result
            else "아직 계산 전입니다. 참석자 위치만 표시합니다."
        ),
        trace_id=str(result_row.get("trace_id") or "") if result_row else "",
        geocoded=pins_from_session(row),
        edits=edits_from_session(row),
    )
