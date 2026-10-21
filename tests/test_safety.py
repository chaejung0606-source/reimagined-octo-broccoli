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


def test_parking_screens_press_nothing():
    """할인 적용 · 할인 내역(parking_screens.py, 담당자 요청 2026-10-21)은 실측 전이라 아무것도 누르지 않는다 — 할인 적용은 차량번호 칸
    (표시를 붙인 칸 하나)에 넣어 두기만, 할인 내역은 표를 읽기만. [조회] · [적용] · 쪽 넘기기는 실측 뒤에."""
    from claim_downloader import parking_screens
    text = (SRC / "parking_screens.py").read_text(encoding="utf-8")
    assert re.findall(r"\.fill\(([A-Z_]+),", text) == ["CAR_SELECTOR"]
    for name in (".click(", "press(", "type(", "keyboard.", "select_option(", "set_checked(", "set_input_files(", "dispatchEvent",
                 "submit(", ".value =", "load_login", "ERP_URL", "knu-icf"):
        assert name not in text, name
    for js in (parking_screens.MARK_CAR_JS, parking_screens.TABLE_JS):
        assert "click" not in js and "setAttribute('data-coss-car'" in parking_screens.MARK_CAR_JS
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
    로그인 화면 · 신청 · 삭제 · 청구서복사 · 작성 화면의 '새 청구서' · 탭 닫기는 누르지 않고 값도 넣지 않는다."""
    from claim_downloader import navigate
    text = (SRC / "navigate.py").read_text(encoding="utf-8")
    pressing = {"CLICK_PROJECT_JS": navigate.CLICK_PROJECT_JS, "CLICK_CLAIM_TAB_JS": navigate.CLICK_CLAIM_TAB_JS,
                "CLICK_NEW_SHEET_JS": navigate.CLICK_NEW_SHEET_JS, "CLICK_MAIN_TAB_JS": navigate.CLICK_MAIN_TAB_JS,
                "CLICK_PROJECT_TAB_JS": navigate.CLICK_PROJECT_TAB_JS, "CLICK_CARD_SHEET_JS": navigate.CLICK_CARD_SHEET_JS,
                "CLICK_PAGE_JS": navigate.CLICK_PAGE_JS, "ALL_PROJECTS_JS": navigate.ALL_PROJECTS_JS}
    assert text.count(".click()") == 11 and sum(js.count(".click()") for js in pressing.values()) == 11
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


def test_file_upload_lives_only_in_attach():
    """OS 대화상자 없이 파일을 넣는 set_input_files 는 claims/attach.py 한 곳에서만."""
    users = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if "set_input_files(" in p.read_text(encoding="utf-8"))
    assert users == ["claims/attach.py"], users
