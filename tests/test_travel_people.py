"""출장증빙 — 출장신청서 검토 · 출장자 정리 · 출장자별 증빙 확인 · 네이버 지도 최단거리(담당자 2026-11-10, CLAUDE.md 28절).

신청서 · 증빙 · 지도는 가짜를 코드로 만든다(실명 · 실제 영수증은 저장소에 두지 않는다 — 10절). 네이버 지도는 실제 Chromium 에서
map.naver.com 요청을 가로채 모의 화면 · 모의 검색 결과로 답한다(이 환경은 네이버에 닿지 않는다).
"""
from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from claim_downloader.travel import application, model, navermap
from claim_downloader.travel.model import Evidence, Trip

LABELED = """국내 출장 신청서
출장자 연구원 홍길동, 연구원 김철수
출 장 기 간 2026. 11. 10.(화) 09:00 ~ 2026. 11. 12.(목) 18:00
출장지 원주
출장목적 공동 교육과정 운영 협의
결재 기안자 이몽룡 단장 성춘향
"""

TABLE = """출장 계획서
소속 직급 성명
데이터보안활용혁신융합대학사업단 연구원 홍길동
데이터보안활용혁신융합대학사업단 학생 김철수
일시 2026-11-10 ~ 11-12
목적지 연세대학교 원주캠퍼스
기안 연구원 이몽룡
"""


# ── 출장신청서 읽기 ───────────────────────────────────────────────────
def test_reads_labeled_application_and_skips_approvers():
    app = application.parse_text(LABELED)
    assert app.travelers == ["홍길동", "김철수"]                 # 결재 줄의 이몽룡 · 성춘향은 출장자가 아니다
    assert (app.start, app.end) == (date(2026, 11, 10), date(2026, 11, 12))
    assert app.places == ["원주"] and app.purpose == "공동 교육과정 운영 협의"
    assert app.found[:3] == ["출장자", "출장기간", "출장지"] and not app.notes
    assert "지역 이름뿐" in application.vague_place("원주")     # 시 이름뿐 — 길찾기에 쓸 곳이 아니다


def test_reads_table_shaped_application():
    app = application.parse_text(TABLE)
    assert app.travelers == ["홍길동", "김철수"]
    assert (app.start, app.end) == (date(2026, 11, 10), date(2026, 11, 12))     # 끝 날에 해가 없는 꼴
    assert app.places == ["연세대학교 원주캠퍼스"] and application.vague_place(app.places[0]) == ""


def test_application_notes_what_it_could_not_read():
    app = application.parse_text("출장자 홍길동 외 2명\n출장지 관외\n")
    assert app.travelers == ["홍길동"] and app.expected == 3
    assert any("3명으로 적혀" in n for n in app.notes) and any("출장기간을 찾지" in n for n in app.notes)
    assert "여러 곳을 묶은" in application.vague_place("관외")
    assert application.vague_place("") and application.vague_place("강원도 원주시")
    assert application.vague_place("삼척 쏠비치") == "" and application.vague_place("서울 일원")
    assert application.parse_period("2026.11.30 ~ 12.2") == (date(2026, 11, 30), date(2026, 12, 2))
    assert application.parse_period("2026년 12월 30일 ~ 1월 2일") == (date(2026, 12, 30), date(2027, 1, 2))


def test_find_and_read_files(tmp_path):
    (tmp_path / "증빙").mkdir()
    for name in ("국내 출장신청서(1110).txt", "국내 출장신청서(1110).hwp", "홍길동 출장증빙_26.11.10.pdf", "홍길동_체류증빙.png"):
        (tmp_path / name).write_text(LABELED, encoding="utf-8")
    found = application.find(tmp_path)
    assert [p.name for p in found] == ["국내 출장신청서(1110).txt", "국내 출장신청서(1110).hwp"]    # 읽을 수 있는 것 먼저 · 출장증빙은 뺌
    assert "읽지 못합니다" in application.read(found[1]).notes[0]
    merged = application.merge([application.read(p) for p in found])
    assert merged.travelers == ["홍길동", "김철수"] and merged.destination == "원주"
    assert "출장자 2명" in application.log_line(merged, found) and "홍길동" not in application.log_line(merged, found)


def test_reads_hwpx(tmp_path):
    path = tmp_path / "출장신청서.hwpx"
    body = "".join(f"<hp:p><hp:run><hp:t>{line}</hp:t></hp:run></hp:p>" for line in LABELED.splitlines())
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("Contents/section0.xml", f'<hs:sec xmlns:hp="x" xmlns:hs="y">{body}</hs:sec>')
    app = application.read(path)
    assert app.travelers == ["홍길동", "김철수"] and app.start == date(2026, 11, 10)


# 출장이 둘 적힌 신청서 — 양식이 출장마다 되풀이되는 꼴(담당자 2026-11-10 "출장신청서에 출장이 1건 이상이 있을 수 있는데")
TWO_FORMS = """국내 출장 신청서
출장자 연구원 홍길동
출장기간 2026. 11. 3.(화) ~ 2026. 11. 4.(수)
출장지 삼척 쏠비치
출장목적 워크숍
국내 출장 신청서
출장자 연구원 홍길동, 연구원 김철수
출장기간 2026. 11. 10.(화) ~ 2026. 11. 12.(목)
출장지 연세대학교 원주캠퍼스
출장목적 공동 교육과정 협의
결재 기안자 이몽룡
"""

# 표에 출장이 줄마다 적힌 꼴
TWO_ROWS = """출장 계획서
출장자 연구원 홍길동
연번 출장기간 출장지 목적
1 2026.11.03 ~ 11.04 삼척 쏠비치
2 2026.11.10 ~ 11.12 연세대학교 원주캠퍼스
기안 연구원 이몽룡
"""


@pytest.mark.parametrize("text", [
    # 공문식 — 가. 나. 다. 번호(2026-11-10 실제 신청서에서 기간 · 출장지를 못 읽음)
    "국내 출장 신청서\n가. 출 장 자: 연구원 홍길동\n나. 출장기간: 2026. 11. 10.(화) ~ 11. 12.(목) [3일간]\n다. 출 장 지: 연세대학교 원주캠퍼스\n라. 출장목적: 협의",
    # 칸 이름이 먼저 다 나오고 값이 아래에 차례로(표를 PDF 로 저장하면 이렇게 읽히기도 한다)
    "출장신청서\n출장자\n출장기간\n출장지\n출장목적\n연구원 홍길동\n2026. 11. 10. ~ 2026. 11. 12.\n연세대학교 원주캠퍼스\n협의",
    # 한 줄 머리 + 값 줄 · 해 없는 기간(신청일의 해로)
    "출장신청서 신청일 2026. 11. 3.\n출장자 연구원 홍길동\n출장기간 출장지\n11. 10.(화) ~ 11. 12.(목)\n출장지 연세대학교 원주캠퍼스",
    # 숫자를 한 글자씩 띄운 PDF · 날짜가 두 줄에 · '부터'
    "출 장 기 간\n2 0 2 6 . 1 1 . 1 0 . 09:00 부터\n2 0 2 6 . 1 1 . 1 2 . 18:00 까지\n출 장 지 연세대학교 원주캠퍼스\n출장자 연구원 홍길동",
])
def test_application_reads_period_and_place_in_other_layouts(text):
    app = application.parse_text(text)
    assert (app.start, app.end) == (date(2026, 11, 10), date(2026, 11, 12)), application.shape(text)
    assert app.places == ["연세대학교 원주캠퍼스"]
    assert app.travelers == ["홍길동"]


