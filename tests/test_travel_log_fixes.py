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
    # 괄호 속 지역이 이름에 든 곳이 먼저 — '인터불고(원주)' 에서 '인터불고 레스토랑' 을 골랐다(2026-11-26 담당자 기록)
    food = navermap.Place(name="인터불고 레스토랑", x=127.9, y=37.3, id="3")
    hotel = navermap.Place(name="호텔인터불고 원주", x=127.9, y=37.3, id="4")
    assert navermap.rank("인터불고(원주)", [food, hotel])[0] is hotel
    assert navermap.rank("인터불고", [food, hotel])[0] is food          # 지역이 없으면 전처럼 이름이 검색어로 시작하는 곳


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
    assert table.apply_dates() == 2 and [table.item(r, 1).text() for r in range(2)] == ["2026-10-20"] * 2
    assert table.ai_wanted() == files                       # 출장일로 적은 일자는 AI 가 읽은 일자로 바꿀 자리
    table.apply_ai(files[1], ai_read.summary(model.TOLL, _read(("2026-10-19", 3000, "", "", "", "", ""))))
    assert table.item(1, 1).text() == "2026-10-19"         # 영수증의 날짜가 먼저(출장기간 밖으로 칠해진다)
    table.item(0, 1).setText("2026-10-21")                   # 사람이 고친 일자
    period["v"] = (date(2026, 10, 20), date(2026, 10, 21))
    table.apply_dates()
    assert [table.item(r, 1).text() for r in range(2)] == ["2026-10-21", "2026-10-19"]
    other = travel_page.EvidenceTable(model.PUBLIC)
    other.period_of = lambda person: period["v"]
    other.add_files([_image(tmp_path / "홍길동_대중교통 증빙.png")], 2026)
    assert other.apply_dates() == 0 and other.item(0, 1).text() == ""     # 이틀 출장이면 적지 않는다
    period["v"] = (date(2026, 10, 20), date(2026, 10, 20))
    assert other.apply_dates() == 1 and other.item(0, 1).text() == "2026-10-20"
    period["v"] = (date(2026, 10, 20), date(2026, 10, 22))
    other.apply_dates()
    assert other.item(0, 1).text() == ""                    # 기간이 늘면 앱이 적은 일자는 지운다


NAVER_LIKE = """<body style='margin:0;font:14px sans-serif'>
<div style='display:flex;height:100vh'>
 <div id='left' style='width:340px;display:flex;flex-direction:column'>
  <div style='height:180px'>강원대학교 춘천캠퍼스 → 가나협회 [길찾기]</div>
  <div id='list' style='flex:1;overflow-y:auto'>
   <div class='item' style='height:220px'><b>1 실시간 추천</b><div>1시간 36분 95km</div><div>중앙고속도로 13km</div></div>
   <div class='item' style='height:220px'><b>2 큰길우선</b><div>1시간 41분 99km</div></div>
   <div class='item' style='height:220px'><b>3 무료우선</b><div>2시간 13분 95km</div></div>
   <div class='item' id='short' style='height:220px'><b><span>4</span> <a href='#'>거리우선</a></b><div><span>1시간 41분</span> <span>94km</span></div></div>
  </div>
 </div>
 <div id='detail' style='display:none;width:300px;background:#fff'><b>4 거리우선</b><div>출발 · 우회전 26m</div></div>
 <div style='flex:1;background:#e8efe4'><canvas width='300' height='200'></canvas></div>
</div>
<script>
 window.clickWidth = 0;
 document.querySelector('#short a').addEventListener('click', e => {
   e.preventDefault(); window.clickWidth = innerWidth; document.getElementById('detail').style.display = 'block'; });
</script></body>"""


def _chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    import os
    try:
        pw = sync_api.sync_playwright().start()
        path = "/opt/pw-browsers/chromium"
        browser = pw.chromium.launch(executable_path=path if os.path.exists(path) else None)
    except Exception as exc:  # noqa: BLE001 — 브라우저가 없는 곳
        pytest.skip(str(exc))
    return pw, browser


