"""다운로드 현황(progress.py) — 담당자 2026-10-23: 건별로 청구서 · 구매요청 · 검사처리 서류를 받았으면 O, 못 받았으면 X, 대상이 아니면 회색,
구글 시트 탭 하나('다운로드 현황')에 읽기 좋은 서식으로, [다운로드 현황] 단추로 연다.
구글은 부르지 않는다(가짜 opener · node 로 돌리는 스크립트). 이름 · 번호는 모두 가짜다."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import pytest

from claim_downloader import parking_sheet, progress, purchase, settings
from conftest import make_row


class _Answer:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.data


def _opener(calls: list, answer: dict):
    def opener(request, timeout=0):
        calls.append(json.loads(request.data.decode("utf-8")))
        return _Answer(answer)
    return opener


# ── 받을 것인지 · 왜 아닌지 ─────────────────────────────────────────────────
def test_claim_marks_follow_the_download_rules(isolated_home):
    done = {"202408470003-20261008-1"}
    assert progress.claim_mark(make_row(docNo="202408470003-20261008-1"), done, []) == ("O", "")
    assert progress.claim_mark(make_row(docNo="202408470003-20261008-2"), done, []) == ("△", "")
    mark, why = progress.claim_mark(make_row(state="신청"), done, [])
    assert mark == "" and "승인" in why
    mark, why = progress.claim_mark(make_row(gubun="반납요구"), done, [])
    assert mark == "" and "반납" in why
    mark, why = progress.claim_mark(make_row(docNo=""), done, [])
    assert mark == "" and "문서번호" in why
    mark, why = progress.claim_mark(make_row(expDt=""), done, [])
    assert mark == "" and "지출예정일" in why
    unwanted = [{"project": "202408470003", "seq": "7", "docNo": "", "gubun": "잔액조정", "cont": "", "reason": "청구서출력 없음", "at": ""}]
    mark, why = progress.claim_mark(make_row(gubun="잔액조정", docNo="202408470003-20261008-9"), done, unwanted)
    assert mark == "" and "잔액조정" in why and "청구서출력" in why


def test_list_read_keeps_a_failure_until_the_claim_is_received(isolated_home, tmp_path):
    root = tmp_path / "(202408470003)_2026년도 사업비"
    (root / "09. 그 밖의사업운영경비").mkdir(parents=True)
    pdf = root / "09. 그 밖의사업운영경비" / "09_(261008) 정수기_생협_(51,900).pdf"
    pdf.write_bytes(b"%PDF-")
    settings.archive_cache_path().write_text(json.dumps({str(pdf): "202408470003-20261008-1"}), encoding="utf-8")
    rows = [make_row(no="1", seq="101", docNo="202408470003-20261008-1"),
            make_row(no="2", seq="102", docNo="202408470003-20261008-2"),
            make_row(no="3", seq="103", docNo="", state="신청")]
    progress.record_claims("202408470003", rows, {"202408470003-20261008-1"}, [], root)
    items = {e.key: e for _l, e in progress.entries(str(tmp_path))}
    assert items["202408470003-20261008-1"].claim == "O" and items["202408470003-20261008-1"].files.endswith("정수기_생협_(51,900).pdf")
    assert items["202408470003-20261008-2"].claim == "△"
    assert items["결의 103"].claim == "" and "승인" in items["결의 103"].detail
    # 받기 — 둘째 건 실패
    progress.record_claim_item(dict(rows[1], project="202408470003"), "failed", "상세화면이 안 뜸")
    items = {e.key: e for _l, e in progress.entries(str(tmp_path))}
    assert items["202408470003-20261008-2"].claim == "X" and "상세화면" in items["202408470003-20261008-2"].detail
    # 목록을 다시 읽어도 X 는 남는다(다시 받기 전) — 받으면 O
    progress.record_claims("202408470003", rows, {"202408470003-20261008-1"}, [], root)
    items = {e.key: e for _l, e in progress.entries(str(tmp_path))}
    assert items["202408470003-20261008-2"].claim == "X"
    progress.record_claim_item(dict(rows[1], project="202408470003"), "done", "09_(261010) 둘째_(1,000).pdf")
    items = {e.key: e for _l, e in progress.entries(str(tmp_path))}
    assert items["202408470003-20261008-2"].claim == "O" and items["202408470003-20261008-2"].files == "09_(261010) 둘째_(1,000).pdf"
    # 목록에서 사라진 줄은 빠지고, 받지 않는 결의서(unwanted)는 회색
    progress.record_claims("202408470003", rows[:1], {"202408470003-20261008-1"}, [], root)
    assert [e.key for _l, e in progress.entries(str(tmp_path))] == ["202408470003-20261008-1"]
    progress.record_claim_item(dict(rows[0], project="202408470003"), "unwanted", "청구서출력이 없는 결의서")
    assert progress.entries(str(tmp_path))[0][1].claim == ""


def test_blocked_project_rows_are_gray_with_the_reason(isolated_home):
    progress.record_claims("202409710001", [make_row(docNo="202409710001-20261008-1")], set(), [], None, blocked="과제 폴더가 없음")
    entry = progress.entries()[0][1]
    assert entry.claim == "" and entry.detail == "과제 폴더가 없음"


# ── 구매요청(계약) 서류 ────────────────────────────────────────────────────
def _purchase_row(req_no="202606170005", prj="202408470003", **extra):
    return dict({"req_no": req_no, "prj_no": prj, "seq": "3", "req_dt": "2026-06-17", "title": "데스크톱 구입", "amount": "1,200,000",
                 "kind": "물품", "state": "지급완료"}, **extra)


def test_purchase_rows_and_results(isolated_home):
    progress.record_purchases("202408470003", [_purchase_row(), _purchase_row("202605010001", seq="2"), _purchase_row("202604010001", seq="1")],
                              {"202604010001": {"at": "2026-10-22 18:00", "files": 7}})
    items = {e.key: e for _l, e in progress.entries()}
    assert items["202606170005"].marks == ("", "△", "△") and items["202606170005"].date == "2026-06-17"
    assert items["202604010001"].marks == ("", "O", "O") and "지난 받기" in items["202604010001"].files
    assert items["202606170005"].gubun == "구매요청(물품) · 지급완료" and items["202606170005"].amt == "1200000"
    good = purchase.CaseResult("202606170005", "데스크톱 구입", "202408470003", folder="/x/(260617) 데스크톱 구입_(202606170005)",
                               saved=["견적서.pdf", "검사처리/계약 관련 서류.pdf"], photos=1, inspected=True, inspect_seen=2)
    partly = purchase.CaseResult("202605010001", "LMS 임차", "202408470003", folder="/x/(260501) LMS 임차_(202605010001)",
                                 saved=["견적서.pdf"], failed=["검사처리/확인서.pdf: HTML 이 왔습니다"], inspected=True, inspect_seen=1, ok=False)
    progress.record_purchase_results([good, partly])
    items = {e.key: e for _l, e in progress.entries()}
    assert items["202606170005"].marks == ("", "O", "O") and "물품 사진 1장" in items["202606170005"].files and items["202606170005"].detail == ""
    assert items["202605010001"].marks == ("", "O", "X") and "확인서.pdf" in items["202605010001"].detail
    # 첨부가 없는 건 · 검사처리에 없는 건 · 상세를 못 띄운 건
    none = purchase.CaseResult("202606170005", "데스크톱 구입", "202408470003", folder="/x/a", inspected=False)
    broken = purchase.CaseResult("202605010001", "LMS 임차", "202408470003", note="상세를 띄우지 못함", ok=False)
    progress.record_purchase_results([none, broken])
    items = {e.key: e for _l, e in progress.entries()}
    assert items["202606170005"].marks == ("", "", "") and "첨부 없음" in items["202606170005"].detail and "검사처리 화면에" in items["202606170005"].detail
    assert items["202605010001"].marks[1] == "X" and "상세를 띄우지 못함" in items["202605010001"].detail
    # 목록을 다시 읽어도 결과는 남는다
    progress.record_purchases("202408470003", [_purchase_row("202605010001", seq="2")], {})
    items = {e.key: e for _l, e in progress.entries()}
    assert list(items) == ["202605010001"] and items["202605010001"].marks[1] == "X"


# ── 표 · 시트 ──────────────────────────────────────────────────────────────
def test_table_orders_by_project_folder_then_kind_then_no(isolated_home, tmp_path):
    (tmp_path / "(202408470002)_2025년도 사업비_1,000").mkdir()
    (tmp_path / "(202408470003)_2026년도 사업비_2,000").mkdir()
    progress.record_claims("202408470003", [make_row(no="2", seq="2", docNo="202408470003-20261008-2"), make_row(no="10", seq="10", docNo="202408470003-20261008-10")],
                           set(), [], None)
    progress.record_purchases("202408470003", [_purchase_row(seq="1")], {})
    progress.record_claims("202408470002", [make_row(no="1", seq="1", docNo="202408470002-20261008-1")], {"202408470002-20261008-1"}, [], None)
    head, rows, legend = progress.table(str(tmp_path))
    assert head == progress.HEAD and len(head) == len(progress.WIDTHS)
    assert [(r[0], r[1], r[2]) for r in rows] == [("202408470002 2025년도 사업비", "청구서", "1"), ("202408470003 2026년도 사업비", "청구서", "2"),
                                                 ("202408470003 2026년도 사업비", "청구서", "10"), ("202408470003 2026년도 사업비", "구매요청(계약)", "1")]
    assert rows[0][9] == "O" and rows[1][9] == "△" and rows[3][9:12] == ["", "△", "△"]
    assert rows[0][7] == 51900                       # 금액은 숫자로 — 시트가 콤마를 찍는다
    assert "O 받음" in legend and "과제 2개" in legend and "청구서 3건(O 1 · X 0 · △ 2)" in legend and "구매요청(계약) 1건" in legend
    assert progress.summary_text(str(tmp_path)).startswith("과제 2개")


def test_push_sends_the_table_and_explains_an_old_script(isolated_home):
    config = parking_sheet.Config(url="https://script.google.com/macros/s/x/exec", token="tok")
    progress.record_claims("202408470003", [make_row(docNo="202408470003-20261008-1")], set(), [], None)
    calls: list[dict] = []
    result = progress.push(config, "", opener=_opener(calls, {"ok": True, "count": 1, "name": "시트", "url": "https://docs.google.com/x"}))
    assert result.ok and result.total == 1 and result.sheet_url == "https://docs.google.com/x"
    body = calls[0]
    assert body["action"] == "status_put" and body["token"] == "tok" and body["head"] == progress.HEAD and len(body["rows"]) == 1
    assert body["marks"] == [10, 11, 12] and body["amount"] == 8 and body["widths"] == progress.WIDTHS and "O 받음" in body["legend"]
    assert parking_sheet.load_config().sheet_url == "https://docs.google.com/x"      # 다음부터 단추가 이 주소를 연다
    old = progress.push(config, "", opener=_opener([], {"ok": False, "error": "모르는 요청: status_put"}))
    assert not old.ok and "옛 판" in old.note and "새 버전" in old.note
    assert not progress.push(parking_sheet.Config(), "").ok


def test_script_has_the_status_action():
    assert "body.action === 'status_put'" in parking_sheet.SCRIPT and "const STATUS = '다운로드 현황'" in parking_sheet.SCRIPT
    assert "status: true" in parking_sheet.SCRIPT


# ── 스크립트를 node 로 — 탭을 다시 쓰고 서식을 입히는지 ─────────────────────────
HARNESS = r"""
const sheets = {};
function makeRange(sh, r, c, nr, nc) {
  const range = {};
  const proxy = new Proxy(range, {get: (t, p) => {
    if (p in t) return t[p];
    return (...args) => { (sh.calls[p] = sh.calls[p] || []).push([r, c, nr, nc, JSON.stringify(args).slice(0, 120)]); return proxy; };
  }});
  range.setValues = (vals) => { vals.forEach((v, i) => { while (sh.rows.length < r + i) sh.rows.push([]); const row = sh.rows[r + i - 1];
    v.forEach((cell, j) => { row[c + j - 1] = cell; }); }); return proxy; };
  range.setValue = (v) => range.setValues([[v]]);
  range.getDisplayValues = () => Array.from({length: nr}, (_, i) => Array.from({length: nc}, (_, j) => {
    const v = (sh.rows[r + i - 1] || [])[c + j - 1]; return v === undefined || v === null ? '' : String(v); }));
  range.setBackgrounds = (b) => { sh.backgrounds.push([r, c, b.map(x => x[0])]); return proxy; };
  range.setFontColors = (b) => { sh.fontColors.push([r, c, b.map(x => x[0])]); return proxy; };
  range.createFilter = () => { sh.filter = {r, c, nr, nc, remove: () => { sh.filter = null; }}; return sh.filter; };
  return proxy;
}
function makeSheet(name) {
  const sh = {name, rows: [], calls: {}, backgrounds: [], fontColors: [], filter: null, frozenRows: 0, frozenCols: 0, widths: {}, maxRows: 5, maxCols: 3, cleared: 0,
    getName: () => name, getLastRow: () => sh.rows.length, getLastColumn: () => sh.rows.reduce((m, r) => Math.max(m, r.length), 0),
    getMaxRows: () => sh.maxRows, getMaxColumns: () => sh.maxCols,
    insertRowsAfter: (at, n) => { sh.maxRows += n; }, insertColumnsAfter: (at, n) => { sh.maxCols += n; },
    setFrozenRows: (n) => { sh.frozenRows = n; }, setFrozenColumns: (n) => { sh.frozenCols = n; }, setColumnWidth: (i, w) => { sh.widths[i] = w; },
    hideColumns: () => {}, deleteRows: (start, count) => { sh.rows.splice(start - 1, count); },
    clear: () => { sh.rows.length = 0; sh.cleared += 1; }, getFilter: () => sh.filter,
    getRange: (r, c, nr, nc) => makeRange(sh, r, c, nr || 1, nc || 1)};
  return sh;
}
const ss = {getSheetByName: (n) => sheets[n] || null, insertSheet: (n) => (sheets[n] = makeSheet(n)), getName: () => '시트', getUrl: () => 'https://docs.google.com/x'};
var SpreadsheetApp = {getActive: () => ss, WrapStrategy: {CLIP: 'CLIP'}, BorderStyle: {SOLID: 'SOLID'}};
var LockService = {getScriptLock: () => ({waitLock: () => {}, releaseLock: () => {}})};
var Session = {getScriptTimeZone: () => 'Asia/Seoul'};
var Utilities = {formatDate: () => '20261023-0900', getUuid: () => 'u-x'};
var ContentService = {MimeType: {JSON: 'json'}, createTextOutput: (t) => ({text: t, setMimeType() { return this; }})};
"""

DRIVER = r"""
const post = (body) => JSON.parse(doPost({postData: {contents: JSON.stringify(Object.assign({token: 'tok'}, body))}}).text);
const res = {};
res.ping = post({action: 'ping'});
const table = __TABLE__;
res.first = post(Object.assign({action: 'status_put'}, table));
res.second = post(Object.assign({action: 'status_put'}, table, {rows: table.rows.slice(0, 1)}));
const sh = sheets['다운로드 현황'];
res.rows = JSON.parse(JSON.stringify(sh.rows));          // 뒤의 빈 표 쓰기가 같은 배열을 비우므로 사본으로
res.frozen = [sh.frozenRows, sh.frozenCols];
res.widths = Object.assign({}, sh.widths);
res.filter = sh.filter && [sh.filter.r, sh.filter.nr, sh.filter.nc];
res.backgrounds = JSON.parse(JSON.stringify(sh.backgrounds));
res.fontColors = JSON.parse(JSON.stringify(sh.fontColors));
res.formats = (sh.calls.setNumberFormat || []).map(a => [a[1], a[4]]);
res.cleared = sh.cleared;
res.maxRows = sh.maxRows;
res.empty = post({action: 'status_put', head: table.head, rows: [], legend: '없음'});
console.log(JSON.stringify(res));
"""


def test_script_rewrites_the_status_tab_with_formatting_in_node(isolated_home, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    progress.record_claims("202408470003", [make_row(no="1", seq="1", docNo="202408470003-20261008-1"), make_row(no="2", seq="2", docNo="202408470003-20261008-2", state="신청")],
                           {"202408470003-20261008-1"}, [], None)
    progress.record_purchases("202408470003", [_purchase_row(seq="3")], {})
    head, rows, legend = progress.table("")
    table = {"head": head, "rows": rows, "legend": legend, "marks": list(progress.MARK_COLS), "amount": progress.AMOUNT_COL,
             "texts": list(progress.TEXT_COLS), "widths": progress.WIDTHS}
    script = parking_sheet.SCRIPT.replace("__TOKEN__", "tok").replace("__LOGKEY__", "KEY")
    path = tmp_path / "run.js"
    path.write_text(HARNESS + script + DRIVER.replace("__TABLE__", json.dumps(table, ensure_ascii=False)), encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["ping"]["ok"] and out["ping"]["status"] is True and out["ping"]["logs"] is True
    assert out["first"]["ok"] and out["first"]["count"] == 3 and out["second"]["count"] == 1
    # 두 번째 쓰기 뒤: 1행 설명 · 2행 머리글 · 3행부터 줄 하나(통째로 다시 쓴다)
    assert out["cleared"] == 2 and out["maxRows"] >= 5
    assert out["rows"][0][0].startswith("O 받음") and out["rows"][1] == progress.HEAD and len(out["rows"]) == 3
    assert out["rows"][2][1] == "청구서" and out["rows"][2][9] == "O" and out["rows"][2][7] == 51900
    assert out["frozen"] == [2, 2] and out["widths"]["7"] == progress.WIDTHS[6]
    assert out["filter"] == [2, 2, len(progress.HEAD)]
    # O/X 칸의 색 — 마지막 쓰기(줄 하나)의 세 칸: 청구서 O 초록, 구매요청 · 검사처리 빈칸 회색
    last = out["backgrounds"][-3:]
    assert [b[1] for b in last] == [10, 11, 12] and last[0][2] == ["#D9EAD3"] and last[1][2] == ["#E3E3E3"]
    assert out["fontColors"][-3][2] == ["#1E7F37"]
    # 첫 쓰기(줄 셋)의 청구서 칸: O · 회색(승인 아님) · 회색(구매요구 줄)
    first = out["backgrounds"][:3]
    assert first[0][2] == ["#D9EAD3", "#E3E3E3", "#E3E3E3"] and first[1][2] == ["#E3E3E3", "#E3E3E3", "#FFF2CC"]
    assert any(col == progress.AMOUNT_COL and "#,##0" in fmt for col, fmt in out["formats"])
    assert any(col == 4 and '"@"' in fmt for col, fmt in out["formats"])
    assert out["empty"]["ok"] and out["empty"]["count"] == 0


# ── 화면 — [다운로드 현황] 단추 ───────────────────────────────────────────────
def _qt_app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, check, seconds: float = 5.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if check():
            return True
        time.sleep(0.02)
    return False


def test_download_page_button_writes_the_sheet_then_opens_it(isolated_home, monkeypatch):
    app = _qt_app()
    from PySide6.QtWidgets import QMessageBox
    from claim_downloader.ui import sheet_sync
    from claim_downloader.ui.pages import download as page_mod
    from claim_downloader.ui.worker import SessionWorker

    opened: list[str] = []
    boxes: list[str] = []
    monkeypatch.setattr(page_mod.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: boxes.append(self.text()))
    worker = SessionWorker()
    page = page_mod.DownloadPage(worker=worker)
    try:
        assert page.progress_button.text() == "다운로드 현황"
        # 연결 전 — 안내 창(설정으로)
        page.progress_button.click()
        assert boxes and "연결돼 있지 않아" in boxes[0] and not opened
        # 연결 뒤 — 시트에 쓰고 연다(구글 대신 가짜 push)
        parking_sheet.save_config(parking_sheet.Config(url="https://script.google.com/macros/s/x/exec", token="tok", sheet_url="https://docs.google.com/x"))
        monkeypatch.setattr(progress, "push", lambda out_root="", **k: parking_sheet.Result(ok=True, note="'다운로드 현황' 탭에 2줄을 썼습니다", total=2,
                                                                                            sheet_url="https://docs.google.com/x"))
        page.progress_button.click()
        assert _wait(app, lambda: opened == ["https://docs.google.com/x"])
        assert page.progress_button.isEnabled()
        # 옛 스크립트 — 까닭 창
        monkeypatch.setattr(progress, "push", lambda out_root="", **k: parking_sheet.Result(note=progress.OLD_SCRIPT, sheet_url="https://docs.google.com/x"))
        page.progress_button.click()
        assert _wait(app, lambda: len(boxes) == 2) and "옛 판" in boxes[1] and len(opened) == 1
        assert not sheet_sync.instance().status_busy
    finally:
        page.deleteLater()
        app.processEvents()