# 실제 신청서(2026-11-10 담당자가 보낸 PDF — 한글에서 PDF 로 저장한 내부결재 공문)를 pypdf 로 읽은 줄 차례를 그대로 본뜬 것. 이름 · 곳 · 메일은 바꿨다.
GONGMUN = """『실사구시(實事求是)』
가나대학교
HRHFB261020UF0000000642231001101
수신 내부결재
결
재
비전임산
학협력중
점교수
데이터보안·
활용혁신융
합대학사업
부단장
(경유)
 2026.10.20.
부서명 데이터보안 ·활용혁신융합대학사업단
국내 출장신청서
  끝.
협조자
시행 데이터보안 ·활용혁신융합대학사업단-3699 ( ) 접수 ( )
우 24341 강원특별자치도 춘천시 효자동 가나대학길 1 (효자동) / www.example.ac.kr
전화번호 팩스번호 / someone@example.com / 공개
하나 된 가나대, 청렴으로 여는 고등교육의 미래
다음과 같이 출장을 명함
소속 직급 성명 출장내용 출장기간 출장지
여비지급
대상여부
데이터보안·활
용혁신융합대학
사업단
비전임산학협력
중점교수 홍길동
비교과 교육과정 운
영을 위한 합성데이
터 제공 협의
2026.10.20. (화) 09:00 가나다라정보
활용지원센터
(원주)
예~
2026.10.20. (화) 18:00
출장목적 업무회의
이동사항 및
출장비고
출장추가비고
회계구분 지급기관
연구비
지급
공용차량
이용
"""


def test_reads_real_gongmun_table_layout():
    """담당자 2026-11-10 "여기 PDF파일을 읽으면 되는데 뭐가 문제인가요" — 표 칸이 칸마다 줄을 바꿔 나와, 출장지가 기간 줄들 사이에 끼고
    '예'(여비지급 대상여부)가 '~' 에 붙어 나온다. 시작 · 끝 날짜가 네 줄 떨어져 있다."""
    app = application.parse_text(GONGMUN)
    assert app.travelers == ["홍길동"]
    assert (app.start, app.end) == (date(2026, 10, 20), date(2026, 10, 20))
    assert app.places == ["가나다라정보활용지원센터 (원주)"] and application.vague_place(app.places[0]) == ""
    assert app.purpose == "업무회의" and not app.notes


def test_naver_search_queries_drop_parentheses():
    assert navermap.search_queries("가나다라정보활용지원센터 (원주)") == [
        "가나다라정보활용지원센터 (원주)", "가나다라정보활용지원센터", "원주 가나다라정보활용지원센터"]
    assert navermap.search_queries("연세대학교 원주캠퍼스") == ["연세대학교 원주캠퍼스"]


def test_shape_hides_names_and_places_but_keeps_labels_and_dates():
    lines = application.shape("가. 출 장 자: 연구원 홍길동\n나. 출장기간: 2026. 11. 10.(화) ~ 11. 12.(목)\n다. 출장지: 연세대학교 원주캠퍼스\n"
                              "연락처 01012345678")
    text = "\n".join(lines)
    assert "홍길동" not in text and "연세대학교" not in text and "01012345678" not in text
    assert "출장기간" in text and "2026. 11. 10.(화) ~ 11. 12.(목)" in text and "연구원" in text and "□□□" in text


def test_application_with_several_trips_picks_by_folder_date():
    """담당자 2026-11-10 "그럴땐 저장폴더명에 있는 날짜를 기준으로 출장증빙 생성"."""
    app = application.parse_text(TWO_FORMS)
    assert [t.label() for t in app.trips] == ["2026-11-03 ~ 11-04 · 삼척 쏠비치", "2026-11-10 ~ 11-12 · 연세대학교 원주캠퍼스"]
    assert app.trips[1].travelers == ["홍길동", "김철수"] and app.everyone == ["홍길동", "김철수"]
    chosen = application.select(app, Path("출장비 지급(26.11.10. 원주)"))
    assert chosen.chosen == 1 and (chosen.start, chosen.end) == (date(2026, 11, 10), date(2026, 11, 12))
    assert chosen.places == ["연세대학교 원주캠퍼스"] and chosen.travelers == ["홍길동", "김철수"] and chosen.purpose == "공동 교육과정 협의"
    assert "폴더 이름" in chosen.notes[0] and "2026-11-10" in chosen.notes[0]
    again = application.select(application.parse_text(TWO_FORMS), Path("26.11.04 삼척"))     # 기간 안의 날짜
    assert again.chosen == 0 and again.travelers == ["홍길동"]
    rows = application.parse_text(TWO_ROWS)
    assert [(t.start, t.places) for t in rows.trips] == [(date(2026, 11, 3), ["삼척 쏠비치"]), (date(2026, 11, 10), ["연세대학교 원주캠퍼스"])]
    assert application.select(rows, Path("2026-11-10 원주")).destination == "연세대학교 원주캠퍼스"
    blank = application.select(application.parse_text(TWO_FORMS), Path("원주 출장"))
    assert blank.chosen == 0 and "폴더 이름에 날짜가 없어" in blank.notes[0]
    far = application.select(application.parse_text(TWO_FORMS), Path("출장비(26.11.09.)"))
    assert far.chosen == 1 and "가장 가까운" in far.notes[0]
    single = application.select(application.parse_text(LABELED), Path("26.12.01"))       # 하나면 그대로
    assert single.start == date(2026, 11, 10) and len(single.trips) == 1
    assert "신청서의 출장 2건 중 2번째" in application.log_line(chosen, [Path("a.pdf")])


def test_folder_date_forms():
    assert application.folder_date("출장비 지급(26.05.28. 삼척)", 2026) == date(2026, 5, 28)
    assert application.folder_date("26.08.26-30. 학회", 2026) == date(2026, 8, 26)
    assert application.folder_date("2026-11-10 원주", 2025) == date(2026, 11, 10)
    assert application.folder_date("1110 원주", 2026) == date(2026, 11, 10)
    assert application.folder_date("11월 10일 원주", 2026) == date(2026, 11, 10)
    assert application.folder_date("원주 출장", 2026) is None


def test_merge_files_for_different_trips_keeps_both():
    """출장마다 신청서 파일이 따로여도 출장을 모두 모아 둔다 — 고르기는 폴더 날짜로."""
    first = application.parse_text(TWO_FORMS.split("국내 출장 신청서\n출장자 연구원 홍길동, ")[0])
    second = application.parse_text(LABELED)
    merged = application.merge([first, second])
    assert len(merged.trips) == 2 and merged.chosen == 0 and merged.start == date(2026, 11, 3)
    assert application.select(merged, Path("26.11.11")).places == ["원주"]
    same = application.merge([application.parse_text(LABELED), application.parse_text(LABELED.replace("홍길동, 연구원 김철수", "이순신"))])
    assert len(same.trips) == 1 and same.travelers == ["홍길동", "김철수", "이순신"]


# ── 출장자 · 증빙 ─────────────────────────────────────────────────────
def test_person_from_file_name_convention():
    """담당자 2026-11-10 — 파일명은 이름_체류증빙 · 이름_하이패스 증빙 · 이름_숙박비 증빙 · 이름_대중교통 증빙."""
    names = ["홍길동", "김철수"]
    assert model.person_hint(Path("홍길동_체류증빙 1110.jpg")) == "홍길동"
    assert model.person_hint(Path("체류/0528.png")) == ""
    assert model.person_of(Path("김철수_하이패스 증빙.pdf"), names) == "김철수"
    assert model.person_of(Path("증빙/홍길동/0528.png"), names) == "홍길동"
    assert model.person_of(Path("0528.png"), names) == "" and model.person_of(Path("0528.png"), ["홍길동"]) == "홍길동"
    assert model.names_in_files([Path("홍길동_체류증빙.png"), Path("김철수_숙박비 증빙.pdf"), Path("영수증.png")]) == ["홍길동", "김철수"]
    assert model.kind_of("홍길동_숙박비 증빙") == model.LODGING and model.kind_of("홍길동_대중교통 증빙") == model.PUBLIC
    assert model.split_names("홍길동, 김철수 · 이영희") == ["홍길동", "김철수", "이영희"]


def ev(name, day=None, amount=None, person="", nights=1):
    return Evidence(Path(name), day, amount, nights=nights, person=person)


