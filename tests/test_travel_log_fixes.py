"""출장증빙 — 2026-11-25 담당자 공유 기록에서 찾은 문제들(CLAUDE.md 28절). 이름 · 곳 · 금액은 모두 지어낸 것이다."""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from claim_downloader.travel import application, model, navermap
from claim_downloader.travel.model import Evidence, Trip

import pytest

from test_travel_people import GONGMUN, FakeWorker, _image
from test_travel_receipts import _read


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

HEAD = GONGMUN[:GONGMUN.index("다음과 같이 출장을 명함")]
FORM = GONGMUN[GONGMUN.index("다음과 같이 출장을 명함"):]


def _form(name: str, day: str, place: str, region: str) -> str:
    return (FORM.replace("홍길동", name).replace("2026.10.20. (화) 09:00 가나다라정보", f"{day} (목) 09:00 {place}")
            .replace("활용지원센터\n(원주)", region).replace("2026.10.20. (화) 18:00", f"{day} (목) 18:00"))


THREE = (HEAD + _form("홍길동", "2026.11.12.", "가나호텔", "(원주)") + _form("홍길동", "2026.11.13.", "한국가나진흥원", "(서울송파)")
         + _form("김철수", "2026.11.13.", "한국가나진흥원", "(서울송파)"))


def test_a_gongmun_with_three_forms_reads_every_trip():
    """'국내 출장신청서 (3건)' — 한 공문에 '다음과 같이 출장을 명함' 양식이 출장마다 되풀이된다. 전에는 첫 양식만 읽었다."""
    app = application.parse_text(THREE)
    assert [(t.start, tuple(t.travelers)) for t in app.trips] == [(date(2026, 11, 12), ("홍길동",)),
                                                                  (date(2026, 11, 13), ("홍길동", "김철수"))]
    assert app.trips[0].places == ["가나호텔 (원주)"] and app.trips[1].places == ["한국가나진흥원 (서울송파)"]


def test_trips_inside_the_folder_range_become_one_trip():
    """폴더 '26.11.12-13' 이면 그 기간의 같은 사람 출장을 하나로 — 원주를 거쳐 서울(담당자가 손으로 기간 · 경유지를 고쳤던 것).
    다른 사람(김철수)은 제 날짜의 출장으로 남는다."""
    app = application.select(application.parse_text(THREE), "/x/출장비 지급(26.11.12-13. 원주 서울)")
    assert (app.start, app.end, app.travelers) == (date(2026, 11, 12), date(2026, 11, 13), ["홍길동"])
    assert app.places == ["가나호텔 (원주)", "한국가나진흥원 (서울송파)"]
    assert app.trips[app.chosen].days == {"가나호텔 (원주)": (date(2026, 11, 12), date(2026, 11, 12)),
                                          "한국가나진흥원 (서울송파)": (date(2026, 11, 13), date(2026, 11, 13))}
    assert [t.travelers for t in app.trips] == [["홍길동"], ["김철수"]] and "합쳤습니다" in app.notes[0]
    # 날짜 하나뿐인 폴더는 전처럼 그 날의 출장만
    one = application.select(application.parse_text(THREE), "/x/출장비 지급(26.11.13. 서울)")
    assert (one.start, one.end, len(one.trips)) == (date(2026, 11, 13), date(2026, 11, 13), 2)


def test_folder_range_forms():
    cases = {"출장비 지급(26.11.12-13. 원주)": (date(2026, 11, 12), date(2026, 11, 13)),
             "26.08.26-30. 학회": (date(2026, 8, 26), date(2026, 8, 30)),
             "2026-10-31~11-02 서울": (date(2026, 10, 31), date(2026, 11, 2)),
             "1112-1113 서울": (date(2026, 11, 12), date(2026, 11, 13)),
             "26.12.31-01.02": (date(2026, 12, 31), date(2027, 1, 2)),
             "출장비 지급(26.10.28.-29.)": (date(2026, 10, 28), date(2026, 10, 29)),
             "26.05.28. 삼척": None, "1110 원주": None}
    for name, want in cases.items():
        assert application.folder_range(name, 2026) == want, name


