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


# 로그인 정보를 다뤄도 되는 곳 — 주차등록 사이트뿐(담당자 허락 2026-10-21: "여기엔 개인정보같은게 없어서 자동 로그인해도 괜찮습니다").
# ERP 로그인 정보는 여전히 어디에도 두지 않는다(CLAUDE.md 9절).
# 로그인 정보 칸은 설정 화면의 ui/parking_login.py 에 있다(담당자 요청 2026-10-21: "주차등록 로그인 정보는 설정에서 입력하고 저장하는걸로")
PARKING_FILES = {SRC / "parking.py", SRC / "ui" / "parking_login.py"}


def test_no_credentials_anywhere():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        # storage_state · user_data_dir 는 로그인 쿠키를 디스크에 남긴다 — 주차등록도 안 된다
        for word in ("storage_state", "user_data_dir"):
            assert word not in text, f"{path.name}: {word}"
        if path in PARKING_FILES:
            continue
        for word in ("password", "passwd"):
            assert word not in text, f"{path.name}: {word}"


def test_parking_login_stays_with_parking():
    """주차등록 자동 로그인은 그 사이트에만 — ERP 쪽 코드는 그 로그인 정보를 읽지 않고, 주차 코드는 ERP 주소에 가지 않는다.
    로그인 정보는 저장소 · config.json 이 아니라 사용자 폴더의 _주차로그인.json 에(윈도우 DPAPI), 기록에는 비밀번호를 남기지 않는다."""
    from claim_downloader import parking
    text = (SRC / "parking.py").read_text(encoding="utf-8")
    assert "knu-icf" not in text and "ERP_URL" not in text
    assert "dpapi" in text.lower() and "CryptProtectData" in text
    for path in SRC.rglob("*.py"):
        if path in PARKING_FILES or path.name in ("session.py", "worker.py"):
            continue
        body = path.read_text(encoding="utf-8")
        assert "load_login" not in body and "_주차로그인" not in body or path.name == "settings.py", path.name
    # 넣는 칸은 표시를 붙인 아이디 · 비밀번호 둘뿐이고, 누르는 것은 Enter 와 '로그인' 단추 하나(SUBMIT_JS)뿐
    fills = re.findall(r"\.fill\(([A-Z_]+),", text)
    assert sorted(fills) == ["ID_SELECTOR", "PW_SELECTOR"], fills
    assert re.findall(r"\.press\(([A-Z_]+), \"(\w+)\"\)", text) == [("PW_SELECTOR", "Enter")]
    assert text.count(".click()") == 1 and parking.SUBMIT_JS.count(".click()") == 1
    assert "로그인|login" in parking.SUBMIT_JS and "cands.length !== 1" in parking.SUBMIT_JS
    # 비밀번호를 기록에 쓰는 줄이 없다 — log(...) 안에 secret 이 들어가지 않는다
    for call in re.findall(r"log\(([^\n]*)\)", text):
        assert "secret" not in call, call
    # 실패하면 다시 시도하지 않는다(계정 잠김) — 한 번 실패를 기억한다
    assert "_failed[\"why\"] = report.note" in text


def test_parking_link_presses_only_new_link_and_save():
    """주차등록 2단계(parking_link.py, 담당자 허락 2026-10-21: "어플에서 등록 누르면 사이트에도 눌리는걸로")가 누르는 것은
    할인 링크 화면의 [새 링크] 와 그 창의 [저장] 둘뿐이다. 값은 표시를 붙인 칸(링크 이름 · 주차장 · 상품 · 유효기간 · 활성 · '처음으로')에만.
    '삭제' · '수정' · '취소' · 'QR 보기' · 로그아웃 · 비밀번호 변경은 누르지 않고, ERP 에 가지 않으며 로그인 정보도 읽지 않는다."""
    from claim_downloader import parking_link
    text = (SRC / "parking_link.py").read_text(encoding="utf-8")
    assert re.findall(r"\.fill\(([A-Z_]+),", text) == ["NAME_SELECTOR", "START_SELECTOR", "END_SELECTOR"]
    assert re.findall(r"\.select_option\(([A-Z_]+),", text) == ["LOT_SELECTOR", "PRODUCT_SELECTOR"]
    assert re.findall(r"\.set_checked\(([A-Z_]+),", text) == ["ACTIVE_SELECTOR", "RESTART_SELECTOR"]
    assert re.findall(r"\.click\(([A-Z_]+)\)", text) == ["SAVE_SELECTOR"]
    assert text.count(".click()") == 1 and parking_link.OPEN_JS.count(".click()") == 1
    assert "'새링크'" in parking_link.OPEN_JS and "cands.length !== 1" in parking_link.OPEN_JS
    assert "squash(b.innerText) === '저장'" in parking_link.MARK_FORM_JS and "saves.length !== 1" in parking_link.MARK_FORM_JS
    for name in ("press(", "type(", "keyboard.", "set_input_files(", "dispatchEvent", "load_login", "ERP_URL", "knu-icf"):
        assert name not in text, name
    for js in (parking_link.OPEN_JS, parking_link.MARK_FORM_JS):
        for word in ("삭제", "수정", "취소", "QR", "로그아웃", "비밀번호"):
            assert word not in js, word
    assert "import playwright" not in text and "from playwright" not in text


