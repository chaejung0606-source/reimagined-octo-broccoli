"""로그 보내기(log_send.py) — 담당자 2026-10-22 "오류 생겼거나 했을 때 … 버튼하나만 누르면 … 읽을 수 있도록" · "구글시트를 사용해서".

구글은 부를 수 없으므로 웹 앱을 흉내 낸 opener 로 보낸 것을 보고, 스크립트(parking_sheet.SCRIPT)의 '로그' 탭 쓰기 · 읽기는
가짜 SpreadsheetApp 위에서 node 로 실제로 돌려 본다(node 가 없으면 건너뜀). 이름 · 번호는 모두 가짜다.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import urllib.parse

import pytest

from claim_downloader import log_send, parking_sheet, settings

LOG = """\
15:30:01 ── 과제 202408470003 → 결의서 목록
15:30:02 [1/3] No 5 (결의 324) · 구매요청(물품)
15:30:03 소득자 자동 선택: 홍길동(202600001) — 학번 일치
15:30:04 ✗ 실패: 첨부를 받지 못했습니다 — HTML 이 왔습니다
"""


class FakeOpener:
    """parking_sheet.call 의 opener — 보낸 요청을 남기고 정한 답을 준다."""

    def __init__(self, answer):
        self.answer = answer
        self.bodies: list[dict] = []

    def __call__(self, request, timeout=0):
        self.bodies.append(json.loads(request.data.decode("utf-8")))
        return io.BytesIO(json.dumps(self.answer, ensure_ascii=False).encode("utf-8"))


def _config(**extra):
    base = dict(url="https://script.google.com/macros/s/abc/exec", token="tok", log_key="k" * 32)
    base.update(extra)
    return parking_sheet.Config(**base)


def test_split_keeps_lines_and_joins_back():
    text = "".join(f"{i:05d} " + "가" * 30 + "\n" for i in range(4000))
    parts = log_send.split(text, size=10000)
    assert len(parts) > 1 and "".join(parts) == text
    assert all(len(p) <= 10000 for p in parts)
    assert all(p.endswith("\n") for p in parts)                  # 줄 가운데서 자르지 않는다
    long = "x" * 25000 + "\n끝\n"
    parts = log_send.split(long, size=10000)
    assert "".join(parts) == long and max(map(len, parts)) <= 10000
    assert log_send.split("") == [""]


def test_send_posts_masked_parts_and_gives_a_line_to_paste():
    settings.log_path().write_text(LOG, encoding="utf-8")
    # 과제현황에서 읽은 과제 — 그 번호는 12자리여도 계좌처럼 가리지 않는다(진단에 쓴다)
    settings.projects_path().write_text(json.dumps({"projects": [{"no": "202408470003"}]}), encoding="utf-8")
    opener = FakeOpener({"ok": True, "id": "20261022-153100-ab12", "name": "시트", "url": "https://docs.google.com/x"})
    sent = log_send.send("증빙 다운로드", error="첨부를 받지 못했습니다 — 홍길동", names=["홍길동"], version="abc1234",
                         config=_config(), opener=opener)
    assert sent.ok and sent.log_id == "20261022-153100-ab12"
    body = opener.bodies[0]
    assert body["action"] == "log_add" and body["token"] == "tok" and body["task"] == "증빙 다운로드"
    joined = "".join(body["parts"])
    assert joined == sent.text
    assert "업무 증빙 다운로드" in joined and "오류 첨부를 받지 못했습니다" in joined and "abc1234" in joined
    assert "홍길동" not in joined and "홍길동" not in body["error"] and "202600001" not in joined
    assert "결의 324" in joined and "202408470003" in joined          # 진단에 쓰는 것은 그대로
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(sent.url).query)
    assert query == {"key": ["k" * 32], "id": ["20261022-153100-ab12"]}
    assert sent.url.startswith("https://script.google.com/macros/s/abc/exec?")
    assert sent.line.startswith("로그 보냈어요 (증빙 다운로드") and sent.line.endswith(sent.url)


def test_send_without_connection_or_with_old_script_says_why_and_keeps_text():
    settings.log_path().write_text(LOG, encoding="utf-8")
    sent = log_send.send("일반청구", config=parking_sheet.Config())
    assert not sent.ok and sent.note == log_send.NOT_CONNECTED and "홍길동" not in sent.text and sent.text
    # 로그 보내기 전에 붙여 넣은 스크립트 — 열쇠가 없다: 만들어 두고 새로 붙여 넣게
    config = _config(log_key="")
    sent = log_send.send("일반청구", config=config)
    assert sent.old_script and sent.note == log_send.OLD_SCRIPT
    assert parking_sheet.load_config().log_key                         # 다음 [스크립트 복사] 에 들어갈 열쇠
    # 열쇠는 있는데 배포한 스크립트가 옛 판
    sent = log_send.send("일반청구", config=_config(), opener=FakeOpener({"ok": False, "error": "모르는 요청: log_add"}))
    assert sent.old_script and not sent.ok
    # 그 밖의 실패
    sent = log_send.send("일반청구", config=_config(), opener=FakeOpener({"ok": False, "error": "토큰이 다릅니다"}))
    assert not sent.ok and not sent.old_script and "토큰이 다릅니다" in sent.note


def test_known_project_numbers_stay_but_other_long_numbers_are_hidden():
    from claim_downloader import share_log
    text = "과제 202408470003 · 문서번호 202408470003-20261008-1 · 계좌 110594395796 · 202409710003"
    out = share_log.mask_text(text, keep={"202408470003"})
    assert "과제 202408470003 · 문서번호 202408470003-20261008-1" in out
    assert "110594395796" not in out and "202409710003" not in out     # 모르는 12자리는 그대로 가린다


def test_control_characters_are_dropped_so_the_paste_is_not_cut():
    # 실제(2026-10-22 19:34): 받은 결재문서의 글 앞부분이 기록에 섞여 NUL 에서 클립보드가 끊겼다 — 그 뒤 기록이 사라졌다
    from claim_downloader import share_log
    settings.log_path().write_text(
        "18:35:29 ✖ 내부품의.pdf — HTML 이 왔습니다 · 글 'Handysoft Approval Document File\ufffd\x01\x02\x00\x00\x1b'\n"
        "18:35:30 과제 202408470003 · 계좌 110594395796\t끝\n", encoding="utf-8")
    text = share_log.compose(keep={"202408470003"})
    assert not any(ord(c) < 32 and c not in "\n\t" for c in text) and "\x7f" not in text
    assert "Document File\ufffd'" in text and text.rstrip().endswith("끝")         # 끊기지 않고 마지막 줄까지
    assert "과제 202408470003" in text and "110594395796" not in text and "\ue000" not in text


def test_send_without_any_log():
    sent = log_send.send("일반청구", config=_config())
    assert not sent.ok and not sent.text and "없습니다" in sent.note


def test_script_keeps_token_and_adds_a_separate_log_key():
    text, config = parking_sheet.script_text(parking_sheet.Config(url="u", token="tok"))
    assert config.token == "tok" and len(config.log_key) == 32 and config.log_key.isalnum()
    assert "__TOKEN__" not in text and "__LOGKEY__" not in text
    assert f"const LOG_KEY = '{config.log_key}'" in text and "const TOKEN = 'tok'" in text
    again, same = parking_sheet.script_text()
    assert same.log_key == config.log_key and again == text          # 다시 복사해도 같은 글(열쇠가 바뀌면 붙인 스크립트와 어긋난다)
    assert "body.action === 'log_add'" in text and "p.key === LOG_KEY" in text


# ── 스크립트를 node 로 돌려 본다 ─────────────────────────────────────────
HARNESS = r"""
const sheets = {};
function makeSheet(name) {
  const rows = [];
  const sh = {
    name, rows,
    getName: () => name,
    getLastRow: () => rows.length,
    getLastColumn: () => rows.reduce((m, r) => Math.max(m, r.length), 0),
    setFrozenRows: () => {},
    hideColumns: () => {},
    deleteRows: (start, count) => { rows.splice(start - 1, count); },
    getRange: (r, c, nr, nc) => {
      nr = nr || 1; nc = nc || 1;
      const range = {
        setValues: (vals) => { vals.forEach((v, i) => { while (rows.length < r + i) rows.push([]); const row = rows[r + i - 1];
          v.forEach((cell, j) => { row[c + j - 1] = String(cell); }); }); return range; },
        getDisplayValues: () => Array.from({length: nr}, (_, i) => Array.from({length: nc}, (_, j) => ((rows[r + i - 1] || [])[c + j - 1]) || '')),
        setNumberFormat: () => range, setFontWeight: () => range,
      };
      return range;
    },
  };
  return sh;
}
const ss = {
  getSheetByName: (n) => sheets[n] || null,
  insertSheet: (n) => (sheets[n] = makeSheet(n)),
  getName: () => '시트', getUrl: () => 'https://docs.google.com/x',
};
var SpreadsheetApp = {getActive: () => ss};
var LockService = {getScriptLock: () => ({waitLock: () => {}, releaseLock: () => {}})};
var Session = {getScriptTimeZone: () => 'Asia/Seoul'};
let n = 0;
var Utilities = {formatDate: () => '20261022-1531' + String(n).padStart(2, '0'), getUuid: () => 'u' + String(n++).padStart(7, '0') + '-x'};
var ContentService = {MimeType: {JSON: 'json'}, createTextOutput: (t) => ({text: t, setMimeType() { return this; }})};
"""

DRIVER = r"""
const post = (body) => JSON.parse(doPost({postData: {contents: JSON.stringify(Object.assign({token: 'tok'}, body))}}).text);
const res = {};
res.ping = post({action: 'ping'});
res.first = post({action: 'log_add', task: '증빙 다운로드', error: '첨부 실패', version: 'v1', parts: ['=1+1 머리\n', '+둘째\n', '셋째']});
for (let i = 0; i < 31; i++) post({action: 'log_add', task: '일반청구', parts: ['기록 ' + i + '\n']});
res.wrong = post({action: 'log_add', token: 'nope', parts: ['x']});
res.latest = doGet({parameter: {key: 'KEY', id: ''}}).text;
res.old = doGet({parameter: {key: 'KEY', id: res.first.id}}).text;
res.list = doGet({parameter: {key: 'KEY', id: 'list'}}).text;
res.nokey = doGet({parameter: {key: 'bad'}}).text;
res.rows = sheets['로그'].rows.length;
console.log(JSON.stringify(res));
"""


def test_script_writes_and_reads_logs_in_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    script = parking_sheet.SCRIPT.replace("__TOKEN__", "tok").replace("__LOGKEY__", "KEY")
    path = tmp_path / "run.js"
    path.write_text(HARNESS + script + DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["ping"]["ok"] and out["ping"]["logs"] is True
    assert out["first"]["ok"] and out["first"]["id"]
    assert out["wrong"]["ok"] is False
    # 최근 30번만 — 첫 것(조각 셋)은 지워졌다. 머리 1 + 30줄
    assert out["rows"] == 31
    assert "그 로그가 없습니다" in out["old"]
    assert out["latest"].endswith("기록 30\n") and "업무 일반청구" in out["latest"]
    assert len(out["list"].splitlines()) == 30 and "일반청구" in out["list"].splitlines()[0]
    assert "켜져 있습니다" in out["nokey"]


def test_script_joins_parts_back_in_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    script = parking_sheet.SCRIPT.replace("__TOKEN__", "tok").replace("__LOGKEY__", "KEY")
    driver = r"""
const post = (body) => JSON.parse(doPost({postData: {contents: JSON.stringify(Object.assign({token: 'tok'}, body))}}).text);
const sent = post({action: 'log_add', task: '증빙 다운로드', error: '첨부 실패', version: 'v1', parts: ['=1+1 머리\n', '+둘째\n', '셋째']});
console.log(JSON.stringify({text: doGet({parameter: {key: 'KEY', id: sent.id}}).text, cells: sheets['로그'].rows.slice(1).map(r => r[6])}));
"""
    path = tmp_path / "run.js"
    path.write_text(HARNESS + script + driver, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["text"].endswith("\n=1+1 머리\n+둘째\n셋째")
    assert "업무 증빙 다운로드" in out["text"] and "오류 첨부 실패" in out["text"] and "앱 v1" in out["text"]
    assert all(cell.startswith("[조각 ") for cell in out["cells"])      # 시트가 '=' · '+' 를 수식으로 읽지 않게
