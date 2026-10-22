"""진단 모드(diagnose.py) — 브라우저 없이 글 만들기와 가림 규칙만 본다. JS 는 모의 ERP 로 따로 돌린다."""
from __future__ import annotations

import datetime as dt

import pytest

from claim_downloader import diagnose, settings


def _el(**kw):
    base = {"tag": "input", "type": "text", "id": "", "name": "", "cls": "", "label": "", "text": "",
            "value": "", "options": None, "onclick": "", "href": "", "disabled": False, "readonly": False,
            "visible": True}
    base.update(kw)
    return base


def test_password_values_are_never_written():
    el = _el(type="password", id="pw", value="secret123")
    line = diagnose._element_line(el)
    assert "secret123" not in line and "값:" not in line
    assert "값:" not in diagnose._element_line(_el(type="file", value="C:/x.pdf"))


def test_long_values_are_cut():
    el = _el(id="acct", value="1" * 100)
    line = diagnose._element_line(el)
    assert "1" * 41 not in line and "…" in line


def test_report_lists_visible_first_then_hidden_and_marks_known_frames():
    windows = [{"title": "ERP", "url": "https://erp/main", "frames": [
        {"url": "https://erp/rtask_0008_t04_01.act", "title": "", "kind": "결의서 목록", "elements": [
            _el(tag="button", type="", id="btnDetail", text="상세조회/변경"),
            _el(tag="input", type="hidden", name="prjNo", value="P-1", visible=False),
            _el(tag="select", type="", name="bimok", label="비목", value="인건비", options=["인건비", "장학금"]),
        ]},
        {"url": "about:blank", "title": "", "kind": "", "elements": [], "error": "Execution context was destroyed"},
    ]}]
    text = diagnose.format_report(windows, when="2026-10-13 10:00")
    lines = text.splitlines()
    assert lines[0].startswith("COSS 업무데스크 화면 구조")
    assert "[창 0] ERP | https://erp/main" in text
    assert "<== 결의서 목록" in text
    assert "요소 3개 (보임 2 · 숨김 1)" in text
    assert "<button>  #btnDetail  '상세조회/변경'" in text
    assert "<select>  name=bimok  라벨: 비목  값: 인건비  보기: 인건비 | 장학금" in text
    assert "[숨김] <input hidden>  name=prjNo  값: P-1" in text
    assert "(읽지 못함: Execution context was destroyed)" in text
    assert text.index("#btnDetail") < text.index("[숨김] <input")


def test_empty_report_and_path():
    assert "(열린 창이 없음)" in diagnose.format_report([], when="x")
    assert settings.structure_path().name == "_화면구조.txt"


def test_repeated_elements_are_collapsed():
    """목록 행마다 있는 체크박스 30개가 30줄이 되지 않게 — 같은 줄이 잇달으면 (× N)."""
    els = [_el(type="checkbox", value="꺼짐")] * 30 + [_el(id="x")] + [_el(type="checkbox", value="꺼짐")] * 2
    lines = diagnose._collapsed(els)
    assert len(lines) == 3
    assert lines[0].endswith("(× 30)") and "#x" in lines[1] and lines[2].endswith("(× 2)")