def test_capture_scrolls_the_route_list_so_the_shortest_route_km_shows(tmp_path):
    """담당자 2026-11-26 그림 — 경로 목록에 ①~③ 만 보이고 고른 ④ 거리우선(94km)이 목록 아래로 잘려 증빙에 거리우선 주행거리가 없었다
    ("거리우선 주행거리가 보이도록 왼쪽 경로 목록을 아래로 스크롤한 뒤에 캡쳐해주세요"). '거리우선' 은 넓힌 화면에서 누른다(지도를 그 크기에 맞추게)."""
    pw, browser = _chromium()
    try:
        page = browser.new_context(no_viewport=True).new_page()
        page.set_content(NAVER_LIKE)
        out = tmp_path / "shot.png"
        result = navermap.capture(page, out, "출장자 1 가는 길", wait=lambda s: page.wait_for_timeout(int(s * 50)))
        assert page.evaluate("window.clickWidth") == navermap.CAPTURE_SIZE[0]          # 넓힌 뒤에 눌렀다
        assert page.evaluate("document.getElementById('list').scrollTop") > 0
        assert _step(result, "경로 목록을 '거리우선' 이 보이게 내림") and not any("찾지 못" in s for s in result.steps)
        assert "지도를 가리는 세부 경로 창을 숨기고 찍음" in result.steps
        assert page.evaluate("getComputedStyle(document.getElementById('detail')).visibility") == "visible"   # 찍은 뒤 되돌림
        assert result.km == 94 and out.exists()
        # 이미 보이면 내리지 않는다
        page.set_content(NAVER_LIKE.replace("height:220px", "height:60px"))
        result = navermap.capture(page, tmp_path / "shot2.png", "출장자 1 가는 길", wait=lambda s: page.wait_for_timeout(int(s * 50)))
        assert page.evaluate("document.getElementById('list').scrollTop") == 0
        assert _step(result, "경로 목록에 '거리우선' 이 보임")
    finally:
        browser.close()
        pw.stop()


def _step(result, head: str) -> bool:
    return any(s.startswith(head) for s in result.steps)


def _wide_page(browser):
    """찍는 크기로 정해 둔 화면 — 찍은 뒤 되돌려도 크기가 같아, 찍을 때의 자리를 테스트가 볼 수 있다."""
    w, h = navermap.CAPTURE_SIZE
    return browser.new_context(viewport={"width": w, "height": h}).new_page()


def _drawn_in(page, sel: str, text: str) -> bool:
    """그 글자가 있는 자리에 실제로 그려진 것이 sel 안인가 — 덮은 줄 밑이면 아니다."""
    return page.evaluate("""([sel, text]) => {
      const box = document.querySelector(sel);
      const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        if (!n.nodeValue.includes(text)) continue;
        const r = document.createRange(); r.selectNodeContents(n); const q = r.getBoundingClientRect();
        const at = document.elementFromPoint(q.left + 2, q.top + q.height / 2);
        return !!at && box.contains(at);
      }
      return false; }""", [sel, text])


# 같은 날 다시 찍은 그림 — 기록은 '내림' 인데 거리우선이 안 보였다. 네이버 목록 아래에는 '출발 → 도착 ☆' 줄이 목록 위에 겹쳐 있어,
# 자리로는 목록 안(보임)이어도 그 줄 밑에 가려진다
COVERED = (NAVER_LIKE.replace("<div id='left' style='width:340px;display:flex;flex-direction:column'>",
                              "<div id='left' style='width:340px;display:flex;flex-direction:column;position:relative'>")
           .replace("<div id='list' style='flex:1;overflow-y:auto'>", "<div id='list' style='flex:1;overflow-y:auto;padding-bottom:170px'>")
           .replace("<div class='item' style='height:220px'><b>3", "<div class='item' style='height:60px'><b>3")
           .replace("<div class='item' style='height:220px'><b>2", "<div class='item' style='height:60px'><b>2")
           .replace("<div class='item' style='height:220px'><b>1", "<div class='item' style='height:60px'><b>1")
           .replace("<div class='item' id='short' style='height:220px'>", "<div class='item' id='short' style='height:120px'>")
           .replace("  </div>\n </div>\n <div id='detail'",
                    "  </div>\n  <div id='foot' style='position:absolute;left:0;right:0;bottom:0;height:160px;background:#fff'>"
                    "출발 → 도착 ☆</div>\n </div>\n <div id='detail'")
           .replace("<div style='height:180px'>", "<div style='height:560px'>")
           # 화면 밖에 숨겨 둔 같은 글자(보기 목록 같은 것)는 목록이 아니다
           .replace("<script>", "<span style='position:absolute;left:-9999px;top:300px'>거리우선</span>\n<script>"))