def test_parking_apply_presses_only_the_described_steps():
    """할인 적용(parking_screens.py) — 담당자가 알려 준 차례(2026-10-21: "차량번호를 입력하고 보유 할인권에서 공무확인증 클릭, 그리고 할인선택에서
    공무확인증 선택하고 종료 버튼 클릭하면 할인이 적용됩니다. 이런 과정이 어플내에서")만 누른다: 차량번호 칸에 넣고 Enter · [조회](Enter 로 안 될 때) ·
    그 차의 줄 · '공무확인증' 이 든 것 · 할인 선택 고르기 칸의 보기 · [종료]. 화면 스크립트는 표시를 붙이기만 하고 누르지 않는다(누르기는
    표시를 붙인 것 하나를 Playwright 로). 할인 내역은 읽기만 — 모든 쪽을 읽으려고(담당자 2026-10-22 "전체 페이지 확인해주세요") 시작일 칸 ·
    건수 고르기(100건) · [검색] · 다음 쪽 '›' 만 다룬다. 로그인 정보 · ERP 는 보지 않는다."""
    from claim_downloader import parking_screens
    text = (SRC / "parking_screens.py").read_text(encoding="utf-8")
    assert re.findall(r"\.fill\(([A-Z_]+),", text) == ["CAR_SELECTOR", "HISTORY_FROM"]
    assert re.findall(r"\.press\(([A-Z_]+), \"(\w+)\"\)", text) == [("CAR_SELECTOR", "Enter")]
    assert re.findall(r"\.click\(([^)]*)\)", text) == ['f"[data-coss-apply={mark}]", timeout=5000',      # _click 하나
                                                       'f"[data-coss-history={mark}]", timeout=5000']    # _press 하나
    assert sorted(set(re.findall(r"_press\(frame, \"(\w+)\"\)", text))) == ["next", "search"]
    assert re.findall(r"\.select_option\(([A-Z_]+),", text) == ["HISTORY_SIZE"]
    marks = re.findall(r"_click\(frame, f?\"([a-z]+)-", text)
    assert sorted(set(marks)) == ["car", "finish", "search", "ticket"]
    assert re.findall(r"\.select_option\(f\"\[data-coss-apply=(\w+)-", text) == ["select"]
    for name in (".type(", "keyboard.", "set_checked(", "set_input_files(", "dispatchEvent", "submit(", ".value =", "load_login",
                 "ERP_URL", "knu-icf"):
        assert name not in text, name
    for js in (parking_screens.MARK_CAR_JS, parking_screens.TABLE_JS, parking_screens.SCAN_APPLY_JS, parking_screens.FEEDBACK_JS,
               parking_screens.HISTORY_CONTROLS_JS, parking_screens.HISTORY_NEXT_JS):
        assert "click(" not in js and ".value =" not in js
    # 할인 내역에서 누를 후보는 [검색](글자 12자 이하) 하나와 '›' 하나 — 엑셀 · 차량번호 단추 · 줄은 아니다
    assert "엑셀" not in parking_screens.HISTORY_CONTROLS_JS and "/검색|조회/" in parking_screens.HISTORY_CONTROLS_JS
    assert "t === '›'" in parking_screens.HISTORY_NEXT_JS
    # 누를 후보는 이름으로만 — [종료] · [조회] 는 글자가 그것뿐인 단추, 할인권은 '공무확인증' 이 든 것
    assert "/^종료(하기)?$/" in parking_screens.SCAN_APPLY_JS and parking_screens.TICKET_WORD == "공무확인증"
    for word in ("삭제", "수정", "취소", "로그아웃", "비밀번호"):
        assert word not in parking_screens.SCAN_APPLY_JS, word
    # [종료] 는 '하나일 때만' · 그 앞에서 멈추는 길이 있다
    assert 'seen.get("finishes") != 1' in text and text.index('seen.get("finishes") != 1') < text.index('_click(frame, "finish-0")')
    assert "import playwright" not in text and "from playwright" not in text