def test_split_by_traveler_and_review():
    d = lambda n: date(2026, 11, n)  # noqa: E731
    trip = Trip(name="홍길동, 김철수", start=d(10), end=d(12), destination="원주",
                stay=[ev("a.png", d(10), person="홍길동"), ev("b.png", d(12), person="홍길동"), ev("c.png", d(10), person="김철수"),
                      ev("d.png", d(15), person="김철수")],
                tolls=[ev("h.png", d(10), 3100, person="홍길동")],
                lodging=[ev("l.png", d(10), 150000, person=model.SHARED, nights=3)],
                legs=[76], route_maps=[Path("map.png")], fuel="휘발유")
    names = ["홍길동", "김철수"]
    hong, kim = (model.for_traveler(trip, n, names) for n in names)
    assert [e.path.name for e in hong.stay] == ["a.png", "b.png"] and len(hong.tolls) == 1 and hong.lodging and hong.fuel == "휘발유"
    assert not kim.tolls and kim.route_maps == [] and kim.legs == [] and kim.fuel == "" and kim.lodging    # 공통 숙박은 둘 다
    review = model.review(hong)
    assert any("체류 증빙이 없는 날: 11월 11일(수)" in r for r in review)
    assert any("숙박 3박" in r for r in review)
    assert not any("자차" in r for r in review)                      # 지도 · km · 연료가 있다
    kim_review = model.review(kim)
    assert any("출장기간 밖의 날짜(11월 15일(일))" in r for r in kim_review) and any("교통비 증빙" in r for r in kim_review)
    trip.stay.append(ev("e.png", d(11)))
    trip.stay.append(ev("f.png", d(11), person="이몽룡"))
    probs = model.traveler_problems(trip, names)
    assert any("e.png: 어느 출장자" in p for p in probs) and any("'이몽룡' 는 출장자 목록에 없습니다" in p for p in probs)
    no_route = model.review(Trip(name="가", start=d(10), end=d(10), stay=[ev("a", d(10))], tolls=[ev("h", d(10), 100)]))
    assert any("최단거리 그림" in r for r in no_route) and any("km" in r for r in no_route) and any("연료" in r for r in no_route)


def test_one_map_for_a_round_trip_and_fuel_in_head():
    """담당자 2026-11-10 — 출발지와 목적지가 같으면(왕복) 지도 하나, 경유지가 있을 때만 구간마다. 자차 쪽에 연료도."""
    trip = Trip(name="가", tolls=[ev("h.png", date(2026, 11, 10), 3100)], legs=[76], route_maps=[Path("go.png")], fuel="경유")
    page = model.car_pages(trip)[0]
    assert page.head == ["* 교통비 증빙 (자차)", "연료 경유", "3,100원"]
    route = page.blocks[-1]
    assert route.title == ["* 이동경로", "출발지→도착지 76km", "도착지→출발지 76km", "총 이동경로 152km"]
    assert [p.name for p in route.images] == ["go.png"] and route.captions == []
    trip.route_stops, trip.legs = ["원주시청", "연세대학교 원주캠퍼스"], [80, 5, 79]
    trip.route_maps = [Path("1.png"), Path("2.png"), Path("3.png")]
    route = model.car_pages(trip)[0].blocks[-1]
    assert route.title == ["* 이동경로", "출발지→원주시청 80km", "원주시청→연세대학교 원주캠퍼스 5km", "연세대학교 원주캠퍼스→출발지 79km",
                           "총 이동경로 164km"]
    assert route.captions[0] == "출발지→원주시청 80km" and len(route.images) == 3


def test_scan_finds_go_and_back_maps(tmp_path):
    for name in ("홍길동_하이패스 증빙.png", "네이버지도 최단거리_가는 길.png", "네이버지도 최단거리_오는 길.png"):
        (tmp_path / name).write_bytes(b"x")
    scan = model.scan_folder(tmp_path)
    assert [p.name for p in scan.route_maps] == ["네이버지도 최단거리_가는 길.png", "네이버지도 최단거리_오는 길.png"]
    assert scan.route_map.name.endswith("가는 길.png") and [p.name for p in scan.files["toll"]] == ["홍길동_하이패스 증빙.png"]


def test_fuels_setting_round_trip(isolated_home):
    from claim_downloader import settings
    assert model.parse_fuels("홍길동=휘발유\n김철수 = 경유\n잘못된 줄\n=LPG") == {"홍길동": "휘발유", "김철수": "경유"}
    settings.update(travel_fuels=model.format_fuels({"홍길동": "휘발유"}))
    assert model.parse_fuels(settings.load().travel_fuels) == {"홍길동": "휘발유"}


# ── 네이버 지도 ───────────────────────────────────────────────────────
ROUTE_TEXT = """강원대학교 춘천캠퍼스 → 연세대학교 원주캠퍼스
1 추천 1시간 8분 79km 택시비 128,000원
2 큰길우선 1시간 7분 83km 택시비 136,500원 중앙고속도로 75km
3 무료우선 1시간 21분 76km 통행료 무료
4 거리우선 1시간 10분 76km 택시비 124,220원 중앙고속도로 52km 경강로 3km
1시간 10분"""


def test_route_km_reads_the_shortest_route():
    assert model.route_km(ROUTE_TEXT) == 76
    assert model.route_km(ROUTE_TEXT.replace("4 거리우선 1시간 10분 76km", "4 거리우선 1시간 9분 75.4km")) == 75.4
    assert model.route_km("1 추천 52분 61km\n2 큰길우선 58분 66km") == 61          # 거리우선이 없으면 가장 짧은 것
    assert model.route_km("중앙고속도로 52km") is None


def test_directions_url_uses_web_mercator():
    x, y = navermap.mercator(127.7300, 37.8700)
    assert 14_218_000 < x < 14_220_000 and 4_558_000 < y < 4_562_000
    url = navermap.directions_url(navermap.Place("강원대학교", 127.73, 37.87, "11591563"), navermap.Place("원주시청", 127.92, 37.34, ""))
    assert url.startswith("https://map.naver.com/p/directions/1421") and url.endswith("ADDRESS_POI/-/car")
    assert "PLACE_POI" in url and "%EA%B0%95" in url


MOCK_PAGE = """<!doctype html><html><body><div id="panel"></div><script>
const routes = location.pathname.includes('/-/car');
document.getElementById('panel').innerHTML = routes ? `
  <ul><li>1 <b>추천</b> 1시간 8분 79km</li><li>2 <b>큰길우선</b> 1시간 7분 83km</li>
  <li><a href="#" onclick="document.body.dataset.picked='1';return false;"><span>거리우선</span></a> 1시간 10분 76km</li></ul>` : '<input placeholder="출발지를 입력하세요">';
</script></body></html>"""


@pytest.fixture
def browser_page():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        import os
        pw = sync_api.sync_playwright().start()
        path = "/opt/pw-browsers/chromium"
        browser = pw.chromium.launch(executable_path=path if os.path.exists(path) else None)
    except Exception as exc:  # noqa: BLE001 — 브라우저가 없는 곳
        pytest.skip(str(exc))
    page = browser.new_page(viewport=navermap.VIEWPORT)
    yield page
    browser.close()
    pw.stop()


def _mock_naver(page, places: dict):
    def handle(route):
        url = route.request.url
        if "/p/api/search/allSearch" in url:
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(url).query)["query"][0]
            found = [places[query]] if query in places else []
            route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps({"result": {"place": {"list": found}}}))
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=MOCK_PAGE)
    page.route("https://map.naver.com/**", handle)


