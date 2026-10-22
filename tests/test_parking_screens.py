"""주차등록 — 할인 적용(차량번호 → 보유 할인권 → 할인 선택 → [종료]) · 할인 내역(표 읽기만). 두 화면 모두 실측 전이라 가짜 화면으로 갈래만 본다.
실제 Chromium 으로는 모의 사이트에서 따로 확인했다(CLAUDE.md 20절)."""
from __future__ import annotations

from claim_downloader import parking, parking_screens as ps

CAR = "12가3456"


class Frame:
    """가짜 화면 — 할인 적용은 단계(stage)마다 SCAN_APPLY_JS 의 답을 바꾼다(실제 Chromium 은 모의 사이트로 따로)."""

    def __init__(self, logged_in=True, shape=None, table=None, keeps=True, scans=None):
        self.logged_in = logged_in
        self.shape = shape if shape is not None else {"ok": True, "label": "차량번호", "inputs": ["차량번호"], "selects": [],
                                                      "buttons": ["조회"]}
        self.table = table
        self.keeps = keeps
        self.value = None
        self.filled = []
        self.clicked = []
        self.pressed = []
        self.selected = []
        self.scans = scans or {}           # stage → SCAN_APPLY_JS 의 답
        self.stage = "typed"
        self.feedback = []
        self.page = None

    def evaluate(self, js, *args):
        if js == parking.LOGIN_FORM_JS:
            return 0 if self.logged_in else 1
        if js == ps.MARK_CAR_JS:
            return self.shape
        if js == ps.CAR_VALUE_JS:
            return "" if self.stage == "reset" else self.value
        if js == ps.TABLE_JS:
            return self.table
        if js == ps.SCAN_APPLY_JS:
            assert args[0]["word"] == "공무확인증"
            return self.scans.get(self.stage, self.scans.get("*", {}))
        if js == ps.FEEDBACK_JS:
            return self.feedback
        if js in (ps.HISTORY_CONTROLS_JS, ps.HISTORY_NEXT_JS):
            return {}                      # 거르기 칸 · 쪽 단추가 없는 화면
        raise AssertionError(js[:60])

    def fill(self, selector, value):
        assert selector == ps.CAR_SELECTOR
        self.filled.append(value)
        if self.keeps:
            self.value = value

    def press(self, selector, key):
        assert (selector, key) == (ps.CAR_SELECTOR, "Enter")
        self.pressed.append(key)
        self.stage = self.scans.get("after_enter", "found")

    def click(self, selector, timeout=None):
        mark = selector.split("=", 1)[1].rstrip("]")
        self.clicked.append(mark)
        self.stage = self.scans.get("after_" + mark, self.stage)
        if mark == "finish-0" and self.page is not None:
            for message in self.scans.get("finish_dialogs", []):
                self.page.dialog(message)

    def select_option(self, selector, index):
        self.selected.append((selector, index))
        self.stage = self.scans.get("after_select", self.stage)


class Dialog:
    def __init__(self, message):
        self.message = message
        self.accepted = False

    def accept(self):
        self.accepted = True


class Page:
    def __init__(self, frame):
        self.main_frame = frame
        frame.page = self
        self.went = []
        self.handlers = []

    def goto(self, url, wait_until=None):
        self.went.append(url)

    def on(self, name, handler):
        self.handlers.append(handler)

    def remove_listener(self, name, handler):
        self.handlers.remove(handler)

    def dialog(self, message):
        for handler in list(self.handlers):
            handler(Dialog(message))


def apply(frame, car=CAR):
    page, logs = Page(frame), []
    report = ps.apply_discount(page, car, logs.append, wait=lambda s: None, base_url="https://traffic.kangwon.ac.kr", finish_wait=1.0)
    return report, page, logs


def history(frame):
    page, logs = Page(frame), []
    report = ps.read_history(page, logs.append, wait=lambda s: None, base_url="https://traffic.kangwon.ac.kr", tries=8)
    return report, page, logs