def test_auto_logout_presses_only_logout():
    """ERP 자동 로그아웃(담당자 요청 2026-10-21: 30분 활동 없음 · 로그아웃 없이 창을 닫음)이 누르는 것은 ERP 틀 위쪽의 [로그아웃]
    (#layoutMain_btn_logout, 글자 '로그아웃') 하나다. ERP 창에 미리 넣는 스크립트는 활동을 알리기만 하고 누르거나 값을 넣지 않는다."""
    from claim_downloader import logout
    text = (SRC / "logout.py").read_text(encoding="utf-8")
    assert text.count(".click()") == 1 and logout.CLICK_LOGOUT_JS.count(".click()") == 1
    assert "getElementById('layoutMain_btn_logout')" in logout.CLICK_LOGOUT_JS and "!== '로그아웃'" in logout.CLICK_LOGOUT_JS
    script = logout.activity_script("knu-icf.kangwon.ac.kr")
    for name in ("fill(", "type(", "press(", "set_input_files(", "keyboard.", ".value =", "dispatchEvent", ".click(", "submit("):
        assert name not in script, name
    assert "import playwright" not in text and "from playwright" not in text
    for word in ("신청", "삭제", "저장", "로그인'", "USER_PW"):
        assert word not in logout.CLICK_LOGOUT_JS, word
    session = (SRC / "session.py").read_text(encoding="utf-8")
    assert session.count("logout_mod.CLICK_LOGOUT_JS") == 1          # 세션이 누르는 로그아웃은 이것 하나


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


