"""관리대장 구글 시트 연동(parking_sheet.py) — 담당자 2026-10-22 "할인내역을 구글시트에 저장하고 그 구글시트를 연동해서 어플에서 관리대장을 확인".

진짜 구글은 부를 수 없으므로 Apps Script 웹 앱처럼 구는 가짜 서버(POST → 302 → GET 으로 결과)를 띄운다. 이름 · 차량번호는 모양만 같은 가짜다.
"""
from __future__ import annotations

import http.server
import json
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
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
        self.ping = {"logs": True, "status": True, "styled": True}     # 붙여 넣은 스크립트의 판(ping 이 알리는 것)
        self.style_error = ""                                          # 스크립트가 서식을 입히다 실패했을 때의 글
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
            return dict(ok=True, **self.ping, **info)
        if body["action"] == "ledger_get":
            return dict(ok=True, rows=[list(r) for r in self.ledger], **info)
        if body["action"] == "ledger_put":
            self.ledger = [["" if c is None else str(c) for c in r] for r in body["rows"]]
            return dict(ok=True, count=len(self.ledger), styleError=self.style_error, **info)
        if body["action"] == "status_put":
            self.status = body
            return dict(ok=True, count=len(body.get("rows") or []), **info)
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
    for action in ("ping", "ledger_get", "ledger_put", "history_add", "log_add", "status_put"):
        assert f"body.action === '{action}'" in sheet.SCRIPT
    assert "body.token !== TOKEN" in sheet.SCRIPT and "LockService" in sheet.SCRIPT
    head = sheet.SCRIPT.split("const LEDGER_HEAD = [")[1].split("]")[0]
    assert [h.strip(" '") for h in head.split(",")] == list(ledger.SHEET_HEAD)


# ── 구글에 붙기 · 못 붙을 때의 진단 ─────────────────────────────────────────
# 담당자 PC(2026-10-22): [저장하고 연결 확인] → '[WinError 10060] … 응답이 없어 연결하지 못했거나' (깃허브 · Claude · 브라우저는 됨).
def _listener():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    return server, server.getsockname()[1]


def _closed_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _addrinfo(*entries):
    return [(family, socket.SOCK_STREAM, 6, "", where) for family, where in entries]


def test_connect_tries_ipv4_first_and_keeps_the_read_timeout(monkeypatch):
    server, port = _listener()
    made = []
    real = socket.socket

    class Recording(real):
        def __init__(self, family=-1, *args, **kwargs):
            made.append(family)
            super().__init__(family, *args, **kwargs)

    # 운영체제가 IPv6 를 먼저 준다 — 그 주소는 닿지 않는다고 본다
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(
        (socket.AF_INET6, ("2404:6800::1", 443, 0, 0)), (socket.AF_INET, ("127.0.0.1", port))))
    monkeypatch.setattr(socket, "socket", Recording)
    monkeypatch.setattr(sheet, "CONNECT_WAITS", (1,))
    try:
        sock = sheet._connect(("script.google.com", 443), timeout=40)
        assert made == [socket.AF_INET] and sock.getpeername()[0] == "127.0.0.1"
        assert sock.gettimeout() == 40                                    # 붙은 뒤에는 읽기 시간 그대로
        sock.close()
    finally:
        server.close()


def test_connect_failure_names_every_address(monkeypatch):
    closed = _closed_port()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(
        (socket.AF_INET6, ("::1", closed, 0, 0)), (socket.AF_INET, ("127.0.0.1", closed))))
    monkeypatch.setattr(sheet, "CONNECT_PAUSE", 0)
    with pytest.raises(OSError) as caught:
        sheet._connect(("script.google.com", 443), timeout=5)
    text = str(caught.value)
    assert text.startswith("script.google.com 에 붙지 못함(3번 시도) — IPv4 127.0.0.1 거절됨 · IPv6 ::1 ")   # IPv6 를 못 쓰는 곳이어도 그 까닭으로


