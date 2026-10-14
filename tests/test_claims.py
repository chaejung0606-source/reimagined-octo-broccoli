"""일반청구 (claims/) — 브라우저·AI 없이 계약·규칙·채우기 순서·안전을 본다.

ERP 프레임은 가짜(evaluate 가 JS 상수를 알아보고 흉내 낸다). 실제 화면은 모의 페이지(tools 밖)와
담당자 PC 에서 확인한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from claim_downloader import settings
from claim_downloader.claims import extract, form, process, record, rules, schema
from claim_downloader.minutes.backends.base import BackendError, MinutesBackend
from claim_downloader.minutes import errors

CLAIMS = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "claims"


def sample(**overrides) -> dict:
    data = {
        "summary": "09_2026년 사업단 정수기 임차료(9월)", "expCategory": "그 밖의 사업운영 경비", "expDetail": "임차료",
        "evidence": "세금계산서", "expenseDate": "2026.09.30", "amount": "51,900원", "supplyAmount": 47182,
        "taxAmount": 4718, "payeeName": "코웨이(주)", "payeeBizNo": "123-45-67890", "bank": "국민은행",
        "accountNo": "123-456-789", "owner": "코웨이(주)", "settleMethod": "", "attachments": ["세금계산서.pdf"],
        "notes": "",
    }
    data.update(overrides)
    return data


# ── schema ───────────────────────────────────────────────────────────
def test_category_code_accepts_any_spelling():
    assert schema.category_code("그 밖의 사업운영 경비") == "09"
    assert schema.category_code("기타운영경비") == "09"
    assert schema.category_code("09") == "09"
    assert schema.category_code("교육연구프로그램개발운영비") == "03"
    assert schema.category_code("지역연계협업지원비") == "06"
    assert schema.category_code("") == "" and schema.category_code("모르는비목") == ""
    assert schema.category_name("09") == "기타운영경비"
    assert schema.category_name("이상한") == "이상한"       # 사람이 고치게 그대로


def test_normalize_coerces_amounts_dates_and_options():
    data = schema.normalize(sample())
    assert data["amount"] == 51900 and data["supplyAmount"] == 47182 and data["taxAmount"] == 4718
    assert data["expenseDate"] == "2026-09-30"
    assert data["expCategory"] == "기타운영경비"
    assert data["settleMethod"] == "계좌이체"
    assert data["attachments"] == ["세금계산서.pdf"]
    assert set(data) == set(schema.KEYS)
    assert schema.normalize({"evidence": "전자세금계산서", "expenseDate": "20261013"})["evidence"] == "세금계산서"
    assert schema.normalize({"amount": None})["amount"] is None


def test_problems_flag_missing_and_inconsistent_values():
    assert schema.problems(schema.normalize(sample())) == []
    found = schema.problems(schema.normalize(sample(summary="", amount="", accountNo="")))
    assert "적요 없음" in found and "청구액 없음" in found and "계좌번호 없음 (ERP 에서 직접 넣어야 함)" in found
    found = schema.problems(schema.normalize(sample(supplyAmount=1, taxAmount=1)))
    assert any("≠ 청구액" in f for f in found)
    found = schema.problems(schema.normalize(sample(expenseDate="9월말", evidence="영수증")))
    assert any("형식이 YYYY-MM-DD" in f for f in found) and any("증빙구분" in f for f in found)


def test_summary_lines_are_readable():
    lines = schema.summary_lines(schema.normalize(sample(notes="금액 상이")))
    assert lines[0] == "적요: 09_2026년 사업단 정수기 임차료(9월)"
    assert "청구액: 51,900원" in lines[3] and lines[-1] == "확인: 금액 상이"


# ── rules · record ───────────────────────────────────────────────────
def test_rules_files_and_user_edits(isolated_home):
    assert rules.load_rules() == rules.RULES_DEFAULT
    path = settings.claims_rules_path()
    assert path.parent == isolated_home and settings.claims_rules_base_path().exists()
    path.write_text("# 메모\n- 내 규칙\n", encoding="utf-8")
    assert rules.load_rules() == "- 내 규칙"
    assert "NN_내용" in rules.RULES_DEFAULT and "추측 금지" in rules.RULES_DEFAULT


def test_record_remembers_filled_folders(isolated_home, tmp_path):
    folder = tmp_path / "지출1"
    assert record.previous(folder) is None
    record.remember(folder, {"amount": 51900, "summary": "09_정수기"})
    before = record.previous(str(folder))
    assert before["amount"] == 51900 and before["summary"] == "09_정수기" and before["when"]
    assert settings.claim_record_path().parent == isolated_home


# ── extract ──────────────────────────────────────────────────────────
def test_prompt_names_folder_json_and_rules(tmp_path):
    prompt = extract.build_prompt(str(tmp_path), str(tmp_path / "claim.json"), "규칙 ABC")
    assert str(tmp_path) in prompt and "claim.json" in prompt and prompt.endswith("[규칙]\n규칙 ABC")
    for key in schema.KEYS:
        assert f'"{key}"' in prompt, key
    assert "기타운영경비" in prompt and "세금계산서" in prompt
    assert "폴더 안의 파일을 고치거나 지우지 마세요" in prompt


def test_extractor_registry_and_missing_claude(monkeypatch):
    assert extract.keys() == ["claude-cli"]
    assert isinstance(extract.get("없는키"), extract.ClaudeCliExtractor)
    # available() 은 claude_cli.check_claude 가, generate() 는 extract 가 각자 find_claude 를 본다
    monkeypatch.setattr(extract, "find_claude", lambda: "")
    monkeypatch.setattr(extract.claude_cli_module, "find_claude", lambda: "")
    backend = extract.ClaudeCliExtractor(model="")
    ok, note = backend.available()
    assert not ok and "claude 명령을 찾을 수 없습니다" in note
    with pytest.raises(BackendError):
        backend.generate(Path("."), "r")
    source = (CLAIMS / "extract.py").read_text(encoding="utf-8")
    assert '"Read,Glob,Grep,Write,Edit,Bash,PowerShell"' in source


class FakeExtractor:
    key = "fake"
    label = "시험용"

    def __init__(self, fail_with=None):
        self.calls = []
        self._fail = list(fail_with or [])

    def available(self):
        return True, "시험용"

    def generate(self, folder, rules_text):
        self.calls.append((Path(folder), rules_text))
        if self._fail:
            error = self._fail.pop(0)
            if error is not None:
                raise error
        return sample()


def _folders(tmp_path, n):
    out = []
    for i in range(n):
        d = tmp_path / f"지출{i + 1}"
        d.mkdir()
        (d / "세금계산서.pdf").write_bytes(b"%PDF-")
        out.append(d)
    return out


def test_process_run_with_fake_extractor(tmp_path):
    folders = _folders(tmp_path, 2)
    backend = FakeExtractor()
    assert isinstance(backend, MinutesBackend)
    events = list(process.run(folders, backend, rules="r"))
    assert [e for _, e, _ in events] == ["start", "done", "start", "done"]
    result = events[1][2]
    assert result.ok and result.data["amount"] == 51900 and result.problems == []
    assert backend.calls[0][1] == "r"


def test_process_skips_after_fatal_and_continues_after_transient(tmp_path):
    folders = _folders(tmp_path, 3)
    events = list(process.run(folders, FakeExtractor([BackendError(errors._LIMIT)]), rules="r"))
    assert [e for _, e, _ in events] == ["start", "done", "skip", "skip"]
    assert events[1][2].kind == "limit"
    events = list(process.run(folders, FakeExtractor([BackendError("네트워크 연결 오류")]), rules="r"))
    results = [p for _, e, p in events if e == "done"]
    assert [r.ok for r in results] == [False, True, True]


# ── form ─────────────────────────────────────────────────────────────
class FakeFrame:
    """evaluate 가 form.py 의 JS 상수를 알아보고 ERP 화면처럼 반응한다."""

    def __init__(self, mod_yn="N", options=None, screen=None, save_works=True, hidden=()):
        self.values = dict(screen or {})
        self.sets = []
        self.clicks = []
        self.mod_yn = mod_yn
        self.save_works = save_works
        self.hidden = set(hidden)              # 숨은 select (세목이 없는 과제)
        self.options = options or {
            "PAY_EXP_CD": ["선택", "인건비", "기타운영경비"], "DTL_EXP_CD": ["선택", "임차료"],
            "EVDI_DIV_CD": ["선택", "세금계산서", "계산서"], "SETTLE_METH_CD": ["계좌이체", "현금/지로"],
            "BNK_CD": ["해당없음", "국민은행", "신한은행"],
        }

    def evaluate(self, js, arg=None):
        if js is form.PROBE_JS:
            return True
        if js is form.STATE_JS:
            return {i: {"tag": "input", "value": self._value(i)} for i in arg}
        if js is form.CLICK_SAVE_JS:
            self.clicks.append(arg)
            if arg == form.SAVE_TEXT and self.save_works:
                self.values["REQ_SEQ_NO"] = "REQ-2026-0001"
                self.values["MOD_YN"] = "Y"
            return {"ok": True}
        if js is form.SELECT_STATE_JS:
            return {"count": len(self.options.get(arg, [])), "visible": arg not in self.hidden}
        if js is form.SET_SELECT_JS:
            element_id, wanted = arg
            hit = next((o for o in self.options.get(element_id, []) if o.replace(" ", "") == wanted.replace(" ", "")), None)
            self.sets.append((element_id, wanted))
            return {"ok": True, "now": hit} if hit else {"ok": False, "why": "보기에 없음", "options": self.options.get(element_id, [])}
        if js is form.SET_TEXT_JS:
            element_id, value = arg
            self.sets.append((element_id, value))
            return {"ok": True, "now": value}
        raise AssertionError("모르는 JS")

    def _value(self, element_id):
        if element_id in self.values:
            return self.values[element_id]
        if element_id == "MOD_YN":
            return self.mod_yn
        if element_id == "PROC_TYP_CD":
            return "P10"
        return ""


def test_fill_sets_fields_in_order_and_never_touches_buttons():
    frame = FakeFrame()
    logs = []
    report = form.fill(frame, schema.normalize(sample()), logs.append, dry_run=False, wait=lambda s: None)
    assert report.ok and not report.blocked
    ids = [i for i, _ in frame.sets]
    assert ids[:2] == ["PAY_EXP_CD", "DTL_EXP_CD"] and ids[-1] == "REQ_PTCL"
    assert ("REQ_AMT", "51900") in frame.sets and ("EXP_DT", "2026-09-30") in frame.sets
    assert set(ids) <= form.ALLOWED_IDS
    assert any("채우기 끝" in line for line in logs)
    assert "저장" in " ".join(report.manual) and "신청" in " ".join(report.manual)


def test_dry_run_reads_only_and_existing_claim_is_refused():
    frame = FakeFrame()
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=True)
    assert report.dry_run and frame.sets == [] and [s.label for s in report.steps][0] == "비목"
    assert report.lines()[0].startswith("미리 보기")
    frame = FakeFrame(mod_yn="Y")
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=False)
    assert report.blocked and "새 청구서 화면이 아닙니다" in report.blocked and frame.sets == [] and not report.ok


def test_unknown_option_is_reported_not_fatal():
    frame = FakeFrame()
    report = form.fill(frame, schema.normalize(sample(bank="토스뱅크")), lambda m: None, dry_run=False, wait=lambda s: None)
    bank = next(s for s in report.steps if s.label == "은행")
    assert not bank.ok and "보기에 없음" in bank.note and "국민은행" in bank.note
    assert not report.ok and any(s.label == "적요" and s.ok for s in report.steps)   # 나머지는 계속 넣는다


def test_form_module_only_fills_allowed_fields_and_clicks_only_save():
    text = (CLAIMS / "form.py").read_text(encoding="utf-8")
    assert text.count(".click(") == 1 and ".click(" in form.CLICK_SAVE_JS      # 누르는 곳은 임시저장 하나
    assert "submit" not in text.lower()
    assert "import playwright" not in text and "from playwright" not in text
    assert "신청" in form.FORBIDDEN_TEXTS and form.SAVE_TEXT not in form.FORBIDDEN_TEXTS
    assert {f[1] for f in form.FIELDS} <= form.ALLOWED_IDS
    assert "RCV_CD" not in {f[1] for f in form.FIELDS}      # 입금처는 팝업 — 직접 쓰지 않는다


def test_save_draft_waits_for_payee_and_reports_change():
    """입금처가 비어 있으면 누르지 않고, 다 있으면 [저장] 하나만 눌러 결의번호가 생기는 것을 확인한다."""
    frame = FakeFrame(screen={"REQ_PTCL": "09_정수기", "REQ_AMT": "51,900", "RCV_NM": ""})
    report = form.save_draft(frame, lambda m: None, [], wait=lambda s: None)
    assert not report.ok and "입금처" in report.note and frame.clicks == []

    frame = FakeFrame(screen={"REQ_PTCL": "09_정수기", "REQ_AMT": "51,900", "RCV_NM": "코웨이(주)"})
    messages = []
    report = form.save_draft(frame, lambda m: None, messages, wait=lambda s: None)
    assert report.ok and frame.clicks == [form.SAVE_TEXT]
    assert report.after["REQ_SEQ_NO"] == "REQ-2026-0001" and report.after["MOD_YN"] == "Y"
    assert "[신청] 은 직접 누르세요" in " ".join(report.lines())

    frame = FakeFrame(screen={"REQ_PTCL": "x", "REQ_AMT": "1", "RCV_NM": "y"}, save_works=False)
    report = form.save_draft(frame, lambda m: None, ["필수 항목이 비어 있습니다"], wait=lambda s: None, tries=2)
    assert not report.ok and report.messages == ["필수 항목이 비어 있습니다"]
    # 화면은 안 바뀌어도 '저장되었습니다' 가 뜨면 됨으로, '저장하시겠습니까?' 만 떴으면 아직 아님
    frame = FakeFrame(screen={"REQ_PTCL": "x", "REQ_AMT": "1", "RCV_NM": "y"}, save_works=False)
    assert form.save_draft(frame, lambda m: None, ["저장하시겠습니까?", "저장되었습니다."], wait=lambda s: None, tries=2).ok
    frame = FakeFrame(screen={"REQ_PTCL": "x", "REQ_AMT": "1", "RCV_NM": "y"}, save_works=False)
    assert not form.save_draft(frame, lambda m: None, ["저장하시겠습니까?"], wait=lambda s: None, tries=2).ok


def test_missing_detail_select_is_skipped_quickly():
    """세목이 없는 과제(실측 2026-10-13: 비목을 골라도 세목 select 가 숨은 채 비어 있음) — 5초 기다리지 않고 건너뛴다."""
    options = {"PAY_EXP_CD": ["선택", "기타운영경비"], "DTL_EXP_CD": [], "EVDI_DIV_CD": ["선택", "세금계산서"],
               "SETTLE_METH_CD": ["계좌이체"], "BNK_CD": ["해당없음", "국민은행"]}
    frame = FakeFrame(options=options, hidden=("DTL_EXP_CD",))
    waits = []
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=False, wait=waits.append)
    assert report.ok
    detail = next(s for s in report.steps if s.label == "세목")
    assert detail.ok and "세목이 없음" in detail.note
    assert "DTL_EXP_CD" not in [i for i, _ in frame.sets]           # 보기 없는 select 에 넣으려 하지 않는다
    assert len(waits) <= 4                                          # 숨은 채 비어 있으면 ~1초만 기다린다
    # 보기가 오면 넣는다
    frame = FakeFrame()
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=False, wait=lambda s: None)
    assert ("DTL_EXP_CD", "임차료") in frame.sets or any(i == "DTL_EXP_CD" for i, _ in frame.sets)


# ── 입금처 · 세금계산서 팝업 ──────────────────────────────────────────────
from claim_downloader.claims import payee, taxbill  # noqa: E402


class FakePopup:
    """팝업 창 — 실측된 요소(입금처: 구분 라디오·검색 칸·[검색] / 세금계산서: 구분 select·사업자번호·기간·[조회])만 안다."""

    def __init__(self, kind="payee", checked="거래처", rows=3, closes_after=None, listing=None, form=None,
                 values=None, rows_for=None, child_rows=None):
        self.kind = kind
        self.checked = checked
        self.rows = rows
        self.values = dict(values or {})        # 팝업 칸의 현재 값 (START_DATE 기본 기간 등)
        self.rows_for = rows_for                # {조회 조건 값: 행 수} — 조건에 따라 결과가 달라지는 흉내. None 이면 늘 rows
        self.inquiries = []                     # [조회] 때마다 (CORP_TXT, TAX_RCV_EMAIL_V) 값
        self.checked_boxes = []
        if child_rows is not None:              # 결과가 자식 iframe 에 뜨는 팝업(입금처 팝업의 빈 iframe) 흉내 — 창 자체에는 행이 없다
            self.frames = [self, _ChildView(self, child_rows)]
            self.rows, listing = 0, None
        self.sets = []
        self.clicks = []
        self.listeners = []
        self.closed = False
        self.closes_after = closes_after        # wait_closed 가 이만큼 물어본 뒤 닫힌 것으로
        self.asked = 0
        self.listing = listing or []            # 결과 목록 행 [{index, text, titles, pick}]
        self.form = form                        # FakeFormFrame — [확인] 을 누르면 작성 화면에 반영한다
        self.picked = None

    def evaluate(self, js, arg=None):
        if js is payee.POPUP_PROBE_JS:
            return self.kind == "payee"
        if js is taxbill.POPUP_PROBE_JS:
            return self.kind == "taxbill"
        if js is payee.CHECK_DIV_JS:
            name, label = arg
            assert name == "RCV_DIV_CD"
            if self.checked == label:
                return {"ok": True, "same": True}
            self.checked = label
            self.clicks.append("radio:" + label)
            return {"ok": True}
        if js is form.SET_TEXT_JS or js is form.SET_SELECT_JS:
            self.sets.append(tuple(arg))
            self.values[arg[0]] = arg[1]
            return {"ok": True, "now": arg[1]}
        if js is form.STATE_JS:
            return {i: {"value": self.values.get(i, "")} for i in arg}
        if js is taxbill.CHECK_BOX_JS:
            self.checked_boxes.append(arg)
            self.clicks.append("check:" + arg)
            return {"ok": True, "checked": True}
        if js is payee.CLICK_ID_JS:
            self.clicks.append(arg)
            if arg == taxbill.INQUIRY_BUTTON_ID:
                self.inquiries.append((self.values.get(taxbill.BIZNO_TEXT_ID, ""), self.values.get(taxbill.EMAIL_TEXT_ID, "")))
                if self.rows_for is not None:
                    self.rows = self.rows_for.get(self.values.get(taxbill.BIZNO_TEXT_ID, ""), 0)
            if arg in (payee.CONFIRM_BUTTON_ID, taxbill.CONFIRM_BUTTON_ID) and self.picked is not None and self.form is not None:
                self.form.apply(self.listing[self.picked])   # ERP 의 callback 흉내 — 작성 화면에 들어간다
                self.closed = True
            return {"ok": True}
        if js is payee.RESULT_COUNT_JS:
            return {"rows": self.rows, "kind": "grid"}
        if js is payee.ROWS_JS:
            return {"kind": "grid", "rows": self.listing}
        if js is payee.PICK_ROW_JS:
            self.picked = arg
            self.clicks.append(f"row:{arg}")
            return {"ok": True, "how": "선택 칸"}
        raise AssertionError("모르는 JS")

    def on(self, event, handler):
        self.listeners.append((event, handler))

    def remove_listener(self, event, handler):
        self.listeners.remove((event, handler))

    def is_closed(self):
        self.asked += 1
        if self.closes_after is not None and self.asked > self.closes_after:
            self.closed = True
        return self.closed


class _ChildView:
    """팝업 안의 자식 프레임 — 결과 목록만 들고 있다."""

    def __init__(self, popup, listing):
        self.popup, self.listing = popup, listing

    def evaluate(self, js, arg=None):
        if js is payee.RESULT_COUNT_JS:
            return {"rows": len(self.listing), "kind": "grid" if self.listing else "unknown"}
        if js is payee.ROWS_JS:
            return {"kind": "grid", "rows": self.listing}
        if js is payee.PICK_ROW_JS:
            self.popup.picked = arg
            self.popup.listing = self.listing
            self.popup.clicks.append(f"row:{arg}")
            return {"ok": True, "how": "선택 칸"}
        raise AssertionError("자식 프레임이 모르는 JS")


class FakeContext:
    def __init__(self, pages):
        self.pages = pages


class FakePage:
    """작성 화면이 있는 창. 단추를 누르면 팝업이 '뜬다'."""

    def __init__(self, popup, opens=True, already_open=False):
        self.popup = popup
        self.opens = opens
        self.context = FakeContext([self] + ([popup] if already_open else []))
        self.opened = 0

    def evaluate(self, js, arg=None):
        return False                      # 이 창 자체는 팝업이 아니다

    def expect_popup(self, timeout=0):
        page = self

        class Waiter:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, kind, value, tb):
                if kind:
                    return False
                if not page.opens:
                    raise TimeoutError("Timeout 8000ms exceeded while waiting for event \"popup\"")
                page.opened += 1
                self_inner.value = page.popup
                return False
        return Waiter()


class FakeFormFrame:
    def __init__(self, link_visible=True):
        self.clicks = []
        self.link_visible = link_visible
        self.values = {"RCV_NM": "", "TAXBILL_SEQ_NO": "", "EXP_DT": "2026-10-13", "BUY_WHERE": ""}

    def apply(self, row):
        """팝업 [확인] 의 callback 흉내."""
        if "rcv" in row:
            self.values["RCV_NM"] = row["rcv"]
        if "bill" in row:
            self.values["TAXBILL_SEQ_NO"] = row["bill"]
            self.values["EXP_DT"] = row.get("date", self.values["EXP_DT"])

    def evaluate(self, js, arg=None):
        if js is payee.CLICK_ID_JS:
            self.clicks.append(arg)
            return {"ok": True}
        if js is taxbill.LINK_VISIBLE_JS:
            return self.link_visible
        if js is form.STATE_JS:
            return {i: {"tag": "input", "value": self.values.get(i, "")} for i in arg}
        raise AssertionError("모르는 JS")


def test_payee_search_opens_popup_and_searches_only_with_allowed_buttons():
    popup = FakePopup(checked="참여인력")
    page, frame = FakePage(popup), FakeFormFrame()
    logs = []
    report = payee.search(page, frame, {"payeeName": "코웨이(주)"}, logs.append, wait=lambda s: None, auto_pick=False)
    assert report.ok and report.query == "코웨이(주)" and report.rows == 3 and not report.picked
    assert frame.clicks == [payee.OPEN_BUTTON_ID] and page.opened == 1
    assert popup.clicks == ["radio:거래처", payee.SEARCH_BUTTON_ID]
    assert popup.sets == [(payee.SEARCH_TEXT_ID, "코웨이(주)")]
    assert popup.listeners == []                                    # 알림 듣기는 끝나면 거둔다
    assert set(c for c in popup.clicks + frame.clicks if not c.startswith("radio:")) <= payee.ALLOWED_CLICK_IDS
    assert "확인" in report.lines()[0] and "고르고" in report.lines()[0]


def test_payee_search_reuses_open_popup_and_reports_failures():
    popup = FakePopup()
    page, frame = FakePage(popup, already_open=True), FakeFormFrame()
    report = payee.search(page, frame, {"payeeName": "", "payeeBizNo": "123-45-67890"}, lambda m: None, wait=lambda s: None, auto_pick=False)
    assert report.ok and report.query == "1234567890" and frame.clicks == [] and page.opened == 0

    page, frame = FakePage(FakePopup(), opens=False), FakeFormFrame()
    report = payee.search(page, frame, {"payeeName": "코웨이"}, lambda m: None, wait=lambda s: None)
    assert not report.ok and "Timeout" in report.note and frame.clicks == [payee.OPEN_BUTTON_ID]
    assert "직접" in report.lines()[0]

    report = payee.search(FakePage(FakePopup()), FakeFormFrame(), {"payeeName": ""}, lambda m: None, wait=lambda s: None)
    assert not report.ok and "이름이 없습니다" in report.note

    page, frame = FakePage(FakePopup(kind="other")), FakeFormFrame()
    report = payee.search(page, frame, {"payeeName": "코웨이"}, lambda m: None, wait=lambda s: None)
    assert not report.ok and "입금처조회 화면이 아닙니다" in report.note


def test_taxbill_search_uses_bizno_and_period_and_only_select_inquiry():
    popup = FakePopup(kind="taxbill", rows=1)
    page, frame = FakePage(popup), FakeFormFrame()
    data = {"evidence": "세금계산서", "payeeBizNo": "123-45-67890", "payeeName": "코웨이", "expenseDate": "2026-09-30"}
    assert taxbill.wanted(data) and taxbill.query_for(data) == "1234567890"
    assert taxbill.start_date_for(data) == "2026-08-30"
    assert taxbill.start_date_for(data, "2026-07-13") == "2026-07-13"        # 팝업 기본 기간이 더 넓으면 좁히지 않는다
    assert taxbill.start_date_for(data, "2026-09-15") == "2026-08-30"        # 기본이 더 좁으면 31일 전으로 넓힌다
    assert taxbill.bizno_forms("123-45-67890") == ["1234567890", "123-45-67890"] and taxbill.bizno_forms("12") == []
    report = taxbill.search(page, frame, data, lambda m: None, wait=lambda s: None, auto_pick=False)
    assert report.ok and report.rows == 1 and not report.picked
    assert frame.clicks == [taxbill.SELECT_LINK_ID] and popup.clicks == [taxbill.INQUIRY_BUTTON_ID]
    assert (taxbill.SELLER_SELECT_ID, "공급자") in popup.sets
    assert (taxbill.BIZNO_TEXT_ID, "1234567890") in popup.sets and (taxbill.START_DATE_ID, "2026-08-30") in popup.sets
    assert popup.listeners == []
    assert "계산서를 고르고 [확인]" in report.lines()[0]

    # 사업자번호가 없으면 거래처 이름으로, [선택] 이 안 보이면(증빙구분이 다름) 열지 않는다
    popup = FakePopup(kind="taxbill")
    report = taxbill.search(FakePage(popup), FakeFormFrame(), {"evidence": "세금계산서", "payeeName": "코웨이"}, lambda m: None, wait=lambda s: None, auto_pick=False)
    assert report.ok and (taxbill.NAME_TEXT_ID, "코웨이") in popup.sets and not any(i == taxbill.SELLER_SELECT_ID for i, _ in popup.sets)
    frame = FakeFormFrame(link_visible=False)
    report = taxbill.search(FakePage(FakePopup(kind="taxbill")), frame, data, lambda m: None, wait=lambda s: None)
    assert not report.ok and "[선택] 이 보이지 않습니다" in report.note and frame.clicks == []
    assert not taxbill.wanted({"evidence": "기타"})


def test_wait_closed_polls_until_popup_closes():
    popup = FakePopup(closes_after=3)
    waits = []
    assert payee.wait_closed(popup, waits.append, seconds=10)
    assert 3 <= popup.asked <= 5 and all(w == 0.5 for w in waits)
    popup = FakePopup()
    assert not payee.wait_closed(popup, lambda s: None, seconds=1)


def test_fill_report_shows_popup_results():
    report = form.FillReport(dry_run=False, steps=[form.Step("적요", "09_정수기", True)])
    report.taxbill = taxbill.TaxbillReport(ok=True, query="1234567890", rows=2)
    report.payee = payee.PayeeReport(ok=True, query="코웨이", rows=1)
    text = "\n".join(report.lines())
    assert "1234567890" in text and "코웨이" in text and "결과 1행" in text
    assert text.index("1234567890") < text.index("코웨이") < text.index("사람이 할 것")


def test_taxbill_locks_expense_date_so_fill_skips_it():
    """실측(2026-10-13): 증빙구분이 세금계산서면 지출일자 칸이 잠긴다 — 못 넣은 게 아니라 팝업에서 채워지는 것."""
    class LockedDate(FakeFrame):
        def evaluate(self, js, arg=None):
            if js is form.SET_TEXT_JS and arg[0] == "EXP_DT":
                return {"ok": False, "why": "읽기전용"}
            return super().evaluate(js, arg)
    report = form.fill(LockedDate(), schema.normalize(sample()), lambda m: None, dry_run=False, wait=lambda s: None)
    date = next(s for s in report.steps if s.label == "지출일자")
    assert date.ok and "세금계산서" in date.note and report.ok
    report = form.fill(LockedDate(), schema.normalize(sample(evidence="기타")), lambda m: None, dry_run=False, wait=lambda s: None)
    assert not next(s for s in report.steps if s.label == "지출일자").ok


# ── 자동 선택 (담당자 결정 2026-10-13: 확실하면 앱이, 애매하면 사람) ──────────
def _rows(*texts, **extra):
    return [{"index": i, "text": t, "titles": "", "pick": True, **extra} for i, t in enumerate(texts)]


def test_payee_match_picks_only_an_unambiguous_row():
    data = {"payeeName": "코웨이(주)", "payeeBizNo": "123-45-67890"}
    assert payee.match(_rows("1 코웨이(주) 123-45-67890 활동", "2 코웨이엔텍 987-65-43210 활동"), data) == (0, "사업자번호 일치")
    # 상호가 똑같은 칸만 고른다 — ㈜코웨이 는 코웨이, 코웨이산업은 다른 회사
    assert payee.match(_rows("1 ㈜코웨이 111-11-11111", "2 코웨이산업 222-22-22222"), {"payeeName": "코웨이"}) == (0, "상호 일치")
    assert payee.match(_rows("1 ㈜코웨이 111-11-11111", "2 코웨이(주) 222-22-22222"), {"payeeName": "코웨이"}) == (None, "상호가 같은 행이 2개 — 어느 것인지 애매함")
    # 이름만 담은 행은 고르지 않는다('한빛' → '한빛소프트')
    index, why = payee.match(_rows("1 한빛소프트 444-44-44444"), {"payeeName": "한빛"})
    assert index is None and "똑같지 않아" in why
    # 서류의 사업자번호가 목록에 없으면 이름이 같아도 고르지 않는다(다른 거래처)
    index, why = payee.match(_rows("1 코웨이 999-99-99999"), {"payeeName": "코웨이", "payeeBizNo": "123-45-67890"})
    assert index is None and "사업자번호" in why
    assert payee.match(_rows("1 ㈜코웨이 111-11-11111"), {"payeeName": "코웨이 주식회사"}) == (0, "상호 일치")
    assert payee.match([], data)[0] is None
    assert payee.match(_rows("1 다른회사 333-33-33333"), {"payeeName": "코웨이"})[0] is None
    assert payee.match(_rows("1 코"), {"payeeName": "코"})[0] is None                   # 너무 짧은 상호
    index, why = payee.match(_rows("1 코웨이 123-45-67890", "2 코웨이 123-45-67890"), data)
    assert index is None and "2개" in why


def test_taxbill_match_uses_amount_then_date():
    data = {"amount": 51900, "supplyAmount": 47182, "expenseDate": "2026-09-30"}
    assert taxbill.match(_rows("2026-09-30 코웨이(주) 47,182 4,718 51,900", "2026-08-31 코웨이(주) 30,000"), data) == (0, "금액 일치")
    assert taxbill.match(_rows("2026-09-30 코웨이 51,900", "2026-08-30 코웨이 51,900"), data) == (0, "금액·일자 일치")
    index, why = taxbill.match(_rows("20260930 코웨이 51900", "20260930 코웨이 51900"), data)
    assert index is None and "애매" in why
    assert taxbill.match(_rows("2026-09-30 코웨이 30,000"), data)[0] is None
    assert taxbill.match(_rows("x"), {"amount": ""})[0] is None
    assert taxbill.match([], data)[0] is None


def test_payee_search_auto_picks_and_confirms_when_sure():
    frame = FakeFormFrame()
    listing = [{"index": 0, "text": "코웨이(주) 123-45-67890", "titles": "", "pick": True, "rcv": "코웨이(주)"},
               {"index": 1, "text": "코웨이엔텍 987-65-43210", "titles": "", "pick": True, "rcv": "코웨이엔텍"}]
    popup = FakePopup(listing=listing, form=frame)
    logs = []
    report = payee.search(FakePage(popup), frame, {"payeeName": "코웨이(주)", "payeeBizNo": "123-45-67890"}, logs.append, wait=lambda s: None)
    assert report.ok and report.picked and report.chosen == "코웨이(주)" and report.pick_note == "사업자번호 일치"
    assert popup.clicks == [payee.SEARCH_BUTTON_ID, "row:0", payee.CONFIRM_BUTTON_ID] and popup.closed
    assert "골라 [확인] 까지" in report.lines()[0]
    # 애매하면 [확인] 을 누르지 않는다 — 상호가 똑같은 행이 둘
    same = [{"index": 0, "text": "코웨이(주) 123-45-67890", "titles": "", "pick": True, "rcv": "코웨이(주)"},
            {"index": 1, "text": "㈜코웨이 987-65-43210", "titles": "", "pick": True, "rcv": "㈜코웨이"}]
    popup = FakePopup(listing=same, form=FakeFormFrame())
    report = payee.search(FakePage(popup), FakeFormFrame(), {"payeeName": "코웨이"}, lambda m: None, wait=lambda s: None)
    assert report.ok and not report.picked and payee.CONFIRM_BUTTON_ID not in popup.clicks and "2개" in report.pick_note
    assert "직접" not in report.lines()[0] and "고르고 [확인]" in report.lines()[0]
    # 골랐는데 작성 화면에 안 들어오면(callback 없음) 사람에게 넘긴다
    popup = FakePopup(listing=[{"index": 0, "text": "코웨이 123-45-67890", "titles": "", "pick": True}], form=None)
    report = payee.search(FakePage(popup), FakeFormFrame(), {"payeeName": "코웨이", "payeeBizNo": "123-45-67890"}, lambda m: None, wait=lambda s: None)
    assert report.ok and not report.picked and "채워지지 않음" in report.pick_note


def test_taxbill_search_auto_picks_and_confirms_when_sure():
    frame = FakeFormFrame()
    listing = [{"index": 0, "text": "2026-09-30 코웨이(주) 47,182 4,718 51,900", "titles": "", "pick": True, "bill": "TB1", "date": "2026-09-30"}]
    popup = FakePopup(kind="taxbill", listing=listing, form=frame)
    data = {"evidence": "세금계산서", "payeeBizNo": "123-45-67890", "amount": 51900, "supplyAmount": 47182, "expenseDate": "2026-09-30"}
    report = taxbill.search(FakePage(popup), frame, data, lambda m: None, wait=lambda s: None)
    assert report.ok and report.picked and report.pick_note == "금액 일치"
    assert popup.clicks == [taxbill.INQUIRY_BUTTON_ID, "row:0", taxbill.CONFIRM_BUTTON_ID] and frame.values["EXP_DT"] == "2026-09-30"
    popup = FakePopup(kind="taxbill", listing=_rows("2026-09-30 코웨이 30,000"), form=FakeFormFrame())
    report = taxbill.search(FakePage(popup), FakeFormFrame(), data, lambda m: None, wait=lambda s: None)
    assert report.ok and not report.picked and taxbill.CONFIRM_BUTTON_ID not in popup.clicks


def _grid_rows(*cells_list):
    """실측(2026-10-13) 세금계산서 그리드처럼 열 값(k_*)이 있는 행."""
    return [{"index": i, "text": " ".join(str(v) for v in c.values()), "titles": "", "pick": True, "cells": c,
             "bill": f"TB{i}", "date": c.get(taxbill.COL_DATE, "")} for i, c in enumerate(cells_list)]


def _bill(no="578-86-00021", total=51900, supply=47182, date="2026-09-30", bal=None, mail="me@kangwon.ac.kr"):
    return {taxbill.COL_SELLER_NO: no, taxbill.COL_SELLER_NM: "코웨이", taxbill.COL_TOTAL: str(total), taxbill.COL_SUPPLY: str(supply),
            taxbill.COL_DATE: date, taxbill.COL_BALANCE: str(total if bal is None else bal), taxbill.COL_EMAIL: mail}


def test_taxbill_match_uses_grid_columns_when_present():
    """열 값이 있으면 공급자 사업자번호 → 잔액 0 제외 → 합계/공급가액 → 수신메일 → 작성일자 순으로 좁힌다 (실측 그리드 기준)."""
    data = {"amount": 51900, "supplyAmount": 47182, "expenseDate": "2026-09-30", "payeeBizNo": "578-86-00021"}
    rows = _grid_rows(_bill(no="111-11-11111"), _bill(), _bill(total=30000, supply=27273))
    assert taxbill.match(rows, data) == (1, "사업자번호·금액 일치")
    # 사업자번호가 맞는 행이 없으면 금액이 맞아도 고르지 않는다
    assert taxbill.match(_grid_rows(_bill(no="111-11-11111")), data)[0] is None
    # 이미 다 청구된 계산서(잔액 0)는 뺀다 — 남는 하나를 고른다. 전부 청구됐으면 사람에게
    assert taxbill.match(_grid_rows(_bill(bal=0), _bill()), data) == (1, "사업자번호·금액 일치")
    index, why = taxbill.match(_grid_rows(_bill(bal=0)), data)
    assert index is None and "이미 모두 청구" in why
    # 같은 금액이 둘이면 수신메일이 내 것인 행 → 그래도 둘이면 작성일자
    rows = _grid_rows(_bill(mail="other@kangwon.ac.kr"), _bill(mail="me@kangwon.ac.kr"))
    assert taxbill.match(rows, data, email="me@kangwon.ac.kr") == (1, "사업자번호·금액·수신메일 일치")
    rows = _grid_rows(_bill(date="2026-08-30"), _bill(date="2026-09-30"))
    assert taxbill.match(rows, data, email="me@kangwon.ac.kr") == (1, "사업자번호·금액·일자 일치")
    index, why = taxbill.match(_grid_rows(_bill(), _bill()), data, email="me@kangwon.ac.kr")
    assert index is None and "2개" in why
    # 공급가액만 맞아도(세액 계산이 달라도) 고른다. 사업자번호를 모르면 금액만으로
    assert taxbill.match(_grid_rows(_bill(total=51910)), data) == (0, "사업자번호·금액 일치")
    assert taxbill.match(_grid_rows(_bill()), {"amount": 51900}) == (0, "금액 일치")
    # 25행 이상인데 못 찾으면 가상 스크롤 때문일 수 있다고 알린다
    many = _grid_rows(*[_bill(total=1, supply=1) for _ in range(26)])
    assert "다 읽지 못했을 수 있음" in taxbill.match(many, data)[1]


def test_taxbill_search_filters_by_my_email_and_retries_bizno_format():
    """계산서수신메일을 켜고 내 메일을 넣은 뒤 조회한다. 숫자만 넣어 0행이면 하이픈 형식으로, 그래도 0행이면 메일로만 다시 조회한다."""
    data = {"evidence": "세금계산서", "payeeBizNo": "578-86-00021", "amount": 51900, "expenseDate": "2026-09-30"}
    frame = FakeFormFrame()
    popup = FakePopup(kind="taxbill", values={"START_DATE": "2026-07-13"}, rows_for={"578-86-00021": 1}, listing=_grid_rows(_bill()), form=frame)
    logs = []
    report = taxbill.search(FakePage(popup), frame, data, logs.append, wait=lambda s: None, email="me@kangwon.ac.kr")
    assert popup.checked_boxes == [taxbill.EMAIL_CHECK_ID] and (taxbill.EMAIL_TEXT_ID, "me@kangwon.ac.kr") in popup.sets
    assert popup.inquiries == [("5788600021", "me@kangwon.ac.kr"), ("578-86-00021", "me@kangwon.ac.kr")]
    assert report.ok and report.rows == 1 and report.query == "578-86-00021" and report.picked
    assert not any(i == taxbill.START_DATE_ID for i, _ in popup.sets)      # 기본 3개월이 31일보다 넓으니 그대로
    # 두 형식 다 0행이면 번호를 비우고 메일로만 — 사람이 볼 목록을 남긴다
    popup = FakePopup(kind="taxbill", rows_for={"": 7}, form=FakeFormFrame())
    report = taxbill.search(FakePage(popup), FakeFormFrame(), data, lambda m: None, wait=lambda s: None, email="me@kangwon.ac.kr")
    assert [q for q, _ in popup.inquiries] == ["5788600021", "578-86-00021", ""] and report.ok and report.rows == 7 and not report.picked
    # 메일이 없으면 체크를 건드리지 않고 번호로만 (형식 재시도까지만)
    popup = FakePopup(kind="taxbill", rows_for={}, form=FakeFormFrame())
    report = taxbill.search(FakePage(popup), FakeFormFrame(), data, lambda m: None, wait=lambda s: None)
    assert popup.checked_boxes == [] and [q for q, _ in popup.inquiries] == ["5788600021", "578-86-00021"] and report.ok and report.rows == 0
    # 번호도 이름도 없지만 메일은 있으면 메일로만 조회한다
    popup = FakePopup(kind="taxbill", rows=4, form=FakeFormFrame())
    report = taxbill.search(FakePage(popup), FakeFormFrame(), {"evidence": "세금계산서"}, lambda m: None, wait=lambda s: None,
                            email="me@kangwon.ac.kr", auto_pick=False)
    assert report.ok and report.rows == 4 and popup.inquiries == [("", "me@kangwon.ac.kr")]


def test_payee_pick_reads_rows_from_a_child_frame():
    """입금처 팝업에는 빈 iframe 이 하나 더 있다(실측) — 결과가 그 안에 뜨더라도 읽고 고른다."""
    frame = FakeFormFrame()
    listing = [{"index": 0, "text": "코웨이(주) 123-45-67890", "titles": "", "pick": True, "rcv": "코웨이(주)"}]
    popup = FakePopup(child_rows=listing, form=frame)
    report = payee.search(FakePage(popup), frame, {"payeeName": "코웨이(주)", "payeeBizNo": "123-45-67890"}, lambda m: None, wait=lambda s: None)
    assert report.ok and report.rows == 1 and report.picked and report.chosen == "코웨이(주)"
    assert popup.clicks == [payee.SEARCH_BUTTON_ID, "row:0", payee.CONFIRM_BUTTON_ID]


def test_fill_refuses_a_sheet_that_was_already_saved():
    """저장 뒤에도 MOD_YN 은 N 이다(실측 ⑤) — 결의번호(REQ_CNT)가 있으면 이미 저장된 청구서라 일반 건을 더하지 않는다(2026-10-14 점검)."""
    frame = FakeFrame()
    frame.values["REQ_CNT"] = "324"
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=False, wait=lambda s: None)
    assert report.blocked and "324" in report.blocked and frame.sets == []
    report = form.fill(frame, schema.normalize(sample()), lambda m: None, dry_run=True)
    assert not report.blocked                                   # 미리 보기는 ERP 를 건드리지 않으니 보여 준다


def test_save_is_not_counted_when_the_page_navigated_away():
    """[저장] 뒤 로그인 · 오류 화면으로 넘어가 칸이 모두 비면 저장된 것으로 보지 않는다."""
    before = {"REQ_SEQ_NO": "TMP_REQ_1", "MOD_YN": "N", "APPR_DIV_CD": "", "REQ_CNT": ""}
    assert not form._changed(before, {k: "" for k in before})
    assert form._changed(before, {**before, "REQ_CNT": "322", "APPR_DIV_CD": "40"})


def test_amounts_with_decimals_and_korean_dates():
    assert schema.parse_amount("51900.0") == 51900 and schema.parse_amount("51,900.00") == 51900
    assert schema.parse_amount("51,900원") == 51900 and schema.parse_amount("₩ 51,900") == 51900
    assert schema.normalize_date("2026년 10월 13일") == "2026-10-13"
    assert schema.normalize_date("2026. 10. 13.") == "2026-10-13"


def test_taxbill_does_not_pick_from_an_unfiltered_list():
    """사업자번호 · 거래처명 · 수신메일 없이 조회하면 산학협력단 전체 목록 — 금액만 맞는 남의 계산서를 고르지 않는다."""
    frame = FakeFormFrame()
    listing = [{"index": 0, "text": "2026-09-30 남의회사 47,182 4,718 51,900", "titles": "", "pick": True, "bill": "TB9"}]
    popup = FakePopup(kind="taxbill", listing=listing, form=frame)
    data = {"evidence": "세금계산서", "amount": 51900, "supplyAmount": 47182, "expenseDate": "2026-09-30"}
    report = taxbill.search(FakePage(popup), frame, data, lambda m: None, wait=lambda s: None)
    assert not report.picked and taxbill.CONFIRM_BUTTON_ID not in popup.clicks