def test_navigation_presses_only_project_claim_tab_and_new_sheet():
    """로그인 뒤 이동(navigate.py, 담당자 허락 2026-10-19)이 누르는 것은 과제현황의 과제명 링크 · 과제정보의 '청구서' 탭 ·
    결의서 목록의 [일반청구](#P10) · [카드청구](#P11, 담당자 허락 2026-10-20) · 위쪽 탭 '메인화면' · '과제정보'(가려진 화면을 앞으로) ·
    과제현황 쪽 넘김(#prevBtn · #nextBtn — 고른 과제가 다른 쪽에 있을 때, 과제 폴더별 받기 2026-10-21) 일곱뿐이다.
    쪽 단추는 화면 스크립트로 눌러도 쪽이 안 바뀌면 마우스(프레임의 click)로 한 번 더 누른다 — 그 단추 둘만. 쪽 번호 링크와
    과제현황 거르기 '전체과제'(+ 목록이 그대로면 [검색])도 누른다 — 끝난 과제는 '전체과제' 둘째 쪽에 있다(2026-10-21).
    대응자금 과제는 비목 차례를 읽으려고 과제정보의 '예산' 하위 탭도 누른다(담당자 2026-10-21 "과제정보-예산에서 확인하고") — 그 화면은 읽기만.
    로그인 화면 · 신청 · 삭제 · 청구서복사 · 작성 화면의 '새 청구서' · 탭 닫기는 누르지 않고 값도 넣지 않는다."""
    from claim_downloader import navigate
    text = (SRC / "navigate.py").read_text(encoding="utf-8")
    pressing = {"CLICK_PROJECT_JS": navigate.CLICK_PROJECT_JS, "CLICK_CLAIM_TAB_JS": navigate.CLICK_CLAIM_TAB_JS,
                "CLICK_NEW_SHEET_JS": navigate.CLICK_NEW_SHEET_JS, "CLICK_MAIN_TAB_JS": navigate.CLICK_MAIN_TAB_JS,
                "CLICK_PROJECT_TAB_JS": navigate.CLICK_PROJECT_TAB_JS, "CLICK_CARD_SHEET_JS": navigate.CLICK_CARD_SHEET_JS,
                "CLICK_PAGE_JS": navigate.CLICK_PAGE_JS, "ALL_PROJECTS_JS": navigate.ALL_PROJECTS_JS,
                "CLICK_BUDGET_TAB_JS": navigate.CLICK_BUDGET_TAB_JS, "CLICK_DETAIL_JS": navigate.CLICK_DETAIL_JS}
    assert text.count(".click()") == 13 and sum(js.count(".click()") for js in pressing.values()) == 13
    # 첨부만 다시 올리기(2026-10-23)가 이미 있는 청구서를 여는 [상세조회/변경] — 받기와 같은 #btnDetail 하나뿐(#btnDelete · #btnClone 이 아니다)
    assert "getElementById('btnDetail')" in navigate.CLICK_DETAIL_JS and navigate.CLICK_DETAIL_JS.count("getElementById") == 1
    assert "open_saved_sheet" in text and 'DETAIL_BUTTON_ID = "btnDetail"' in text
    # 예산 탭은 글자가 정확히 '예산' 인 보이는 링크 하나만(그 화면의 [변경신청서작성] · [삭제] · [예산출력] 은 아니다), 예산내역은 읽기만
    assert "txt(a) === '예산'" in navigate.CLICK_BUDGET_TAB_JS and "shown.length !== 1" in navigate.CLICK_BUDGET_TAB_JS
    assert ".click()" not in navigate.BUDGET_JS and ".value =" not in navigate.BUDGET_JS
    # 쪽 넘김은 단추 둘과, 두 단추를 함께 담은 묶음 안의 숫자뿐인 쪽 번호 링크(과제 줄의 fnPage 금액 링크는 아님)만
    assert "which !== 'nextBtn' && which !== 'prevBtn'" in navigate.CLICK_PAGE_JS
    assert "/^[0-9]{1,2}$/.test(which)" in navigate.CLICK_PAGE_JS and "box.contains(pb)" in navigate.CLICK_PAGE_JS
    assert "!/fnPage/.test(" in navigate.CLICK_PAGE_JS and "hits.length !== 1" in navigate.CLICK_PAGE_JS
    # 과제현황 거르기(담당자 2026-10-21 "전체과제로 설정하고 2페이지를 눌러야함") — #SEARCH_GB · 보기 '전체과제' 하나 · 과제현황 [검색](빈 검색 칸일 때)뿐.
    # 카드미청구 탭의 거르기(#CARD_SEARCH_GB) 곁으로는 올라가지 않는다
    js = navigate.ALL_PROJECTS_JS
    assert js.count(".click()") == 3 and "getElementById('SEARCH_GB')" in js and "getElementById('btnPrjSearch')" in js
    assert "txt(e) === '전체과제'" in js and "box.contains(card)" in js and "opts.length !== 1" in js
    assert "txt(b) !== '검색'" in js and "String(q.value || '').trim()" in js
    for word in ("진행과제", "종료", "중단", "S_PRJ_NM').value =", "CARD_SEARCH_GB').click"):
        assert word not in js.replace("getElementById('CARD_SEARCH_GB')", ""), word
    # 화면 스크립트로 눌러도 쪽이 안 바뀌면 같은 쪽 단추를 마우스로 한 번 더(2026-10-21) — 그 한 곳뿐이고 쪽 단추 둘 밖은 받지 않는다
    assert navigate.PAGE_BUTTONS == ("nextBtn", "prevBtn")
    assert re.findall(r"\bclick\((?!\))", text) == ["click("] and 'click(f"#{which}", timeout=3000)' in text
    assert "if which not in PAGE_BUTTONS:" in text.split("def _mouse_click", 1)[1].split("click(f", 1)[0]
    assert ".click()" not in navigate.PAGER_JS + navigate.PAGE_STATE_JS                       # 쪽 모양 · 단추 상태 · 거르기는 읽기만
    assert ".value =" not in navigate.PAGER_JS and "q.value" in navigate.PAGER_JS                # 검색 칸은 글자가 있는지만
    assert "getElementById('P11')" in navigate.CLICK_CARD_SHEET_JS and "!== '카드청구'" in navigate.CLICK_CARD_SHEET_JS
    assert "fnPage\\\\(\\\\s*'01'" in navigate.CLICK_PROJECT_JS                  # 과제명 링크(fnPage('01', 과제번호))만
    assert "=== '청구서'" in navigate.CLICK_CLAIM_TAB_JS
    assert "getElementById('P10')" in navigate.CLICK_NEW_SHEET_JS and "!== '일반청구'" in navigate.CLICK_NEW_SHEET_JS
    assert "a.mul_txt" in navigate.CLICK_MAIN_TAB_JS and "=== '메인화면'" in navigate.CLICK_MAIN_TAB_JS
    assert "a.mul_txt" in navigate.CLICK_PROJECT_TAB_JS and "=== '과제정보'" in navigate.CLICK_PROJECT_TAB_JS
    assert "close" not in navigate.CLICK_MAIN_TAB_JS + navigate.CLICK_PROJECT_TAB_JS          # 탭 닫기(#close)가 아니다
    for name, js in pressing.items():
        for word in ("신청", "삭제", "btnDelete", "btnClone", "새 청구서", "로그인", "USER_PW") + (() if name == "CLICK_CARD_SHEET_JS" else ("P11",)):
            assert word not in js, word
    for name in ("fill(", "type(", "press(", "set_input_files(", "keyboard.", ".value =", "dispatchEvent"):
        assert name not in text, name
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