def test_receipts_of_a_merged_trip_take_the_place_of_their_day():
    """합친 출장(원주 → 서울)에서 영수증마다 출장지를 고르지 않아도 그 날의 출장지 — 체류 지역 · 숙박 상한도 그곳으로."""
    trip = Trip(name="홍길동", start=date(2026, 11, 12), end=date(2026, 11, 13), destination="가나호텔 (원주), 한국가나진흥원 (서울송파)",
                place_days={"가나호텔 (원주)": (date(2026, 11, 12), date(2026, 11, 12)),
                            "한국가나진흥원 (서울송파)": (date(2026, 11, 13), date(2026, 11, 13))},
                place_regions={"한국가나진흥원 (서울송파)": "서울"})
    stay = Evidence(path=Path("홍길동_체류증빙1.png"), day=date(2026, 11, 12), shop_region="원주")
    lodging = Evidence(path=Path("홍길동_숙박비 증빙.pdf"), day=date(2026, 11, 12), amount=80000, nights=1)
    assert trip.place_of(stay) == "가나호텔 (원주)" and model.unclear(trip, model.STAY, stay) == []
    assert trip.cap_region(lodging) == model.lodging_region("원주")
    assert trip.place_of(Evidence(path=Path("a.png"), day=date(2026, 11, 13))) == "한국가나진흥원 (서울송파)"


def test_stay_receipt_at_a_via_city_is_in_region():
    """② 의 경유지(원주)에서 쓴 체류 영수증은 '지역 다름' 이 아니다 — 같은 줄을 다섯 번 고쳤다."""
    trip = Trip(name="홍길동", start=date(2026, 11, 12), end=date(2026, 11, 13), destination="서울 한국가나진흥원", vias=["원주 가나호텔"])
    stay = Evidence(path=Path("홍길동_체류증빙1.png"), day=date(2026, 11, 12), shop_region="원주")
    assert "가맹점 지역(다름)" not in model.unclear(trip, model.STAY, stay)


def test_naver_rank_prefers_the_school_over_a_branch_store():
    """'영남이공대(대구)' 에서 '지지고 영남이공대점' 을 골랐다(2026-11-16)."""
    shop = navermap.Place(name="지지고 영남이공대점", x=128.6, y=35.8, id="1")
    school = navermap.Place(name="영남이공대학교", x=128.6, y=35.8, id="2")
    assert navermap.rank("영남이공대(대구)", [shop, school])[0] is school
    assert navermap.rank("지지고 영남이공대점", [school, shop])[0] is shop


def test_stray_weekday_bits_do_not_stay_in_the_place():
    """요일 괄호가 줄에서 갈라져 나오면(' (화' / ') 09:00 …') 출장지 앞에 ')' 가 붙었다."""
    text = GONGMUN.replace("2026.10.20. (화) 09:00 가나다라정보", "2026.10.20. (화\n) 09:00 가나다라정보")
    assert application.parse_text(text).places == ["가나다라정보활용지원센터 (원주)"]


