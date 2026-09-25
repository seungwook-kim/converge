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


def test_내일모레는_모레다():
    assert rules.parse_meet_date("내일모레 7시", TODAY) == date(2026, 9, 24)
    assert rules.parse_meet_date("낼모레", TODAY) == date(2026, 9, 24)


def test_오늘인데_시각이_지났으면_되묻는다():
    now = datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc)  # 한국 14:00
    assert rules.meet_time_passed(TODAY, "12:00", TODAY, now) is True
    assert rules.meet_time_passed(TODAY, "19:00", TODAY, now) is False
    assert rules.meet_time_passed(date(2026, 9, 23), "12:00", TODAY, now) is False
    assert rules.meet_time_passed(TODAY, None, TODAY, now) is False


# ── 첫차·막차 (schedule.md 야간, SDD 5절 7단계) ─────────────────────────────


def test_지하철_탑승_구간과_탑승_시각을_뽑는다():
    legs = [
        {"mode": "WALK", "route": None, "from": "출발지", "to": "코레일사상역", "sec": 300},
        {"mode": "BUS", "route": "일반:61", "from": "코레일사상역", "to": "감전역", "sec": 600},
        {"mode": "WALK", "route": None, "from": "감전역", "to": "감전", "sec": 120},
        {"mode": "SUBWAY", "route": "부산2호선", "from": "감전", "to": "서면", "sec": 900},
        {"mode": "SUBWAY", "route": "수도권5호선", "from": "서대문", "to": "여의나루", "sec": 600},
        {"mode": "WALK", "route": None, "from": "서면", "to": "도착지", "sec": 60},
    ]
    boardings = rules.subway_boardings(legs, "00:05")
    # 앞 구간 17분(300+600+120초) 뒤에 탄다
    assert boardings[0] == {"city": "busan", "line": "2", "station": "감전", "board_min": 22}
    assert boardings[1] == {"city": "seoul", "line": "5", "station": "서대문", "board_min": 37}


def test_조회할_수_없는_노선은_뺀다():
    legs = [
        {"mode": "SUBWAY", "route": "수도권경의중앙선", "from": "공덕", "to": "서울", "sec": 600},
        {"mode": "SUBWAY", "route": "부산김해경전철", "from": "사상", "to": "김해", "sec": 600},
        {"mode": "SUBWAY", "route": None, "from": "a", "to": "b", "sec": 60},
    ]
    assert rules.subway_boardings(legs, "23:00") == []
    assert rules.subway_boardings(None, "23:00") == []


def test_요일을_시각표_구분으로_바꾼다():
    assert rules.day_type(date(2026, 9, 22)) == "weekday"  # 화
    assert rules.day_type(date(2026, 9, 26)) == "sat"
    assert rules.day_type(date(2026, 9, 27)) == "holiday"  # 일요일은 휴일 시각표
    assert rules.day_type(None) == "weekday"


def test_막차가_끊긴_시간인지_본다():
    # 막차가 자정을 넘겨 24:10 으로 온다
    assert rules.train_missed(5, "05:30", "24:10") is False  # 00:05 는 전날 막차 전
    assert rules.train_missed(30, "05:30", "24:10") is True  # 00:30 은 끊겼다
    assert rules.train_missed(3 * 60, "05:30", "24:10") is True
    assert rules.train_missed(5 * 60 + 40, "05:30", "24:10") is False  # 첫차 뒤
    assert rules.train_missed(23 * 60, "05:30", "24:10") is False
    assert rules.train_missed(23 * 60 + 50, "05:30", "23:40") is True
    # 탑승이 자정을 넘겨 1440 이상으로 와도 같은 답
    assert rules.train_missed(1440 + 30, "05:30", "24:10") is True


def test_24시를_넘긴_시각을_시계_표기로_바꾼다():
    assert rules.clock("24:10") == "00:10"
    assert rules.clock("23:40") == "23:40"


# ── 출입 절차 판정 보정 (access.md, 09-23) ─────────────────────────────────
# 모델이 같은 문장에 절차 있음·없음·모름을 오간다. 문장의 단서로 최종값을 정한다.


def _settle(text, destination=None, purpose=None, access=None, missing=None, followup=False, judge=None):
    access, missing, _basis = rules.settle_access(text, destination, purpose, access, list(missing or []), followup, judge)
    return access, missing