def test_payee_popup_presses_only_search_pick_and_confirm():
    """입금처 팝업(claims/payee.py)은 돋보기 · 구분 라디오 · [검색] · 고른 행 · [확인] 만 누른다.

    계좌등록 · 거래처등록 같은 기준 정보 단추를 누르는 코드가 들어오면 깨진다. [확인] 은 match 가 하나로 확정한 뒤에만(2026-10-13 담당자 결정).
    """
    text = (SRC / "claims" / "payee.py").read_text(encoding="utf-8")
    assert text.count(".click(") == 4                                   # 단추 id · 구분 라디오 · 행의 선택 칸 · 행
    assert set(re.findall(r"evaluate\(CLICK_ID_JS,\s*([A-Za-z_]+)\)", text)) == {"button_id", "SEARCH_BUTTON_ID", "CONFIRM_BUTTON_ID"}
    assert re.findall(r"open_popup\(page, frame, ([A-Z_]+),", text) == ["OPEN_BUTTON_ID"]
    assert 'OPEN_BUTTON_ID = "btnRcvCd"' in text and 'SEARCH_BUTTON_ID = "btn_search"' in text and 'CONFIRM_BUTTON_ID = "btn_s_confirm1"' in text
    for line in _click_lines(text):
        for word in ("btnReg", "btnUpd", "rbaseRegg", "rbaseUpt", "계좌등록", "거래처등록"):
            assert word not in line, line
    # [확인] 은 match() 가 index 를 돌려준 뒤에만 — pick() 안에서 index is None 이면 먼저 돌아간다
    body = text.split("def pick(", 1)[1]
    assert body.index("if index is None:") < body.index("CONFIRM_BUTTON_ID")


def test_taxbill_popup_presses_only_select_inquiry_pick_and_confirm():
    """세금계산서 조회 팝업(claims/taxbill.py)은 [선택] · [조회] · 고른 행 · [확인] 만 누른다 — [등록] · XML 등록은 아니다."""
    text = (SRC / "claims" / "taxbill.py").read_text(encoding="utf-8")
    # 누르는 JS 는 payee 의 것을 빌려 쓴다. 이 파일의 .click( 은 '계산서수신메일' 체크 하나뿐(CHECK_BOX_JS) 이고 EMAIL_CHECK_ID 로만 부른다
    assert text.count(".click(") == 1 and ".click(" in text.split("CHECK_BOX_JS = ", 1)[1].split('"""', 2)[1]
    assert set(re.findall(r"evaluate\(CHECK_BOX_JS,\s*([A-Za-z_]+)\)", text)) == {"EMAIL_CHECK_ID"}
    assert 'EMAIL_CHECK_ID = "self_enter"' in text
    assert set(re.findall(r"evaluate\(CLICK_ID_JS,\s*([A-Za-z_]+)\)", text)) == {"INQUIRY_BUTTON_ID", "CONFIRM_BUTTON_ID"}
    assert re.findall(r"open_popup\(page, frame, ([A-Z_]+),", text) == ["SELECT_LINK_ID"]
    assert 'SELECT_LINK_ID = "onlyEvdiDivList"' in text and 'INQUIRY_BUTTON_ID = "btn_inquiry"' in text and 'CONFIRM_BUTTON_ID = "btn_out"' in text
    for line in _click_lines(text):
        for word in ("btn_insert", "btn_reg_xml", "btnSupOrgCd", "btn_detail"):
            assert word not in line, line
    body = text.split("def pick(", 1)[1]
    assert body.index("if index is None:") < body.index("CONFIRM_BUTTON_ID")