def test_find_route_in_mock_naver_map(browser_page, tmp_path, monkeypatch):
    monkeypatch.setattr(navermap, "SEARCH_POLLS", 4)
    page = browser_page
    places = {"강원대학교 춘천캠퍼스": {"id": "11591563", "name": "강원대학교 춘천캠퍼스", "x": "127.7432", "y": "37.8687"},
              "연세대학교 원주캠퍼스": {"id": "11622019", "name": "연세대학교 미래캠퍼스", "x": "127.9030", "y": "37.2777"}}
    _mock_naver(page, places)
    logs = []
    out = navermap.shot_path(tmp_path, "홍길동 가는 길(오는 길도 같은 거리)")
    result = navermap.find_route(page, "강원대학교 춘천캠퍼스", "연세대학교 원주캠퍼스", out, logs.append,
                                 wait=lambda s: page.wait_for_timeout(int(s * 300)), label="가는 길")
    assert result.ok and result.km == 76 and Path(result.image).exists() and Path(result.image).stat().st_size > 1000
    assert page.evaluate("document.body.dataset.picked") == "1"           # '거리우선' 을 눌렀다
    assert "/-/car" in page.url and "PLACE_POI" in page.url
    # 목적지가 검색되지 않으면 그 곳을 돌려준다 — 화면이 그 출장자의 출장목적지를 묻는다
    missing = navermap.find_route(page, "강원대학교 춘천캠퍼스", "원주", tmp_path / "x.png", logs.append,
                                  wait=lambda s: page.wait_for_timeout(int(s * 300)))
    assert not missing.ok and missing.need_place == "원주" and "찾지 못했습니다" in missing.note
    assert navermap.shot_path(tmp_path, "홍길동 가는 길(오는 길도 같은 거리)").name.endswith("_2.png")     # 덮어쓰지 않는다


SEARCH_PAGE = """<!doctype html><html><body><div id="list">검색 중</div><script>
const q = decodeURIComponent(location.pathname.split('/p/search/')[1] || '');
fetch('/p/api/mockgraphql?q=' + encodeURIComponent(q)).then(r => r.json()).then(j => {
  document.getElementById('list').textContent = JSON.stringify(j).length + '';
});
</script></body></html>"""


def _mock_naver_new(page, places: dict, calls: list):
    """2026-11-10 담당자 PC 처럼 검색 주소(allSearch)의 답에 곳이 없고, 지도 검색 화면은 다른 꼴(GraphQL 같은)의 답을 스스로 받는다."""
    from urllib.parse import parse_qs, urlparse

    def handle(route):
        url = route.request.url
        calls.append(urlparse(url).path)
        if "/p/api/search/allSearch" in url:
            route.fulfill(status=200, content_type="application/json; charset=utf-8",
                          body=json.dumps({"result": {"type": "place", "metaInfo": {"searchedQuery": "x"}, "place": None, "address": None}}))
        elif "/p/api/mockgraphql" in url:
            query = parse_qs(urlparse(url).query)["q"][0]
            near = {"id": "1", "name": "춘천 닭갈비 골목", "x": "127.72", "y": "37.88"}         # 이름이 다른 곳이 먼저 와도
            items = [near, places[query]] if query in places else []
            route.fulfill(status=200, content_type="application/json; charset=utf-8",
                          body=json.dumps({"data": {"businesses": {"total": len(items), "items": items}}}))
        elif "/p/search/" in url:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=SEARCH_PAGE)
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=MOCK_PAGE)
    page.route("https://map.naver.com/**", handle)


def test_find_route_reads_what_the_search_screen_receives(browser_page, tmp_path, monkeypatch):
    """담당자 2026-11-10 "목적지가 검색이 안된다고 하는데 둘다 검색이 됩니다" — 앱의 검색 주소는 '강원대학교 춘천캠퍼스' 도 비어 왔다.
    이제 답의 꼴을 짐작하지 않고, 안 되면 지도 검색 화면이 받는 답에서 이름이 맞는 곳을 읽고, 찾은 곳은 기억한다."""
    monkeypatch.setattr(navermap, "SEARCH_POLLS", 6)
    page = browser_page
    places = {"강원대학교 춘천캠퍼스": {"id": "11591476", "name": "강원대학교 춘천캠퍼스", "x": "127.7445", "y": "37.8690"},
              "강원가명정보활용지원센터 (원주)": {"id": "2008011046", "name": "강원 가명정보 활용지원센터", "x": "127.9550", "y": "37.3260"}}
    calls: list = []
    _mock_naver_new(page, places, calls)
    known: dict = {}
    logs: list = []
    wait = lambda s: page.wait_for_timeout(int(s * 300))  # noqa: E731
    result = navermap.find_route(page, "강원대학교 춘천캠퍼스", "강원가명정보활용지원센터 (원주)", tmp_path / "a.png", logs.append,
                                 wait=wait, label="가는 길", known=known)
    assert result.ok and result.km == 76, result.lines()
    assert "/p/search/" in " ".join(calls) and "PLACE_POI" in page.url and "2008011046" in page.url and "11591476" in page.url
    assert any("곳 없음" in step and "place=null" in step for step in result.steps)          # 검색 주소의 답 모양을 기록에
    assert any("강원 가명정보 활용지원센터 (이름이 같은 곳)" in step for step in result.steps)
    assert known[navermap.norm("강원가명정보활용지원센터")]["id"] == "2008011046"
    # 두 번째부터는 기억한 곳 — 검색하지 않는다
    calls.clear()
    again = navermap.find_route(page, "강원대학교 춘천캠퍼스", "강원가명정보활용지원센터 (원주)", tmp_path / "b.png", logs.append,
                                wait=wait, label="가는 길", known=known)
    assert again.ok and not any("search" in c for c in calls)
    # 출발지부터 못 찾으면 목적지를 묻지 않는다(그때 화면이 목적지를 물었다)
    lost = navermap.find_route(page, "없는 곳", "강원가명정보활용지원센터 (원주)", tmp_path / "c.png", logs.append, wait=wait, known={})
    assert not lost.ok and lost.need_place == "" and lost.note.startswith("출발지 '없는 곳'")


def test_places_in_any_shape_and_ranking():
    data = {"result": {"place": {"list": [{"id": "9", "name": "<b>강원대학교</b> 춘천캠퍼스", "x": "127.74", "y": "37.86"}]}},
            "other": [{"title": "주소", "mapx": "1279550000", "mapy": "373260000"}, {"name": "바다 위", "x": "10", "y": "10"}]}
    found = navermap.places_in(data)
    assert [(p.name, p.id) for p in found] == [("강원대학교 춘천캠퍼스", "9"), ("주소", "")] and found[1].x == pytest.approx(127.955)
    near = navermap.Place("춘천 닭갈비 골목", 127.72, 37.88, "1")
    center = navermap.Place("강원 가명정보 활용지원센터", 127.955, 37.326, "2008011046")
    assert navermap.rank("강원가명정보활용지원센터 (원주)", [near, center])[0] is center
    assert navermap.rank("아무 곳", [near, center]) == (near, "첫 결과(이름이 같은 곳 없음)")
    assert navermap.rank("아무 곳", [near, center], prefer_id="2008011046")[0] is center
    assert navermap.shape({"result": {"type": "place", "place": None}}) == "{result:{type,place=null}}"


def test_places_from_directions_url_learns_both_ends():
    start = navermap.Place("강원대학교 춘천캠퍼스", 127.7445, 37.8690, "11591476")
    goal = navermap.Place("강원 가명정보 활용지원센터", 127.955, 37.326, "2008011046")
    learned = navermap.places_from_url(navermap.directions_url(start, goal) + "?c=15.00,0,0,0,dh")
    assert [(p.name, p.id) for p in learned] == [("강원대학교 춘천캠퍼스", "11591476"), ("강원 가명정보 활용지원센터", "2008011046")]
    assert learned[0].x == pytest.approx(127.7445, abs=1e-6) and learned[1].y == pytest.approx(37.326, abs=1e-6)
    known: dict = {}
    navermap.remember(known, "강원가명정보활용지원센터 (원주)", learned[1])
    assert navermap.search_place(None, "강원가명정보활용지원센터 (원주)", known=known)[0].id == "2008011046"
    assert navermap.places_from_url("https://map.naver.com/p/entry/place/1") == []


