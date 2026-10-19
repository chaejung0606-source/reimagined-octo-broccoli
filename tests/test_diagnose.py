"""진단 모드(diagnose.py) — 브라우저 없이 글 만들기와 가림 규칙만 본다. JS 는 모의 ERP 로 따로 돌린다."""
from __future__ import annotations

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
