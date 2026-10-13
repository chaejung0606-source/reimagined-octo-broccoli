"""안전 원칙을 코드로 지킨다.

  - ERP 에서는 받기만 한다. 누르는 것은 목록 선택·상세조회·청구서출력·OZ 저장·목록 복귀뿐.
    저장·신청·제출 버튼을 누르는 코드가 들어오면 여기서 깨진다.
  - 로그인 정보를 저장하지 않는다.
  - 브라우저를 띄우는 곳은 session.py 하나뿐이다.

새 기능(일반청구 작성 등)을 넣느라 이 테스트를 고쳐야 한다면, 고치기 전에
CLAUDE.md '안전 원칙' 을 다시 읽는다.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "claim_downloader"
ERP = (SRC / "erp.py").read_text(encoding="utf-8")

# JS 안에서 글자로 찾아 누르거나 비교하는 대상
ALLOWED_TEXT = {"청구서출력", "목록", "확인", "비목", "예금주", "입금처"}
ALLOWED_IDS = {"#btnDetail"}
ALLOWED_PY_CLICKS = {'popup.click("input.btnSAVEAS")'}


def test_erp_only_touches_known_targets():
    texts = set(re.findall(r"===\s*'([^']+)'", ERP))
    assert texts <= ALLOWED_TEXT, texts - ALLOWED_TEXT
    ids = set(re.findall(r"'(#[A-Za-z_][\w-]*)'", ERP))
    assert ids <= ALLOWED_IDS, ids - ALLOWED_IDS
    py_clicks = set(re.findall(r"\w+\.click\([^)]*\)", ERP)) - {"b.click()", "e.click()", "c.click()", "cb.click()"}
    assert py_clicks <= ALLOWED_PY_CLICKS, py_clicks - ALLOWED_PY_CLICKS


def test_no_typing_into_erp():
    for name in ("fill(", "type(", "press(", "set_input_files(", "keyboard."):
        assert name not in ERP, name


def test_no_credentials_anywhere():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        # storage_state · user_data_dir 는 로그인 쿠키를 디스크에 남긴다
        for word in ("password", "passwd", "storage_state", "user_data_dir"):
            assert word not in text, f"{path.name}: {word}"


def test_browser_is_launched_in_one_place():
    pattern = re.compile(r"^\s*(from|import)\s+playwright", re.M)
    users = sorted(p.name for p in SRC.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8")))
    assert users == ["session.py"], users


def test_diagnose_only_reads():
    """진단 모드는 화면을 읽기만 한다 — 누르거나 값을 넣거나 이벤트를 일으키는 코드가 들어오면 깨진다."""
    text = (SRC / "diagnose.py").read_text(encoding="utf-8")
    for forbidden in (".click(", ".submit(", "dispatchEvent", ".focus(", "setAttribute(", "fill(", "type(", "press("):
        assert forbidden not in text, forbidden
    assert not re.search(r"\.(value|checked|selectedIndex|innerHTML)\s*=[^=]", text)
    assert "import playwright" not in text and "from playwright" not in text


def test_claim_fill_lives_outside_erp_and_cannot_press_money_buttons():
    """값 넣기는 claims/form.py 에만 — 받기 코드(erp.py)에는 끝까지 없다.

    누르는 단추는 임시저장('저장') 하나뿐이고(담당자 결정 2026-10-13), 돈이 나가는 '신청' 을 누르는 코드는 어디에도 없다.
    """
    form = (SRC / "claims" / "form.py").read_text(encoding="utf-8")
    assert "FORBIDDEN_TEXTS" in form and form.count(".click(") == 1
    assert 'SAVE_TEXT = "저장"' in form and '"신청"' in form.split("FORBIDDEN_TEXTS = ", 1)[1].split("\n", 1)[0]
    for name in ("fill(", "type(", "press(", "set_input_files(", "keyboard."):
        assert name not in ERP, name
    for path in (SRC / "claims").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "playwright" not in text, path.name
        body = text.replace('FORBIDDEN_TEXTS = ("신청",', "").replace('SAVE_TEXT = "저장"', "")
        for word in ("신청')", '"신청"', "evaluate(CLICK_SAVE_JS, \"신청"):
            # 글자로 '신청' 단추를 찾아 누르는 코드가 들어오면 여기서 걸린다 (금지 목록 상수는 제외)
            assert word not in body, f"{path.name}: {word}"


def _click_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if "CLICK_ID_JS" in line and "evaluate(" in line]


def test_payee_popup_presses_only_search_buttons():
    """입금처 팝업(claims/payee.py)은 돋보기 · 구분 라디오 · [검색] 만 누른다.

    계좌등록 · 거래처등록 같은 기준 정보 단추와, 결과 목록 실측 전인 [확인](btn_s_confirm1)을 누르는 코드가 들어오면 깨진다.
    """
    text = (SRC / "claims" / "payee.py").read_text(encoding="utf-8")
    assert text.count(".click(") == 2                                   # 단추 id 하나 · 구분 라디오 하나
    # 단추를 누르는 곳: open_popup 안(넘겨받은 button_id) 과 [검색] 뿐. 여는 단추로 넘기는 것은 돋보기 하나.
    assert set(re.findall(r"evaluate\(CLICK_ID_JS,\s*([A-Za-z_]+)\)", text)) == {"button_id", "SEARCH_BUTTON_ID"}
    assert re.findall(r"open_popup\(page, frame, ([A-Z_]+),", text) == ["OPEN_BUTTON_ID"]
    assert 'OPEN_BUTTON_ID = "btnRcvCd"' in text and 'SEARCH_BUTTON_ID = "btn_search"' in text
    for line in _click_lines(text):
        for word in ("btnReg", "btnUpd", "rbaseRegg", "rbaseUpt", "btn_s_confirm", "계좌등록", "거래처등록"):
            assert word not in line, line
    assert "btn_s_confirm" not in text.split("POPUP_PROBE_JS", 1)[1].split('"""', 2)[2]   # 알아보기용 선택자에만


def test_taxbill_popup_presses_only_select_and_inquiry():
    """세금계산서 조회 팝업(claims/taxbill.py)은 [선택] 과 [조회] 만 누른다 — [등록] · XML 등록 · [확인](btn_out) 은 아니다."""
    text = (SRC / "claims" / "taxbill.py").read_text(encoding="utf-8")
    assert ".click(" not in text                                         # 누르는 JS 는 payee.CLICK_ID_JS 를 빌려 쓴다
    assert set(re.findall(r"evaluate\(CLICK_ID_JS,\s*([A-Za-z_]+)\)", text)) == {"INQUIRY_BUTTON_ID"}
    assert re.findall(r"open_popup\(page, frame, ([A-Z_]+),", text) == ["SELECT_LINK_ID"]
    assert 'SELECT_LINK_ID = "onlyEvdiDivList"' in text and 'INQUIRY_BUTTON_ID = "btn_inquiry"' in text
    for line in _click_lines(text):
        for word in ("btn_insert", "btn_reg_xml", "btnSupOrgCd", "btn_detail", "btn_out"):
            assert word not in line, line
    assert "btn_out" not in text.split("POPUP_PROBE_JS", 1)[1].split('"""', 2)[2]