# ── 화면 ─────────────────────────────────────────────────────────────
@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(str(exc))
    return QApplication.instance() or QApplication([])


def _image(path: Path) -> Path:
    from PySide6.QtGui import QColor, QImage
    image = QImage(200, 260, QImage.Format_RGB32)
    image.fill(QColor("#cccccc"))
    image.save(str(path))
    return path


class FakeWorker:
    """브라우저 스레드 흉내 — 찾기를 부르면 바로 결과를 돌려준다(목적지가 '원주' 면 못 찾음)."""

    def __init__(self, tmp_path: Path):
        from PySide6.QtCore import QObject, Signal

        class _Sig(QObject):
            routes_found = Signal(object)
        self._sig = _Sig()
        self.routes_found = self._sig.routes_found
        self.calls = []
        self.tmp = tmp_path

    def find_routes(self, legs, folder, keys, owner="travel"):
        self.calls.append(legs)
        out = []
        for (origin, goal, label), key in zip(legs, keys):
            if goal == "원주":
                out.append((key, navermap.RouteResult(origin, goal, label, need_place="원주", note="'원주' 를 네이버 지도에서 찾지 못했습니다")))
            else:
                image = _image(Path(folder) / f"지도 {len(self.calls)}.png")
                out.append((key, navermap.RouteResult(origin, goal, label, km=76.0, image=str(image), ok=True)))
        self.routes_found.emit(out)

    def open_site(self, site):
        pass