def test_grids_are_listed_with_columns_and_masked_first_row():
    """검색 결과 목록의 열 구조를 알 수 있어야 고르는 코드를 짤 수 있다 — 입력 요소만으로는 안 보인다(입금처 팝업 실측)."""
    grids = [
        {"kind": "grid", "visible": True, "rows": 3, "cols": [
            {"key": "k_CUST_NM", "head": "거래처명", "sample": "코웨이(주)"},
            {"key": "k_BIZ_NO", "head": "사업자번호", "sample": "12…"}]},
        {"kind": "table", "visible": False, "rows": 2, "heads": ["선택", "성명"], "first": ["", "홍길동"], "picks": 1,
         "onclick": "fn_select(this)"},
    ]
    lines = diagnose._grid_lines(grids)
    assert lines[0] == "그리드: 행 3 · 열: k_CUST_NM(거래처명) | k_BIZ_NO(사업자번호)"
    assert lines[1] == "  첫 행: k_CUST_NM=코웨이(주) | k_BIZ_NO=12…"
    assert lines[2].startswith("[숨김] 표: 행 2 · 머리글: 선택 | 성명")
    assert "행마다 선택 칸 1개" in lines[3] and "fn_select" in lines[3]
    windows = [{"title": "입금처조회", "url": "https://erp/pop", "frames": [
        {"url": "https://erp/pop", "title": "", "kind": "", "elements": [], "grids": grids[:1]}]}]
    text = diagnose.format_report(windows, when="x")
    assert "    그리드: 행 3" in text
    assert "\\d{6,}" in diagnose._GRID_JS                    # 긴 숫자(계좌·사업자번호)는 가린다


def test_ibsheet_tables_are_listed_with_their_first_rows():
    """구매진행관리(IBSheet) 목록이 'div.SheetMain' 한 줄로만 잡혀 열을 알 수 없었다(2026-10-22 실측 1 · 2번)."""
    grids = [
        {"kind": "ibsheet", "visible": True, "rows": 5, "tables": 2, "attrs": ["id", "col"], "classes": ["GMHeader"],
         "sample": [["", "구매요구번호", "대표건명"], ["1", "20…", "노트북 구입"], ["2", "20…", "전산용품"]]},
        {"kind": "ibsheet", "visible": False, "rows": 0, "tables": 0, "attrs": [], "classes": ["GMBody", "GMRow"], "sample": []},
    ]
    lines = diagnose._grid_lines(grids)
    assert lines[0] == "IBSheet 표: 글자 줄 5 · table 2개 · 칸 속성: id,col"
    assert lines[1] == "  줄 1: 구매요구번호 | 대표건명" and lines[3] == "  줄 3: 2 | 20… | 전산용품"
    assert lines[4] == "[숨김] IBSheet 표: 글자 줄 0 · table 0개 · 안쪽 class: GMBody,GMRow"   # 줄을 못 읽으면 모양 단서만


def test_ibsheet_rows_are_read_in_a_real_browser():
    """실제 Chromium 이 있을 때만 — IBSheet 흉내(머리글 table + 줄 table, 긴 번호)에서 줄과 첫 칸 속성을 읽는다."""
    import os
    import pytest
    sync_api = pytest.importorskip("playwright.sync_api")
    html = ("<div class='SheetMain RERPMain' onclick='return IBSheet[0].SheetClick(event)'>"
            "<div class='GMHeader'><table><tr><td id='S0_H_0'>선택</td><td id='S0_H_1'>구매요구번호</td><td id='S0_H_2'>대표건명</td></tr></table></div>"
            "<div class='GMBody'><table><tr><td id='S0_1_0'><input type=checkbox></td><td id='S0_1_1'>202604130007</td><td id='S0_1_2'>노트북 구입</td></tr>"
            "<tr><td id='S0_2_0'></td><td id='S0_2_1'>202609290005</td><td id='S0_2_2'>용역</td></tr></table></div></div>")
    try:
        with sync_api.sync_playwright() as p:
            path = "/opt/pw-browsers/chromium"
            browser = p.chromium.launch(executable_path=path if os.path.exists(path) else None)
            page = browser.new_page()
            page.set_content(html)
            got = page.evaluate(diagnose._GRID_JS)
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
    assert len(got) == 1 and got[0]["kind"] == "ibsheet" and got[0]["rows"] == 3 and got[0]["tables"] == 2
    assert got[0]["sample"][0] == ["선택", "구매요구번호", "대표건명"] and got[0]["sample"][1][1] == "20…"   # 긴 번호는 가림
    assert got[0]["attrs"] == ["id"] and "root" not in got[0]