def test_capture_shows_the_shortest_route_from_under_the_bottom_bar(tmp_path):
    """자리로는 목록 안이지만 아래 줄에 덮인 거리우선 — 덮였는지는 그 자리에 그려진 것으로 보고, 목록 가운데로 내린다."""
    pw, browser = _chromium()
    try:
        page = _wide_page(browser)
        page.set_content(COVERED)
        assert page.evaluate("document.getElementById('foot') !== null")
        result = navermap.capture(page, tmp_path / "shot.png", "출장자 1 가는 길", wait=lambda s: page.wait_for_timeout(int(s * 50)))
        assert any(s.startswith("경로 목록을") and "보이게 내림" in s for s in result.steps), result.steps
        assert _drawn_in(page, "#short", "94km")        # 찍을 때 그대로 남은 자리 — 아래 줄 밑이 아니다
        assert result.km == 94
    finally:
        browser.close()
        pw.stop()


# 스크롤 칸이 아니라 마우스 휠로만 움직이는 목록(내용을 옮겨 그림) — 스크립트로는 못 내리고, 사람처럼 휠을 굴린다
WHEEL_ONLY = (NAVER_LIKE.replace("<div id='list' style='flex:1;overflow-y:auto'>",
                                 "<div id='list' style='flex:1;min-height:0;overflow:clip'><div id='inner'>")
              .replace("  </div>\n </div>\n <div id='detail'", "  </div></div>\n </div>\n <div id='detail'")
              .replace("<script>", """<script>
 let off = 0;
 document.getElementById('list').addEventListener('wheel', e => {
   e.preventDefault();
   const list = document.getElementById('list'), inner = document.getElementById('inner');
   off = Math.max(0, Math.min(inner.scrollHeight - list.clientHeight, off + e.deltaY));
   inner.style.transform = 'translateY(' + (-off) + 'px)'; window.wheelOff = off; }, {passive: false});
 document.addEventListener('mousemove', e => { const it = e.target.closest && e.target.closest('.item'); window.hovered = it ? (it.id || 'other') : ''; });
"""))


def test_capture_wheels_a_list_that_scripts_cannot_scroll(tmp_path):
    pw, browser = _chromium()
    try:
        page = _wide_page(browser)
        page.set_content(WHEEL_ONLY)
        result = navermap.capture(page, tmp_path / "shot.png", "출장자 1 가는 길", wait=lambda s: page.wait_for_timeout(int(s * 50)))
        assert _step(result, "경로 목록을 마우스 휠로 '거리우선' 이 보이게 내림"), result.steps
        assert page.evaluate("window.wheelOff") > 0
        assert _drawn_in(page, "#short", "94km")
        assert page.evaluate("window.hovered") == "short"        # 휠을 굴린 마우스는 거리우선 위에 둔다(다른 경로를 밝히지 않게)
    finally:
        browser.close()
        pw.stop()


def test_capture_says_when_the_list_cannot_be_moved(tmp_path):
    """덮인 채 움직이지 않는 목록 — 내렸다고 하지 않고 그림을 확인하라고 남긴다(무엇이 덮었는지와 함께)."""
    pw, browser = _chromium()
    try:
        page = browser.new_context(no_viewport=True).new_page()
        page.set_content(COVERED.replace("padding-bottom:170px", "overflow:hidden").replace("overflow-y:auto;", ""))
        result = navermap.capture(page, tmp_path / "shot.png", "출장자 1 가는 길", wait=lambda s: page.wait_for_timeout(int(s * 50)))
        assert _step(result, "경로 목록을 '거리우선' 이 보이게 내리지 못함"), result.steps
        assert any("그 자리에 div" in s for s in result.steps)
        assert (tmp_path / "shot.png").exists()
    finally:
        browser.close()
        pw.stop()
