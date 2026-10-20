"""입력 방어. LLM 에 들어가기 전의 문장과 캡처 글자를 정리하고, 명백한 공격 문구를 거른다. (SDD 2절 입력 방어, 10-20)

계산만 한다. 네트워크·LLM 호출이 없다 (domain/ 규칙).

하는 일 세 가지:
  1. clean        유니코드 정규화(NFC), 제어문자·폭 없는 문자·양방향 제어문자 제거, 빈 줄 줄이기, 길이 자르기
  2. attack_reason 프롬프트 주입·역할 바꾸기·스크립트·SQL·템플릿 문구면 그 종류를 돌려준다. 정상이면 None
  3. clip         판정 모델이 쓴 자유 글(이유 등)을 화면에 내기 전에 정리하고 자른다

구조적 방어는 따로 있다: 출력은 Slots 스키마(slots._ALLOWED_TEXT)로 검증, DB 는 파라미터 쿼리와 암호화,
화면은 React 이스케이프(dangerouslySetInnerHTML 없음), 서비스 전체 로그인 필수. 이 파일은 그 앞단이다.
여기서 거르는 것은 "명백한" 공격 문구뿐이다. 애매한 문장을 막으면 정상 약속 문장이 같이 막힌다.

길이 값은 운영 한도다. 도메인 규칙값(skills/converge/rules/)이 아니라서 여기 둔다.
"""
from __future__ import annotations

import re
import unicodedata

MAX_TEXT_CHARS = 1000  # 요청 문장. 약속 문장은 길어야 몇백 자다 (schemas/request.py 와 같은 값)
MAX_TRANSCRIPT_CHARS = 2000  # 캡처에서 읽은 글자. 대화 캡처라 문장보다 길 수 있다
MAX_REASON_CHARS = 200  # 판정 모델이 쓴 이유 한 줄

# 지울 문자: 제어문자(줄바꿈·탭 제외), 폭 없는 문자, 양방향 제어문자, BOM.
# 눈에 안 보이는 글자로 지시를 숨기거나 화면 글자 순서를 뒤집는 데 쓰인다
_INVISIBLE = re.compile(
    "[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f"
    "​-‏ -‮⁠-⁤⁦-⁯﻿￹-￻]"
)
_MANY_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")

# 명백한 공격 문구. (종류, 정규식). 대소문자 무시
_ATTACKS: list[tuple[str, re.Pattern[str]]] = [
    (
        "prompt_injection",
        re.compile(
            r"(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|system)\s+"
            r"(instructions?|prompts?|rules?|messages?)"
            r"|(system|developer|hidden)\s+prompt"
            r"|you\s+are\s+now\s+|act\s+as\s+(an?\s+)?(ai|assistant|system|developer)|jailbreak|developer\s+mode|\bDAN\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection",
        re.compile(
            r"(이전|위의?|앞의?|기존|모든)\s*(지시|명령|지침|규칙|프롬프트)\S*\s*(을|를|은|는|다)?\s*(무시|잊|따르지\s*마)"
            r"|(지시|명령|지침|규칙|프롬프트)\S*\s*(을|를)?\s*무시"
            r"|시스템\s*프롬프트|프롬프트\s*(를|을)?\s*(보여|알려|출력|공개|말해)"
            r"|(너는|넌|당신은)\s*(이제|지금부터)|역할\s*(을|를)?\s*(바꿔|바꾸|변경)|탈옥"
        ),
    ),
    (
        "role_marker",
        re.compile(
            r"^\s*(system|assistant|developer)\s*:|<\|?(im_start|im_end|system|endoftext)\|?>|\[/?INST\]|<</?SYS>>",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    ("script", re.compile(r"<\s*/?\s*(script|iframe|object|embed|svg|img)\b|javascript\s*:|\bon\w+\s*=", re.IGNORECASE)),
    (
        "sql",
        re.compile(
            r"\b(drop|truncate|alter)\s+table\b|\bunion\s+(all\s+)?select\b|;\s*(delete|update|insert)\s|'\s*or\s+'?1'?\s*=\s*'?1",
            re.IGNORECASE,
        ),
    ),
    ("template", re.compile(r"\{\{.*?\}\}|\$\{.*?\}|\{%.*?%\}", re.DOTALL)),
]


def clean(text: str | None, limit: int = MAX_TEXT_CHARS) -> str:
    """정규화하고 안 보이는 문자를 지운 뒤 limit 자로 자른다. None 이면 빈 문자열."""
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = _INVISIBLE.sub("", out)
    out = _SPACES.sub(" ", out)
    out = _MANY_BLANK_LINES.sub("\n\n", out)
    return out.strip()[:limit]


def attack_reason(text: str | None) -> str | None:
    """명백한 공격 문구의 종류. 없으면 None. clean 을 거친 글자에 쓴다."""
    if not text:
        return None
    for kind, pattern in _ATTACKS:
        if pattern.search(text):
            return kind
    return None


def clip(text: str | None, limit: int = MAX_REASON_CHARS) -> str | None:
    """판정 모델이 쓴 자유 글을 화면용으로 정리한다. 비면 None."""
    out = clean(text, limit)
    return out or None