def test_ibsheet_api_and_images_are_written():
    """IBSheet 스크립트로 읽은 열 · 줄과 그림(물품 사진) 주소가 보고서에 적힌다 — 2026-10-22 13:46 · 13:49 실측에서 DOM 만으로는
    머리글 27칸 · 자료 줄 20칸이라 열을 못 맞췄고, 물품 사진은 숨은 번호 칸만 잡혔다."""
    grids = [{"kind": "ibsheet-api", "index": 0, "id": "sheet1", "version": "8.0", "total": 58, "headerRows": 1,
              "funcs": ["GetDataRows", "GetValue"], "cols": [{"save": "sChk", "head": ""}, {"save": "PURCH_REQ_NO", "head": "구매요청번호", "type": "Text"},
                                                            {"save": "PURCH_CONT", "head": "내용"}],
              "sample": [["", "20…", "노트북 구입"]]}]
    lines = diagnose._grid_lines(grids)
    assert lines[0] == "IBSheet 스크립트 [0] id sheet1 판 8.0 · 줄 58 · 열 3 · 머리글 줄 1"
    assert lines[1] == "  함수: GetDataRows GetValue"
    assert lines[2] == "  열: sChk | PURCH_REQ_NO(구매요청번호)<Text> | PURCH_CONT(내용)"
    assert lines[3] == "  줄 1: - | 20… | 노트북 구입"
    images = [{"src": "/comm0008_01.act?ATTFILE_SEQ_NO=19…", "alt": "물품사진", "w": 120, "h": 90, "nw": 640, "nh": 480,
               "id": "img1", "onclick": "", "visible": True},
              {"src": "/img/x.png", "alt": "", "w": 0, "h": 0, "nw": 0, "nh": 0, "id": "", "onclick": "", "visible": False}]
    got = diagnose._image_lines(images)
    assert got[0] == "그림: /comm0008_01.act?ATTFILE_SEQ_NO=19…  120×90 (원본 640×480)  #img1  alt='물품사진'"
    assert got[1] == "[숨김] 그림: /img/x.png  0×0"
    windows = [{"title": "물품내역팝업", "url": "https://erp/pop", "frames": [
        {"url": "https://erp/pop", "title": "", "kind": "", "elements": [], "grids": grids, "images": images}]}]
    text = diagnose.format_report(windows, when="x")
    assert "    IBSheet 스크립트 [0]" in text and "    그림: /comm0008_01.act" in text