def test_scholarship_presses_only_tab_save_person_and_attach_buttons():
    """장학금 청구(claims/scholarship.py · person.py · attach.py) — 담당자 결정 2026-10-14: 학생마다 [저장](임시저장)까지, [신청] 은 사람.

    scholarship.py 가 직접 누르는 것은 인건비 탭(#20) 과 [예금주조회](btn_ownrInq — 담당자 결정 2026-10-14: 앱이 누르고 '성공' 이 아니면
    사람에게. 돈이 나가지 않는 조회다). '일괄예금주조회' 는 누르지 않는다. 소득자 팝업은 돋보기 · 구분 라디오 · [검색] · 고른 행 · [확인](인적정보 3 · 참여인력 4),
    첨부 팝업은 '첨부' 링크 · [업로드] 뿐 — '외부인 등록' · 파일 '삭제'(btn_del) · 전체 체크는 누르지 않는다.
    """
    claims = SRC / "claims"
    sch = (claims / "scholarship.py").read_text(encoding="utf-8")
    assert ".click(" not in sch
    # 탭은 서브탭 둘뿐 — 인건비(소득성 경비) #20, 개인 지급(2026-10-19)은 일반청구 #10. 청구구분 라디오(REQ_DIV_CD)는 읽기만 한다
    assert set(re.findall(r"evaluate\(CLICK_ID_JS,\s*([A-Za-z_.]+)\)", sch)) == {"spec.tab_id", "OWNER_CHECK_ID"}
    assert 'TAB_ID = "20"' in sch and 'GENERAL_TAB_ID = "10"' in sch
    assert set(re.findall(r"tab_id=([A-Z_]+)", sch)) <= {"TAB_ID", "GENERAL_TAB_ID"}
    assert "REQ_DIV_CD" not in "".join(_click_lines(sch))
    assert 'OWNER_CHECK_ID = "btn_ownrInq"' in sch and all("일괄" not in line for line in _click_lines(sch))
    press = sch.split("def _press_owner_check(", 1)[1]
    assert press.index("VISIBLE_ID_JS") < press.index("CLICK_ID_JS, OWNER_CHECK_ID")      # 보이는 단추가 있을 때만
    assert "PSNL_EXPN_DIV_CD" not in sch.split('"""', 2)[2]          # 인건비구분 라디오는 건드리지 않는다(설명 글 밖에서)

    per = (claims / "person.py").read_text(encoding="utf-8")
    assert ".click(" not in per
    assert set(re.findall(r"evaluate\(CLICK_ID_JS,\s*([A-Za-z_]+)\)", per)) == {"SEARCH_BUTTON_ID", "confirm_id"}
    assert re.findall(r"open_popup\(page, frame, ([A-Z_]+),", per) == ["OPEN_BUTTON_ID"]
    assert 'CONFIRM_IDS = {TAB_STUDENT: "btn_s_confirm3", TAB_STAFF: "btn_s_confirm4"}' in per
    body = per.split("def pick(", 1)[1]
    assert body.index("if index is None:") < body.index("confirm_id)")

    # 국적조회 팝업(실측 2026-10-14 18:45): 돋보기 · [검색](person.run_search) · 고른 행 · '확인' 뿐 — 숨은 '선택없음' 은 아니다
    nat = (claims / "nation.py").read_text(encoding="utf-8")
    assert ".click(" not in nat and "CLICK_ID_JS" not in nat
    assert re.findall(r"open_popup\(page, frame, ([A-Z_]+),", nat) == ["OPEN_BUTTON_ID"] and 'OPEN_BUTTON_ID = "btnNationCd"' in nat
    assert re.findall(r"evaluate\(CLICK_TEXT_JS,\s*([A-Za-z_]+)\)", nat) == ["CONFIRM_TEXT"] and 'CONFIRM_TEXT = "확인"' in nat
    assert 'FORBIDDEN_TEXTS = ("선택없음",)' in nat and all("FORBIDDEN_TEXTS" not in line for line in nat.splitlines() if "evaluate(" in line)
    body = nat.split("def pick(", 1)[1]
    assert body.index("if index is None:") < body.index("CLICK_TEXT_JS, CONFIRM_TEXT")      # 하나로 확실할 때만 [확인]

    att = (claims / "attach.py").read_text(encoding="utf-8")
    assert att.count(".click(") == 1 and ".click(" in att.split("CLICK_TEXT_JS = ", 1)[1].split('"""', 2)[1]
    assert re.findall(r"evaluate\(CLICK_TEXT_JS,\s*([A-Za-z_]+)\)", att) == ["OPEN_TEXT"] and 'OPEN_TEXT = "첨부"' in att
    assert re.findall(r"evaluate\(CLICK_ID_JS,\s*([A-Za-z_]+)\)", att) == ["UPLOAD_BUTTON_ID"] and 'UPLOAD_BUTTON_ID = "btn_upload"' in att
    for word in ("btn_del", "allCheck"):
        assert all(word not in line for line in _click_lines(att)), word


def test_card_presses_only_inquiry_payment_category_evidence_and_saves():
    """카드청구(claims/card_erp.py) — 담당자 허락(2026-10-20 "네 눌러도 됩니다"): 미청구 카드내역 [조회] · 결제 건 라디오 · 청구구분 라디오 ·
    증빙 [신규등록] · 회의록등록 창의 [저장] 과 외부참석자 [행 추가] · 작성 화면 [저장] · 첨부. [신청] 은 사람.
    (85) [등록] · 참여인력/내부참석자 [행 추가] · 돋보기 · [카드매출전표] · 결의서내역 [카드청구](#P11) 는 미실측 · 허락 전이라 누르지 않는다."""
    text = (SRC / "claims" / "card_erp.py").read_text(encoding="utf-8")
    assert text.count(".click(") == 2                       # 청구구분 라디오(REQ_DIV_CLICK_JS) · 결제 건 줄의 라디오(PICK_R_JS)
    assert ".click(" in text.split("REQ_DIV_CLICK_JS = ", 1)[1].split('"""', 2)[1]
    assert ".click(" in text.split("PICK_R_JS = ", 1)[1].split('"""', 2)[1]
    assert re.findall(r"evaluate\(REQ_DIV_CLICK_JS,\s*([A-Za-z_.]+)\)", text) == ["item.req_div"]
    assert set(re.findall(r"_click\((?:frame|popup), ([A-Z_]+)\)", text)) == {"LIST_BUTTON_ID", "MINUTES_SAVE_ID", "EXTERNAL_ADD_ID"}
    assert re.findall(r"open_popup\(page, frame, ([A-Z_]+),", text) == ["MINUTES_BUTTON_ID"]
    assert re.findall(r"evaluate\(CLICK_ID_JS, ([A-Za-z_]+)\)", text) == ["element_id"]              # _click 안에서만
    assert "assert element_id in ALLOWED_CLICK_IDS" in text
    for line in ('LIST_BUTTON_ID = "btn_cardList"', 'MINUTES_BUTTON_ID = "btn_addEvid2"', 'MINUTES_SAVE_ID = "save"',
                 'EXTERNAL_ADD_ID = "btnRowAdd2"',
                 "ALLOWED_CLICK_IDS = frozenset({LIST_BUTTON_ID, MINUTES_BUTTON_ID, MINUTES_SAVE_ID, EXTERNAL_ADD_ID})"):
        assert line in text, line
    body = text.split("def _run_item(", 1)[1]
    assert body.index("if key is not None:") < body.index("pick_row(")       # 결제 건은 card.pick 이 하나로 정한 줄만
    assert "save_draft(" in text and '"신청"' not in text and "신청')" not in text
    for line in [ln for ln in text.splitlines() if "evaluate(" in ln or "_click(" in ln]:
        for word in ('"btn_addEvid"', '"P11"', "btn_gridCard", '"btnRowAdd"', "btnRowAdd1", "btnEmpInfo", "oz_report", "CALL_PRE_SFRC",
                     "btn_del", "FORBIDDEN_IDS"):
            assert word not in line, line