def test_connect_tries_again_when_google_does_not_answer_for_a_moment(isolated_home, monkeypatch):
    # 담당자 PC 진단(2026-10-22): googleusercontent 주소가 12초 동안 응답이 없다가 몇 초 뒤에는 0.0초에 붙었다
    server, port = _listener()
    real = socket.socket
    waits, lookups = [], []

    class Flaky(real):
        tries = 0

        def connect(self, where):
            waits.append(self.gettimeout())
            Flaky.tries += 1
            if Flaky.tries == 1:
                raise TimeoutError("timed out")
            return super().connect(where)

    def lookup(*args, **kwargs):
        lookups.append(args[0])
        return _addrinfo((socket.AF_INET, ("127.0.0.1", port)))

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket, "socket", Flaky)
    monkeypatch.setattr(sheet, "CONNECT_PAUSE", 0)
    try:
        sock = sheet._connect(("script.googleusercontent.com", 443), timeout=40)
        assert sock.getpeername()[0] == "127.0.0.1" and sock.gettimeout() == 40
        assert waits == list(sheet.CONNECT_WAITS[:2]) and lookups == ["script.googleusercontent.com"] * 2   # 바퀴마다 길게 · 이름도 다시
        sock.close()
    finally:
        server.close()
    from claim_downloader import settings
    assert "구글 연결: script.googleusercontent.com 에 2번째에 붙음 (처음: IPv4 127.0.0.1 응답 없음)" in settings.log_path().read_text(encoding="utf-8")


def test_https_requests_use_the_ipv4_first_connection():
    assert sheet._Https("script.google.com")._create_connection is sheet._connect
    opener = urllib.request.build_opener(sheet._HttpsHandler())
    assert any(isinstance(h, sheet._HttpsHandler) for h in opener.handlers)
    assert not any(type(h) is urllib.request.HTTPSHandler for h in opener.handlers)


def test_check_writes_why_google_could_not_be_reached(isolated_home, monkeypatch):
    def unreachable(request, timeout=0):
        raise urllib.error.URLError(OSError("script.google.com 에 붙지 못함 — IPv4 142.250.0.1 응답 없음"))

    monkeypatch.setattr(sheet, "network_report", lambda url, wait=0: ["깃허브(앱 업데이트)에는 붙는데 구글에는 못 붙습니다", "github.com: IPv4 붙음"])
    result = sheet.check(sheet.Config(url="https://script.google.com/macros/s/x/exec", token="tok"), opener=unreachable)
    assert not result.ok and "IPv4 142.250.0.1 응답 없음" in result.note
    assert "진단 — 깃허브(앱 업데이트)에는 붙는데" in result.note
    from claim_downloader import settings
    logged = settings.log_path().read_text(encoding="utf-8")
    assert "구글 시트 연결 확인 실패" in logged and "진단: github.com: IPv4 붙음" in logged
    # 시트가 거절한 것(닿기는 함)에는 진단을 붙이지 않는다
    refused = FakeWebApp()
    try:
        assert "진단" not in sheet.check(refused.config(token="다른것")).note
    finally:
        refused.close()


