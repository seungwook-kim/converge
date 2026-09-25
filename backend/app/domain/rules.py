"""규칙값 로드. skills/converge/rules/*.md 의 yaml 프론트매터를 읽어 dict로 돌려준다.

왜 이 파일이 있나 (SDD 7절):
  규칙값(여유 시간, 보관 일수, 출입 절차 소요 등)은 코드가 아니라 문서가 기준이다.
  코드에 숫자를 직접 적으면 문서와 코드가 따로 놀게 되고, 값을 바꿀 때 코드를 찾아 고쳐야 한다.
  그래서 코드는 이 함수로 문서를 읽기만 한다. 값을 바꾸려면 .md 파일만 고친다.

이 폴더의 규칙 (domain/CLAUDE.md):
  - 네트워크·LLM 호출 없음. 파일만 읽는다
  - API 키 없이 pytest가 돌아야 한다. 이 파일은 키가 전혀 필요 없다

지금은 로드 함수만 있다. 절차 소요·여유·역산·전환 조건 같은 계산식은 SDD 5절 5·7단계를
구현할 때 여기에 붙인다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# 규칙 문서 폴더. 이 파일(backend/app/domain/rules.py)에서 저장소 루트까지 올라간 뒤 skills/로.
# Docker 이미지 안에서도 같은 상대 구조로 복사되므로(Dockerfile이 루트를 빌드 컨텍스트로 씀) 그대로 동작한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_DIR = _REPO_ROOT / "skills" / "converge" / "rules"

# 프론트매터 = 파일 맨 앞의 `---` 와 `---` 사이. 그 아래 본문(근거 사례·설명)은 사람이 읽는 부분이라 무시한다.
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


@lru_cache(maxsize=None)
def load_rule(name: str) -> dict:
    """skills/converge/rules/<name>.md 의 프론트매터를 dict로 돌려준다.

    예) load_rule("session") -> {"register_within_days": 30, "retain_after_meet_days": 30, ...}

    lru_cache: 같은 파일을 요청마다 다시 읽지 않도록 첫 호출 결과를 기억한다.
    규칙 파일은 배포 중에 바뀌지 않으므로(바꾸면 재배포) 캐시해도 안전하다.

    파일이 없거나 프론트매터가 없으면 바로 예외를 낸다. 규칙값이 없는 채로 조용히 돌아가면
    기본값이 코드에 숨어 들어가게 되므로, 시작 시점에 크게 실패하는 쪽을 택했다.
    """
    path = RULES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"규칙 파일 없음: {path}")

    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError(f"프론트매터(--- ... ---)가 없음: {path}")

    data = yaml.safe_load(match.group(1))  # safe_load: 임의 파이썬 객체 생성 금지. 문서는 데이터일 뿐
    if not isinstance(data, dict):
        raise ValueError(f"프론트매터가 key: value 형식이 아님: {path}")
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 출발 시각 역산 (SDD 5절 7단계, MCP 도구 departure_calc)
# ─────────────────────────────────────────────────────────────────────────────
# 이 폴더 규칙대로 순수 계산만. 소요시간은 카카오·TMAP이 준 값을 인자로 받고, 여유·절차 소요는
# skills/converge/rules/ 의 값을 호출 쪽이 읽어 넘긴다. 여기서 규칙 파일을 직접 읽지 않는 이유는
# 프리셋(meeting/visit)마다 다른 값을 고르는 판단이 파이프라인 몫이기 때문이다.

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def calc_departure(
    arrive_by: str, duration_sec: int, buffer_min: int, access_lead_min: int
) -> dict:
    """도착 기한에서 거꾸로 빼서 출발 시각을 구한다.

      arrive_by            "09:00"  약속 시각 (점검 시작, 배포 시작)
      − access_lead_min    15       출입 절차(방문자 확인·출입증 수령). 이 시각까지 절차 시작점에 도착해야 함
      = arrive_by_adjusted "08:40"
      − duration_sec       2700     이동 (45분)
      − buffer_min         20       여유 (정체·환승)
      = depart_at          "07:35"

    반환: {"depart_at": "07:35", "arrive_by_adjusted": "08:40", "day_offset": 0}
    day_offset: 출발이 도착 기한의 전날이면 -1 (늦은 밤 약속에서 실제로 생긴다).
                "HH:MM" 문자열만 주면 날짜가 사라지므로 따로 준다 (SDD 6절, 09-18 추가).
    """
    if duration_sec < 0 or buffer_min < 0 or access_lead_min < 0:
        raise ValueError("소요·여유·절차 시간은 음수일 수 없다")

    # 날짜는 계산용 임의 기준일. 시각 차이만 쓰므로 어느 날이든 상관없다.
    base = datetime(2000, 1, 2)  # 1월 2일: 전날(1월 1일)로 넘어가도 음수 날짜가 안 되게
    arrive = base.replace(hour=int(arrive_by[:2]), minute=int(arrive_by[3:5]))

    adjusted = arrive - timedelta(minutes=access_lead_min)
    depart = adjusted - timedelta(seconds=duration_sec) - timedelta(minutes=buffer_min)

    return {
        "depart_at": depart.strftime("%H:%M"),
        "arrive_by_adjusted": adjusted.strftime("%H:%M"),
        "day_offset": (depart.date() - arrive.date()).days,  # 0 = 같은 날, -1 = 전날
    }


# ─────────────────────────────────────────────────────────────────────────────
# 규칙 적용 (SDD 5절 5단계)
# ─────────────────────────────────────────────────────────────────────────────
# 값은 전부 skills/converge/rules/ 에서 읽는다. 여기에 숫자를 적지 않는다 (SDD 7절 원칙).

import re

_TIME_WORDS = {"아침": 8, "오전": 9, "점심": 12, "오후": 14, "저녁": 18, "밤": 21, "새벽": 5}


def parse_meet_time(text: str | None) -> str | None:
    """사람이 쓴 시각 표현에서 "HH:MM" 을 뽑는다. 못 뽑으면 None.

      "목요일 08:00" → "08:00"     "오늘 22:00" → "22:00"
      "목요일 아침 8시" → "08:00"   "오후 2시" → "14:00"

    날짜는 여기서 다루지 않는다. 날짜는 세션의 meet_at 이 가진다 (테이블정의서 1절).
    LLM 에 맡기지 않는 이유는 같은 문장이 늘 같은 시각으로 읽혀야 하기 때문이다.
    """
    if not text:
        return None

    hhmm = re.search(r"(\d{1,2})\s*:\s*(\d{2})", text)
    if hhmm:
        hour, minute = int(hhmm.group(1)), int(hhmm.group(2))
    else:
        korean = re.search(r"(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?", text)
        if not korean:
            return None
        hour, minute = int(korean.group(1)), int(korean.group(2) or 0)

    # "오후 2시" 처럼 앞에 붙은 말로 12시간제를 푼다
    if hour < 12:
        for word, base in _TIME_WORDS.items():
            if word in text and base >= 12:
                hour += 12
                break
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


_WEEKDAYS = "월화수목금토일"
# 긴 말부터 본다. "내일모레" 안의 "내일"이 먼저 걸리면 하루가 빠진다
_RELATIVE_DAYS = {"내일모레": 2, "낼모레": 2, "오늘": 0, "금일": 0, "내일": 1, "낼": 1, "모레": 2, "글피": 3}


def today_local(now_utc: datetime) -> date:
    """UTC 시각을 session.md timezone 기준 날짜로. 서버는 UTC 로 돌아서 밤 9시(KST 오전 6시) 전후로 하루가 어긋난다."""
    return now_utc.astimezone(ZoneInfo(load_rule("session")["timezone"])).date()


def parse_meet_date(text: str | None, today: date) -> date | None:
    """사람이 쓴 날짜 표현을 날짜로. 못 읽으면 None (SDD 5절 1-3).

      "2026-10-03 12:00" / "10월 3일" / "10/3"  → 그 날. 연도가 없고 이미 지났으면 내년
      "15일"                                   → 이번 달. 지났으면 다음 달
      "오늘" "내일" "모레" "글피"
      "목요일"            → 오늘 포함 가장 가까운 목요일
      "이번주 목요일"      → 이번 주(월요일 시작) 목요일. 지났으면 지난 날짜 그대로 (1-3 이 되묻는다)
      "다음주 목요일"      → 다음 주 목요일

    LLM 에 맡기지 않는다. 같은 문장이 요일에 따라 다른 날로 읽히면 기간 판정과 보관 기간이 흔들린다.
    """
    if not text:
        return None

    full = re.search(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    if full:
        return _safe_date(int(full.group(1)), int(full.group(2)), int(full.group(3)))

    month_day = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text) or re.search(
        r"(?<![\d:])(\d{1,2})\s*/\s*(\d{1,2})(?![\d:])", text
    )
    if month_day:
        month, day = int(month_day.group(1)), int(month_day.group(2))
        found = _safe_date(today.year, month, day)
        if found is not None and found < today:
            found = _safe_date(today.year + 1, month, day)
        return found

    after = re.search(r"(\d{1,2})\s*일\s*(?:뒤|후)", text)
    if after:
        return today + timedelta(days=int(after.group(1)))

    for word, offset in _RELATIVE_DAYS.items():
        if word in text:
            return today + timedelta(days=offset)

    weekday = re.search(rf"([{_WEEKDAYS}])요일", text)
    if weekday:
        target = _WEEKDAYS.index(weekday.group(1))
        this_monday = today - timedelta(days=today.weekday())
        if re.search(r"다음\s*주|담주|다다음", text):
            weeks = 2 if "다다음" in text else 1
            return this_monday + timedelta(weeks=weeks, days=target)
        if re.search(r"이번\s*주", text):
            return this_monday + timedelta(days=target)
        return today + timedelta(days=(target - today.weekday()) % 7)

    day_only = re.search(r"(?<!\d)(\d{1,2})\s*일", text)
    if day_only:
        day = int(day_only.group(1))
        found = _safe_date(today.year, today.month, day)
        if found is not None and found < today:
            next_year, next_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            found = _safe_date(next_year, next_month, day)
        return found
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def meet_window_problem(meet: date, today: date) -> str | None:
    """등록 가능 범위(session.md register_within_days)를 벗어났으면 되물을 말. 괜찮으면 None."""
    within = load_rule("session")["register_within_days"]
    if meet < today:
        return "이미 지난 날짜입니다. 약속 날짜를 다시 알려 주세요."
    if meet > today + timedelta(days=within):
        return f"{within}일 안의 약속만 잡을 수 있습니다. 날짜를 다시 알려 주세요."
    return None


def meet_time_passed(meet: date, hhmm: str | None, today: date, now_utc: datetime) -> bool:
    """오늘 약속인데 그 시각이 이미 지났는가. 시각을 모르면 False.

    요일만 말하면 오늘을 포함해 가장 가까운 날로 읽는다. 토요일 오후에 "토요일 12시"라고 쓰면
    오늘 12시가 되는데, 다음 주를 뜻했을 수도 있다. 어느 쪽인지 추측하지 않고 되묻게 한다.
    """
    if meet != today or not hhmm:
        return False
    return meet_at_local(meet, hhmm) <= now_utc


def meet_at_local(meet: date, hhmm: str | None) -> datetime:
    """저장할 meet_at. 시각을 모르면 그날 0시로 둔다 (보관·잠금은 날짜만 본다)."""
    hour, minute = (int(x) for x in hhmm.split(":")) if hhmm else (0, 0)
    tz = ZoneInfo(load_rule("session")["timezone"])
    return datetime(meet.year, meet.month, meet.day, hour, minute, tzinfo=tz)


def lead_min(preset: str | None, access_required: bool | None = None) -> int:
    """출입 절차 소요(분). 방문자 확인·출입증 수령에 걸리는 시간 (access.md).

    기준은 프리셋이 아니라 절차가 있느냐다. preset 이 visit 이어도 절차가 없다고 확인됐으면 0 이다.
    없는 절차에 시간을 빼 두면 매번 15분씩 일찍 나가게 된다.
    """
    if access_required is False or preset == "meeting":
        return 0
    return int(load_rule("access")["entry_lead_min"])


def buffer_min(preset: str | None) -> int:
    """여유(분). 절차가 있는 방문은 절차 소요를 따로 빼므로 여유를 조금 줄인다 (transport.md)."""
    transport = load_rule("transport")
    key = "buffer_visit_min" if preset == "visit" else "buffer_meeting_min"
    return int(transport[key])


def traffic_extra_min(raw_min: int, transport: str, transfer_count: int | None) -> int:
    """경로 API 값에 얹는 시간. 자동차는 정체분, 대중교통은 환승 가산 (transport.md)."""
    rules = load_rule("transport")
    if transport == "car":
        pct = int(rules["car_traffic_pct"])
        return max(int(rules["car_traffic_min_min"]), round(raw_min * pct / 100))
    if transfer_count:
        return int(rules["transit_transfer_extra_min"])
    return 0


def access_ok(kind: str, applied: bool | None) -> bool:
    """이 자리에서 지금 만날 수 있는가 (SDD 4절 Candidate.access_ok).

    후보는 전부 건물 밖이거나 절차가 시작되는 자리(정문·로비·본사)다. 신청 전이어도 거기까지는
    갈 수 있고, 거기서 신청 결과를 확인한다. 그래서 지금은 항상 True 다.

    값을 남겨 두는 이유는 화면이 이 칸을 읽고, 들어가야 만날 수 있는 자리를 후보로 쓰게 되면
    그때 여기만 고치면 되기 때문이다.
    """
    _ = (kind, applied)
    return True


def is_provisional(schedule_confirmed: bool | None) -> bool:
    """결과에 잠정 표시를 달지 (schedule.md unconfirmed_is_provisional).

    시각이 아직 아니라고 말한 경우에만 잠정이다. 언급이 없으면(None) 확정으로 본다.
    말하지 않은 것을 미확정으로 잡으면 거의 모든 결과에 잠정 딱지가 붙는다.
    """
    if not load_rule("schedule")["unconfirmed_is_provisional"]:
        return False
    return schedule_confirmed is False


def is_night(hhmm: str | None) -> bool:
    """이 시각이 야간인가 (schedule.md night_start ~ night_end).

    야간이면 귀가가 문제다. 막차를 넘겼는지, 첫차가 몇 시인지를 같이 봐야 한다.
    구간이 자정을 넘으므로(22:00~06:00) 시작보다 크거나 끝보다 작으면 야간이다.
    """
    if not hhmm:
        return False
    rules = load_rule("schedule")
    start, end = str(rules["night_start"]), str(rules["night_end"])
    return hhmm >= start or hhmm <= end


# TMAP 은 지하철 구간 이름을 "수도권5호선", "부산2호선" 처럼 준다 (09-23 실측).
# 앞말이 도시를 가른다. 어느 노선까지 볼 수 있는지는 schedule.md train_lookup_lines 가 정한다
_SUBWAY_ROUTE = re.compile(r"^(\w+?)(\d+)호선$")
_ROUTE_CITY = {"수도권": "seoul", "부산": "busan"}  # 첫차·막차 API 의 city 값 (services/transit_schedule.py)


def _to_min(hhmm: str) -> int:
    """"24:10" → 1450. 24시를 넘겨 적은 막차도 그대로 분으로 센다."""
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def subway_boardings(legs: list[dict[str, Any]] | None, depart_at: str) -> list[dict[str, Any]]:
    """경로의 지하철 구간마다 어느 역에서 몇 시에 타는지. 첫차·막차를 조회할 재료다.

    탑승 시각은 출발 시각에 앞 구간(걷기·버스)의 소요를 더한 값이다. 자정을 넘기면 1440 이상이 된다.
    볼 수 없는 노선(경의중앙선, 경전철 등)은 뺀다. 빼는 것이 "모른다"는 뜻이다.
    """
    out: list[dict[str, Any]] = []
    elapsed_sec = 0
    for leg in legs or []:
        match = _SUBWAY_ROUTE.match(leg.get("route") or "") if leg.get("mode") == "SUBWAY" else None
        max_line = load_rule("schedule")["train_lookup_lines"].get(match.group(1)) if match else None
        if match and max_line and match.group(1) in _ROUTE_CITY:
            city = _ROUTE_CITY[match.group(1)]
            line = int(match.group(2))
            if 1 <= line <= int(max_line):
                out.append(
                    {
                        "city": city,
                        "line": str(line),
                        "station": leg["from"],
                        "board_min": _to_min(depart_at) + elapsed_sec // 60,
                    }
                )
        elapsed_sec += int(leg.get("sec") or 0)
    return out


def day_type(meet_date: date | None) -> str:
    """시각표 구분. 토요일은 sat, 일요일은 holiday. 공휴일은 모르므로 평일로 본다. 날짜가 없으면 평일."""
    if meet_date is None:
        return "weekday"
    return {5: "sat", 6: "holiday"}.get(meet_date.weekday(), "weekday")


def train_missed(board_min: int, first: str, last: str) -> bool:
    """이 시각에 타려면 지하철이 끊겨 있는가.

    막차는 자정을 넘겨 "24:10" 처럼 온다. 그래서 00:05 에 타는 것은 전날 운행의 끝자락이라 탈 수 있다.
    첫차 전이면 전날 막차(+1440)로 되는지 보고, 첫차 뒤면 오늘 막차 전인지 본다.
    """
    board = board_min % 1440
    first_min, last_min = _to_min(first), _to_min(last)
    if board < first_min:
        return board + 1440 > last_min
    return board > last_min


def clock(hhmm: str) -> str:
    """"24:10" → "00:10". 결과 스키마는 00~23시만 받는다 (SDD 4절)."""
    minutes = _to_min(hhmm) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _squash(text: str | None) -> str:
    """띄어쓰기를 지운다. "방문자등록" 과 "방문자 등록" 을 같게 본다."""
    return re.sub(r"\s+", "", text or "")


def _has_any(text: str | None, words: list[str]) -> bool:
    body = _squash(text)
    return any(_squash(w) in body for w in words)


def _place_kind(destination: str | None, rule: dict) -> str | None:
    """목적지의 마지막 장소 단어로 "open" / "closed" 를 가른다. 못 가르면 None.

    한국어는 끝말이 종류를 정한다. "판교 본사 앞" 은 밖(open), "여의도역 근처 사무실" 은 안(closed).
    그래서 가장 뒤에서 끝나는 단어의 종류를 쓴다. 같은 자리에서 끝나면 긴 단어가 이긴다.
    """
    body = _squash(destination)
    best: tuple[int, int, str] | None = None
    for kind, key in (("open", "open_place_words"), ("closed", "closed_place_words")):
        for word in rule[key]:
            w = _squash(word)
            at = body.rfind(w)
            if at >= 0:
                cand = (at + len(w), len(w), kind)
                best = cand if best is None or cand[:2] > best[:2] else best
    return best[2] if best else None


def settle_access(
    text: str,
    destination: str | None,
    purpose: str | None,
    access: dict[str, Any] | None,
    missing: list[str],
    followup: bool = False,
    judge: dict[str, Any] | str | None = None,
) -> tuple[dict[str, Any] | None, list[str], str]:
    """모델이 뽑은 access 를 문장 단서로 확정한다 (access.md "절차 판정").

    돌려주는 것: (access dict 또는 None, missing, 근거). access 가 None 이면 파이프라인 1-2 가
    "출입 절차가 있나요?"를 묻는다. 근거는 어느 순위에서 정했는지다:
      stated_none · cue · open_place · closed_place · casual · followup · judge · model
    followup: 재질문 뒤의 답이다(이전 슬롯이 있다). 그때는 1·2순위 단서만 보고 나머지는 모델을 믿는다.
              답 문장에는 장소가 없고, 이미 정한 절차를 목적지만 보고 다시 모름으로 돌리면 끝없이 묻는다.
    judge: 규칙이 못 정한 5순위에서 판단 모델(Jev)에 물은 결과. access.md judge_none_min_probability 참고.
      None      물어보지 않았다(꺼져 있음). 슬롯 모델 값을 따른다. 단서 없는 "절차 있음"은 믿지 않는다
      "failed"  물었는데 실패했다. 되묻는다. 장애가 오답으로 새지 않게 한다
      dict      {"choice", "p_none", "confidence"}. "없음" 만, 확률이 기준 이상이고 슬롯 모델도
                "있음" 이라 하지 않을 때만 받는다. 판단 모델은 "있음" 을 만들지 못한다
                (절차가 있는데 없다고 하면 당일 못 들어가고, 없는데 있다고 하면 15분을 헛되이 뺀다)
    """
    rule = load_rule("access")
    rest = [m for m in missing if not m.startswith("access.")]
    model_required = access.get("required") if access else None
    model_applied = access.get("applied") if access else None

    def none_needed(basis: str) -> tuple[dict[str, Any], list[str], str]:
        return {"required": False, "applied": None, "lead_min": None}, rest, basis

    def ask(basis: str) -> tuple[None, list[str], str]:
        return None, [*rest, "access.required"], basis

    # 1. 절차가 없다고 말했다
    if _has_any(text, rule["no_procedure_words"]):
        return none_needed("stated_none")
    # 2. 절차 단서가 있다. 신청 여부는 모델이 읽은 값을 쓰고, 모르면 되묻는다
    if _has_any(text, rule["procedure_words"]):
        applied = model_applied if model_required is True else None
        # 남이 해 주기로 했거나 앞으로 할 신청을 끝난 것으로 읽는 경우가 있다(09-23 측정). 모르면 되묻는다
        if applied is True and _has_any(text, rule["applied_pending_words"]):
            applied = None
        # "아직 안 했어요" 를 모름으로 두는 모델이 있다(09-23 gpt-4o-mini). 말한 그대로 신청 안 함이다
        if _has_any(text, rule["applied_not_yet_words"]):
            applied = False
        return (
            {"required": True, "applied": applied, "lead_min": None},
            rest if applied is not None else [*rest, "access.applied"],
            "cue",
        )
    if followup:
        # 되물은 뒤의 답("아니요", "없어요")은 모델을 믿는다. 다시 모름으로 돌리면 끝없이 묻는다
        return (access, missing, "followup") if access is not None else ask("followup")
    # 3. 목적지의 종류
    kind = _place_kind(destination, rule)
    if kind == "open":
        return none_needed("open_place")
    if kind == "closed":
        return ask("closed_place")
    # 4. 목적이 일상 약속
    if _has_any(purpose, rule["casual_purpose_words"]):
        return none_needed("casual")
    # 5. 규칙이 못 정한 구간
    if isinstance(judge, dict):
        sure = float(judge.get("p_none") or 0.0) >= float(rule["judge_none_min_probability"])
        if judge.get("choice") == "none" and sure and model_required is not True:
            return none_needed("judge")
        return ask("judge")
    if judge == "failed":
        return ask("judge")
    # 판단 모델을 안 쓰면 슬롯 모델 값. 단서 없는 "절차 있음"은 믿지 않는다 (없는 절차 소요를 빼게 된다)
    if model_required is True or access is None:
        return ask("model")
    return none_needed("model")


def access_assumed(basis: str, access: dict[str, Any] | None) -> bool:
    """"절차 없음" 을 문장 단서가 아니라 모델 추정으로 정했는가. 그렇다면 결과에 알린다.

    틀렸을 때 가장 큰 피해(절차가 있는데 없다고 해서 당일 못 들어감)를 사용자가 바로 잡을 수 있게 한다.
    역 앞·식당처럼 규칙으로 정한 것까지 알리면 매번 같은 말이 붙어 소음이 된다.
    """
    return bool(access) and access.get("required") is False and basis in ("judge", "model")


# 문장을 사람별 이야기로 나누는 자리. 쉼표·마침표와 "가고 ", "오며 ", "오면서 " 뒤
_CLAUSE_SPLIT = re.compile(r"[,.!?\n;]|(?<=고)\s+|(?<=며)\s+|(?<=면서)\s+")
# "나" 로 정리된 참석자를 문장에서 찾는 말. "나가야"·"하나" 에 걸리지 않게 앞뒤가 한글이 아니어야 한다
_FIRST_PERSON = re.compile(r"(?<![가-힣])(나|저|제가|내가)(는|도|랑|가|의)?(?![가-힣])")
_HONORIFIC = re.compile(r"(씨|님|이)$")


def _mentions(clause: str, name: str) -> bool:
    if name == "나":
        return bool(_FIRST_PERSON.search(clause))
    core = _HONORIFIC.sub("", name)
    return name in clause or (len(core) >= 2 and core in clause)


def unstated_transports(text: str, people: list[dict[str, Any]]) -> list[int]:
    """이동수단을 말하지 않았는데 채워진 참석자 번호 (transport.md "말하지 않은 이동수단").

    people: [{"name", "transport", "pickup"}]. 이동수단이 비었거나 태워지는 사람은 보지 않는다.
    이름이 문장 어디에도 없으면 모른다고 보고 건드리지 않는다 (캡처 옮긴 글 등).
    """
    words = load_rule("transport")["transport_words"]
    clauses = [c for c in _CLAUSE_SPLIT.split(text or "") if c and c.strip()]
    out: list[int] = []
    for index, person in enumerate(people):
        if person.get("transport") is None or person.get("pickup"):
            continue
        mine = [c for c in clauses if _mentions(c, str(person.get("name") or ""))]
        if mine and not any(_has_any(c, words) for c in mine):
            out.append(index)
    return out


def candidate_score(kind: str, access_required: bool) -> int:
    """후보를 줄 세우는 점수. 클수록 앞. 대형 모델을 부르지 않는 경우에 쓴다 (SDD 5절 라우팅 small).

    절차가 있는 현장이면 절차 시작점이 먼저다 (access.md rendezvous_is_procedure_start).
    절차가 없으면 찾기 쉬운 랜드마크가 먼저다.
    """
    procedure_start = {"gate", "lobby", "hq"}
    if access_required:
        return 2 if kind in procedure_start else 1
    return 2 if kind == "landmark" else 1


def switch_outside(constraints: list[str]) -> bool:
    """도착이 어긋나 절차를 포기하고 밖에서 만나야 하는가 (access.md switch_if_delay_min).

    도착이 크게 벌어지면 먼저 온 사람이 절차 앞에서 오래 서 있게 된다. 그럴 때는 절차를 미루고
    밖 랜드마크에서 만난 뒤 같이 들어가는 편이 낫다.

    지금은 슬롯에 "몇 분 어긋났는지"가 없고 `arrival_delayed` 플래그만 있다. 그래서 플래그가 있으면
    기준을 넘었다고 본다. 분 단위가 슬롯에 들어오면 switch_if_delay_min 과 직접 비교로 바꾼다
    (SDD 11절에 남겨 둔 항목).
    """
    if "arrival_delayed" not in constraints:
        return False
    return int(load_rule("access")["switch_if_delay_min"]) > 0