def test_reattach_presses_only_row_radio_file_delete_and_reuses_attach_and_save():
    """첨부만 다시 올리기(claims/reattach.py, 담당자 2026-10-23 "네 삭제 눌러도 됩니다") — 누르는 것은 청구내역 줄의 ○(CUR_REQ 라디오)와
    첨부문서 목록(#fileList) 옆의 '삭제' 뿐이고, 첨부는 attach.upload · [저장] 은 form.save_draft 를 그대로 쓴다. 값 넣기 · 파일 넣기는 없다.
    '삭제' 는 #fileList 와 같은 칸 안의 글자 '삭제' 하나만 — 청구내역 줄의 '[삭제]'(btn_del_N) · 결의서 목록의 [삭제] · [신청] 은 아니다."""
    from claim_downloader.claims import reattach
    text = (SRC / "claims" / "reattach.py").read_text(encoding="utf-8")
    assert text.count(".click()") == 2
    assert ".click()" in reattach.OPEN_ROW_JS and ".click()" in reattach.CLICK_FILE_DELETE_JS
    assert ".click()" not in reattach.SELECT_ALL_FILES_JS                      # 보기를 고르기만
    assert "input[name=CUR_REQ]" in reattach.OPEN_ROW_JS and reattach.ROW_RADIO_NAME == "CUR_REQ"
    js = reattach.CLICK_FILE_DELETE_JS
    assert "pickEl('fileList')" in js and "!== '삭제'" in js and "/^btn_del/.test(e.id" in js and "hits.length !== 1" in js
    assert "tr.querySelector('input[name=CUR_REQ]')" in js                     # 청구내역 줄 안의 것은 아니다
    for word in ("신청", "btnDelete", "btnClone", "allCheck", "btn_file", "새 청구서", "초기화"):
        assert word not in reattach.OPEN_ROW_JS + reattach.CLICK_FILE_DELETE_JS + reattach.SELECT_ALL_FILES_JS, word
    for name in ("fill(", "type(", "press(", "set_input_files(", "keyboard.", "SET_TEXT_JS", "SET_SELECT_JS", "CLICK_SAVE_JS", "CLICK_ID_JS"):
        assert name not in text, name
    assert "attach.upload(" in text and "save_draft(" in text and "import playwright" not in text
    assert reattach.STATE_WORDS == ("임시저장", "보완")                            # 승인된 청구서는 손대지 않는다
    assert reattach.DELETE_TEXT == "삭제"


def test_file_upload_lives_only_in_attach():
    """OS 대화상자 없이 파일을 넣는 set_input_files 는 claims/attach.py 한 곳에서만."""
    users = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if "set_input_files(" in p.read_text(encoding="utf-8"))
    assert users == ["claims/attach.py"], users


def test_structure_card_only_reads_and_does_not_reload_open_sites():
    """화면 구조 저장 업무(담당자 2026-10-21) — 고른 사이트를 여는 것은 창을 앞으로 가져오기 · 새 탭에 첫 화면 열기뿐이고
    (이미 열린 창은 다시 불러오지 않아 로그인 · 띄운 화면이 그대로), 화면을 누르거나 값을 넣지 않는다. 화면 코드는 브라우저를 직접 만지지 않는다."""
    import inspect
    from claim_downloader import session
    for name in ("show_erp", "show_kcloud", "open_sites", "_site_finder", "capture_structure"):
        code = inspect.getsource(getattr(session.ErpSession, name))
        for word in ("evaluate", ".click", "fill(", "press(", "type(", "set_input_files", "reload"):
            assert word not in code, (name, word)
    show = inspect.getsource(session.ErpSession.show_erp)
    assert show.index("bring_to_front") < show.index("goto")        # 열린 ERP 창이 있으면 앞으로만 — 그 뒤에야 새로 연다
    page = (SRC / "ui" / "pages" / "structure.py").read_text(encoding="utf-8")
    assert "evaluate" not in page and "playwright" not in page.lower()