def test_network_report_says_what_to_do(monkeypatch):
    server, port = _listener()
    closed = _closed_port()
    table = {}
    monkeypatch.setattr(socket, "getaddrinfo", lambda name, *a, **k: table[name]())
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(sheet, "_windows_proxy", lambda: ("", False))
    good = lambda: _addrinfo((socket.AF_INET, ("127.0.0.1", port)))       # noqa: E731
    bad = lambda: _addrinfo((socket.AF_INET, ("127.0.0.1", closed)))      # noqa: E731

    def nothing():
        raise socket.gaierror(11001, "getaddrinfo failed")

    try:
        table.update({"script.google.com": good, "script.googleusercontent.com": good, "github.com": good})
        lines = sheet.network_report("https://script.google.com/macros/s/x/exec", wait=1)
        assert lines[0].startswith("지금은 구글에 붙습니다") and lines[1].startswith("script.google.com: IPv4 127.0.0.1 붙음(")
        table.update({"script.google.com": bad})
        lines = sheet.network_report("https://script.google.com/macros/s/x/exec", wait=1)
        assert lines[0].startswith("깃허브(앱 업데이트)에는 붙는데 구글에는 못 붙습니다") and "거절됨" in lines[1]
        assert lines[4] == "앱(파이썬)이 쓰는 프록시: 없음"
        # 브라우저만 자동 구성 스크립트(프록시)로 나가는 PC
        monkeypatch.setattr(sheet, "_windows_proxy", lambda: ("프록시 서버 끔 · 자동 구성 스크립트 http://pac.example/proxy.pac", True))
        lines = sheet.network_report("", wait=1)
        assert "자동 구성 스크립트" in lines[0] and lines[-1].startswith("윈도우 인터넷 설정: 프록시 서버 끔")
        table.update({"github.com": nothing})
        monkeypatch.setattr(sheet, "_windows_proxy", lambda: ("", False))
        monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "http://kim:비밀@proxy.example:8080"})
        lines = sheet.network_report("", wait=1)
        assert lines[0].startswith("구글 · 깃허브 모두 붙지 못합니다") and lines[3].startswith("github.com: 주소를 찾지 못함")
        assert "비밀" not in lines[4] and "//***@proxy.example:8080" in lines[4]
    finally:
        server.close()


def test_new_empty_sheet_does_not_wipe_the_local_ledger(app):
    """담당자 실제(2026-10-23): 지워진 시트 대신 새 시트로 연결 — 지난 시트와 맞춘 줄이 새(빈) 시트에 없다고 이 PC 의 대장을 지우면 안 된다.
    새 시트에는 이 PC 의 대장을 그대로 올린다. 웹 앱 URL 을 바꿔 저장하거나 연동을 끊어도 맞춘 기록을 잊는다."""
    ledger.add(ledger.Entry(date="2026-10-01", bought=100, content="구입(이월)"))
    ledger.add(ledger.Entry(date="2026-10-02", given=1, content="방문", user="가나다", car="12가3456"))
    assert sheet.sync_ledger().ok and len(app.ledger) == 2 and len(ledger.sync_state()[0]) == 2
    # ① 시트가 지워지고 새 시트(빈 관리대장 탭)가 같은 주소로 답하는 경우 — 탭이 비어 있으면 새로 올린다
    app.ledger = []
    result = sheet.sync_ledger()
    assert result.ok and result.total == 2 and len(ledger.load()) == 2 and len(app.ledger) == 2
    # ② 다른 시트가 답하면(주소가 다름) 맞춘 기록을 잊는다
    old_url = app.url
    config = sheet.load_config()
    assert config.sheet_url.endswith("/x")
    sheet._remember(config, {"url": "https://docs.google.com/spreadsheets/d/y", "name": "새 시트"})
    assert ledger.sync_state()[0] == set() and sheet.load_config().sheet_url.endswith("/y")
    # (가짜 시트는 늘 /x 로 답하므로 되돌려 둔다 — 다시 바뀐 것으로 보고 한 번 더 잊는다)
    sheet._remember(sheet.load_config(), {"url": "https://docs.google.com/spreadsheets/d/x", "name": "공무확인증 관리대장"})
    # ③ 지운 줄 목록은 잊지 않는다 · 연동을 끊어도 맞춘 기록을 잊는다
    assert sheet.sync_ledger().ok and len(ledger.sync_state()[0]) == 2
    gone = ledger.load()[1]
    ledger.remove(gone.id)
    assert ledger.reset_sync() == 2 and ledger.sync_state() == (set(), {gone.id})      # 지운 줄은 맞춘 id 에 남아 있다(remove 는 ids 를 안 건드린다)
    assert sheet.sync_ledger().ok and len(ledger.sync_state()[0]) == 1
    sheet.forget()
    assert ledger.sync_state()[0] == set() and not sheet.load_config().connected and len(ledger.load()) == 1
    assert old_url == app.url