def test_열린_장소면_절차_없음으로_정한다():
    # 모델이 모름(null)으로 두고 되묻던 것들 (09-23 측정: 식당 회식 3/3, 역 앞 저녁 3/3)
    for text, dest in [
        ("금요일 7시 강남역 근처 고깃집에서 회식", "강남역 근처 고깃집"),
        ("금요일 오후 6시 잠실역 앞에서 저녁 약속", "잠실역 앞"),
        ("토요일 11시 광화문 교보문고 앞에서 보자", "광화문 교보문고 앞"),
        ("일요일 오후 3시 여의도 한강공원 피크닉", "여의도 한강공원"),
        ("토요일 오후 2시 강남역 근처에서 봅시다", "강남역 근처"),
    ]:
        access, missing = _settle(text, dest, None, None, ["access.required"])
        assert access == {"required": False, "applied": None, "lead_min": None}, dest
        assert missing == [], dest


def test_닫힌_장소인데_단서가_없으면_되묻는다():
    # 모델이 절차 있음으로 단정하던 것 (09-23 측정: eval3 2/3)
    for dest in ["여의도 사무실", "판교 본사", "서울대병원", "평택 공장", "여의도역 근처 사무실"]:
        access, missing = _settle(f"수요일 3시 {dest}에서 미팅", dest, "미팅", {"required": True, "applied": None}, [])
        assert access is None, dest
        assert missing == ["access.required"], dest


def test_끝말이_장소의_종류를_정한다():
    # 사무실 앞에서 만나면 밖이다. 역 근처 사무실이면 안이다
    assert _settle("판교 본사 앞에서 보자", "판교 본사 앞")[0]["required"] is False
    assert _settle("회사 근처 카페", "회사 근처 카페")[0]["required"] is False
    assert _settle("여의도역 근처 사무실", "여의도역 근처 사무실")[0] is None


def test_절차_단어가_있으면_절차_있음이다():
    access, missing = _settle("1층에서 방문자 등록을 해야 합니다", "구청", "민원 상담", None, ["access.required"])
    assert access == {"required": True, "applied": None, "lead_min": None}
    assert missing == ["access.applied"]
    # 모델이 신청 여부를 읽었으면 그대로 둔다
    access, missing = _settle("방문자 등록은 해 뒀습니다", "창원 사무소", None, {"required": True, "applied": True}, [])
    assert access["applied"] is True and missing == []
    # 띄어쓰기가 달라도 잡는다
    assert _settle("방문자등록 필수래", "공장")[0]["required"] is True


def test_절차가_없다고_말하면_장소와_상관없이_없음이다():
    access, missing = _settle("을지로 사무실 방문. 따로 출입 절차는 없어요", "을지로 사무실", None, None, ["access.required"])
    assert access["required"] is False and missing == []
    # "출입증 필요 없어요" 는 절차 단어가 들어 있어도 없음이다
    assert _settle("출입증 필요 없어요", "사무실")[0]["required"] is False


def test_장소를_모르면_일상_약속만_절차_없음으로_본다():
    assert _settle("성수동에서 저녁 모임", "성수동", "저녁 모임")[0]["required"] is False
    # 일상 약속도 아니고 장소도 모르면 모델 값을 따른다. 단 단서 없는 절차 있음은 믿지 않는다
    assert _settle("성수동에서 만나", "성수동", "만남", {"required": False, "applied": None}, [])[0]["required"] is False
    access, missing = _settle("성수동에서 만나", "성수동", "만남", {"required": True, "applied": None}, [])
    assert access is None and missing == ["access.required"]


def test_되물은_뒤의_답은_모델을_믿는다():
    # "출입 절차가 있나요?" 에 "아니요" 라고 답했다. 사무실이라고 다시 모름으로 돌리면 무한히 되묻는다
    access, missing = _settle("아니요", "여의도 사무실", "미팅", {"required": False, "applied": None}, [], followup=True)
    assert access["required"] is False and missing == []
    # 되물은 뒤라도 절차 단어가 오면 절차 있음이다
    access, _ = _settle("네 방문자 등록 해야 돼요", "여의도 사무실", "미팅", None, ["access.required"], followup=True)
    assert access["required"] is True


def test_다른_것이_필요_없다는_말은_절차_없음이_아니다():
    # "필요 없" 만 보면 차·짐 이야기에도 걸린다. 절차 명사가 붙은 경우만 본다
    access, missing = _settle("여의도 사무실 미팅. 차는 필요 없어요", "여의도 사무실", "미팅", None, ["access.required"])
    assert access is None and missing == ["access.required"]



# ── 남은 구간을 판단 모델(Jev)에 물을 때의 안전장치 (09-23) ──────────────────
# 틀렸을 때 피해: 절차가 있는데 없다고 하면 당일 못 들어간다(가장 큼). 없는데 있다고 하면 15분을 헛되이 뺀다.
# 그래서 판단 모델은 "없음" 만 높은 확률로 받아들이고, "있음" 은 만들지 못하게 한다.


