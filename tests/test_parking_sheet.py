"""관리대장 구글 시트 연동(parking_sheet.py) — 담당자 2026-10-22 "할인내역을 구글시트에 저장하고 그 구글시트를 연동해서 어플에서 관리대장을 확인".

진짜 구글은 부를 수 없으므로 Apps Script 웹 앱처럼 구는 가짜 서버(POST → 302 → GET 으로 결과)를 띄운다. 이름 · 차량번호는 모양만 같은 가짜다.
"""
from __future__ import annotations

import http.server
import json
import threading
import uuid

import pytest

from claim_downloader import parking_ledger as ledger
from claim_downloader import parking_sheet as sheet


class FakeWebApp:
    """스크립트(parking_sheet.SCRIPT)가 하는 일을 흉내 — 시트 칸은 글자로(getDisplayValues)."""

    def __init__(self, token="tok", html=False):
        self.token, self.html = token, html
        self.ledger: list[list[str]] = []
        self.history: list[list[str]] = []
        self.history_keys: set[str] = set()
        self.answers: dict[str, dict] = {}
        self.calls: list[str] = []
        app = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                key = uuid.uuid4().hex
                app.answers[key] = app.handle(body)
                self.send_response(302)                       # 구글처럼 결과 주소로 돌린다
                self.send_header("Location", f"/echo?id={key}")
                self.end_headers()

            def do_GET(self):
                if app.html:                                  # '모든 사용자' 로 배포하지 않으면 로그인 화면(HTML)이 온다
                    data = b"<html><body>Sign in</body></html>"
                else:
                    data = json.dumps(app.answers.pop(self.path.split("id=")[1])).encode("utf-8")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/macros/s/x/exec"

    def handle(self, body):
        self.calls.append(body.get("action"))
        if body.get("token") != self.token:
            return {"ok": False, "error": "토큰이 다릅니다"}
        info = {"name": "공무확인증 관리대장", "url": "https://docs.google.com/spreadsheets/d/x"}
        if body["action"] == "ping":
            return dict(ok=True, **info)
        if body["action"] == "ledger_get":
            return dict(ok=True, rows=[list(r) for r in self.ledger], **info)
        if body["action"] == "ledger_put":
            self.ledger = [["" if c is None else str(c) for c in r] for r in body["rows"]]
            return dict(ok=True, count=len(self.ledger), **info)
        if body["action"] == "history_add":
            added = 0
            for row, key in zip(body["rows"], body["keys"]):
                if key not in self.history_keys:
                    self.history_keys.add(key)
                    self.history.append(row)
                    added += 1
            return dict(ok=True, added=added, **info)
        return {"ok": False, "error": "모르는 요청"}

    def config(self, token=None):
        return sheet.Config(url=self.url, token=token or self.token)

    def close(self):
        self.server.shutdown()


@pytest.fixture
def app(isolated_home):
    fake = FakeWebApp()
    sheet.save_config(fake.config())
    yield fake
    fake.close()


def test_merge_rules():
    a = ledger.Entry(date="2026-10-01", bought=100, id="a", updated="2026-10-21T01:00:00.000Z")
    b_local = ledger.Entry(date="2026-10-02", given=1, user="옛", id="b", updated="2026-10-21T01:00:00.000Z")
    b_sheet = ledger.Entry(date="2026-10-02", given=1, user="새", id="b", updated="2026-10-21T02:00:00.000Z")   # 시트에서 나중에 고침
    c = ledger.Entry(date="2026-10-03", given=1, id="c")       # 이 PC 에서 새로 적음(시트에 올린 적 없음)
    d = ledger.Entry(date="2026-10-04", given=1, id="d")       # 지난번 맞춘 뒤 시트에서 지움
    e = ledger.Entry(date="2026-10-05", given=1, id="e")       # 시트에서 새로 적음
    f = ledger.Entry(date="2026-10-06", given=1, id="f")       # 이 PC 에서 지움
    merged = ledger.merge([a, b_local, c, d], [a, b_sheet, e, f], synced={"a", "b", "d", "f"}, deleted={"f"})
    assert [(x.id, x.user) for x in merged] == [("a", ""), ("b", "새"), ("c", ""), ("e", "")]