def test_log_lines_from_threads_do_not_interleave(isolated_home):
    """회의록 · AI 읽기 스레드와 화면이 같은 기록 파일에 한꺼번에 쓰면 줄이 섞였다('�음 3)')."""
    from claim_downloader import settings
    path = settings.log_path()

    def write(tag: str) -> None:
        for i in range(200):
            settings.append_log(f"{tag} {i:03d} " + "가" * 40 + "\n")
    threads = [threading.Thread(target=write, args=(t,)) for t in "ABCD"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 800 and all(line.endswith("가" * 40) and len(line) == 46 for line in lines)


def test_preview_says_receipts_are_still_being_read(qapp, tmp_path, isolated_home, monkeypatch):
    """AI 가 영수증을 읽는 동안 미리 보기 위에 한 줄 — 다 읽기 전에 고치면 읽은 값과 겹친다. 로그인이 풀려 멈추면 그 까닭."""
    from claim_downloader.ui.pages import travel as travel_page
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    assert page.ai_busy_text() == ""
    page._ai_left, page._ai_stop = 2, ""
    page._ai_running = 1
    assert "읽는 중" in page.ai_busy_text()
    page._ai_running = 0
    page._ai_stop = "login"
    assert "로그인이 풀려" in page.ai_busy_text() and "2개" in page.ai_busy_text()


def test_making_with_a_route_still_on_the_naver_window_asks_first(qapp, tmp_path, isolated_home, monkeypatch):
    """네이버 지도 창에 띄워 두고 찍지 않은 구간이 있는데 내보내면 그 구간의 지도 · km 가 빠진다 — 먼저 묻는다."""
    from PySide6.QtWidgets import QMessageBox

    from claim_downloader.ui.pages import travel as travel_page
    folder = tmp_path / "출장비 지급(26.11.10. 원주)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(GONGMUN, encoding="utf-8")
    _image(folder / "홍길동_체류증빙 1020.png")
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.load_folder(str(folder))
    page._set_fuel("홍길동", "휘발유")
    page._routes[("홍길동", 0)] = {"origin": "강원대학교 춘천캠퍼스", "goal": "가나다라정보활용지원센터 (원주)", "label": "가는 길",
                                   "km": None, "image": "", "status": "확인 기다림 — 네이버 지도 창"}
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    page._make()
    assert asked and "아직 찍지 않은 구간" in asked[0] and not list(folder.glob("*출장증빙*.pdf"))


def test_a_one_day_trip_fills_undated_receipts_with_the_trip_day(qapp, tmp_path):
    """하루 출장이면 날짜를 못 읽은 체류 · 대중교통 · 하이패스 증빙의 일자는 출장일 — 그림 영수증마다 같은 날을 적게 하지 않는다.
    AI 가 영수증에서 날짜를 읽으면 그 값이 먼저이고(출장기간 밖이면 칠해지게), 기간이 늘면 앱이 적은 일자를 지운다. 사람이 적은 일자는 그대로."""
    from claim_downloader.travel import ai_read
    from claim_downloader.ui.pages import travel as travel_page
    period = {"v": (date(2026, 10, 20), date(2026, 10, 20))}
    table = travel_page.EvidenceTable(model.TOLL)
    table.period_of = lambda person: period["v"]
    files = [_image(tmp_path / "홍길동_하이패스 증빙 4,100원.png"), _image(tmp_path / "홍길동_하이패스 증빙2.png")]
    table.add_files(files, 2026)
    assert table.ai_wanted() == files                       # 일자가 비었다 — AI 로 읽는다
    assert table.apply_orders() == 2 and [table.item(r, 1).text() for r in range(2)] == ["2026-10-20"] * 2
    assert table.ai_wanted() == files                       # 출장일로 적은 일자는 AI 가 읽은 일자로 바꿀 자리
    table.apply_ai(files[1], ai_read.summary(model.TOLL, _read(("2026-10-19", 3000, "", "", "", "", ""))))
    assert table.item(1, 1).text() == "2026-10-19"         # 영수증의 날짜가 먼저(출장기간 밖으로 칠해진다)
    table.item(0, 1).setText("2026-10-21")                   # 사람이 고친 일자
    period["v"] = (date(2026, 10, 20), date(2026, 10, 21))
    table.apply_orders()
    assert [table.item(r, 1).text() for r in range(2)] == ["2026-10-21", "2026-10-19"]
    other = travel_page.EvidenceTable(model.PUBLIC)
    other.period_of = lambda person: period["v"]
    other.add_files([_image(tmp_path / "홍길동_대중교통 증빙.png")], 2026)
    assert other.apply_orders() == 0 and other.item(0, 1).text() == ""     # 이틀 출장이면 적지 않는다
    period["v"] = (date(2026, 10, 20), date(2026, 10, 20))
    assert other.apply_orders() == 1 and other.item(0, 1).text() == "2026-10-20"
    period["v"] = (date(2026, 10, 20), date(2026, 10, 22))
    other.apply_orders()
    assert other.item(0, 1).text() == ""                    # 기간이 늘면 앱이 적은 일자는 지운다