def test_purchase_presses_only_menu_search_pick_detail_list_and_item_rows():
    """구매요청(계약) 서류 받기(purchase.py, 2026-10-22 · 23절)가 누르는 것은 위 메뉴 '구매·자산'(#menu_id_3) · 왼쪽 메뉴 글자 · 위쪽 탭 ·
    [검색](#btnSearch) · 목록 줄의 선택 칸(chk, IBSheet setValue) · [상세조회/변경](#btnDetail) · [진행관리목록](#btnList) · 검사처리 줄의 라디오 ·
    물품정보 줄 더블클릭뿐이다. 값을 넣는 칸은 조회 조건의 일자 둘(#START_DATE · #END_DATE)뿐. 등록 · 삭제 · 저장 · 구매요청 · 취소 · 검사처리(취소) ·
    완료 · 첨부 추가/삭제 · 사진등록/삭제 · [구매진행상세] · [구매요청서] 출력은 누르지 않고, 파일은 링크 주소를 받기만 한다."""
    from claim_downloader import purchase
    text = (SRC / "purchase.py").read_text(encoding="utf-8")
    pressing = {"MENU_JS": purchase.MENU_JS, "LEFT_MENU_JS": purchase.LEFT_MENU_JS, "TOP_TAB_JS": purchase.TOP_TAB_JS,
                "SEARCH_JS": purchase.SEARCH_JS, "PICK_DETAIL_JS": purchase.PICK_DETAIL_JS, "LIST_BACK_JS": purchase.LIST_BACK_JS,
                "INSPECT_PICK_JS": purchase.INSPECT_PICK_JS}
    assert text.count(".click()") == 7 and all(js.count(".click()") == 1 for js in pressing.values())
    assert "getElementById('menu_id_3')" in purchase.MENU_JS and "t !== '구매자산'" in purchase.MENU_JS
    assert "getElementById('btnSearch')" in purchase.SEARCH_JS
    assert "getElementById('btnDetail')" in purchase.PICK_DETAIL_JS and "t.startsWith('상세조회')" in purchase.PICK_DETAIL_JS
    assert "getElementById('btnList')" in purchase.LIST_BACK_JS and "t.includes('목록')" in purchase.LIST_BACK_JS
    assert "input[type=radio]" in purchase.INSPECT_PICK_JS and "k_PURCH_REQ_NO" in purchase.INSPECT_PICK_JS
    assert "hits.length !== 1" in purchase.LEFT_MENU_JS and "shown.length !== 1" in purchase.TOP_TAB_JS
    # 선택 칸만 setValue — 다른 열은 안 된다. 그 줄 하나만 체크됐는지 getRowsByChecked 로 다시 본 뒤에야 단추를 누른다
    assert re.findall(r"setValue\(\s*[^,()]+,\s*'(\w+)'", text) == ["chk", "chk"] and text.count("setValue(") == 2
    assert "checked.length !== 1" in purchase.PICK_DETAIL_JS
    # 값을 넣는 칸은 일자 둘뿐(SET_RANGE_JS 의 el.value = v 한 곳)
    assert re.findall(r"\w+\.value\s*=[^=]\s*\w*", text) == ["el.value = v"] and "'START_DATE'" in purchase.SET_RANGE_JS and "'END_DATE'" in purchase.SET_RANGE_JS
    assert text.count("dblclick(") == 1 and "k_CONT_ITEM_NM_KR" in purchase.ITEM_ROW_SELECTOR
    for name in (".fill(", ".type(", ".press(", "set_input_files(", "keyboard.", "import playwright", "from playwright"):
        assert name not in text, name
    # 검사처리 화면을 알아보는 데만 #btnPunch 가 쓰인다(있는지 보기만) — 누르지 않는다
    assert text.count("btnPunch") == 1 and "!!document.getElementById('btnPunch')" in purchase.INSPECT_PROBE_JS
    for forbidden in ("btnInsert", "btnDelete", "btnSave", "btnRequest", "btnCancel", "btnWorkSave", "btnWorkCancel", "btnAttachSave",
                      "btnMyGrid2", "btnImgIns", "btnImgDel", "btnFileAdd", "btnFileDel", "btnPrint", "gridDonw", "btnDownload", "btnSaveAdd",
                      "btnUpdate", "btnImpCopy", "btn_detail", "btnContItem", "btnCAC"):
        assert f"'{forbidden}'" not in text and f'"{forbidden}"' not in text and f"#{forbidden}" not in text.replace("`#btnDetail`", ""), forbidden