def _basis(text, destination=None, purpose=None, access=None, followup=False, judge=None):
    return rules.settle_access(text, destination, purpose, access, [], followup, judge)[2]


def _judge(choice, p_none, confidence=0.9):
    return {"choice": choice, "p_none": p_none, "confidence": confidence}


def test_규칙이_정한_것은_판단_모델을_보지_않는다():
    assert _basis("잠실역 앞 저녁", "잠실역 앞") == "open_place"
    assert _basis("여의도 사무실 미팅", "여의도 사무실") == "closed_place"
    assert _basis("방문자 등록 해야 해요", "구청") == "cue"
    assert _basis("출입 절차 없어요", "사무실") == "stated_none"
    assert _basis("성수동 저녁 모임", "성수동", "저녁 모임") == "casual"
    assert _basis("아니요", "사무실", "미팅", {"required": False, "applied": None}, followup=True) == "followup"
    # 판단 모델 값이 와도 규칙이 먼저다
    access, _ = _settle("여의도 사무실 미팅", "여의도 사무실", judge=_judge("none", 0.99))
    assert access is None


def test_남은_구간은_판단_모델이_확실할_때만_절차_없음이다():
    open_case = dict(text="성수동에서 만나", destination="성수동", purpose="만남")
    assert _basis(**open_case) == "model"  # 판단 모델을 부를 자리
    access, missing = _settle(**open_case, access=None, missing=["access.required"], judge=_judge("none", 0.95))
    assert access["required"] is False and missing == []
    assert _basis(**open_case, judge=_judge("none", 0.95)) == "judge"
    # 확률이 기준에 못 미치면 되묻는다
    access, missing = _settle(**open_case, access=None, judge=_judge("none", 0.7))
    assert access is None and missing == ["access.required"]


def test_판단_모델은_절차_있음을_만들지_못한다():
    access, missing = _settle("성수동에서 만나", "성수동", "만남", access=None, judge=_judge("required", 0.02))
    assert access is None and missing == ["access.required"]


def test_슬롯_모델과_판단_모델이_엇갈리면_되묻는다():
    access, _ = _settle("성수동에서 만나", "성수동", "만남",
                        access={"required": True, "applied": None}, judge=_judge("none", 0.95))
    assert access is None


def test_판단_모델이_실패하면_되묻는다():
    # 장애가 오답으로 새지 않게 한다. 슬롯 모델이 없음이라 해도 확인 없이 믿지 않는다
    access, missing = _settle("성수동에서 만나", "성수동", "만남",
                              access={"required": False, "applied": None}, judge="failed")
    assert access is None and missing == ["access.required"]


def test_판단_모델을_안_쓰면_지금처럼_슬롯_모델을_따른다():
    access, _ = _settle("성수동에서 만나", "성수동", "만남", access={"required": False, "applied": None}, judge=None)
    assert access["required"] is False
    assert _basis("성수동에서 만나", "성수동", "만남", access={"required": False, "applied": None}) == "model"


def test_추정으로_절차_없음을_정했으면_알린다():
    assert rules.access_assumed("judge", {"required": False}) is True
    assert rules.access_assumed("model", {"required": False}) is True
    assert rules.access_assumed("open_place", {"required": False}) is False  # 역 앞 저녁까지 알리면 소음이다
    assert rules.access_assumed("stated_none", {"required": False}) is False  # 본인이 없다고 말했다
    assert rules.access_assumed("judge", None) is False


def test_새_문장에서_드러난_장소_빈틈():
    # 09-23 새 문장 측정: 모델이 지어내거나 규칙이 잘못 가른 것
    assert _settle("화물터미널 사무동 미팅", "인천공항 화물터미널 사무동", access={"required": True, "applied": None})[0] is None
    assert _settle("성남 시청 민원실", "성남 시청 민원실", access={"required": True, "applied": None})[0] is None
    assert _settle("세종 정부청사 방문", "세종 정부청사")[0] is None
    assert _settle("본사 로비에서 봬요", "여의도 본사 로비")[0] is None
    assert _settle("연남동 파스타집 예약", "연남동 파스타집")[0]["required"] is False
    assert _settle("망원시장 입구에서 보자", "망원시장 입구")[0]["required"] is False


