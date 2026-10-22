"""구매요청(계약) 서류 받기(purchase.py) — 날짜 창 · 폴더 이름 · 가짜 프레임으로 받기 흐름 · 실제 Chromium 모의 ERP(구매·자산 메뉴).

실측(CLAUDE.md 23절, 2026-10-22)의 모양을 흉내 낸다: 구매진행관리 목록은 IBSheet 8(getDataRows · getValue · setValue(chk) · getRowsByChecked),
[상세조회/변경] 은 체크된 줄 하나를 같은 프레임의 구매요구서작성으로, 검사처리는 JGM 그리드(라디오 → 아래 첨부 표 · 물품정보), 물품정보 줄 더블클릭 →
물품내역팝업(사진 주소). 값(거래처 · 사람)은 가짜.
"""
from __future__ import annotations

import datetime as dt
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from claim_downloader import purchase
from claim_downloader.navigate import Project

TODAY = dt.date(2026, 10, 22)


# ── 순수 함수 ──────────────────────────────────────────────────────────────


def test_span_joins_project_periods_and_stops_at_today():
    projects = [Project("202408470003", "a", "2026-03-01", "2027-02-28"), Project("202408470001", "b", "2024-06-01", "2025-02-28")]
    assert purchase.span(projects, TODAY) == ("2024-06-01", "2026-10-22")
    assert purchase.span([Project("x", "", "", "")], TODAY) is None


