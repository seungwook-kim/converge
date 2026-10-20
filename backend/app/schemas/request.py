"""요청 스키마. 브라우저가 보내는 것. (SDD 2절)

user_id 는 본문에 없다. Authorization 헤더의 토큰에서 꺼낸다 (services/auth.py). 본문으로 받으면
남의 id를 적어 보낼 수 있다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from backend.app.domain.guard import MAX_TEXT_CHARS
from backend.app.schemas.slots import Preset, check_text

MAX_IMAGE_BASE64 = 8_000_000  # 약 6MB 이미지. 이보다 크면 비전 모델 호출 전에 막는다 (비용 방어)
MAX_PARTICIPANTS = 30  # 핀 확인으로 한 번에 보내는 참석자 수 상한 (10-20 입력 방어)
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class ParticipantInput(BaseModel):
    """핀 확인 단계에서 사용자가 확정한 좌표 하나. PATCH 본문에서 claim 만 뺀 모양이다 (SDD 2절)."""

    name: str = Field(max_length=40)
    lng: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.0)
    origin: str | None = Field(
        default=None,
        max_length=100,
        description="새 출발지 이름. 장소 검색이면 장소 이름, 지도 클릭·드래그면 그 자리 주소. 없으면 이름은 그대로",
    )

    @model_validator(mode="after")
    def _check(self) -> ParticipantInput:
        check_text(self.name, "참석자 이름")
        check_text(self.origin, "출발지")
        return self


class AgentRequest(BaseModel):
    """POST /api/agent 본문.

    confirmed_participants 가 오면 슬롯 추출을 건너뛰고 계산부터 한다 (SDD 5절 2-1).
    그때도 text 를 함께 받는 이유는 재질문·재계산이 같은 세션에서 이어지기 때문이다.
    """

    session_id: str | None = Field(default=None, pattern=UUID_PATTERN, description="재질문이면 기존 세션")
    text: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="약속 문장. 1000자까지 (10-20 입력 방어)")
    image_base64: str | None = Field(default=None, max_length=MAX_IMAGE_BASE64, description="카톡 캡처(jpeg/png)")
    preset: Preset | None = Field(default=None, description="사용자가 고른 경우")
    confirmed_participants: list[ParticipantInput] | None = Field(
        default=None, max_length=MAX_PARTICIPANTS, description="핀 확인 단계에서 수정한 좌표"
    )

    @model_validator(mode="after")
    def _check(self) -> AgentRequest:
        if not self.text and not self.image_base64:
            raise ValueError("text 또는 image_base64 중 하나는 필요합니다")
        return self


class ParticipantPatchRequest(ParticipantInput):
    """PATCH /api/session/{id}/participants 본문. 핀 소유권 (SDD 7절).

    claim=True   "이 사람이 나다" 등록. owner_user_id 가 비어 있을 때만 성공, 아니면 409
    claim=False  위치만 수정. 링크를 아는 로그인 사용자 누구나 (09-18 결정: 핀 소유권은 표시용, SDD 7절)
    """

    claim: bool = False