OWN = {"text": "교환공무확인증4시간 85매", "section": "own", "active": False}
PICK_SELECT = {"options": [{"index": 1, "text": "공무확인증4시간"}], "chosen": "선택", "section": "pick"}


def flow(**changes):
    """담당자가 알려 준 차례 그대로인 화면 — 차량번호 Enter → 그 차 보임 → 보유 할인권 '공무확인증' → 할인 선택(고르기 칸) → [종료]."""
    scans = {
        "found": {"carShown": True, "cars": 0, "tickets": [OWN], "selects": [], "finishes": 1, "searches": 1},
        "picked": {"carShown": True, "cars": 0, "tickets": [OWN], "selects": [PICK_SELECT], "finishes": 1},
        "chosen": {"carShown": True, "cars": 0, "tickets": [OWN], "selects": [dict(PICK_SELECT, chosen="공무확인증4시간")], "finishes": 1},
        "after_ticket-0": "picked", "after_select": "chosen", "after_finish-0": "reset",
        "reset": {"carShown": False, "tickets": [OWN], "selects": [], "finishes": 1},
        "finish_dialogs": ["할인을 적용하시겠습니까?", "12가3456 차량에 할인이 적용되었습니다."],
    }
    scans.update(changes)
    return Frame(scans=scans)


def test_apply_goes_through_the_described_steps():
    frame = flow()
    report, page, logs = apply(frame, " 12가 3456 ")
    assert report.applied and report.confirmed and report.pressed_finish and not report.capture
    assert frame.filled == [CAR] and frame.pressed == ["Enter"]                        # 띄어쓰기만 뗀다
    assert frame.clicked == ["ticket-0", "finish-0"] and frame.selected == [("[data-coss-apply=select-0]", 1)]
    assert page.went == ["https://traffic.kangwon.ac.kr/discount-apply"]
    assert report.ticket == "교환공무확인증4시간"                                        # 남은 수는 뗀다
    assert report.left_before == 85                    # 보유 할인권 글자의 남은 수 — 화면이 관리대장 잔여를 맞춘다(85 → 적용 뒤 84)
    assert CAR not in "\n".join(logs + report.lines()) and "(차량번호)" in report.messages[-1]   # 차량번호는 기록에 남기지 않는다
    assert "✓ 할인을 적용했습니다" in report.lines()[0] and not page.handlers


def test_apply_clicks_choice_button_and_car_row_when_needed():
    pick = {"text": "공무확인증", "section": "pick", "active": False}
    frame = flow(found={"carShown": True, "cars": 1, "tickets": [], "selects": [], "finishes": 1},
                 **{"after_car-0": "listed",
                    "listed": {"carShown": True, "cars": 1, "tickets": [OWN], "selects": [], "finishes": 1},
                    "picked": {"carShown": True, "cars": 1, "tickets": [OWN, pick], "selects": [], "finishes": 1},
                    "after_ticket-1": "picked"})
    report, _, _ = apply(frame)
    assert report.applied and frame.clicked == ["car-0", "ticket-0", "ticket-1", "finish-0"]


def test_apply_searches_once_when_enter_does_nothing():
    frame = flow(after_enter="typed", typed={"carShown": False, "searches": 1}, **{"after_search-0": "found"})
    report, _, _ = apply(frame)
    assert report.applied and frame.clicked[0] == "search-0"