def test_windows_are_at_most_730_days():
    got = purchase.windows("2024-06-01", "2026-10-22")
    assert got == [("2024-06-01", "2026-05-31"), ("2026-06-01", "2026-10-22")]
    for s, e in got:
        assert (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days < 730
    assert purchase.window_for("2026-06-17", "2024-06-01", "2026-10-22") == ("2026-06-01", "2026-10-22")
    assert purchase.windows("2026-10-22", "2026-10-22") == [("2026-10-22", "2026-10-22")]
    assert purchase.windows("2027-01-01", "2026-01-01") == []


def test_request_date_comes_from_the_request_number():
    assert purchase.req_date("202606170005") == "2026-06-17"       # 실측 10번: REQ_DT 2026-06-17
    assert purchase.req_date("83") == ""
    assert purchase.iso("20261022") == "2026-10-22" and purchase.iso("2026.10.22") == "2026-10-22" and purchase.iso("") == ""


def test_case_folder_sits_beside_project_folders_and_reuses_a_folder_by_request_number(tmp_path):
    root = tmp_path / "지출결의서"
    (root / "(202408470003)_2026년도 사업비_4,438,000,000" / "01. 인건비").mkdir(parents=True)
    folder, why = purchase.case_dir(root, "202408470003", "202606170005", "연구용 노트북 구입 / 10대", "2026-06-17")
    assert why == "" and folder == root / purchase.FOLDER_NAME / "(202408470003)_2026년도 사업비_4,438,000,000" / "(260617) 연구용 노트북 구입 10대_(202606170005)"
    # 담당자가 폴더 이름을 바꿨어도 끝의 구매요구번호로 같은 건을 알아본다
    kept = folder.parent / "(260617) 노트북_(202606170005)"
    kept.mkdir(parents=True)
    (kept / "견적서.pdf").write_bytes(b"%PDF-1.4")
    again, _ = purchase.case_dir(root, "202408470003", "202606170005", "다른 제목", "")
    assert again == kept and purchase.existing_files(again) == 1
    # 과제 폴더가 없는 과제는 받지 않는다(담당자 2026-10-22 — 22절과 같은 규칙)
    none, why = purchase.case_dir(root, "202502320001", "202601010001", "x")
    assert none is None and "(202502320001)_" in why
    # 저장 폴더 자체가 과제 폴더면 그 위에
    own, _ = purchase.project_base(root / "(202408470003)_2026년도 사업비_4,438,000,000", "202408470003")
    assert own == root / purchase.FOLDER_NAME / "(202408470003)_2026년도 사업비_4,438,000,000"


def test_file_and_photo_names_are_safe():
    assert purchase.file_name('견적서(9/11).pdf') == "견적서(9 11).pdf"
    long = purchase.file_name("가" * 200 + ".xlsx")
    assert long.endswith("….xlsx") and len(long) <= purchase.NAME_ROOM
    assert purchase.photo_name("노트북", 1, "image/jpeg") == "물품사진_노트북_1.jpg"
    assert purchase.photo_name("", 2, "image/png") == "물품사진_물품_2.png"
    assert purchase.case_dir_name("202606170005", "x" * 300).endswith("_(202606170005)")
    assert len(purchase.case_dir_name("202606170005", "x" * 300)) <= purchase.NAME_ROOM


def test_list_row_becomes_a_table_row_like_a_claim():
    row = {"req_no": "202610220001", "prj_no": "202408470003", "req_dt": "2026-10-22", "title": "취약점 진단 솔루션",
           "state": "보완(접수)", "kind": "물품", "amount": "49,500,000", "seq": "1"}
    t = purchase.as_target(row)
    assert t["kind"] == purchase.KIND and t["project"] == "202408470003" and t["expDt"] == "2026-10-22"
    assert t["cont"] == "취약점 진단 솔루션" and t["amt"] == "49500000" and t["gubun"] == "구매요청(물품) · 보완(접수)" and t["no"] == "1"
    assert t["docNo"] == "" and t["existing"] == 0


def test_photo_urls_skip_the_noimage_placeholder():
    info = {"seq1": "1922592", "src1": "/comm0008_01.act?USEFAC_SEQ_NO=10&ATTFILE_SEQ_NO=1922592&PROC_CD=preview",
            "seq2": "0", "src2": "/proto/web/img/groupware/img_noimage.png"}
    assert purchase._photo_urls(info) == [(1, info["src1"])]


# ── 모의 ERP(실제 Chromium) ─────────────────────────────────────────────────

CASES = [
    {"no": "202610220001", "prj": "202408470003", "dt": "2026-10-22", "title": "2026년 AI 기반 자동 취약점 진단 솔루션", "state": "보완(접수)", "files": []},
    {"no": "202606170005", "prj": "202408470003", "dt": "2026-06-17", "title": "연구용 노트북 구입", "state": "지급완료",
     "files": [("1", "견적서.pdf"), ("2", "재료구매내역서.xlsx")]},
    {"no": "202509010002", "prj": "202408470002", "dt": "2025-09-01", "title": "다른 과제 가구", "state": "계약완료", "files": [("3", "다른과제.pdf")]},
    {"no": "202504010001", "prj": "202408470003", "dt": "2025-04-01", "title": "작년 봄 장비", "state": "지급완료", "files": [("4", "작년.pdf")]},
]
FILES = {"1": (b"%PDF-1.4 quote", "application/pdf"), "2": (b"PK\x03\x04 xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
         "3": (b"%PDF-1.4 other", "application/pdf"), "4": (b"%PDF-1.4 old", "application/pdf"),
         "7": (b"%PDF-1.4 contract", "application/pdf"), "9": (b"\xff\xd8\xff photo", "image/jpeg")}

TOP = """<!doctype html><html><body>
<a id="menu_id_3" href="javascript:" onclick="openTab('구매진행관리','/rexpe_0155_01.act')">구매·자산</a>
<a id="menu_id_1" href="javascript:">과제관리</a>
<div id="tabs"><a class="mul_txt">메인화면</a></div><div id="frames"></div>
<script>
function openTab(name, url) {
  if (document.getElementById('f_' + name)) { showTab(name); return; }
  const a = document.createElement('a'); a.className = 'mul_txt'; a.textContent = name; a.onclick = () => showTab(name); document.getElementById('tabs').appendChild(a);
  const f = document.createElement('iframe'); f.id = 'f_' + name; f.src = url; f.style.width = '900px'; f.style.height = '600px'; document.getElementById('frames').appendChild(f);
  showTab(name);
}
function showTab(name) { document.querySelectorAll('#frames iframe').forEach(f => { f.style.display = f.id === 'f_' + name ? 'block' : 'none'; }); }
</script></body></html>"""

LIST = """<!doctype html><html><body>
<a href="javascript:" onclick="parent.openTab('구매진행관리','/rexpe_0155_01.act')">구매진행관리</a>
<a href="javascript:" onclick="parent.openTab('검사처리','/rexpe_0201_01.act')">검사처리</a>
<input id="START_DATE" value="__START__"> <input id="END_DATE" value="__END__"> <input id="SEARCH_PURCH_REQ_NO">
<input type="button" id="btnSearch" value="검색"> <input type="hidden" id="PURCH_MENU_ID" value="373">
<div class="SheetMain" onclick="return IBSheet[0].SheetClick(event)"><table id="t"></table></div>
<a id="btnInsert">등록</a> <a id="btnDetail">상세조회/변경</a> <a id="btnDelete">삭제</a>
<script>
const ALL = __ROWS__;
let data = [];
const sheet = {
  id: 'sheet', Cols: {chk: {Header: '선택'}, PURCH_REQ_NO: {Header: '구매요청번호'}},
  getDataRows: () => data, getValue: (r, c) => r[c], getText: (r, c) => c === 'REQ_DT' ? String(r[c]).replace(/-/g, '-') : String(r[c] ?? ''),
  setValue: (r, c, v) => { r[c] = v; render(); }, getRowsByChecked: c => data.filter(r => Number(r[c]) === 1), SheetClick: () => true,
  setFocus: () => { throw new Error('눌리면 안 됨'); },
};
window.IBSheet = [sheet];
function render() { document.getElementById('t').innerHTML = data.map(r => '<tr><td>' + (r.chk ? '☑' : '☐') + '</td><td>' + r.PURCH_REQ_NO + '</td><td>' + r.PURCH_CONT + '</td></tr>').join(''); }
function search() {
  const s = document.getElementById('START_DATE').value, e = document.getElementById('END_DATE').value;
  const days = (new Date(e) - new Date(s)) / 86400000 + 1;
  if (days > 730) { alert('구매요청일자는 최대 2년까지 조회 가능합니다.'); return; }
  data = [];
  setTimeout(() => { data = ALL.filter(r => r.REQ_DT >= s && r.REQ_DT <= e).map(r => Object.assign({Kind: 'Data', chk: 0}, r)); render(); }, 300);
}
document.getElementById('btnSearch').onclick = search;
document.getElementById('btnDetail').onclick = () => {
  const c = sheet.getRowsByChecked('chk');
  if (c.length !== 1) { alert('상세조회/변경할 내역을 체크해 주시기 바랍니다.'); return; }
  location.href = '/rexpe_0156_01.act?no=' + c[0].PURCH_REQ_NO + '&s=' + document.getElementById('START_DATE').value + '&e=' + document.getElementById('END_DATE').value;
};
document.getElementById('btnDelete').onclick = () => { fetch('/deleted'); };
if ('__START__' !== '') search();
</script></body></html>"""

DETAIL = """<!doctype html><html><body>
<input type="hidden" id="PROC_TYP_CD" value="C10"><input type="hidden" id="PURCH_REQ_NO" value="__NO__">
<input type="hidden" id="PRJ_NO" value="__PRJ__"><input id="REQ_DT" value="__DT__" readonly><input id="PURCH_CONT" value="__TITLE__" readonly>
<input id="PURCH_PROG_STS_NM" value="__STATE__" readonly>
<div>__LINKS__</div>
<a id="btnPrint">구매요청서</a> <a id="btnSave">임시저장</a> <a id="btnRequest">구매요청</a> <a id="btnCancel">구매요청취소</a>
<a id="btnList" href="javascript:" onclick="location.href='/rexpe_0155_01.act?s=__S__&e=__E__'">진행관리목록</a>
<script>document.getElementById('btnSave').onclick = () => fetch('/saved'); document.getElementById('btnRequest').onclick = () => fetch('/requested');</script>
</body></html>"""

INSPECT = """<!doctype html><html><head><style>
.jgrid-viewport{height:120px;overflow:auto;border:1px solid #999}.jgrid-row{height:30px}
</style></head><body>
<a href="javascript:" onclick="parent.openTab('구매진행관리','/rexpe_0155_01.act')">구매진행관리</a>
<input id="START_DATE" value=""> <input id="END_DATE" value=""> <input type="button" id="btnSearch" value="검색">
<div class="jgrid-viewport" id="list"></div>
<input type="hidden" id="PURCH_REQ_NO"><input type="hidden" id="PRJ_NO"><input type="hidden" id="CONT_SEQ_NO">
<input id="DLVR_DT"> <a id="btnPunch">검사처리</a> <a id="btnWorkSave">완료</a>
<div id="att"></div><div class="jgrid-viewport" id="items"></div>
<script>
const ALL = __ROWS__;
let rows = [];
function render() {
  document.getElementById('list').innerHTML = rows.map((r, i) => '<div class="jgrid-row" r="' + i + '"><input type="radio" name="radioJGM5" onclick="pick(' + i + ')">'
    + '<span class="k_ROW_SEQ">' + (i + 1) + '</span> <span class="k_PRJ_NM">가짜사업</span> <span class="k_CONT_NO">' + r.cont_no + '</span>'
    + '<span class="k_CONT_PROG_STS_NM">' + r.state + '</span> <span class="k_CONT_DT">' + r.cont_dt + '</span> <span class="k_CONT_NM">' + r.cont_nm + '</span>'
    + '<span class="k_PURCH_REQ_NO">' + r.req_no + '</span></div>').join('');
}
function search() {
  const s = document.getElementById('START_DATE').value, e = document.getElementById('END_DATE').value;
  rows = []; render();
  setTimeout(() => { rows = ALL.filter(r => r.cont_dt >= s && r.cont_dt <= e); render(); }, 300);
}
document.getElementById('btnSearch').onclick = search;
document.getElementById('btnWorkSave').onclick = () => fetch('/completed');
function pick(i) {
  const r = rows[i];
  setTimeout(() => {
    document.getElementById('PURCH_REQ_NO').value = r.req_no; document.getElementById('PRJ_NO').value = r.prj; document.getElementById('CONT_SEQ_NO').value = r.cont_no;
    document.getElementById('att').innerHTML = r.files.map(f => '<div class="jgrid-row"><select><option>증빙문서</option><option selected>구매관련문서</option></select>'
      + '<a class="btn_lnk" href="/comm0008_01.act?USEFAC_SEQ_NO=10&ATTFILE_SEQ_NO=' + f[0] + '&SKEY=abc">' + f[1] + '</a></div>').join('');
    document.getElementById('items').innerHTML = r.items.map((it, j) => '<div class="jgrid-row" r="' + j + '" ondblclick="window.open(\\'/rexpe_0054_t01_02.act?item=' + encodeURIComponent(it) + '\\', \\'pop\\', \\'width=600,height=400\\')">'
      + '<span class="k_ROW_SEQ">' + (j + 1) + '</span> <span class="k_CONT_ITEM_NM_KR">' + it + '</span> <span class="k_ITEM_VIEW_NO">24000' + j + '</span></div>').join('');
  }, 200);
}
</script></body></html>"""

POPUP = """<!doctype html><html><body>
<input id="ITEM_NM" value="__ITEM__" readonly>
<input type="hidden" id="IMGFILE_SEQ_NO" value="9"><input type="hidden" id="IMGFILE_SEQ_NO2" value="0">
<img id="USER_PICTURE" src="/comm0008_01.act?USEFAC_SEQ_NO=10&ATTFILE_SEQ_NO=9&PROC_CD=preview" width="340" height="120">
<img id="USER_PICTURE2" src="/proto/web/img/groupware/img_noimage.png">
<a id="btnSave">저장</a> <a id="btnImgDel">사진삭제</a>
</body></html>"""


class _Erp(BaseHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, *_a):  # noqa: D401 — 조용히
        return

    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if not ctype.startswith("text/html"):
            self.send_header("Content-Disposition", "attachment; filename=f.bin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        import json
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        _Erp.hits.append(u.path)
        if u.path == "/rderp_layoutMain.act":
            return self._send(TOP.encode())
        if u.path == "/rexpe_0155_01.act":
            rows = [{"PURCH_REQ_NO": c["no"], "PRJ_NO": c["prj"], "REQ_DT": c["dt"], "PURCH_CONT": c["title"], "PURCH_PROG_STS_NM": c["state"],
                     "PURCH_KIND_NM": "물품", "PURCH_AMT": 1000, "CONT_NO": "", "CONT_PROG_STS_NM": "", "ROW_SEQ": i + 1, "PRJ_NM": "가짜"} for i, c in enumerate(CASES)]
            html = LIST.replace("__ROWS__", json.dumps(rows, ensure_ascii=False)).replace("__START__", q.get("s", "")).replace("__END__", q.get("e", ""))
            return self._send(html.encode())
        if u.path == "/rexpe_0156_01.act":
            c = next(c for c in CASES if c["no"] == q.get("no"))
            links = "".join(f'<a href="/comm0008_01.act?USEFAC_SEQ_NO=10&ATTFILE_SEQ_NO={seq}&SKEY=zz">{name}</a>' for seq, name in c["files"])
            html = (DETAIL.replace("__NO__", c["no"]).replace("__PRJ__", c["prj"]).replace("__DT__", c["dt"]).replace("__TITLE__", c["title"])
                    .replace("__STATE__", c["state"]).replace("__LINKS__", links).replace("__S__", q.get("s", "")).replace("__E__", q.get("e", "")))
            return self._send(html.encode())
        if u.path == "/rexpe_0201_01.act":
            rows = [{"req_no": "202606170005", "prj": "202408470003", "cont_no": "C-1", "state": "검사완료", "cont_dt": "2026-07-01", "cont_nm": "[물품] 노트북",
                     "files": [["7", "계약 관련 서류(2026-0701-001).pdf"]], "items": ["노트북 15인치"]},
                    {"req_no": "202509010002", "prj": "202408470002", "cont_no": "C-2", "state": "지출청구", "cont_dt": "2025-10-01", "cont_nm": "[물품] 다른 과제",
                     "files": [["3", "다른.pdf"]], "items": []}]
            return self._send(INSPECT.replace("__ROWS__", json.dumps(rows, ensure_ascii=False)).encode())
        if u.path == "/rexpe_0054_t01_02.act":
            return self._send(POPUP.replace("__ITEM__", q.get("item", "")).encode())
        if u.path == "/comm0008_01.act":
            # 실제 ERP 처럼 화면 밖(Referer 없음)에서 부르면 로그인 화면 HTML 을 준다
            # 2026-10-22 18:10 실제: 화면 안 fetch 로도 HTML — 링크를 눌러(navigate) 받을 때만 파일
            if self.headers.get("Sec-Fetch-Mode") != "navigate" and "PROC_CD=preview" not in self.path:
                return self._send(b"<html><body>login</body></html>")
            body, ctype = FILES.get(q.get("ATTFILE_SEQ_NO", ""), (b"<html>login</html>", "text/html"))
            return self._send(body, ctype)
        self._send(b"<html>login</html>")


@pytest.fixture
def erp_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Erp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Erp.hits = []
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_purchase_documents_are_received_from_a_mock_erp(erp_server, tmp_path):
    """실제 Chromium 이 있을 때만 — 메인화면 → '구매·자산' → 2년 창 둘로 조회 → 고른 과제의 건마다 chk + [상세조회/변경] → 첨부 받기 → [진행관리목록]
    → 검사처리 → 줄 라디오 → 첨부 · 물품 사진. 다른 과제의 건 · 이미 있는 파일은 받지 않고, 저장 · 삭제 · 완료 단추는 눌리지 않는다."""
    import os
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path / "지출결의서"
    (root / "(202408470003)_2026년도 사업비_4,438,000,000" / "01. 인건비").mkdir(parents=True)
    kept = root / purchase.FOLDER_NAME / "(202408470003)_2026년도 사업비_4,438,000,000" / "(260617) 연구용 노트북 구입_(202606170005)"
    kept.mkdir(parents=True)
    (kept / "견적서.pdf").write_bytes(b"old")        # 이미 받은 파일 — 덮어쓰지 않는다
    logs: list[str] = []
    notes: list[tuple] = []
    projects = [Project("202408470003", "가짜", "2024-06-01", "2027-02-28"), Project("202408470002", "가짜", "2025-03-01", "2026-02-28")]
    try:
        with sync_api.sync_playwright() as p:
            path = "/opt/pw-browsers/chromium"
            browser = p.chromium.launch(executable_path=path if os.path.exists(path) else None)
            context = browser.new_context()
            page = context.new_page()
            page.goto(erp_server + "/rderp_layoutMain.act")
            wait = lambda sec: page.wait_for_timeout(int(sec * 1000))  # noqa: E731

            frame, why = purchase.open_list(context, logs.append, wait)
            assert frame is not None, why
            start, end = purchase.span(projects, TODAY)
            rows_all = []
            for s, e in purchase.windows(start, end):
                ok, why = purchase.search(frame, s, e, logs.append, wait)
                assert ok, why
                rows_all += purchase.read_rows(frame)
            mine = [purchase.as_target(r) for r in rows_all if r["prj_no"] == "202408470003"]
            assert sorted(t["req_no"] for t in mine) == ["202504010001", "202606170005", "202610220001"]
            assert all(t["expDt"] for t in mine)
            # 2년 창 둘 — 730일을 넘는 조회를 한 번에 하지 않았다(모의 화면이면 alert)
            assert any("2024-06-01 ~ 2026-05-31" in line for line in logs) and any("2026-06-01 ~ 2026-10-22" in line for line in logs)

            summary = purchase.run(context, page, mine, str(root), logs.append, wait, lambda i, st, d: notes.append((i, st, d)))
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        if "Executable doesn't exist" in str(error) or "browser" in str(error).lower() and "launch" in str(error).lower():
            pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
        raise
    by_no = {c.req_no: c for c in summary.cases}
    assert set(by_no) == {"202504010001", "202606170005", "202610220001"} and not summary.failed, [c.summary() for c in summary.cases]
    base = root / purchase.FOLDER_NAME / "(202408470003)_2026년도 사업비_4,438,000,000"
    assert (kept / "견적서.pdf").read_bytes() == b"old" and by_no["202606170005"].existed == 1      # 있던 파일은 그대로
    assert (kept / "재료구매내역서.xlsx").read_bytes().startswith(b"PK")                           # 새 파일만 받음
    assert (kept / purchase.INSPECT_DIR / "계약 관련 서류(2026-0701-001).pdf").read_bytes() == b"%PDF-1.4 contract"
    assert (kept / purchase.INSPECT_DIR / "물품사진_노트북 15인치_1.jpg").read_bytes() == b"\xff\xd8\xff photo"
    assert by_no["202606170005"].photos == 1 and by_no["202606170005"].inspected
    assert (base / "(250401) 작년 봄 장비_(202504010001)" / "작년.pdf").exists()
    assert by_no["202610220001"].summary() == "첨부 없음" and not (base / "(261022) 2026년 AI 기반 자동 취약점 진단 솔루션_(202610220001)").exists()
    assert not list((root / purchase.FOLDER_NAME).glob("*202408470002*"))                          # 다른 과제의 건은 받지 않음
    assert summary.inspected_rows == 2
    assert not any(h in ("/saved", "/requested", "/deleted", "/completed") for h in _Erp.hits)
    assert [st for _i, st, _d in notes if st == "done"] and all(st != "failed" for _i, st, _d in notes)
    assert all(not p.name.endswith(".part") for p in root.rglob("*"))


def test_purchase_root_setting_moves_case_folders(tmp_path, monkeypatch):
    """설정에서 고른 폴더(구글 드라이브 등)가 있으면 그 아래에 과제 폴더 이름 그대로."""
    from claim_downloader import settings
    root = tmp_path / "지출결의서"
    (root / "(202408470001)_2024년도 사업비_1").mkdir(parents=True)
    drive = tmp_path / "G" / "내 드라이브" / "구매요청(계약) 서류"
    assert purchase.project_base(root, "202408470001")[0] == root / purchase.FOLDER_NAME / "(202408470001)_2024년도 사업비_1"
    cfg = settings.load()
    cfg.purchase_root = str(drive)
    settings.save(cfg)
    base, why = purchase.project_base(root, "202408470001")
    assert base == drive / "(202408470001)_2024년도 사업비_1", why
    assert purchase.project_base(root, "202408470002")[0] is None   # 과제 폴더가 없으면 여전히 받지 않음