def test_page_reviews_application_and_checks_per_traveler(qapp, tmp_path, isolated_home, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from claim_downloader import settings
    from claim_downloader.ui.pages import travel as travel_page
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    settings.update(travel_fuels="홍길동=휘발유")
    folder = tmp_path / "출장비 지급(26.11.10. 원주)"
    folder.mkdir()
    (folder / "국내 출장신청서(1110).txt").write_text(LABELED, encoding="utf-8")
    for name in ("홍길동_체류증빙 1110.png", "홍길동_체류증빙 1111.png", "홍길동_체류증빙 1112.png", "홍길동_하이패스 증빙 1110 3,100원.png",
                 "김철수_체류증빙 1110.png", "김철수_대중교통 증빙 KTX 1110 8,400원.png", "김철수_숙박비 증빙 1110 150,000원.png"):
        _image(folder / name)
    worker = FakeWorker(tmp_path)
    page = travel_page.TravelPage(worker=worker)
    page.show()
    # ① 폴더만 고르면 — 출장신청서를 먼저 검토(출장자 · 기간 · 출장지)
    page.load_folder(str(folder))
    assert page._stage == "review" and page.name_edit.text() == "홍길동, 김철수"
    assert page.start_edit.date().toPython() == date(2026, 11, 10) and page.dest_edit.text() == "원주"
    assert "출장자 2명: 홍길동, 김철수" in page.review_label.text()
    # 하이패스가 있는 홍길동만 자차 — 목적지 '원주' 는 분명하지 않아 홍길동의 출장목적지를 묻는다
    assert page._drivers() == ["홍길동"] and not page.goal_box.isHidden() and "홍길동" in page.goal_edits
    assert not page.car_box.isHidden() and page._fuel_of["홍길동"] == "휘발유"      # 설정의 연료를 이름으로
    assert not page.info_next.isEnabled() and not page.route_ok.isEnabled()          # 목적지 · 확인 전에는 못 넘어간다
    page.goal_edits["홍길동"].setText("연세대학교 원주캠퍼스")
    page.goal_edits["홍길동"].editingFinished.emit()
    assert page.goal_box.isHidden() and page.route_ok.isEnabled()
    # 경유지를 더하면 구간마다 — 빼면 지도 하나(왕복)
    page._add_via("원주시청")
    assert len(page._legs_for("홍길동")) == 3
    page._drop_via(page.via_edits[0].parentWidget(), page.via_edits[0])
    assert len(page._legs_for("홍길동")) == 1
    page.route_ok.setChecked(True)
    assert page.info_next.isEnabled()
    page.info_next.click()
    qapp.processEvents()
    # ③ 들어가면 보이지 않는 브라우저에서 최단거리를 저절로 찾는다
    assert worker.calls and worker.calls[-1][0][1] == "연세대학교 원주캠퍼스"
    assert page._routes[("홍길동", 0)]["km"] == 76.0 and page.route_table.rowCount() == 1
    assert not page.tables["stay"].isColumnHidden(page.tables["stay"].person_col)
    assert page.people_table.rowCount() == 2
    hong, kim = page.trips()
    assert hong.name == "홍길동" and len(hong.stay) == 3 and hong.legs == [76.0] and hong.fuel == "휘발유" and len(hong.route_maps) == 1
    assert kim.name == "김철수" and len(kim.public) == 1 and kim.lodging and not kim.tolls and not kim.route_maps
    review_kim = page.people_table.item(1, 7).text()
    assert "체류 증빙이 없는 날" in review_kim
    # ④ 출장자마다 만든다 — 확인할 것이 있으면 묻는 글 대신 미리 보기가 뜬다(여기서는 [이대로 만들기])
    # 체류 영수증은 출장지(원주)와 같은 시 · 군이어야 한다 — 그림 영수증은 앱이 못 읽어 확인할 것으로 남는다(담당자 2026-11-10)
    assert any("가맹점이 원주 안인지" in r for r in model.review(page.trips()[0]))
    for ev in page.tables["stay"].evidence(2026):
        if ev.person == "홍길동":
            page.apply_edit(ev.ref, {"shop_region": "원주"})
    assert not any("가맹점" in r for r in model.review(page.trips()[0]))
    opened = []
    monkeypatch.setattr(travel_page.TravelPreview, "exec", lambda self: opened.append(self.trip().name) or travel_page.PREVIEW_MAKE)
    page._make()
    assert opened == ["김철수"]                       # 확인할 것이 있는 사람부터
    made = sorted(p.name for p in folder.glob("* 출장증빙_26.11.10.pdf"))
    assert made == ["김철수 출장증빙_26.11.10.pdf", "홍길동 출장증빙_26.11.10.pdf"]
    # 목적지를 못 찾으면 다시 그 출장자의 출장목적지를 묻는다
    page._set_goal("홍길동", "원주")
    page._find_routes(force=True)
    assert "홍길동" in page._needs_goal() and "찾지 못했습니다" in page._needs_goal()["홍길동"]


def test_page_picks_trip_by_folder_date_and_can_switch(qapp, tmp_path, isolated_home):
    from claim_downloader.ui.pages import travel as travel_page
    folder = tmp_path / "출장비 지급(26.11.10. 원주)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(TWO_FORMS, encoding="utf-8")
    _image(folder / "홍길동_체류증빙 1110.png")
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.show()
    page.load_folder(str(folder))
    assert not page.trip_row.isHidden() and page.trip_box.count() == 2 and page.trip_box.currentIndex() == 1
    assert page.start_edit.date().toPython() == date(2026, 11, 10) and page.name_edit.text() == "홍길동, 김철수"
    assert "폴더 이름" in page.review_label.text()
    page.trip_box.setCurrentIndex(0)                 # 사람이 다른 출장으로 바꾸면 그 출장으로 다시 채운다
    assert page.start_edit.date().toPython() == date(2026, 11, 3) and page.dest_edit.text() == "삼척 쏠비치"
    assert page.name_edit.text() == "홍길동"
    one = tmp_path / "하나"
    one.mkdir()
    (one / "국내 출장신청서.txt").write_text(LABELED, encoding="utf-8")
    page.load_folder(str(one))
    assert page.trip_row.isHidden()


def test_public_table_has_route_columns_and_marks_unclear(qapp, tmp_path):
    from claim_downloader.ui.pages import travel as travel_page
    from claim_downloader.ui.pages.travel import EvidenceTable
    table = EvidenceTable(model.PUBLIC)
    table.add_files([_image(tmp_path / "홍길동_대중교통 증빙_1110_춘천-용산_8,400원.png"), _image(tmp_path / "홍길동_대중교통 증빙 1110 KTX.png")], 2026)
    got = table.evidence(2026)
    assert [(e.origin, e.goal, e.amount) for e in got] == [("춘천", "용산", 8400), ("", "", None)]
    assert table.mark_unclear() == 2                 # 첫 줄은 이동편이 없다(이름에 KTX 없음), 둘째 줄은 금액 · 이동편 · 출발지 · 목적지
    assert table.item(1, 4).toolTip() and not table.item(0, 4).toolTip() and table.item(1, 4).data(travel_page.UNCLEAR_ROLE)
    table.item(0, 3).setText("열차")
    table.item(1, 2).setText("8,400")
    table.item(1, 3).setText("열차")
    table.item(1, 4).setText("용산")
    table.item(1, 5).setText("원주")
    assert table.mark_unclear() == 0 and table.evidence(2026)[1].goal == "원주"


def test_preview_marks_unclear_and_edits_in_place(qapp, tmp_path, isolated_home):
    """담당자 2026-11-10 "확인필요한 건은 어플내에서 증빙양식 미리보기 처럼 나오는데 확인이 필요한 부분을 직접 편집할 수 있게"."""
    from claim_downloader.ui.pages import travel as travel_page
    from claim_downloader.ui.travel_preview import TravelPreview
    folder = tmp_path / "출장비 지급(26.11.10. 원주)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(LABELED.replace("홍길동, 연구원 김철수", "홍길동"), encoding="utf-8")
    for name in ("홍길동_체류증빙 1110.png", "홍길동_체류증빙 1111.png", "홍길동_대중교통 증빙_1110_춘천-원주_8,400원.png",
                 "홍길동_대중교통 증빙 1112.png", "홍길동_하이패스 증빙 1110 3,100원.png"):
        _image(folder / name)
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.load_folder(str(folder))
    page._go("files")
    dialog = TravelPreview(page, page, make_text="이대로 만들기")
    flagged = dialog._flagged
    public = {e.path.name: e.ref for e in page.trip().public}
    assert flagged[public["홍길동_대중교통 증빙_1110_춘천-원주_8,400원.png"]] == ["이동편"]
    assert flagged[public["홍길동_대중교통 증빙 1112.png"]] == ["금액", "이동편", "출발지", "목적지"]
    assert set(flagged[("route", "홍길동")]) >= {"km", "지도 그림"}
    hits = {h.ref for h in dialog._hits}
    assert public["홍길동_대중교통 증빙 1112.png"] in hits and ("route", "홍길동") in hits          # 칸 · 이동경로 줄을 누를 수 있다
    assert dialog._selected and dialog.todo_list.count() == len(flagged)
    # 칠한 칸을 누르면 그 증빙의 값을 고치는 칸 — 고치면 증빙 표에 적고 다시 그린다
    dialog._select(public["홍길동_대중교통 증빙 1112.png"])
    fields = dialog._editor_fields
    fields["amount"].setText("3300")
    fields["mode"].setCurrentText("시외버스")
    fields["origin"].setText("원주")
    fields["goal"].setText("춘천")
    dialog._apply()
    row = public["홍길동_대중교통 증빙 1112.png"][1]
    table = page.tables["public"]
    assert [table.item(row, c).text() for c in (2, 3, 4, 5)] == ["3,300", "시외버스", "원주", "춘천"]
    assert public["홍길동_대중교통 증빙 1112.png"] not in dialog._flagged
    assert dialog._selected != public["홍길동_대중교통 증빙 1112.png"]                     # 다음 확인할 것으로 넘어간다
    # 이동경로 줄 — 구간 km · 연료
    dialog._select(("route", "홍길동"))
    kms = dialog._editor_fields["kms"]
    next(iter(kms.values())).setText("76")
    dialog._editor_fields["fuel"].setCurrentIndex(dialog._editor_fields["fuel"].findData("경유"))
    dialog._apply()
    assert page.trip().legs == [76.0] and page.trip().fuel == "경유"
    assert "km" not in dialog._flagged.get(("route", "홍길동"), [])
    dialog.close()


def test_page_puts_named_other_files_into_other_table(qapp, tmp_path, isolated_home):
    from claim_downloader.ui.pages import travel as travel_page
    folder = tmp_path / "출장비 지급(26.11.10. 원주)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(LABELED, encoding="utf-8")
    for name in ("홍길동_체류증빙 1110.png", "김철수_체류증빙 1110.png", "홍길동_참가확인서.png", "김철수 교육 수료증.png"):
        _image(folder / name)
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.load_folder(str(folder))
    table = page.tables["other"]
    rows = {table.item(r, 0).text(): (table.item(r, 2).text(), table.item(r, table.person_col).text()) for r in range(table.rowCount())}
    assert rows == {"김철수 교육 수료증.png": ("교육 수료증", "김철수"), "홍길동_참가확인서.png": ("참가확인서", "홍길동")}
    hong, kim = page.trips()
    assert [e.label for e in hong.other] == ["참가확인서"] and [e.label for e in kim.other] == ["교육 수료증"]
    assert model.pages(hong)[-1].head[0] == "* 기타 증빙"
    page.apply_edit(hong.other[0].ref, {"label": "학회 참가확인서"})
    assert page.trips()[0].other[0].label == "학회 참가확인서"


def test_route_check_turns_on_after_fuel_is_picked(qapp, tmp_path, isolated_home):
    """담당자 2026-11-10 "출발지경유지목적지와 연료를 확인했습니다. 이부분 체크하려고 하는데 체크가 안됩니다" — 설정에 연료가 없는 사람은
    ② 에서 연료를 고르는데, 고른 뒤에도 확인 칸이 꺼진 채('아직 빈 것: 연료')라 눌리지 않았다."""
    from claim_downloader.ui.pages import travel as travel_page
    folder = tmp_path / "출장비 지급(26.10.20. 협의)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(GONGMUN, encoding="utf-8")
    for name in ("홍길동_체류 증빙.png", "홍길동_하이패스 증빙.png"):
        _image(folder / name)
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.show()
    page.load_folder(str(folder))
    assert page._drivers() == ["홍길동"] and page.goal_box.isHidden()
    assert page._car_missing() == ["연료"] and not page.route_ok.isEnabled() and "연료" in page.route_summary.text()
    box = page.fuel_boxes["홍길동"]
    box.setCurrentIndex(box.findData("휘발유"))
    assert page.route_ok.isEnabled() and "아직 빈 것" not in page.route_summary.text()
    page.route_ok.click()
    assert page.route_ok.isChecked() and page.info_next.isEnabled()
    # 연료를 다시 비우면 확인도 풀린다
    box.setCurrentIndex(0)
    assert not page.route_ok.isEnabled() and not page.route_ok.isChecked() and not page.info_next.isEnabled()


def test_origin_search_failure_does_not_ask_for_destination(qapp, tmp_path, isolated_home, monkeypatch):
    """담당자 2026-11-10 "목적지가 검색이 안된다고 하는데 둘다 검색이 됩니다" — 출발지부터 앱의 검색이 비어 왔는데 화면은 목적지를 물었다.
    이제 목적지 이름 탓이 아니면 ③ 에 남아 사람이 할 길([브라우저에서 직접] → [지금 화면 찍기])을 알린다."""
    from PySide6.QtWidgets import QMessageBox

    from claim_downloader import settings
    from claim_downloader.ui.pages import travel as travel_page
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    settings.update(travel_fuels="홍길동=휘발유")
    folder = tmp_path / "출장비 지급(26.10.20. 협의)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(GONGMUN, encoding="utf-8")
    for name in ("홍길동_체류 증빙.png", "홍길동_하이패스 증빙.png"):
        _image(folder / name)
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.show()
    page.load_folder(str(folder))
    page.route_ok.click()
    page.info_next.click()
    qapp.processEvents()
    assert page._stage == "files"
    key = ("홍길동", 0)
    page._routes[key].update(km=None, image="", status="")
    note = "출발지 '강원대학교 춘천캠퍼스' 를 네이버 지도에서 찾지 못했습니다 (검색 결과 없음)"
    page._on_routes([(key, navermap.RouteResult("강원대학교 춘천캠퍼스", "가나다라정보활용지원센터 (원주)", "가는 길", note=note))])
    assert page._stage == "files" and not page._needs_goal() and page.goal_box.isHidden()
    assert told and "[브라우저에서 직접]" in told[-1] and note in told[-1]
    assert page._routes[key]["status"] == "못 찾음 — " + note


def test_several_folders_one_after_another(qapp, tmp_path, isolated_home, monkeypatch):
    """담당자 2026-11-10 "여러 폴더를 선택할 수 있도록" — ① 에 폴더 여럿, 차례로 ② → ③ → ④, 만든 뒤 [다음 폴더]."""
    from PySide6.QtWidgets import QFileDialog

    from claim_downloader.ui.pages import travel as travel_page
    parent = tmp_path / "★완료"
    for name, day in (("출장비 지급(26.11.03. 삼척)", "1103"), ("출장비 지급(26.11.10. 원주)", "1110")):
        folder = parent / name
        folder.mkdir(parents=True)
        (folder / "국내 출장신청서.txt").write_text(TWO_FORMS, encoding="utf-8")
        _image(folder / f"홍길동_체류증빙 {day}.png")
    (parent / "빈 폴더").mkdir()
    assert model.looks_like_trip(parent / "출장비 지급(26.11.03. 삼척)") and not model.looks_like_trip(parent / "빈 폴더")
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.show()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(parent))
    page._pick_parent()
    assert page.folder_list.count() == 2 and "2개" in page.folder_note.text()
    assert page._stage == "folder" and page.start_button.text() == "2개 폴더 차례로 시작"
    page.start_button.click()
    first, second = (str(parent / n) for n in ("출장비 지급(26.11.03. 삼척)", "출장비 지급(26.11.10. 원주)"))
    assert page.folder_edit.text() == first and page.start_edit.date().toPython() == date(2026, 11, 3)   # 폴더 날짜로 그 출장
    assert "지금" in page.folder_list.item(0).text() and page.next_button.text() == "다음 폴더 — 출장비 지급(26.11.10. 원주)"
    page._go("files")
    monkeypatch.setattr(travel_page.TravelPreview, "exec", lambda self: travel_page.PREVIEW_MAKE)
    page._make()
    assert list(Path(first).glob("홍길동 출장증빙_26.11.03.pdf")) and page.folder_list.item(0).text().startswith("✓")
    assert "다음 폴더" in page.result_label.text()
    page.next_button.click()
    assert page.folder_edit.text() == second and page._stage == "review" and page.start_edit.date().toPython() == date(2026, 11, 10)
    page._go("files")
    page._make()
    assert list(Path(second).glob("홍길동 출장증빙_26.11.10.pdf")) and page.next_button.isHidden()
    page._go("folder")
    assert page.start_button.text() == "모두 만들었습니다" and not page.start_button.isEnabled()