def test_남이_해_주기로_했거나_앞으로_할_신청은_끝난_것이_아니다():
    # 모델이 "인사팀이 해준다고 했어" 를 신청 완료로 읽었다(09-23 측정 2/3). 끝났다고 믿으면 후보 판단이 틀어진다
    for text in ["출입 신청은 인사팀이 해준다고 했어", "방문자 등록은 담당자가 대신 하기로 했어요", "출입증은 내일 신청할 예정"]:
        access, missing = _settle(text, "판교 사옥", access={"required": True, "applied": True})
        assert access == {"required": True, "applied": None, "lead_min": None}, text
        assert missing == ["access.applied"], text
    # 끝났다고 말했으면 그대로
    access, _ = _settle("정문에서 방문증 받아야 하고 사전 등록은 끝났어요", "화성 공장", access={"required": True, "applied": True})
    assert access["applied"] is True


def test_아직_안_했다는_말은_신청_안_함이다():
    # gpt-4o-mini 가 "아직 안 했어요" 를 신청 여부 모름(None)으로 뒀다 (09-23 측정)
    for text in ["로비 보안데스크에서 출입 등록해야 하는데 아직 안 했어요", "방문자 등록 아직 못 했어", "출입 신청 안했어요"]:
        access, missing = _settle(text, "여의도 본사 로비", access={"required": True, "applied": None})
        assert access == {"required": True, "applied": False, "lead_min": None}, text
        assert missing == [], text
    # "했어요" 만 있으면 건드리지 않는다
    assert _settle("방문자 등록 했어요", "본사", access={"required": True, "applied": True})[0]["applied"] is True


# ── 말하지 않은 이동수단 (transport.md transport_words, 09-23) ──────────────────
# gpt-4o-mini 가 "한지훈씨는 인천에서 옵니다" 에 지하철을 지어냈다(3회 중 1회). 차인지 대중교통인지로
# 출발 시각이 30분 넘게 갈리므로, 그 사람 이야기에 이동수단 말이 없으면 비우고 되묻는다.


def test_이동수단을_말하지_않은_사람을_찾는다():
    text = "금요일 오후 6시 잠실역 앞에서 저녁 약속. 저는 강동구에서 지하철로 가고 한지훈씨는 인천에서 옵니다."
    people = [{"name": "나", "transport": "transit", "pickup": None}, {"name": "한지훈씨", "transport": "transit", "pickup": None}]
    assert rules.unstated_transports(text, people) == [1]


def test_이동수단을_말했으면_건드리지_않는다():
    cases = [
        ("민수는 인천시청에서 차로, 지호는 의정부시청에서 지하철로 와. 나는 수원시청에서 지하철.",
         [("민수", "car"), ("지호", "transit"), ("나", "transit")]),
        ("토요일 6시 홍대입구역 앞 저녁. 나 마포구 지하철, 지훈이 부천 차.", [("나", "transit"), ("지훈이", "car")]),
        ("박과장님이 서초구에서 차로 오고, 최대리님은 관악구에서 지하철로 옵니다.", [("박과장님", "car"), ("최대리님", "transit")]),
        ("저는 분당에서 신분당선 타고 가요", [("나", "transit")]),
        ("나 성수에서 걸어서 갈게", [("나", "walk")]),
    ]
    for text, pairs in cases:
        people = [{"name": n, "transport": t, "pickup": None} for n, t in pairs]
        assert rules.unstated_transports(text, people) == [], text


def test_태워지는_사람과_이미_빈_사람은_보지_않는다():
    text = "이대리님이 차 가지고 노원구에서 오면서 광진구 역 앞에서 저를 태우고 갑니다."
    people = [{"name": "이대리님", "transport": "car", "pickup": None},
              {"name": "나", "transport": "car", "pickup": "이대리님"}]
    assert rules.unstated_transports(text, people) == []
    assert rules.unstated_transports("민지는 신촌에서 와", [{"name": "민지", "transport": None, "pickup": None}]) == []


def test_이름이_문장에_없으면_판단하지_않는다():
    # 캡처를 옮긴 글처럼 이름이 다른 모양으로 나오면 모른다. 모르면 건드리지 않는다
    assert rules.unstated_transports("다들 지하철로 와", [{"name": "민수", "transport": "transit", "pickup": None}]) == []


def test_가게_지점은_열린_장소다():
    # gpt-4o-mini + v10 측정에서 "○○ 강남점" 을 모름으로 되물었다 (09-23)
    assert _settle("토요일 12시 스타벅스 강남점에서 만나", "스타벅스 강남점")[0]["required"] is False
    assert _settle("신촌 매장 앞", "신촌 매장")[0]["required"] is False
    # 끝말이 닫힌 장소면 그대로 되묻는다
    assert _settle("강남점 사무실", "강남점 사무실")[0] is None