# ── 관리대장 · 할인내역 서식 — 스크립트를 node 로(가짜 SpreadsheetApp) ─────────────
# 담당자 2026-10-27: "구글시트 관리대장이랑 할인내역은 보기좋게 서식을 만들어주세요". 가짜 시트는 칸 값 · 바탕 · 글자색 · 정렬 · 거르기 ·
# 숨김 · 너비 · 메모를 적어 두고, 시트 크기를 넘는 getRange 는 진짜처럼 오류를 낸다.
STYLE_HARNESS = r"""
const sheets = {};
let BREAK = '';
function makeSheet(name) {
  const sh = {name, rows: [], maxRows: 3, maxCols: 30, frozenRows: 0, frozenCols: 0, widths: {}, hidden: [], notes: {}, tab: '', heights: {},
    bg: {}, ink: {}, align: {}, bold: {}, filters: 0, filter: null, cleared: [], sorts: []};
  const at = (r, c) => r + ',' + c;
  function range(r, c, nr, nc) {
    nr = nr || 1; nc = nc || 1;
    if (r + nr - 1 > sh.maxRows) throw new Error('범위가 시트 크기를 넘음: ' + r + '+' + nr + ' > ' + sh.maxRows);
    const each = (fn) => { for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) fn(r + i, c + j, i, j); };
    const g = {
      getRow: () => r, getColumn: () => c, getNumColumns: () => nc, getLastRow: () => r + nr - 1,
      setValues: (vals) => { vals.forEach((v, i) => { while (sh.rows.length < r + i) sh.rows.push([]); const row = sh.rows[r + i - 1];
        v.forEach((cell, j) => { row[c + j - 1] = cell; }); }); return px; },
      getDisplayValues: () => Array.from({length: nr}, (_, i) => Array.from({length: nc}, (_, j) => {
        const v = (sh.rows[r + i - 1] || [])[c + j - 1]; return v === undefined || v === null ? '' : String(v); })),
      clearContent: () => { each((y, x) => { if (sh.rows[y - 1]) sh.rows[y - 1][x - 1] = ''; });
        while (sh.rows.length > 1 && sh.rows[sh.rows.length - 1].every(v => v === '' || v === undefined)) sh.rows.pop(); return px; },
      clearFormat: () => { sh.cleared.push([r, nr]); each((y, x) => { delete sh.bg[at(y, x)]; delete sh.ink[at(y, x)]; delete sh.align[at(y, x)]; }); return px; },
      getBackground: () => sh.bg[at(r, c)] || '#ffffff',
      setBackground: (v) => { each((y, x) => { sh.bg[at(y, x)] = v.toLowerCase(); }); return px; },
      setBackgrounds: (vs) => { each((y, x, i, j) => { sh.bg[at(y, x)] = vs[i][j].toLowerCase(); }); return px; },
      setFontColor: (v) => { each((y, x) => { sh.ink[at(y, x)] = v; }); return px; },
      setFontColors: (vs) => { each((y, x, i, j) => { sh.ink[at(y, x)] = vs[i][j]; }); return px; },
      setHorizontalAlignment: (v) => { each((y, x) => { sh.align[at(y, x)] = v; }); return px; },
      setFontWeight: (v) => { each((y, x) => { sh.bold[at(y, x)] = v; }); return px; },
      setNote: (t) => { sh.notes[at(r, c)] = t; return px; },
      sort: (spec) => { if (sh.filter) throw new Error('거르기 범위와 겹친 정렬'); sh.sorts.push(spec); const body = sh.rows.slice(r - 1, r - 1 + nr); const k = spec.column - 1;
        body.sort((a, b) => (String(a[k]) < String(b[k]) ? -1 : String(a[k]) > String(b[k]) ? 1 : 0) * (spec.ascending ? 1 : -1));
        sh.rows.splice(r - 1, nr, ...body); return px; },
      createFilter: () => { if (sh.filter) throw new Error('거르기가 이미 있음'); sh.filters += 1;
        sh.filter = {getRange: () => range(r, c, nr, nc), remove: () => { sh.filter = null; },
          // 거르기 정렬 — 머리글 줄은 빼고, 빈 줄은 늘 아래로(구글 시트처럼)
          sort: (at, asc) => { sh.sorts.push({filter: at, ascending: asc}); const body = sh.rows.slice(r, r - 1 + nr); const k = at - 1;
            const blank = (row) => row.every(v => v === '' || v === undefined);
            body.sort((a, b) => blank(a) - blank(b) || (String(a[k]) < String(b[k]) ? -1 : String(a[k]) > String(b[k]) ? 1 : 0) * (asc ? 1 : -1));
            sh.rows.splice(r, body.length, ...body); }};
        return sh.filter; },
    };
    // 그 밖의 서식(세로 정렬 · 줄바꿈 · 테두리 · 숫자 서식 …)은 받기만
    const px = new Proxy(g, {get: (t, p) => (p in t ? t[p] : () => px)});
    return px;
  }
  Object.assign(sh, {
    getName: () => name, getLastRow: () => sh.rows.length, getLastColumn: () => sh.rows.reduce((m, row) => Math.max(m, row.length), 0),
    getMaxRows: () => sh.maxRows, getMaxColumns: () => sh.maxCols, insertRowsAfter: (a, n) => { sh.maxRows += n; },
    setFrozenRows: (n) => { sh.frozenRows = n; }, setFrozenColumns: (n) => { sh.frozenCols = n; },
    setColumnWidth: (i, w) => { sh.widths[i] = w; }, setRowHeight: (i, h) => { sh.heights[i] = h; },
    hideColumns: (i, n) => { sh.hidden.push([i, n || 1]); },
    setTabColor: (v) => { if (BREAK) throw new Error(BREAK); sh.tab = v; },
    getFilter: () => sh.filter, getRange: (r, c, nr, nc) => range(r, c, nr, nc),
  });
  return sh;
}
const ss = {getSheetByName: (n) => sheets[n] || null, insertSheet: (n) => (sheets[n] = makeSheet(n)), getName: () => '시트', getUrl: () => 'https://docs.google.com/x'};
var SpreadsheetApp = {getActive: () => ss, WrapStrategy: {CLIP: 'CLIP'}, BorderStyle: {SOLID: 'SOLID'}};
var LockService = {getScriptLock: () => ({waitLock: () => {}, releaseLock: () => {}})};
var Session = {getScriptTimeZone: () => 'Asia/Seoul'};
var Utilities = {formatDate: () => '2026-10-27 09:00', getUuid: () => 'u-x'};
var ContentService = {MimeType: {JSON: 'json'}, createTextOutput: (t) => ({text: t, setMimeType() { return this; }})};
const post = (body) => JSON.parse(doPost({postData: {contents: JSON.stringify(Object.assign({token: 'tok'}, body))}}).text);
const snap = (sh) => JSON.parse(JSON.stringify({rows: sh.rows, frozen: [sh.frozenRows, sh.frozenCols], widths: sh.widths, hidden: sh.hidden,
  notes: sh.notes, tab: sh.tab, bg: sh.bg, ink: sh.ink, align: sh.align, bold: sh.bold, filters: sh.filters, cleared: sh.cleared, sorts: sh.sorts, maxRows: sh.maxRows,
  filter: sh.filter && [sh.filter.getRange().getRow(), sh.filter.getRange().getLastRow(), sh.filter.getRange().getNumColumns()]}));
"""


