"""주차등록 2단계 — 앱 칸의 값으로 할인 링크 만들기(parking_link.py). 실측(2026-10-21 15:06) 모양을 흉내 낸 가짜 화면으로 본다.
실제 Chromium 으로는 모의 사이트(Bootstrap 창 · 표)에서 따로 확인했다(CLAUDE.md 20절)."""
from __future__ import annotations

import datetime as dt

from claim_downloader import parking, parking_link as pl

START = dt.datetime(2026, 10, 23, 9, 0)
END = dt.datetime(2026, 10, 23, 18, 0)
PRODUCT = "교환공무확인증4시간 (잔량 85)"


class Site:
    """할인 링크 화면 하나 — 목록 · [새 링크] 창 · 칸 값."""

    def __init__(self, products=("선택", PRODUCT), logged_in=True, keeps_values=True, saves=True):
        self.rows = [["test", "강원대학교 춘천캠퍼스", "교환공무확인증4시간", "공무확인증4시간", "2026-10-21 14:12 ~", "활성"]]
        self.form_open = False
        self.products = list(products)
        self.lots = ["선택", "강원대학교 춘천캠퍼스"]
        self.values = {}
        self.logged_in = logged_in
        self.keeps_values = keeps_values
        self.saves = saves
        self.clicked = []


class Frame:
    def __init__(self, site, page):
        self.site, self.page = site, page

    def evaluate(self, js, *args):
        s = self.site
        if js == parking.LOGIN_FORM_JS:
            return 0 if s.logged_in else 1
        if not s.logged_in:
            return None if js == pl.ROWS_JS else 0
        if js == pl.ROWS_JS:
            return [list(r) for r in s.rows]
        if js == pl.OPEN_COUNT_JS:
            return 1
        if js == pl.OPEN_JS:
            s.clicked.append("새 링크")
            s.form_open = True
            return {"ok": True}
        if js == pl.FORM_OPEN_JS:
            return s.form_open
        if js == pl.MARK_FORM_JS:
            if not s.form_open:
                return {"open": False}
            return {"open": True, "ok": True, "labels": {"name": "링크명", "lot": "주차장", "product": "할인권상품", "start": "", "end": ""},
                    "lots": s.lots, "lot_index": 1, "products": s.products, "product_index": 0, "restart": True}
        if js == pl.READ_FORM_JS:
            v = s.values
            return {"name": v.get("name", ""), "lot": s.lots[v.get("lot", 1)], "product": s.products[v.get("product", 0)],
                    "start": v.get("start", ""), "end": v.get("end", ""), "active": v.get("active", True)}
        if js == pl.FEEDBACK_JS:
            return ["유효기간을 확인하세요"]
        raise AssertionError(js[:60])

    def fill(self, selector, value):
        key = {pl.NAME_SELECTOR: "name", pl.START_SELECTOR: "start", pl.END_SELECTOR: "end"}[selector]
        if self.site.keeps_values:
            self.site.values[key] = value

    def select_option(self, selector, index):
        self.site.values[{pl.LOT_SELECTOR: "lot", pl.PRODUCT_SELECTOR: "product"}[selector]] = index

    def set_checked(self, selector, checked):
        self.site.values[{pl.ACTIVE_SELECTOR: "active", pl.RESTART_SELECTOR: "restart"}[selector]] = checked

    def click(self, selector):
        assert selector == pl.SAVE_SELECTOR
        s = self.site
        s.clicked.append("저장")
        for handler in list(self.page.handlers):
            handler(Dialog())
        if s.saves:
            s.form_open = False
            v = s.values
            s.rows.insert(0, [v["name"], s.lots[v["lot"]], pl.product_name(s.products[v["product"]]), "", v["start"], "활성"])


class Dialog:
    message = "저장되었습니다."

    def accept(self):
        pass


class Page:
    def __init__(self, site, url="https://traffic.kangwon.ac.kr/discount-links"):
        self.url = url
        self.handlers = []
        self.main_frame = Frame(site, self)
        self.went = []

    def goto(self, url, wait_until=None):
        self.went.append(url)
        self.url = url

    def on(self, name, handler):
        self.handlers.append(handler)

    def remove_listener(self, name, handler):
        self.handlers.remove(handler)


def run(site, page=None, **kw):
    page = page or Page(site)
    request = pl.LinkRequest(name=kw.pop("name", "10/23 자문위원 방문"), start=START, end=END, **kw)
    logs = []
    return pl.create(page, request, logs.append, wait=lambda s: None, base_url="https://traffic.kangwon.ac.kr", save_timeout=0.2), page, logs


def test_creates_link_and_presses_new_and_save_only():
    site = Site()
    report, page, logs = run(site)
    assert report.ok, report.lines()
    assert site.clicked == ["새 링크", "저장"]
    assert site.values == {"name": "10/23 자문위원 방문", "lot": 1, "product": 1, "start": "2026-10-23T09:00",
                           "end": "2026-10-23T18:00", "active": True, "restart": False}
    assert report.row[0] == "10/23 자문위원 방문" and report.products == [PRODUCT]
    assert report.messages == ["저장되었습니다."] and not page.handlers       # 처리기는 [저장] 동안만
    assert "칸 이름" in logs[0] and page.went == ["https://traffic.kangwon.ac.kr/discount-links"]   # 떠 있어도 새로 연다


def test_goes_to_links_page_first():
    site = Site()
    page = Page(site, url="https://traffic.kangwon.ac.kr/discount-apply")
    report, page, _ = run(site, page)
    assert report.ok and page.went == ["https://traffic.kangwon.ac.kr/discount-links"]


def test_same_name_is_not_added_again():
    site = Site()
    report, _, _ = run(site, name="test")
    assert not report.ok and "이미 있어" in report.note and site.clicked == []


def test_not_logged_in_says_so():
    site = Site(logged_in=False)
    report, _, _ = run(site)
    assert not report.ok and "로그인돼 있지 않습니다" in report.note and site.clicked == []


def test_product_choice():
    assert pl.choose(["선택", PRODUCT]) == (1, "")
    assert pl.choose(["선택", PRODUCT], "교환공무확인증4시간") == (1, "")
    assert pl.choose(["선택", "A (잔량 1)", "B (잔량 2)"])[0] is None                  # 여럿이면 앱에서 골라야
    assert pl.choose(["선택", "A (잔량 1)", "B (잔량 2)"], "B")[0] == 2
    assert pl.choose(["선택"])[0] is None
    site = Site(products=("선택", "A (잔량 1)", "B (잔량 2)"))
    report, _, _ = run(site)
    assert not report.ok and "골라야" in report.note and report.products == ["A (잔량 1)", "B (잔량 2)"]
    assert site.clicked == ["새 링크"]                                              # [저장] 은 누르지 않았다
    report, _, _ = run(Site(products=("선택", "A (잔량 1)", "B (잔량 2)")), product="B")
    assert report.ok


def test_values_not_taken_means_no_save():
    site = Site(keeps_values=False)
    report, _, _ = run(site)
    assert not report.ok and "남지 않았습니다" in report.note and "저장" not in site.clicked


def test_form_stays_open_after_save_is_reported():
    site = Site(saves=False)
    report, _, _ = run(site)
    assert not report.ok and "창이 그대로" in report.note and "유효기간을 확인하세요" in report.note


def test_request_checks():
    assert pl.LinkRequest(name=" ", start=START, end=END).problems() == ["링크 이름을 넣어 주세요"]
    assert "끝이 시작보다" in pl.LinkRequest(name="a", start=END, end=START).problems()[0]
    report, _, _ = run(Site(), name="")
    assert not report.ok and "링크 이름" in report.note