STRUCTURE = """════ 화면 구조 3번째 ════
창 1 — 출장명령부(국내)교통비
  프레임 0: https://knu-icf.kangwon.ac.kr/rcomm_0027_07.act
<input radio>  #TRIP_CHANGE  name=TRIP_CHANGE  값: 1  라벨: 자차
<select>  #TRIP_FUEL  name=TRIP_FUEL  라벨: 연비/전비/수소  값: 수소  보기: 연비/전비/수소 | 휘발유 | 경유 | LPG | 전기 | 수소  [비활성]
<select>  #TRIP_GRAD  name=TRIP_GRAD  보기: 연비/전비/수소 | 휘발유 | 경유
<select>  #CAR_USE  name=CAR_USE  보기: 선택 | 하중이 무거운 수하물을 운송해야 하는 경우
"""


def test_fuel_options_come_from_erp_structure_record(isolated_home):
    """담당자 2026-11-10 "연료는 erp에서 출장 교통비 세부내역 작성할 때 연비/전비/수소에 있는 항목 중에 선택 … 화면구조저장 … 기록 찾아서"."""
    from claim_downloader import settings
    from claim_downloader.travel import fuels
    assert fuels.from_text(STRUCTURE) == ["휘발유", "경유", "LPG", "전기", "수소"]            # 안내 글 '연비/전비/수소' 는 보기가 아니다
    assert fuels.from_text("<select>  #X  라벨: 연비/전비/수소  보기: 선택 | 하이브리드 | 수소") == ["하이브리드", "수소"]
    assert fuels.from_text("<select>  #CAR_USE  보기: 선택 | 무거운 짐") == []
    options, source = fuels.options()
    assert options == list(model.FUELS) and "찾지 못해" in source                      # 기록이 없으면 기본 보기
    settings.data_dir().mkdir(parents=True, exist_ok=True)
    settings.structure_book_path().write_text(STRUCTURE, encoding="utf-8")
    options, source = fuels.options()
    assert options == ["휘발유", "경유", "LPG", "전기", "수소"] and "_화면구조_모음.txt" in source
    settings.structure_book_path().unlink()                                          # 모음이 새로 시작해도 남겨 둔 보기로
    assert fuels.options()[0] == ["휘발유", "경유", "LPG", "전기", "수소"] and settings.load().travel_fuel_options


def test_fuel_box_shows_whole_option_text(qapp):
    """설정의 연료 칸이 '…' 로만 보이던 것(담당자 2026-11-10 그림) — 칸 · 펼친 목록 폭을 글자만큼."""
    from claim_downloader.ui.travel_fuel_card import fuel_box
    box = fuel_box(["휘발유", "경유", "전기(전비)"], "경유")
    assert box.currentData() == "경유" and box.count() == 4
    width = box.fontMetrics().horizontalAdvance("전기(전비)")
    assert box.view().minimumWidth() >= width and box.sizeHint().width() >= width


def test_settings_fuel_card(qapp, isolated_home):
    from claim_downloader import settings
    from claim_downloader.ui.travel_fuel_card import TravelFuelCard
    settings.update(travel_fuels="홍길동=휘발유")
    card = TravelFuelCard()
    assert card.fuels() == {"홍길동": "휘발유"}
    card._add_row("김철수", "")
    card.table.cellWidget(1, 1).setCurrentIndex(card.table.cellWidget(1, 1).findData("경유"))
    assert model.parse_fuels(settings.load().travel_fuels) == {"홍길동": "휘발유", "김철수": "경유"}


def test_stay_receipt_must_be_in_the_destination_city(tmp_path):
    """담당자 2026-11-10 "체류증빙은 영수증 가맹점의 주소지와 출장 목적지가 같아야" · "강원도 원주시 인터불고호텔이 출장지이면
    체류증빙은 강원도 원주시 내 영수증이면 됩니다" — 시 · 군까지만 견준다."""
    day = date(2026, 10, 20)
    assert model.region_of("강원도 원주시 인터불고호텔") == "원주" and model.region_of("가나다라정보활용지원센터 (원주)") == "원주"
    assert model.region_of("연세대학교 원주캠퍼스") == "원주" and model.region_of("강원 춘천시 강원대학길 1") == "춘천"
    assert model.shop_region_of("상호: 원주식당\n주소: 강원 원주시 혁신로 19\n합계 9,000원") == "원주"
    same = model.Evidence(_image(tmp_path / "홍길동_체류증빙_원주.png"), day)
    other = model.Evidence(_image(tmp_path / "홍길동_체류증빙 강릉.png"), day)
    unread = model.Evidence(_image(tmp_path / "홍길동_체류증빙.png"), day)
    for ev in (same, other, unread):
        ev.shop_region = model.guess(ev.path, 2026, stay=True).shop_region
    assert (same.shop_region, other.shop_region, unread.shop_region) == ("원주", "강릉", "")
    trip = model.Trip(name="홍길동", start=day, end=day, destination="강원도 원주시 인터불고호텔", stay=[same, other, unread])
    assert model.stay_regions(trip, same) == ["원주"]
    assert model.unclear(trip, model.STAY, same) == []
    assert model.unclear(trip, model.STAY, other) == ["가맹점 지역(다름)"]
    assert model.unclear(trip, model.STAY, unread) == ["가맹점 지역"]
    assert any("강릉" in p and "원주" in p for p in model.problems(trip))
    review = model.review(trip)
    assert any("다른 시 · 군" in r for r in review) and any("1건 — 영수증 가맹점이 원주 안인지" in r for r in review)
    # 출장지 글에 시 · 군이 없으면 네이버에서 찾은 주소의 시 · 군으로
    trip.destination = "가나다라 연구소"
    assert model.stay_regions(trip, same) == [] and not model.unclear(trip, model.STAY, unread)
    trip.place_regions = {"가나다라 연구소": "원주"}
    assert model.stay_regions(trip, same) == ["원주"] and model.unclear(trip, model.STAY, other) == ["가맹점 지역(다름)"]