def _run_style(tmp_path, driver: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    script = sheet.SCRIPT.replace("__TOKEN__", "tok").replace("__LOGKEY__", "KEY")
    path = tmp_path / "run.js"
    path.write_text(STYLE_HARNESS + script + driver, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _ledger_rows() -> tuple[list[list], list[list]]:
    carry = ledger.Entry(date="2026-09-30", content="처음 수량", source="carry", created="2026-09-30 08:00:00")
    give = ledger.Entry(date="2026-10-01", given=1, user="가나다", car="12가3456", source="apply", created="2026-10-01 09:00:00")
    buy = ledger.Entry(date="2026-10-02", bought=10, content="구입", source="manual", created="2026-10-02 09:00:00")
    link = ledger.Entry(date="2026-10-03", content="할인 링크 만듦", note="행사 링크", source="link", created="2026-10-03 09:00:00")
    full = ledger.to_sheet([carry, give, buy, link])
    return full, ledger.to_sheet([give, buy])


def test_script_styles_the_ledger_tab_in_node(tmp_path):
    full, short = _ledger_rows()
    out = _run_style(tmp_path, r"""
const res = {};
res.ping = post({action: 'ping'});
res.put = post({action: 'ledger_put', rows: __FULL__});
res.first = snap(sheets['관리대장']);
sheets['관리대장'].widths[5] = 999;                     // 담당자가 시트에서 '내용' 칸을 넓힘
res.again = post({action: 'ledger_put', rows: __SHORT__});
res.second = snap(sheets['관리대장']);
res.get = post({action: 'ledger_get'});
console.log(JSON.stringify(res));
""".replace("__FULL__", json.dumps(full, ensure_ascii=False)).replace("__SHORT__", json.dumps(short, ensure_ascii=False)))
    assert out["ping"]["ok"] and out["ping"]["styled"] is True and out["ping"]["styleError"] == ""
    assert out["put"]["ok"] and out["put"]["styleError"] == ""
    first = out["first"]
    # 머리글은 1행 그대로(앱이 2행부터 읽는다) — 라벤더 바탕 · 굵게 · 고정 · 거르기
    assert first["rows"][0][:9] == list(ledger.SHEET_HEAD[:9]) and first["bg"]["1,1"] == "#eeeafb" and first["bold"]["1,9"] == "bold"
    assert first["frozen"] == [1, 1] and first["widths"]["5"] == 240 and [10, 3] in first["hidden"] and first["tab"] == "#7058E8"
    assert first["filter"][0] == 1 and first["filter"][1] >= 5 and first["filter"][2] == 9 and first["maxRows"] >= 5
    assert "잔여는 앱이" in first["notes"]["1,4"]
    # 줄 색: 처음 수량 보라 · 배부 흰 · 구입 초록 · 수량 없는 기록(링크) 흰 바탕에 회색 글자, 0 아래 잔여는 빨강
    assert [first["bg"][f"{r},1"] for r in (2, 3, 4, 5)] == ["#f3f0fd", "#ffffff", "#e6f4ea", "#ffffff"]
    assert first["ink"]["3,4"] == "#B3261E" and first["ink"]["3,1"] == "#202124"       # 잔여 −1
    assert first["ink"]["5,5"] == "#8A8A8A" and first["ink"]["2,1"] == "#202124"
    assert first["align"]["2,1"] == "center" and first["align"]["2,4"] == "center" and "2,5" not in first["align"] and first["bold"]["3,4"] == "bold"
    # 두 번째 쓰기(줄 둘): 남은 줄의 서식을 지우고, 너비는 되돌리지 않고, 거르기는 새로 만들지 않는다
    second = out["second"]
    assert len(second["rows"]) == 3 and second["cleared"] == [[2, 4]] and "5,1" not in second["bg"]
    assert second["widths"]["5"] == 999 and second["filters"] == first["filters"]
    assert [second["bg"][f"{r},1"] for r in (2, 3)] == ["#ffffff", "#e6f4ea"]
    # 읽기는 그대로 — 앱이 읽는 줄은 쓴 줄과 같다
    assert [r[9] for r in out["get"]["rows"]] == [r[9] for r in short]


def test_script_styles_the_history_tab_in_node(tmp_path):
    headers = ["할인일시", "차량번호", "할인명", "적용방식", "적용금액"]
    rows = [["2026-10-20 17:37:04", "09주5782", "공무확인증4시간", "수동", "1,000"],
            ["2026-10-22 11:33:12", "38어3853", "공무확인증4시간", "자동", "0"],
            ["2026-10-21 09:00:00", "12가3456", "주말 무료", "자동", "3,700"]]
    out = _run_style(tmp_path, r"""
const res = {};
res.add = post({action: 'history_add', headers: __H__, rows: __R__, keys: ['a', 'b', 'c']});
res.more = post({action: 'history_add', headers: __H__, rows: [['2026-10-23 08:00:00', '45나6789', '공무확인증4시간', '수동', '2,000']], keys: ['d']});
res.dup = post({action: 'history_add', headers: __H__, rows: __R__, keys: ['a', 'b', 'c']});
res.sheet = snap(sheets['할인내역']);
res.ping = post({action: 'ping'});
console.log(JSON.stringify(res));
""".replace("__H__", json.dumps(headers, ensure_ascii=False)).replace("__R__", json.dumps(rows, ensure_ascii=False)))
    assert out["add"]["added"] == 3 and out["more"]["added"] == 1 and out["dup"]["added"] == 0     # 같은 줄은 한 번만(줄 차례가 바뀌어도)
    sh = out["sheet"]
    head = sh["rows"][0]
    assert head == ["저장한 때"] + headers + ["키"] and sh["bg"]["1,1"] == "#eeeafb"
    # 새것이 위로 · 시트 크기(처음 3줄)를 넘어도 늘려서 쓴다
    assert [r[1] for r in sh["rows"][1:]] == ["2026-10-23 08:00:00", "2026-10-22 11:33:12", "2026-10-21 09:00:00", "2026-10-20 17:37:04"]
    assert sh["maxRows"] >= 5 and sh["sorts"][0] == {"column": 2, "ascending": False} and sh["sorts"][-1] == {"filter": 2, "ascending": False}
    # 차량번호까지 고정 · 키 칸 숨김 · 너비 · 거르기
    assert sh["frozen"] == [1, 3] and [7, 1] in sh["hidden"] and sh["widths"]["2"] == 150 and sh["widths"]["6"] == 84 and sh["filters"] == 2   # 시트를 늘릴 때만 다시 건다
    # 공무확인증이 아닌 줄은 회색 글자 · 저장한 때는 늘 회색 · 금액은 오른쪽 · 일시는 가운데
    third = [i for i, r in enumerate(sh["rows"]) if r[3] == "주말 무료"][0] + 1
    assert sh["ink"][f"{third},2"] == "#8A8A8A" and sh["ink"]["2,2"] == "#202124" and sh["ink"]["2,1"] == "#8A8A8A"
    assert sh["align"]["2,6"] == "right" and sh["align"]["2,2"] == "center" and "2,4" not in sh["align"]
    assert out["ping"]["styleError"] == ""


def test_style_failure_does_not_stop_writing_in_node(tmp_path):
    full, _short = _ledger_rows()
    out = _run_style(tmp_path, r"""
BREAK = '탭 색을 못 바꿈';
const res = {};
res.ping = post({action: 'ping'});
res.put = post({action: 'ledger_put', rows: __FULL__});
res.get = post({action: 'ledger_get'});
res.add = post({action: 'history_add', headers: ['할인일시', '차량번호'], rows: [['2026-10-22 11:33:12', '38어3853']], keys: ['a']});
console.log(JSON.stringify(res));
""".replace("__FULL__", json.dumps(full, ensure_ascii=False)))
    assert out["ping"]["ok"] and "탭 색을 못 바꿈" in out["ping"]["styleError"]
    assert out["put"]["ok"] and "탭 색을 못 바꿈" in out["put"]["styleError"] and len(out["get"]["rows"]) == 4
    assert out["add"]["ok"] and out["add"]["added"] == 1


def test_check_tells_whether_the_script_styles_the_tabs(app, monkeypatch):
    assert sheet.check().styled is True
    app.ping = {"logs": True, "status": True}                       # 서식이 없던 판(2026-10-23 ~ 10-26)
    assert sheet.check().styled is False
    noted: list[str] = []
    monkeypatch.setattr(sheet, "log", noted.append)
    monkeypatch.setattr(sheet, "_STYLE_NOTED", set())
    app.style_error = "setTabColor 를 못 함"
    assert sheet.sync_ledger().ok and sheet.sync_ledger().ok             # 자료는 맞춘다
    assert [n for n in noted if "서식" in n] == ["⚠ 구글 시트 서식을 입히지 못했습니다(자료는 그대로 썼습니다) — setTabColor 를 못 함"]