def test_apply_stops_before_finish_when_unsure():
    cases = [
        (flow(found={"carShown": True, "cars": 2, "tickets": [], "finishes": 1}), "2대"),
        (flow(found={"carShown": True, "tickets": [OWN, dict(OWN, text="교환공무확인증2시간")], "finishes": 1}), "여럿"),
        (flow(found={"carShown": True, "tickets": [], "finishes": 1}), "찾지 못했습니다"),
        (flow(picked={"carShown": True, "tickets": [OWN], "selects": [], "finishes": 1, "pickHasWord": True}), "고를 칸"),
        (flow(chosen={"carShown": True, "tickets": [OWN], "selects": [dict(PICK_SELECT, chosen="공무확인증4시간")], "finishes": 2}), "여럿"),
        (flow(picked={"carShown": True, "tickets": [OWN], "finishes": 1,
                      "selects": [dict(PICK_SELECT, options=[{"index": 1, "text": "공무확인증2시간"}, {"index": 2, "text": "공무확인증8시간"}])]}),
         "여럿"),
        (flow(chosen={"carShown": True, "tickets": [OWN], "selects": [PICK_SELECT], "finishes": 1}), "골라지지"),
        (flow(after_enter="typed", typed={"carShown": False, "searches": 0}), "찾지 못했습니다"),
    ]
    for frame, why in cases:
        report, _, logs = apply(frame)
        assert not report.applied and not report.pressed_finish and report.capture, why
        assert "finish-0" not in frame.clicked and why in report.note, (why, report.note)
        assert "[종료] 는 누르지 않았습니다" in report.lines()[0] and any("멈춘 화면" in line for line in logs)


def test_apply_stops_on_site_failure_message():
    frame = flow(**{"after_ticket-0": "picked"})
    real_click = frame.click

    def click(selector, timeout=None):
        real_click(selector, timeout)
        if "ticket-0" in selector:
            frame.page.dialog("잔여 할인권이 없습니다.")
    frame.click = click
    report, _, _ = apply(frame)
    assert not report.applied and "잔여 할인권이 없습니다" in report.note and "finish-0" not in frame.clicked


def test_apply_after_finish_without_word_or_reset_is_unknown():
    frame = flow(finish_dialogs=[], **{"after_finish-0": "chosen"})
    report, _, _ = apply(frame)
    assert report.pressed_finish and not report.applied and report.capture and "알리지 않았습니다" in report.note
    frame = flow(finish_dialogs=[])                       # 완료 글은 없지만 처음 화면으로 돌아감
    report, _, _ = apply(frame)
    assert report.applied and not report.confirmed


def test_apply_needs_car_and_login_and_field():
    report, page, _ = apply(flow(), "")
    assert not report.opened and "넣어 주세요" in report.note and page.went == []
    report, _, _ = apply(Frame(logged_in=False))
    assert not report.opened and "로그인돼 있지 않습니다" in report.note
    frame = Frame(shape={"ok": False, "why": "차량번호로 보이는 칸이 여럿", "inputs": ["차량번호", "차량번호"], "buttons": []})
    report, _, _ = apply(frame)
    assert report.opened and not report.filled and frame.filled == [] and report.capture and "여럿" in report.note
    report, _, _ = apply(Frame(keeps=False))
    assert not report.filled and "남지 않았습니다" in report.note


def test_mask_cars():
    assert ps.mask_cars("12가3456 · 123나 4567 · 2026-10-21") == "(차량번호) · (차량번호) · 2026-10-21"


def test_history_reads_table_and_logs_only_headers():
    table = {"tables": 1, "headers": ["일시", "차량번호", "할인권 상품"], "rows": [["2026-10-21 10:00", CAR, "교환공무확인증4시간"]],
             "note": "", "pager": "1 2 다음", "total": "총 12건"}
    report, page, logs = history(Frame(table=table))
    assert report.ok and report.rows == [["2026-10-21 10:00", CAR, "교환공무확인증4시간"]] and report.headers[1] == "차량번호"
    assert page.went == ["https://traffic.kangwon.ac.kr/discount-history"]
    assert CAR not in "\n".join(logs) and "차량번호" in logs[0] and "1줄" in logs[0]   # 차량번호 값은 기록에 남기지 않는다
    assert report.pages == 1 and "1쪽" in report.lines()[0] and not report.pager and "총 12건" in logs[0]


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


HEAD = ["할인일시arrow_downward", "차량번호", "할인명", "적용방식", "적용금액"]


