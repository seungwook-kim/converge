"""규칙 적용 계산 (SDD 5절 5·7단계). 규칙값은 skills/converge/rules/ 에서 읽는다."""
from __future__ import annotations

from datetime import date, datetime, timezone

from backend.app.domain import rules

# 2026-09-22 는 화요일이다
TODAY = date(2026, 9, 22)


def test_날짜_표현을_날짜로_바꾼다():
    assert rules.parse_meet_date("2026-10-03 12:00", TODAY) == date(2026, 10, 3)
    assert rules.parse_meet_date("10월 3일 저녁 7시", TODAY) == date(2026, 10, 3)
    assert rules.parse_meet_date("10/3 08:00", TODAY) == date(2026, 10, 3)
    assert rules.parse_meet_date("오늘 22:00", TODAY) == TODAY
    assert rules.parse_meet_date("내일 저녁 7시", TODAY) == date(2026, 9, 23)
    assert rules.parse_meet_date("모레", TODAY) == date(2026, 9, 24)
    assert rules.parse_meet_date("3일 뒤", TODAY) == date(2026, 9, 25)
    assert rules.parse_meet_date("30일 12시", TODAY) == date(2026, 9, 30)


def test_연도_없는_날짜가_지났으면_다음으로_넘긴다():
    assert rules.parse_meet_date("9월 1일", TODAY) == date(2027, 9, 1)
    assert rules.parse_meet_date("5일", TODAY) == date(2026, 10, 5)


def test_요일은_가장_가까운_그날로_읽는다():
    assert rules.parse_meet_date("목요일 08:00", TODAY) == date(2026, 9, 24)
    assert rules.parse_meet_date("화요일", TODAY) == TODAY  # 오늘이 화요일이면 오늘
    assert rules.parse_meet_date("월요일", TODAY) == date(2026, 9, 28)
    assert rules.parse_meet_date("다음주 목요일", TODAY) == date(2026, 10, 1)
    assert rules.parse_meet_date("이번주 월요일", TODAY) == date(2026, 9, 21)  # 지났어도 그대로. 1-3 이 되묻는다


def test_날짜가_없으면_None():
    assert rules.parse_meet_date("저녁 7시", TODAY) is None
    assert rules.parse_meet_date("언젠가", TODAY) is None
    assert rules.parse_meet_date(None, TODAY) is None
    assert rules.parse_meet_date("2월 30일", TODAY) is None


def test_등록_범위를_벗어나면_되묻는다():
    within = rules.load_rule("session")["register_within_days"]
    assert rules.meet_window_problem(TODAY, TODAY) is None
    assert rules.meet_window_problem(date(2026, 9, 21), TODAY) is not None
    assert rules.meet_window_problem(date.fromordinal(TODAY.toordinal() + within), TODAY) is None
    assert f"{within}일" in rules.meet_window_problem(date.fromordinal(TODAY.toordinal() + within + 1), TODAY)


def test_오늘은_서버_UTC_가_아니라_규칙의_시간대로_정한다():
    # UTC 9월 21일 20시 = 한국 9월 22일 05시
    assert rules.today_local(datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)) == TODAY


def test_저장용_약속_시각은_규칙의_시간대로_만든다():
    at = rules.meet_at_local(date(2026, 10, 3), "08:00")
    assert at.astimezone(timezone.utc) == datetime(2026, 10, 2, 23, 0, tzinfo=timezone.utc)
    assert rules.meet_at_local(date(2026, 10, 3), None).hour == 0


def test_시각_표현을_HHMM_으로_바꾼다():
    assert rules.parse_meet_time("목요일 08:00") == "08:00"
    assert rules.parse_meet_time("목요일 아침 8시") == "08:00"
    assert rules.parse_meet_time("오후 2시") == "14:00"
    assert rules.parse_meet_time("내일 저녁 7시 30분") == "19:30"
    assert rules.parse_meet_time("언젠가") is None
    assert rules.parse_meet_time(None) is None


def test_절차가_있는_방문만_절차_소요를_뺀다():
    """일반 약속은 들어가는 데 걸리는 시간이 없다. 빼 두면 괜히 일찍 나가게 된다."""
    access = rules.load_rule("access")
    transport = rules.load_rule("transport")
    assert rules.lead_min("meeting") == 0
    assert rules.lead_min("visit") == access["entry_lead_min"]
    assert rules.buffer_min("meeting") == transport["buffer_meeting_min"]
    assert rules.buffer_min("visit") == transport["buffer_visit_min"]


def test_자동차는_정체분_대중교통은_환승만_얹는다():
    assert rules.traffic_extra_min(40, "car", None) == 10  # 15% 는 6분이라 최소 10분
    assert rules.traffic_extra_min(120, "car", None) == 18
    assert rules.traffic_extra_min(40, "transit", 0) == 0
    assert rules.traffic_extra_min(40, "transit", 2) == 10


def test_후보는_신청_전이어도_갈_수_있다():
    """후보는 전부 건물 밖이거나 절차가 시작되는 자리다. 거기까지는 신청 전에도 간다."""
    assert rules.access_ok("gate", None) is True
    assert rules.access_ok("lobby", False) is True
    assert rules.access_ok("landmark", True) is True


def test_절차가_있으면_절차_시작점이_앞선다():
    assert rules.candidate_score("gate", True) > rules.candidate_score("landmark", True)
    assert rules.candidate_score("landmark", False) > rules.candidate_score("gate", False)


def test_도착이_어긋나면_밖으로_전환한다():
    assert rules.switch_outside([]) is False
    assert rules.switch_outside(["port_changed"]) is False
    assert rules.switch_outside(["arrival_delayed"]) is True


def test_출발_시각은_도착_기한에서_거꾸로_뺀다():
    out = rules.calc_departure("08:00", 40 * 60, 20, 20)
    assert out == {"depart_at": "06:40", "arrive_by_adjusted": "07:40", "day_offset": 0}


def test_시각이_아니라고_말한_경우에만_잠정이다():
    """언급이 없으면 확정으로 본다. 아니면 거의 모든 결과에 잠정 딱지가 붙는다."""
    assert rules.is_provisional(False) is True
    assert rules.is_provisional(True) is False
    assert rules.is_provisional(None) is False


def test_야간은_자정을_넘는_구간이다():
    """22:00~06:00 처럼 구간이 날짜를 넘는다 (schedule.md)."""
    schedule = rules.load_rule("schedule")
    assert rules.is_night(schedule["night_start"]) is True
    assert rules.is_night("23:30") is True
    assert rules.is_night("02:00") is True
    assert rules.is_night("14:00") is False
    assert rules.is_night(None) is False


def test_절차가_없으면_프리셋과_무관하게_0분():
    """preset 이 visit 이어도 절차가 없다고 확인됐으면 뺄 시간이 없다."""
    entry = rules.load_rule("access")["entry_lead_min"]
    assert rules.lead_min("visit", True) == entry
    assert rules.lead_min("visit", False) == 0
    assert rules.lead_min("visit", None) == entry   # 아직 모르면 있다고 보고 잡아 둔다
    assert rules.lead_min("meeting", None) == 0