def test_ibsheet_api_and_images_are_read_in_a_real_browser():
    """실제 Chromium 이 있을 때만 — 가짜 IBSheet 객체(Get… 함수만)와 그림에서 열 이름 · 앞 줄 · 그림 주소를 읽고, 작은 아이콘은 뺀다."""
    import os
    import pytest
    sync_api = pytest.importorskip("playwright.sync_api")
    html = """<img src='/img/icon.gif' width=16 height=16><img id='photo' src='/comm0008_01.act?USEFAC_SEQ_NO=10&ATTFILE_SEQ_NO=1922592' width=120 height=90 alt='사진'>
    <div class='SheetMain' onclick='return IBSheet[0].SheetClick(event)'></div>
    <script>
      // 8 판 흉내(14:19 실측 — 줄은 객체 · 열은 Cols · version 은 함수) + 7 판 흉내 하나
      const data = [{Kind: 'Data', sChk: 0, PURCH_REQ_NO: '202604130007', PURCH_CONT: '노트북 구입'},
                    {Kind: 'Data', sChk: 0, PURCH_REQ_NO: '202609290005', PURCH_CONT: '용역'}];
      const v8 = {id: 'sheet1', version: () => '8.0.1', SheetClick: () => true, SetValue: () => { throw new Error('눌림'); },
        Cols: {sChk: {Header: '선택', Type: 'Bool'}, PURCH_REQ_NO: {Header: '구매요청번호', Type: 'Text'}, PURCH_CONT: {Header: '대표건명', Type: 'Text'}},
        GetDataRows: () => data, GetRows: () => [{Kind: 'Header'}].concat(data), GetHeaderRows: () => [{Kind: 'Header'}],
        GetValue: (row, col) => row[col], GetCaption: col => v8.Cols[col].Header};
      // Cols 가 없는 8 판 — 줄 객체의 키로 열을 삼는다
      const v8b = {GetDataRows: () => [{Kind: 'Data', id: 'r1', PURCH_REQ_NO: '202604130007', CONT: '의자', Visible: true}], GetPageNum: () => 3};
      const rows = [['', '선택', '구매요청번호', '대표건명'], ['', '', '202604130007', '노트북 구입'], ['', '', '202609290005', '용역']];
      const v7 = {version: '7.0', GetTotalRows: () => 2, LastCol: () => 2, HeaderRows: () => 1, LastRow: () => 2,
        ColSaveName: c => ['sChk', 'PURCH_REQ_NO', 'PURCH_CONT'][c], GetHeaderText: c => rows[0][c + 1], GetCellText: (r, c) => rows[r][c + 1]};
      window.IBSheet = [v8, v7, v8b];
    </script>"""
    try:
        with sync_api.sync_playwright() as p:
            path = "/opt/pw-browsers/chromium"
            browser = p.chromium.launch(executable_path=path if os.path.exists(path) else None)
            page = browser.new_page()
            page.set_content(html)
            grids = page.evaluate(diagnose._GRID_JS)
            probe = page.evaluate(diagnose._PROBE_JS)
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
    api = [g for g in grids if g["kind"] == "ibsheet-api"]
    assert len(api) == 3
    v8, v7, v8b = api
    assert [c["save"] for c in v8b["cols"]] == ["Kind", "id", "PURCH_REQ_NO", "CONT", "Visible"] and v8b["pages"] == 3
    assert v8b["sample"] == [["Data", "r1", "20…", "의자", "true"]]
    assert "GetDataRows" in v8b["funcs"]
    assert v8["id"] == "sheet1" and v8["version"] == "" and v8["total"] == 2 and v8["headerRows"] == 1    # version 이 함수면 적지 않는다
    assert [c["save"] for c in v8["cols"]] == ["sChk", "PURCH_REQ_NO", "PURCH_CONT"] and v8["cols"][1]["head"] == "구매요청번호"
    assert v8["cols"][1]["type"] == "Text"
    assert v8["sample"] == [["0", "20…", "노트북 구입"], ["0", "20…", "용역"]]           # 긴 번호는 가림
    assert "GetDataRows" in v8["funcs"] and "SetValue" in v8["funcs"]      # 이름은 다 적되 부르지는 않는다(SetValue 는 부르면 던진다)
    assert v7["total"] == 2 and [c["save"] for c in v7["cols"]] == ["sChk", "PURCH_REQ_NO", "PURCH_CONT"]
    assert v7["sample"] == [["", "20…", "노트북 구입"], ["", "20…", "용역"]]
    images = probe["images"]
    assert len(images) == 1 and images[0]["id"] == "photo" and "ATTFILE_SEQ_NO=1922592" in images[0]["src"] and images[0]["alt"] == "사진"


def test_menu_text_without_link_is_marked_pressable():
    """메뉴 · 탭 글자(li · span — a · button 이 아님)도 적는다 — 로그인 뒤 메뉴 이동을 실측하려고(2026-10-19)."""
    line = diagnose._element_line(_el(tag="span", type="", id="menu_1", text="과제관리", pointer=True))
    assert "'과제관리'" in line and "#menu_1" in line and "[누를 수 있음]" in line