class HistoryFrame:
    """할인 내역 화면(실측 2026-10-22 10:07) — 시작일 · 건수 고르기 · [검색] · 쪽 단추 '›'. 처음엔 사이트 기본 기간(첫 묶음)만 보인다."""

    def __init__(self, pages, from_value="2026-09-22", size="20건", moves=True, searches=1):
        self.pages, self.from_value, self.size, self.moves, self.searches = pages, from_value, size, moves, searches
        self.widened = False
        self.index = 0
        self.filled, self.clicked, self.selected = [], [], []
        self.page = None

    def _shown(self):
        return self.pages if self.widened else self.pages[:1]

    def evaluate(self, js, *args):
        if js == parking.LOGIN_FORM_JS:
            return 0
        if js == ps.TABLE_JS:
            return {"tables": 1, "headers": HEAD, "rows": [list(r) for r in self._shown()[self.index]], "note": "",
                    "pager": " ".join(str(n + 1) for n in range(len(self._shown()))), "total": ""}
        if js == ps.HISTORY_CONTROLS_JS:
            return {"from": self.from_value, "dates": 2, "size": self.size, "big": "100건", "searches": self.searches}
        if js == ps.HISTORY_NEXT_JS:
            last = len(self._shown())
            return {"current": str(self.index + 1), "last": last, "next": self.index + 1 < last}
        raise AssertionError(js[:60])

    def select_option(self, selector, label=None, timeout=None):
        assert selector == "[data-coss-history=size]"
        self.selected.append(label)
        self.size = label

    def fill(self, selector, value, timeout=None):
        assert selector == "[data-coss-history=from]"
        self.filled.append(value)
        self.from_value = value

    def click(self, selector, timeout=None):
        mark = selector.split("=", 1)[1].rstrip("]")
        assert mark in ("search", "next"), mark            # 표의 줄 · 차량번호 · 엑셀은 누르지 않는다
        self.clicked.append(mark)
        if mark == "search":
            self.widened, self.index = True, 0
        elif self.moves:
            self.index += 1


def _rows(n, start=0):
    return [[f"2026-10-{20 - i:02d} 10:00:00", f"{10 + i}가{1000 + i}", "공무확인증4시간", "수동", "1,000"] for i in range(start, start + n)]


def test_history_reads_every_page_from_the_start_date():
    """담당자 2026-10-22: "지금 1페이지만 확인했는데 전체 페이지 확인해주세요" — 시작일을 앞당기고 100건씩 '›' 로 끝 쪽까지."""
    frame = HistoryFrame([_rows(3), _rows(3, 3), _rows(2, 6)])
    page, logs = Page(frame), []
    report = ps.read_history(page, logs.append, wait=lambda s: None, base_url="https://traffic.kangwon.ac.kr", tries=6, since="2026-01-01")
    assert report.ok and len(report.rows) == 8 and report.pages == 3 and not report.pager and report.since == "2026-01-01"
    assert frame.selected == ["100건"] and frame.filled == ["2026-01-01"] and frame.clicked == ["search", "next", "next"]
    assert "3쪽" in logs[-1] and "2026-01-01부터" in logs[-1] and "10가1000" not in "\n".join(logs)
    assert report.read_stamp[:2] == "20" and len(report.read_stamp) == 19


def test_history_keeps_an_earlier_start_and_stops_when_paging_sticks():
    frame = HistoryFrame([_rows(2), _rows(2, 2), _rows(1, 4)], from_value="2025-12-01", size="100건", moves=False)
    frame.widened = True
    report = ps.read_history(Page(frame), [].append, wait=lambda s: None, base_url="", tries=6, since="2026-01-01")
    assert report.ok and frame.filled == [] and frame.selected == [] and report.since == "2025-12-01"
    assert len(report.rows) == 2 and "1쪽에서 다음 쪽으로 넘어가지 않아" in report.pager


def test_history_without_search_button_reads_default_range_and_says_so():
    frame = HistoryFrame([_rows(2), _rows(2, 2)], searches=0)
    report = ps.read_history(Page(frame), [].append, wait=lambda s: None, base_url="", tries=6, since="2026-01-01")
    assert report.ok and len(report.rows) == 2 and "기본 기간만" in report.pager and frame.clicked == []
