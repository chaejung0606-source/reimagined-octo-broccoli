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


def test_find_route_in_mock_naver_map(browser_page, tmp_path):
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


def test_settings_fuel_card(qapp, isolated_home):
    from claim_downloader import settings
    from claim_downloader.ui.travel_fuel_card import TravelFuelCard
    settings.update(travel_fuels="홍길동=휘발유")
    card = TravelFuelCard()
    assert card.fuels() == {"홍길동": "휘발유"}
    card._add_row("김철수", "")
    card.table.cellWidget(1, 1).setCurrentIndex(card.table.cellWidget(1, 1).findData("경유"))
    assert model.parse_fuels(settings.load().travel_fuels) == {"홍길동": "휘발유", "김철수": "경유"}