def test_sheet_rows_round_trip():
    entries = [ledger.Entry(date="2026-10-01", bought=100, content="구입(이월)"),
               ledger.Entry(date="2026-10-02", given=1, content="방문", user="가나다", car="12가3456", note="공무확인증4시간 · 10:03 할인", source="site")]
    rows = ledger.to_sheet(entries)
    assert list(ledger.SHEET_HEAD[:9]) == ["일자", "구입", "배부", "잔여", "내용", "사용자", "차량번호", "비고", "적은 곳"]
    assert rows[1][:9] == ["2026-10-02", "", 1, 99, "방문", "가나다", "12가3456", "공무확인증4시간 · 10:03 할인", "사이트 할인 내역"]
    shown = [["" if c == "" else str(c) for c in r] for r in rows]
    shown[0][0] = "2026. 10. 1"                                  # 시트가 날짜를 제 꼴로 보여도
    back = ledger.from_sheet(shown + [["", "", "", "", "", "", "", "", "", "", "", ""]])
    assert [(e.date, e.bought, e.given, e.user, e.car, e.source, e.id) for e in back] == [
        (x.date, x.bought, x.given, x.user, x.car, x.source, x.id) for x in entries]
    # 시트에 손으로 더한 줄 — id 가 없으면 새로 준다
    (hand,) = ledger.from_sheet([["2026-10-09", "", "2", "", "회의", "라마바", "", "", "", "", "", ""]])
    assert hand.given == 2 and hand.id and hand.source == "manual"


def test_check_and_script_token(app):
    result = sheet.check()
    assert result.ok and "공무확인증 관리대장" in result.note
    assert sheet.load_config().sheet_url == "https://docs.google.com/spreadsheets/d/x"
    text, config = sheet.script_text()
    assert f"const TOKEN = '{config.token}';" in text and "__TOKEN__" not in text
    assert sheet.script_text()[1].token == config.token                  # 다시 복사해도 같은 토큰
    assert sheet.looks_like_web_app("https://script.google.com/macros/s/AKfy/exec")
    assert not sheet.looks_like_web_app("https://docs.google.com/spreadsheets/d/x/edit")


def test_wrong_token_and_html_answer(isolated_home):
    fake = FakeWebApp()
    try:
        result = sheet.check(fake.config(token="다른것"))
        assert not result.ok and "토큰이 다릅니다" in result.note
        fake.html = True
        result = sheet.check(fake.config())
        assert not result.ok and "모든 사용자" in result.note
    finally:
        fake.close()
    assert not sheet.check(sheet.Config()).ok


def test_sync_both_ways(app):
    ledger.add(ledger.Entry(date="2026-10-01", bought=100, content="구입(이월)"))
    ledger.add(ledger.Entry(date="2026-10-02", given=1, content="방문", user="가나다", car="12가3456"))
    first = sheet.sync_ledger()
    assert first.ok and first.total == 2 and len(app.ledger) == 2 and app.ledger[1][3] == "99"     # 잔여도 시트에
    # 시트에서 사용자를 고치고(수정시각이 늦음) 줄을 하나 더함
    app.ledger[1][5], app.ledger[1][10] = "라마바", "2999-01-01T00:00:00.000Z"
    app.ledger.append(["2026-10-03", "", "1", "", "워크숍", "사바아", "", "", "", "", "", ""])
    second = sheet.sync_ledger()
    assert second.ok and second.changed and second.total == 3
    assert [(e.user, e.date) for e in ledger.load()] == [("", "2026-10-01"), ("라마바", "2026-10-02"), ("사바아", "2026-10-03")]
    # 이 PC 에서 지운 줄은 시트에서도 지워진다
    gone = ledger.load()[2]
    ledger.remove(gone.id)
    assert sheet.sync_ledger().ok and len(app.ledger) == 2 and all(r[9] != gone.id for r in app.ledger)
    assert ledger.sync_state()[1] == set()                                 # 알렸으니 지운 목록에서 빠짐
    # 시트에서 지운 줄은 이 PC 에서도 지워진다
    app.ledger = app.ledger[:1]
    assert sheet.sync_ledger().ok and len(ledger.load()) == 1


def test_sync_fails_without_touching_local(app):
    ledger.add(ledger.Entry(date="2026-10-01", bought=100))
    app.token = "바뀜"
    result = sheet.sync_ledger()
    assert not result.ok and "토큰" in result.note and len(ledger.load()) == 1 and ledger.sync_state()[0] == set()


def test_history_rows_are_kept_once(app):
    headers = ["할인일시arrow_downward", "차량번호", "할인명"]
    rows = [["2026-10-20 17:37:04", "09주5782", "공무확인증4시간"], ["2026-10-19 11:33:29", "38어3853", "공무확인증4시간"]]
    first = sheet.push_history(headers, rows)
    again = sheet.push_history(headers, rows + [["2026-10-21 09:00:00", "12가3456", "공무확인증4시간"]])
    assert first.ok and first.added == 2 and again.added == 1 and len(app.history) == 3
    assert "2026-10-20 17:37:04|09주5782" in app.history_keys


def test_script_has_the_actions_the_app_uses():
    for action in ("ping", "ledger_get", "ledger_put", "history_add"):
        assert f"body.action === '{action}'" in sheet.SCRIPT
    assert "body.token !== TOKEN" in sheet.SCRIPT and "LockService" in sheet.SCRIPT
    head = sheet.SCRIPT.split("const LEDGER_HEAD = [")[1].split("]")[0]
    assert [h.strip(" '") for h in head.split(",")] == list(ledger.SHEET_HEAD)