def test_probe_finds_menu_text_in_a_real_browser():
    """실제 Chromium 이 있을 때만 — 손가락 커서 글자는 가장 안쪽 하나만, 긴 묶음 · 링크 안의 글자는 빼고."""
    import os
    import pytest
    sync_api = pytest.importorskip("playwright.sync_api")
    html = ("<ul id='gnb' style='cursor:pointer'><li id='m1'><span>과제관리</span><ul><li id='m11'>과제정보</li></ul></li></ul>"
            "<div style='cursor:pointer' class='tab'>청구서</div><a href='#'><span>목록</span></a><span>보통 글자</span>")
    try:
        with sync_api.sync_playwright() as p:
            path = "/opt/pw-browsers/chromium"
            browser = p.chromium.launch(executable_path=path if os.path.exists(path) else None)
            page = browser.new_page()
            page.set_content(html)
            got = page.evaluate(diagnose._PROBE_JS)["elements"]
            browser.close()
    except Exception as error:  # noqa: BLE001 — 브라우저가 없는 곳(CI)
        pytest.skip(f"브라우저 없음: {str(error).splitlines()[0][:80]}")
    pressable = {(e["tag"], e["id"], e["text"]) for e in got if e.get("pointer")}
    assert pressable == {("span", "", "과제관리"), ("li", "m11", "과제정보"), ("div", "", "청구서")}, pressable


def test_each_save_is_added_to_the_book(tmp_path):
    """[화면 구조 저장] 을 여러 번 누르면 모음 파일에 차례로 쌓인다 — 메뉴 이동처럼 화면 여러 개를 실측할 때 하나만 보내면 되게."""
    book = tmp_path / "_화면구조_모음.txt"
    assert diagnose.append_to_book(book, "첫 화면\n") == 1
    assert diagnose.append_to_book(book, "둘째 화면\n") == 2
    text = book.read_text(encoding="utf-8")
    assert text.index("════ 화면 구조 1번째 ════\n첫 화면") < text.index("════ 화면 구조 2번째 ════\n둘째 화면")


def test_capture_keeps_only_the_chosen_site():
    """화면 구조 저장 업무(담당자 2026-10-21) — ERP · 주차등록 사이트 중 고른 곳의 창만 읽는다."""
    class Frame:
        url = ""

        def evaluate(self, js, *args):
            return [] if js is diagnose._GRID_JS else {"elements": [], "title": ""}

    class Page:
        def __init__(self, url):
            self.url, self.frames = url, [Frame()]

        def is_closed(self):
            return False

        def title(self):
            return self.url

    class Context:
        pages = [Page("https://knu-icf.kangwon.ac.kr/rderp_layoutMain.act"), Page("https://traffic.kangwon.ac.kr/discount-apply"),
                 Page("https://knu-icf.kangwon.ac.kr/rexpe_0084_rcv_pop.act")]

    every = diagnose.capture(Context())
    erp_only = diagnose.capture(Context(), keep=lambda url: "knu-icf" in url)
    assert len(every) == 3 and [w["url"] for w in erp_only] == [Context.pages[0].url, Context.pages[2].url]
    assert "대상: ERP" in diagnose.format_report(erp_only, target="ERP").splitlines()[0]


def test_copy_to_desktop_keeps_old_copies(tmp_path):
    """바탕화면에 저장(담당자 2026-10-22) — 모음 파일이 있으면 그것을, 바탕화면의 파일은 덮어쓰지 않는다."""
    desktop, data = tmp_path / "바탕 화면", tmp_path / "data"
    desktop.mkdir()
    data.mkdir()
    book, single = data / "_화면구조_모음.txt", data / "_화면구조.txt"
    when = dt.datetime(2026, 10, 22, 10, 7)
    with pytest.raises(FileNotFoundError):
        diagnose.copy_to_desktop(desktop, book, single, when)
    single.write_text("마지막 화면", encoding="utf-8")
    assert diagnose.copy_to_desktop(desktop, book, single, when).name == "화면구조_20261022_1007.txt"
    book.write_text("모음", encoding="utf-8")
    first = diagnose.copy_to_desktop(desktop, book, single, when)
    again = diagnose.copy_to_desktop(desktop, book, single, when)
    assert (first.name, again.name) == ("화면구조_모음_20261022_1007.txt", "화면구조_모음_20261022_1007_2.txt")
    assert first.read_text(encoding="utf-8") == "모음" == again.read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        diagnose.copy_to_desktop(tmp_path / "없음", book, single, when)