def test_bar_drops_star_and_empty_right_cell():
    """담당자 2026-11-10 — 체류 증빙 머리 줄 오른쪽은 들어갈 것이 없어 칸 나누기가 필요 없다 · 엑셀식 '*' 대신 앱 디자인으로."""
    pytest.importorskip("PySide6")
    from claim_downloader.travel import render
    assert render._bar_cells(["* 체류 증빙", ""]) == ["체류 증빙"]
    assert render._bar_cells(["* 교통비 증빙 (자차)", "연료 경유", "8,200원"]) == ["교통비 증빙 (자차)", "연료 경유", "8,200원"]
    assert render._bar_cells(["2026년 10월 20일", "", "하이패스 8,200원"]) == ["2026년 10월 20일", "", "하이패스 8,200원"]


def test_step_five_preview_in_the_page(qapp, tmp_path, isolated_home):
    """담당자 2026-11-10 "5단계로 미리보기를 넣어주세요" — ③ 증빙 확인 · ④ 만들기 아래 ⑤ 에 PDF 와 같은 쪽, 눌러서 고친다."""
    from claim_downloader import settings
    from claim_downloader.ui.pages import travel as travel_page
    settings.update(travel_fuels="홍길동=휘발유")
    folder = tmp_path / "출장비 지급(26.10.20. 협의)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(GONGMUN, encoding="utf-8")
    for name in ("홍길동_체류 증빙.png", "홍길동_하이패스 증빙 4,100원.png"):
        _image(folder / name)
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.show()
    page.load_folder(str(folder))
    assert page.step_preview.isHidden()                      # ② 에서는 아직
    page.route_ok.click()
    page.info_next.click()
    qapp.processEvents()
    assert page._stage == "files" and not page.step_preview.isHidden()
    page._refresh_preview()
    panel = page.preview_panel
    assert panel._views and panel.todo_list.count() >= 1
    stay = next(ev for ev in page.tables["stay"].evidence(2026))
    assert "가맹점 지역" in panel._flagged.get(stay.ref, [])          # 출장지는 원주 — 그림 영수증이라 앱이 못 읽음
    panel._select(stay.ref)
    panel._editor_fields["shop_region"].setText("원주")
    panel._apply()
    assert page.tables["stay"].item(0, travel_page.SHOP_COL).text() == "원주"
    assert not any(f.startswith("가맹점") for f in panel._flagged.get(stay.ref, []))


CAPTCHA_PAGE = """<!doctype html><html><body><div id="list">검색 중</div><script>
const q = decodeURIComponent(location.pathname.split('/p/search/')[1] || '');
function search() {
  fetch('/p/api/mockgraphql?q=' + encodeURIComponent(q)).then(r => r.json()).then(j => {
    if (j.result && j.result.ncaptcha) { document.getElementById('list').textContent = '보안문자'; setTimeout(search, 400); }
    else document.getElementById('list').textContent = 'ok';
  });
}
search();
</script></body></html>"""


def test_naver_captcha_waits_for_the_person(browser_page, tmp_path, monkeypatch):
    """2026-11-10 담당자 PC — 네이버가 자동 검색에 보안문자(ncaptcha)를 요구했다. 앱은 풀거나 피하지 않고, 앱 브라우저 창에서 사람이 풀 때까지 기다린다.
    여기서는 보안문자 답이 한 번 온 뒤 (사람이 풀어) 화면이 다시 검색하면 곳이 온다."""
    from urllib.parse import parse_qs, urlparse
    monkeypatch.setattr(navermap, "SEARCH_POLLS", 4)
    page = browser_page
    places = {"강원대학교 춘천캠퍼스": {"id": "11591476", "name": "강원대학교 춘천캠퍼스", "x": "127.7445", "y": "37.8690"},
              "원주시청": {"id": "1", "name": "원주시청", "x": "127.92", "y": "37.34", "roadAddress": "강원 원주시 시청로 1"}}
    asked: dict = {}
    captcha = {"result": {"place": None, "ncaptcha": {"uuid": "x", "ip": "x", "confirmRules": [], "timestamp": 1}}}

    def handle(route):
        url = route.request.url
        if "/p/api/search/allSearch" in url:
            route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(captcha))
        elif "/p/api/mockgraphql" in url:
            query = parse_qs(urlparse(url).query)["q"][0]
            asked[query] = asked.get(query, 0) + 1
            body = captcha if asked[query] == 1 else {"data": {"items": [places[query]] if query in places else []}}
            route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(body))
        elif "/p/search/" in url:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=CAPTCHA_PAGE)
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=MOCK_PAGE)
    page.route("https://map.naver.com/**", handle)
    logs: list = []
    known: dict = {}
    result = navermap.find_route(page, "강원대학교 춘천캠퍼스", "원주시청", tmp_path / "a.png", logs.append,
                                 wait=lambda s: page.wait_for_timeout(int(s * 300)), label="가는 길", known=known)
    assert result.ok and result.km == 76, result.lines()
    assert any(navermap.CAPTCHA_NOTE in line for line in logs)                       # 사람에게 알렸다
    assert any(navermap.CAPTCHA_NOTE in step for step in result.steps)
    assert known[navermap.norm("원주시청")]["address"] == "강원 원주시 시청로 1"
    # 2분 안에 풀지 않으면 그 곳만 그만두고 다른 검색어로 되풀이하지 않는다(목적지를 묻지 않는다 — 곳 이름 탓이 아니므로)
    monkeypatch.setattr(navermap, "CAPTCHA_POLLS", 6)
    asked.clear()
    page.unroute("https://map.naver.com/**")

    def always_captcha(route):
        url = route.request.url
        if "/p/api/" in url:
            route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(captcha))
        elif "/p/search/" in url:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=CAPTCHA_PAGE)
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=MOCK_PAGE)
    page.route("https://map.naver.com/**", always_captcha)
    stuck = navermap.find_route(page, "강원 가명정보 (원주)", "원주시청", tmp_path / "b.png", logs.append,
                                wait=lambda s: page.wait_for_timeout(int(s * 300)), known={})
    assert not stuck.ok and stuck.need_place == "" and navermap.CAPTCHA_NOTE in stuck.note
    assert sum("지도 화면 검색" in step for step in stuck.steps) == 1


def test_places_from_directions_url_with_encoded_commas():
    """2026-11-10 담당자가 앱 브라우저에서 띄운 길찾기(82km)를 찍었는데 곳을 못 배웠다 — 주소의 쉼표가 %2C 로 적힌 꼴도 읽는다."""
    start = navermap.Place("강원대학교 춘천캠퍼스", 127.7445, 37.8690, "11591476")
    goal = navermap.Place("강원 가명정보 활용지원센터", 127.955, 37.326, "2008011046")
    url = navermap.directions_url(start, goal).replace(",", "%2C")
    assert [p.id for p in navermap.places_from_url(url)] == ["11591476", "2008011046"]
