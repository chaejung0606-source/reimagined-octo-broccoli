"""주차등록 — 할인 적용(차량번호 칸에 넣어 두기) · 할인 내역(표 읽기만). 두 화면 모두 실측 전이라 가짜 화면으로 갈래만 본다.
실제 Chromium 으로는 모의 사이트에서 따로 확인했다(CLAUDE.md 20절)."""
from __future__ import annotations

from claim_downloader import parking, parking_screens as ps

CAR = "12가3456"


class Frame:
    def __init__(self, logged_in=True, shape=None, table=None, keeps=True):
        self.logged_in = logged_in
        self.shape = shape if shape is not None else {"ok": True, "label": "차량번호", "inputs": ["차량번호"], "selects": [],
                                                      "buttons": ["조회"]}
        self.table = table
        self.keeps = keeps
        self.value = None
        self.filled = []

    def evaluate(self, js, *args):
        if js == parking.LOGIN_FORM_JS:
            return 0 if self.logged_in else 1
        if js == ps.MARK_CAR_JS:
            return self.shape
        if js == ps.CAR_VALUE_JS:
            return self.value
        if js == ps.TABLE_JS:
            return self.table
        raise AssertionError(js[:60])

    def fill(self, selector, value):
        assert selector == ps.CAR_SELECTOR
        self.filled.append(value)
        if self.keeps:
            self.value = value


class Page:
    def __init__(self, frame):
        self.main_frame = frame
        self.went = []

    def goto(self, url, wait_until=None):
        self.went.append(url)


def apply(frame, car=CAR):
    page, logs = Page(frame), []
    report = ps.open_apply(page, car, logs.append, wait=lambda s: None, base_url="https://traffic.kangwon.ac.kr", tries=3)
    return report, page, logs


def history(frame):
    page, logs = Page(frame), []
    report = ps.read_history(page, logs.append, wait=lambda s: None, base_url="https://traffic.kangwon.ac.kr", tries=8)
    return report, page, logs


def test_apply_puts_car_number_and_presses_nothing():
    frame = Frame()
    report, page, logs = apply(frame, " 12가 3456 ")
    assert report.opened and report.filled and frame.filled == [CAR]          # 띄어쓰기만 뗀다
    assert page.went == ["https://traffic.kangwon.ac.kr/discount-apply"]
    assert "조회" in logs[0] and "차량번호" in logs[0]                          # 화면의 칸 · 단추 글자를 기록에
    assert "[적용]" in report.lines()[0]


def test_apply_without_car_only_opens():
    frame = Frame()
    report, _, _ = apply(frame, "")
    assert report.opened and not report.filled and frame.filled == [] and "화면만" in report.note


def test_apply_does_not_guess_when_field_is_unclear():
    frame = Frame(shape={"ok": False, "why": "차량번호로 보이는 칸이 여럿", "inputs": ["차량번호", "차량번호"], "buttons": []})
    report, _, _ = apply(frame)
    assert report.opened and not report.filled and frame.filled == [] and "여럿" in report.note


def test_apply_value_not_kept():
    report, _, _ = apply(Frame(keeps=False))
    assert not report.filled and "남지 않았습니다" in report.note


def test_apply_logged_out():
    report, _, _ = apply(Frame(logged_in=False))
    assert not report.opened and "로그인돼 있지 않습니다" in report.note


def test_history_reads_table_and_logs_only_headers():
    table = {"tables": 1, "headers": ["일시", "차량번호", "할인권 상품"], "rows": [["2026-10-21 10:00", CAR, "교환공무확인증4시간"]],
             "note": "", "pager": "1 2 다음", "total": "총 12건"}
    report, page, logs = history(Frame(table=table))
    assert report.ok and report.rows == [["2026-10-21 10:00", CAR, "교환공무확인증4시간"]] and report.headers[1] == "차량번호"
    assert page.went == ["https://traffic.kangwon.ac.kr/discount-history"]
    assert CAR not in "\n".join(logs) and "차량번호" in logs[0] and "1줄" in logs[0]   # 차량번호 값은 기록에 남기지 않는다
    assert any("처음 보여 주는 쪽" in line for line in report.lines()) and "총 12건" in report.lines()[0]


def test_history_empty_and_missing():
    report, _, _ = history(Frame(table={"tables": 1, "headers": ["일시", "차량번호"], "rows": [], "note": "조회된 내역이 없습니다"}))
    assert report.ok and report.rows == [] and "조회된 내역이 없습니다" in report.lines()[0]
    report, _, _ = history(Frame(table={"tables": 0, "headers": [], "rows": []}))
    assert not report.ok and "표가 없습니다" in report.note
    report, _, _ = history(Frame(logged_in=False))
    assert not report.ok and "로그인돼 있지 않습니다" in report.note


def test_history_waits_while_loading():
    loading = {"tables": 1, "headers": ["일시", "차량번호"], "rows": [], "note": "불러오는 중…"}
    done = {"tables": 1, "headers": ["일시", "차량번호"], "rows": [["10:00", CAR]], "note": ""}
    frame = Frame(table=loading)
    seen = []

    def wait(_s):
        seen.append(1)
        if len(seen) == 3:
            frame.table = done
    report = ps.read_history(Page(frame), [].append, wait=wait, base_url="", tries=8)
    assert report.ok and report.rows == [["10:00", CAR]]
    report = ps.read_history(Page(Frame(table=loading)), [].append, wait=lambda s: None, base_url="", tries=4)
    assert not report.ok and "넘어가지 않았습니다" in report.note
